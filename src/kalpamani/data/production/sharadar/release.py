"""The placement-release contract, and its exact binding (ADR-0036 §2.9).

A task performs **no S3, secret or provider operation** until it has read and
validated a placement release the launch tool wrote only after placement
verification passed. The release names the exact task, the exact task-definition
revision, the run or build identity and the digest of the input the task already
holds, so a release written for another task, another revision, another run or
another input is a **mismatched release** and refuses -- and a release older than
ten minutes from its verification instant is a **stale release** and refuses too.

Two sides use one contract. The launch tool builds a release document with
:func:`build_release_document` from the identifiers its verification produced;
the task validates the delivered bytes with :func:`verify_release` against the
:class:`ReleaseExpectation` it assembled from its own metadata, identity and
input. Neither side can satisfy the other by guessing: the interface and subnet
identifiers exist only because the verification ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.production.sharadar.documents import (
    DocumentDefect,
    DocumentError,
    decode_document,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.keys import RUN_ID_RE
from kalpamani.data.production.sharadar.vocabulary import (
    EXPECTED_PARTITION,
    EXPECTED_REGION,
    MAX_ADVANCED_PARAMETER_BYTES,
    RELEASE_CONTRACT_ID,
    ProductionActor,
    constants_for,
)

#: The one schema version.
RELEASE_SCHEMA_VERSION: Final = 1

#: A release is valid for at most ten minutes after its verification instant.
MAX_RELEASE_VALIDITY: Final = timedelta(minutes=10)

#: Identifier grammars. Account and region are compared, never rendered.
_ACCOUNT: Final = r"[0-9]{12}"
TASK_ARN_RE: Final = re.compile(
    rf"arn:{EXPECTED_PARTITION}:ecs:{EXPECTED_REGION}:({_ACCOUNT}):task/([A-Za-z0-9_-]{{1,255}})/([0-9a-f]{{32}})"
)
TASK_DEFINITION_ARN_RE: Final = re.compile(
    rf"arn:{EXPECTED_PARTITION}:ecs:{EXPECTED_REGION}:({_ACCOUNT}):task-definition/([A-Za-z0-9_-]{{1,255}}):([1-9][0-9]{{0,9}})"
)
NETWORK_INTERFACE_ID_RE: Final = re.compile(r"eni-[0-9a-f]{8,17}")
SUBNET_ID_RE: Final = re.compile(r"subnet-[0-9a-f]{8,17}")

_COMMON_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "actor",
        "task_arn",
        "task_definition_arn",
        "input_digest",
        "network_interface_id",
        "subnet_id",
        "verified_at",
        "expires_at",
    }
)


class ReleaseDefect(StrEnum):
    """Why a release was refused. Closed, structural, and carrying no value.

    The four ``*_MISMATCH`` members and the two staleness members are the
    ``REFUSED_RELEASE_MISMATCH`` family of ADR-0036 §2.9; the rest are document
    defects, which refuse the same way.
    """

    EMPTY = "EMPTY"
    TOO_LARGE = "TOO_LARGE"
    ENCODING_INVALID = "ENCODING_INVALID"
    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    SCHEMA_VERSION_UNKNOWN = "SCHEMA_VERSION_UNKNOWN"
    CONTRACT_ID_UNKNOWN = "CONTRACT_ID_UNKNOWN"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    VALIDITY_MALFORMED = "VALIDITY_MALFORMED"
    VALIDITY_TOO_LONG = "VALIDITY_TOO_LONG"
    ACTOR_MISMATCH = "ACTOR_MISMATCH"
    TASK_MISMATCH = "TASK_MISMATCH"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    INPUT_DIGEST_MISMATCH = "INPUT_DIGEST_MISMATCH"
    VERIFIED_IN_FUTURE = "VERIFIED_IN_FUTURE"
    EXPIRED = "EXPIRED"


class ReleaseError(Exception):
    """A refusal carrying exactly one :class:`ReleaseDefect`, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: ReleaseDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not ReleaseDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact ReleaseDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: ReleaseDefect) -> ReleaseError:
    return ReleaseError(defect)


#: Total: every document defect has a release defect. A test asserts totality.
_DOCUMENT_DEFECTS: Final[dict[DocumentDefect, ReleaseDefect]] = {
    DocumentDefect.EMPTY: ReleaseDefect.EMPTY,
    DocumentDefect.TOO_LARGE: ReleaseDefect.TOO_LARGE,
    DocumentDefect.ENCODING_INVALID: ReleaseDefect.ENCODING_INVALID,
    DocumentDefect.DOCUMENT_MALFORMED: ReleaseDefect.DOCUMENT_MALFORMED,
    DocumentDefect.DUPLICATE_KEY: ReleaseDefect.DUPLICATE_KEY,
}

#: The members that are a *mismatched or stale* release rather than a malformed
#: one -- the task's ``REFUSED_RELEASE_MISMATCH`` outcome.
MISMATCH_DEFECTS: Final[frozenset[ReleaseDefect]] = frozenset(
    {
        ReleaseDefect.ACTOR_MISMATCH,
        ReleaseDefect.TASK_MISMATCH,
        ReleaseDefect.REVISION_MISMATCH,
        ReleaseDefect.IDENTITY_MISMATCH,
        ReleaseDefect.INPUT_DIGEST_MISMATCH,
        ReleaseDefect.VERIFIED_IN_FUTURE,
        ReleaseDefect.EXPIRED,
    }
)


def release_fields(actor: ProductionActor) -> frozenset[str]:
    """The exact field set of ``actor``'s release: the common fields plus its identity field."""
    return _COMMON_FIELDS | {constants_for(actor).identity_field}


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseExpectation:
    """What the task knows before it reads a release, from sources it already proved.

    ``task_arn`` and ``task_definition_arn`` come from task metadata v4;
    ``identity`` from the input it read; ``input_digest`` from the bytes of that
    input. None of the four is read from the release.
    """

    actor: ProductionActor
    task_arn: str
    task_definition_arn: str
    identity: str
    input_digest: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("ReleaseExpectation may not be subclassed")

    def __post_init__(self) -> None:
        """Hold every field to its grammar; an expectation nobody could meet is refused."""
        if type(self.actor) is not ProductionActor:
            raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
        if not TASK_ARN_RE.fullmatch(self.task_arn or ""):
            raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
        if not TASK_DEFINITION_ARN_RE.fullmatch(self.task_definition_arn or ""):
            raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
        if type(self.identity) is not str or not RUN_ID_RE.match(self.identity):
            raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
        if hex_digest(self.input_digest) is None:
            raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None

    def __repr__(self) -> str:
        """The actor only."""
        return f"ReleaseExpectation(actor={self.actor.value!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class PlacementRelease:
    """One validated release, bound to exactly the task that read it."""

    actor: ProductionActor
    network_interface_id: str
    subnet_id: str
    verified_at: datetime
    expires_at: datetime

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("PlacementRelease may not be subclassed")

    def __repr__(self) -> str:
        """The actor only. **Never an identifier.**"""
        return f"PlacementRelease(actor={self.actor.value!r})"


def decode_release(raw: object) -> dict[str, Any]:
    """The closed object of one release parameter, refused above 8 KiB before parsing."""
    try:
        return decode_document(raw, max_bytes=MAX_ADVANCED_PARAMETER_BYTES)
    except DocumentError as error:
        raise _refuse(_DOCUMENT_DEFECTS[error.defect]) from None


def _field(document: dict[str, Any], name: str, grammar: re.Pattern[str]) -> str:
    value = exact_str(document[name])
    if value is None or not grammar.fullmatch(value):
        raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
    return value


def verify_release(
    document: object, *, expectation: ReleaseExpectation, now: datetime
) -> PlacementRelease:
    """Validate an already-decoded release against what the task already holds.

    The order is fixed and every clause is a refusal: the closed shape, the schema
    and contract, then each grammar, then the six binding clauses -- actor, task
    ARN, task-definition ARN, identity, input digest -- then the two instants. A
    document that passes the shape and fails a binding clause is a **mismatched
    release**; one whose ``verified_at`` is in the future or whose ``expires_at``
    has passed is a **stale release**.

    Raises:
        ReleaseError: one closed :class:`ReleaseDefect`; never a value.
    """
    if type(expectation) is not ReleaseExpectation:
        raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
    if type(now) is not datetime or now.tzinfo is None:
        raise _refuse(ReleaseDefect.VALIDITY_MALFORMED) from None
    if type(document) is not dict:
        raise _refuse(ReleaseDefect.DOCUMENT_MALFORMED) from None
    constants = constants_for(expectation.actor)
    fields = release_fields(expectation.actor)
    names = set(document)
    if names - fields:
        raise _refuse(ReleaseDefect.FIELD_UNKNOWN) from None
    if fields - names:
        raise _refuse(ReleaseDefect.FIELD_MISSING) from None

    version = document["schema_version"]
    if type(version) is not int:
        raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
    if version != RELEASE_SCHEMA_VERSION:
        raise _refuse(ReleaseDefect.SCHEMA_VERSION_UNKNOWN) from None
    contract = exact_str(document["contract_id"])
    if contract is None:
        raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
    if contract != RELEASE_CONTRACT_ID:
        raise _refuse(ReleaseDefect.CONTRACT_ID_UNKNOWN) from None

    actor = exact_str(document["actor"])
    if actor is None or actor not in {member.value for member in ProductionActor}:
        raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
    task_arn = _field(document, "task_arn", TASK_ARN_RE)
    task_definition_arn = _field(document, "task_definition_arn", TASK_DEFINITION_ARN_RE)
    identity = exact_str(document[constants.identity_field])
    if identity is None or not RUN_ID_RE.match(identity):
        raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
    input_digest = hex_digest(document["input_digest"])
    if input_digest is None:
        raise _refuse(ReleaseDefect.FIELD_MALFORMED) from None
    interface = _field(document, "network_interface_id", NETWORK_INTERFACE_ID_RE)
    subnet = _field(document, "subnet_id", SUBNET_ID_RE)
    verified_at = instant(document["verified_at"])
    expires_at = instant(document["expires_at"])
    if verified_at is None or expires_at is None or expires_at <= verified_at:
        raise _refuse(ReleaseDefect.VALIDITY_MALFORMED) from None
    if expires_at - verified_at > MAX_RELEASE_VALIDITY:
        raise _refuse(ReleaseDefect.VALIDITY_TOO_LONG) from None

    if actor != expectation.actor.value:
        raise _refuse(ReleaseDefect.ACTOR_MISMATCH) from None
    if task_arn != expectation.task_arn:
        raise _refuse(ReleaseDefect.TASK_MISMATCH) from None
    if task_definition_arn != expectation.task_definition_arn:
        raise _refuse(ReleaseDefect.REVISION_MISMATCH) from None
    if identity != expectation.identity:
        raise _refuse(ReleaseDefect.IDENTITY_MISMATCH) from None
    if input_digest != expectation.input_digest:
        raise _refuse(ReleaseDefect.INPUT_DIGEST_MISMATCH) from None
    if verified_at > now:
        raise _refuse(ReleaseDefect.VERIFIED_IN_FUTURE) from None
    if expires_at <= now:
        raise _refuse(ReleaseDefect.EXPIRED) from None

    return PlacementRelease(
        actor=expectation.actor,
        network_interface_id=interface,
        subnet_id=subnet,
        verified_at=verified_at,
        expires_at=expires_at,
    )


def build_release_document(
    *,
    actor: ProductionActor,
    task_arn: str,
    task_definition_arn: str,
    identity: str,
    input_digest: str,
    network_interface_id: str,
    subnet_id: str,
    verified_at: datetime,
) -> bytes:
    """The release bytes the launch tool writes, valid for exactly ten minutes.

    Built through the same grammars the task verifies with, and re-verified
    against the expectation it encodes before it is returned -- so the launcher
    cannot write a release the task would refuse for shape.

    Raises:
        ReleaseError: ``FIELD_MALFORMED`` for any identifier the grammar refuses.
    """
    expectation = ReleaseExpectation(
        actor=actor,
        task_arn=task_arn,
        task_definition_arn=task_definition_arn,
        identity=identity,
        input_digest=input_digest,
    )
    if type(verified_at) is not datetime or verified_at.tzinfo is None:
        raise _refuse(ReleaseDefect.VALIDITY_MALFORMED) from None
    document: dict[str, Any] = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "contract_id": RELEASE_CONTRACT_ID,
        "actor": actor.value,
        "task_arn": task_arn,
        "task_definition_arn": task_definition_arn,
        constants_for(actor).identity_field: identity,
        "input_digest": input_digest,
        "network_interface_id": network_interface_id,
        "subnet_id": subnet_id,
        "verified_at": verified_at.isoformat(),
        "expires_at": (verified_at + MAX_RELEASE_VALIDITY).isoformat(),
    }
    verify_release(document, expectation=expectation, now=verified_at)
    payload = canonical_bytes(document)
    if len(payload) > MAX_ADVANCED_PARAMETER_BYTES:  # pragma: no cover - grammar-bounded
        raise _refuse(ReleaseDefect.TOO_LARGE) from None
    return payload


__all__ = [
    "MAX_RELEASE_VALIDITY",
    "MISMATCH_DEFECTS",
    "NETWORK_INTERFACE_ID_RE",
    "RELEASE_SCHEMA_VERSION",
    "SUBNET_ID_RE",
    "TASK_ARN_RE",
    "TASK_DEFINITION_ARN_RE",
    "PlacementRelease",
    "ReleaseDefect",
    "ReleaseError",
    "ReleaseExpectation",
    "build_release_document",
    "decode_release",
    "release_fields",
    "verify_release",
]
