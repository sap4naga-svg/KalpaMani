"""The permission-probe contracts shared by the task and the workstation (proposed ADR-0048).

A task-role permission subcell (ADR-0047 s.3) is exercised by a **permission-probe task**:
the actor's probe entry, launched by the actor's launcher through the accepted launch
sequence, composes the accepted bootstrap -- environment, binding, input, self-check,
identity proof, release barrier -- and then issues **exactly one** operation, the one its
probe input names, through the same engine the workstation tool uses for a human
principal. What it establishes travels back in its receipt as one closed block, the
:class:`PermissionProbeObservation`, which the workstation verifies against the launch
record it holds before it writes the permission record.

Two documents live here because both sides read them and neither may import the other's
module at import time (the permission catalogue imports the launch records, which import
the task entry, which imports the bootstrap): the **probe input**
(``kalpamani-permission-probe-input/v1``), the input parameter the launcher materializes
for one probe launch -- the subcell, the statement and attempt it answers, the session
stamp and the exact resolved target, all of which the workstation already bound before the
launch -- and the **probe observation**, the receipt block. The catalogue is consulted
lazily, at parse time, so the leaf stays a leaf.

**A held probe** (``hold_seconds > 0``) issues no operation at all: it is the attributable
running task the launcher's ``ExecuteCommand`` refusal check needs, and it exits on its own
when the hold expires. The hold is bounded by :data:`PROBE_HOLD_CEILING_SECONDS`.

**Mocked results are not AWS verification.** Every observation in this repository's tests is
a counting fake's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import (
    DocumentError,
    decode_document,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.r3_verification import ObservedClass
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

PROBE_INPUT_CONTRACT_ID: Final = "kalpamani-permission-probe-input/v1"
PROBE_INPUT_SCHEMA_VERSION: Final = 1
MAX_PROBE_INPUT_BYTES: Final = 8 * 1024
#: A probe input is valid for at most this long after it is issued (the accepted input
#: validity of ADR-0036 s.2.6).
MAX_PROBE_INPUT_VALIDITY: Final = timedelta(hours=24)
#: The reserved spelling of a probe launch's identity: ``probe-<session stamp>``.
PROBE_IDENTITY_PREFIX: Final = "probe-"
_STAMP_RE: Final = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}")
PROBE_IDENTITY_RE: Final = re.compile(r"probe-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}")
#: A held probe waits at most this long (monotonic seconds) before it exits on its own.
#: Lowerable, never raisable: the launcher's observation ceiling is the outer bound.
PROBE_HOLD_CEILING_SECONDS: Final = 600
PROBE_HOLD_POLL_SECONDS: Final = 5.0


class SubcellOutcome(StrEnum):
    """What one executed subcell established. Closed."""

    MATCHED = "MATCHED"
    INVERTED = "INVERTED"
    UNDECIDED = "UNDECIDED"


def probe_identity(stamp: str) -> str:
    """The launch identity of the probe of one session stamp."""
    if _STAMP_RE.fullmatch(stamp) is None:
        raise ValueError("a session stamp is required")
    return PROBE_IDENTITY_PREFIX + stamp


_INPUT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "actor",
        "identity",
        "subcell_id",
        "statement_sha256",
        "attempt_sha256",
        "stamp",
        "target",
        "hold_seconds",
        "issued_at",
        "expires_at",
    }
)
_TARGET_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "bucket",
        "key",
        "name",
        "cluster_arn",
        "task_definition_arn",
        "task_role_arn",
        "subnet_id",
        "security_group_ids",
        "assign_public_ip",
        "platform_version",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionProbeInput:
    """One probe launch's input: what the workstation bound, for the task to act on.

    ``target`` is the resolved target's closed document exactly as the statement's digest
    covers it; the task rebuilds the :class:`~permission_cells.ResolvedTarget` from it and
    issues the subcell's one operation against it. ``hold_seconds`` is ``0`` for every
    operation-issuing subcell and positive only for the launcher's ``ExecuteCommand``
    subcell, whose probe issues nothing and holds. **Never rendered.**
    """

    actor: ProductionActor
    identity: str
    subcell_id: str
    statement_sha256: str
    attempt_sha256: str
    stamp: str
    target: dict[str, Any]
    hold_seconds: int
    issued_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        return f"PermissionProbeInput(subcell_id={self.subcell_id!r})"

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": PROBE_INPUT_SCHEMA_VERSION,
            "contract_id": PROBE_INPUT_CONTRACT_ID,
            "actor": self.actor.value,
            "identity": self.identity,
            "subcell_id": self.subcell_id,
            "statement_sha256": self.statement_sha256,
            "attempt_sha256": self.attempt_sha256,
            "stamp": self.stamp,
            "target": dict(self.target),
            "hold_seconds": self.hold_seconds,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    @property
    def held(self) -> bool:
        return self.hold_seconds > 0


def parse_permission_probe_input(
    raw: object, *, now: datetime, actor: ProductionActor | None = None
) -> PermissionProbeInput:
    """The probe input, parsed closed and held to the catalogue, or ``ValueError``.

    The subcell must exist and be a task-issued subcell of the input's actor (its
    principal the actor's task role) or that actor's launcher-held ``ExecuteCommand``
    subcell, and ``hold_seconds`` must be positive exactly for the latter; the target
    kind must be the subcell's; the identity must be the stamp's probe identity; the
    validity window must be at most 24 hours and contain ``now``. When ``actor`` is
    given the input must be that actor's.
    """
    # Lazily: the catalogue imports the launch records, which import the task entry.
    from kalpamani.data.production.sharadar.permission_cells import (
        PRINCIPAL_ACTOR,
        Layer,
        Operation,
        subcell,
    )

    try:
        document = (
            raw if type(raw) is dict else decode_document(raw, max_bytes=MAX_PROBE_INPUT_BYTES)
        )
    except DocumentError:
        raise ValueError("permission probe input: document") from None
    if type(document) is not dict or set(document) != _INPUT_FIELDS:
        raise ValueError("permission probe input: closed field set")
    if (
        document["schema_version"] != PROBE_INPUT_SCHEMA_VERSION
        or document["contract_id"] != PROBE_INPUT_CONTRACT_ID
    ):
        raise ValueError("permission probe input: contract")
    actor_value = exact_str(document["actor"])
    if actor_value not in {m.value for m in ProductionActor}:
        raise ValueError("permission probe input: actor")
    input_actor = ProductionActor(actor_value)
    if actor is not None and input_actor is not actor:
        raise ValueError("permission probe input: another actor's")
    identity = exact_str(document["identity"])
    stamp = exact_str(document["stamp"])
    subcell_id = exact_str(document["subcell_id"])
    if (
        identity is None
        or stamp is None
        or subcell_id is None
        or _STAMP_RE.fullmatch(stamp) is None
        or identity != probe_identity(stamp)
    ):
        raise ValueError("permission probe input: identity")
    try:
        cell = subcell(subcell_id)
    except ValueError:
        raise ValueError("permission probe input: subcell") from None
    hold = document["hold_seconds"]
    if type(hold) is not int or hold < 0 or hold > PROBE_HOLD_CEILING_SECONDS:
        raise ValueError("permission probe input: hold")
    if cell.layer is Layer.L3_TASK:
        if PRINCIPAL_ACTOR[cell.principal] is not input_actor or hold != 0:
            raise ValueError("permission probe input: subcell principal")
    elif cell.layer is Layer.L3_HELD_TASK:
        if (
            PRINCIPAL_ACTOR[cell.principal] is not input_actor
            or cell.operation is not Operation.ECS_EXECUTE_COMMAND
            or hold == 0
        ):
            raise ValueError("permission probe input: held subcell")
    else:
        raise ValueError("permission probe input: not a probe subcell")
    statement = hex_digest(document["statement_sha256"])
    attempt = hex_digest(document["attempt_sha256"])
    if statement is None or attempt is None:
        raise ValueError("permission probe input: digest")
    target = document["target"]
    if type(target) is not dict or set(target) != _TARGET_FIELDS:
        raise ValueError("permission probe input: target")
    kind = exact_str(target["kind"])
    if kind != cell.target.value:
        raise ValueError("permission probe input: target kind")
    issued = instant(document["issued_at"])
    expires = instant(document["expires_at"])
    if (
        issued is None
        or expires is None
        or expires <= issued
        or expires - issued > MAX_PROBE_INPUT_VALIDITY
        or not issued <= now < expires
    ):
        raise ValueError("permission probe input: validity")
    return PermissionProbeInput(
        actor=input_actor,
        identity=identity,
        subcell_id=subcell_id,
        statement_sha256=statement,
        attempt_sha256=attempt,
        stamp=stamp,
        target=dict(target),
        hold_seconds=hold,
        issued_at=issued,
        expires_at=expires,
    )


_OBSERVATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "subcell_id",
        "statement_sha256",
        "attempt_sha256",
        "stamp",
        "observed",
        "outcome",
        "created",
        "possibly_created",
        "operations",
        "held_seconds",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionProbeObservation:
    """What one probe task established: the receipt block. Classes and counts, no value.

    ``created`` says the one operation definitely created the object the input named
    (the workstation's attempt already names its exact key); ``possibly_created`` says
    the answer left the write open. A held probe reports ``NOT_EXERCISED`` /
    ``UNDECIDED`` with zero operations and the seconds it held.
    """

    subcell_id: str
    statement_sha256: str
    attempt_sha256: str
    stamp: str
    observed: ObservedClass
    outcome: SubcellOutcome
    created: bool
    possibly_created: bool
    operations: int
    held_seconds: int

    def __post_init__(self) -> None:
        if type(self.observed) is not ObservedClass or type(self.outcome) is not SubcellOutcome:
            raise TypeError("observed and outcome must be exact members")
        if type(self.operations) is not int or self.operations < 0:
            raise ValueError("operations is a non-negative integer")
        if type(self.held_seconds) is not int or self.held_seconds < 0:
            raise ValueError("held_seconds is a non-negative integer")
        if self.created and self.possibly_created:
            raise ValueError("an object is created or possibly created, never both")

    def document(self) -> dict[str, Any]:
        return {
            "subcell_id": self.subcell_id,
            "statement_sha256": self.statement_sha256,
            "attempt_sha256": self.attempt_sha256,
            "stamp": self.stamp,
            "observed": self.observed.value,
            "outcome": self.outcome.value,
            "created": self.created,
            "possibly_created": self.possibly_created,
            "operations": self.operations,
            "held_seconds": self.held_seconds,
        }

    def __repr__(self) -> str:
        return (
            f"PermissionProbeObservation(subcell_id={self.subcell_id!r}, "
            f"outcome={self.outcome.value!r})"
        )


def parse_permission_probe_observation(raw: object) -> PermissionProbeObservation:
    """The receipt block, parsed closed, or ``ValueError``."""
    if type(raw) is not dict or set(raw) != _OBSERVATION_FIELDS:
        raise ValueError("permission probe observation: closed field set")
    subcell_id = exact_str(raw["subcell_id"])
    stamp = exact_str(raw["stamp"])
    statement = hex_digest(raw["statement_sha256"])
    attempt = hex_digest(raw["attempt_sha256"])
    observed = exact_str(raw["observed"])
    outcome = exact_str(raw["outcome"])
    if (
        subcell_id is None
        or stamp is None
        or _STAMP_RE.fullmatch(stamp) is None
        or statement is None
        or attempt is None
        or observed not in {m.value for m in ObservedClass}
        or outcome not in {m.value for m in SubcellOutcome}
        or type(raw["created"]) is not bool
        or type(raw["possibly_created"]) is not bool
        or type(raw["operations"]) is not int
        or type(raw["held_seconds"]) is not int
    ):
        raise ValueError("permission probe observation: field")
    return PermissionProbeObservation(
        subcell_id=subcell_id,
        statement_sha256=statement,
        attempt_sha256=attempt,
        stamp=stamp,
        observed=ObservedClass(observed),
        outcome=SubcellOutcome(outcome),
        created=raw["created"],
        possibly_created=raw["possibly_created"],
        operations=raw["operations"],
        held_seconds=raw["held_seconds"],
    )


__all__ = [
    "MAX_PROBE_INPUT_BYTES",
    "MAX_PROBE_INPUT_VALIDITY",
    "PROBE_HOLD_CEILING_SECONDS",
    "PROBE_HOLD_POLL_SECONDS",
    "PROBE_IDENTITY_PREFIX",
    "PROBE_IDENTITY_RE",
    "PROBE_INPUT_CONTRACT_ID",
    "PermissionProbeInput",
    "PermissionProbeObservation",
    "SubcellOutcome",
    "parse_permission_probe_input",
    "parse_permission_probe_observation",
    "probe_identity",
]
