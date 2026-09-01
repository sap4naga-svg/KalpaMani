"""The deterministic private locator: the one object addressed by name.

**This exists because a key in this system is a name plus a content address, and
the address comes from the payload.** A key is therefore not constructible without
the bytes, which is exactly why an earlier single-request acquisition cannot be
addressed after the fact. The licensed store has no listing surface -- deliberately,
because a producer that could list the store could enumerate what a vendor sent --
so there is no way to go looking for it either.

The locator resolves that asymmetry by being the **one** object addressed from an
identity the owner already knows:

- the locator is retrieved by a key derived from the execution identity alone, and
  validated against its closed schema and size ceiling **after** retrieval;
- every object it references is retrieved by **name and expected digest**, with the
  full-object checksum and byte count verified **before any parsing**.

**One locator per execution, published last.** Per-request locators would need an
index of their own, which is recursion, and would multiply writes by the request
count. One per execution adds one write per run. Published last because a locator
written first would reference objects that do not exist.

**The schema is closed and has no free-text field.** Not a filtered one -- an
absent one. There is no field a bucket, an account, a credential, a provider URL or
a vendor row could arrive through, and :func:`validate_locator_document` refuses an
unknown field rather than ignoring it.

**It is never a cross-execution index.** There is no index of locators, no
enumeration and no cross-reference, because an index of locators would be the
listing capability this architecture removes, rebuilt by hand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.paths import path_segment
from kalpamani.data.contracts.vocabulary import AcquisitionMode, DataClassification
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.ingest.publication import (
    acquisition_claim,
    acquisition_claim_key,
    acquisition_record,
    bronze_acquisition_key,
)
from kalpamani.data.ingest.sharadar.datasets import PROVIDER, SharadarRequest
from kalpamani.data.ingest.sharadar.qualification import PERMITTED_PROFILE
from kalpamani.data.ingest.sharadar.runtime import (
    QualificationOutcome,
    QualificationRunResult,
    RequestOutcome,
)
from kalpamani.data.objectstore import ObjectKey
from kalpamani.data.qualify.sharadar.plan import EmpiricalPlan
from kalpamani.data.qualify.sharadar.publication import qualification_payload_key

#: The locator's own namespace, inside the licensed ``qualification/`` prefix the
#: deletion runbook already deletes wholesale. A new top-level prefix would have
#: been an unexpected-prefix finding in that runbook, and reconciling it would mean
#: editing the deletion procedure to accommodate a storage detail.
LOCATOR_SEGMENTS: Final[tuple[str, ...]] = ("qualification", "sharadar", "locators")

#: The one schema version. Matched exactly on read: a document written for a
#: different shape is refused rather than interpreted.
LOCATOR_SCHEMA_VERSION: Final = "kalpamani-sharadar-empirical-locator-v1"

#: At most 256 KiB, refused above. At 48 entries the document is on the order of
#: 32 KiB, so the ceiling is headroom rather than a constraint -- and it is what
#: stops a malformed or hostile object being parsed at size.
MAX_LOCATOR_BYTES: Final = 256 * 1024


class Completeness(StrEnum):
    """Whether every planned request completed.

    ``PARTIAL`` **preserves accounting and grants no evaluation.** A halted run's
    locator is still published, because the evidence it does describe is real and
    the owner needs to know what landed -- but the assessor refuses to evaluate it,
    since a P-test conclusion drawn from a subset nobody chose is a conclusion
    about a different experiment.
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class ObjectDisposition(StrEnum):
    """What one conditional write did to one name.

    Two states, because a conditional append-only write has two outcomes: it wrote,
    or identical content was already there. Anything else raised and the run halted.
    """

    WRITTEN = "WRITTEN"
    ALREADY_PRESENT = "ALREADY_PRESENT"


class LocatorDefect(StrEnum):
    """Why a locator was refused. Closed, structural, and carrying no value."""

    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    ENCODING_INVALID = "ENCODING_INVALID"
    TOO_LARGE = "TOO_LARGE"
    SCHEMA_VERSION_UNKNOWN = "SCHEMA_VERSION_UNKNOWN"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    ENTRY_MALFORMED = "ENTRY_MALFORMED"
    ENTRY_COUNT_INCONSISTENT = "ENTRY_COUNT_INCONSISTENT"
    ENTRY_DUPLICATED = "ENTRY_DUPLICATED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    RESULT_INCONSISTENT = "RESULT_INCONSISTENT"


class LocatorError(Exception):
    """A refusal carrying exactly one :class:`LocatorDefect`, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: LocatorDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not LocatorDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact LocatorDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: LocatorDefect) -> LocatorError:
    return LocatorError(defect)


#: The exact top-level field set of a locator document. An allowlist.
LOCATOR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "classification",
        "provider",
        "execution_id",
        "acquisition_mode",
        "profile",
        "plan_digest",
        "inventory_digest",
        "source_schema_version",
        "run_started_at",
        "run_completed_at",
        "completeness",
        "publication_state_unknown",
        "planned_request_count",
        "completed_request_count",
        "entries",
    }
)

#: The exact per-entry field set. Same rule, and no free-text member.
LOCATOR_ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "acquisition_id",
        "dataset",
        "subject",
        "requested_range",
        "page_limit",
        "page_skip",
        "claim_key",
        "claim_sha256",
        "claim_bytes",
        "claim_disposition",
        "payload_key",
        "payload_sha256",
        "payload_bytes",
        "payload_disposition",
        "record_key",
        "record_sha256",
        "record_bytes",
        "record_disposition",
    }
)


def locator_key_segments(execution_id: str) -> tuple[str, ...]:
    """The locator's key segments for one execution. **No listing is involved.**

    The final segment is validated by the existing path-segment grammar, which
    refuses a leading underscore, a reserved prefix, a trailing dot and a Windows
    device name at any extension. An execution identity whose first dot-separated
    part collides with a device name therefore refuses here rather than producing a
    file that reads differently on another platform.

    Raises:
        LocatorError: ``IDENTITY_MISMATCH`` if the identity cannot name an object.
    """
    if type(execution_id) is not str:
        raise _refuse(LocatorDefect.IDENTITY_MISMATCH) from None
    try:
        leaf = path_segment(f"{execution_id}.json", kind="locator")
    except Exception:
        raise _refuse(LocatorDefect.IDENTITY_MISMATCH) from None
    return (*LOCATOR_SEGMENTS, leaf)


def plan_digest(plan: EmpiricalPlan) -> str:
    """A deterministic digest of the **stable** acquisition plan two runs must share.

    The accepted locator schema carries exactly one plan digest, and the combined
    assessment requires Run A and Run B to record *the same* one. So this binds the
    part of the plan a legitimate pair holds in common:

    - the acquisition mode and the provider;
    - the dataset inventory, and the subject/request inventory structure;
    - every page limit and page offset, and the request count;
    - the schema, response-format and profile identifiers, and both byte ceilings.

    And it deliberately excludes the values a legitimate pair **must** differ in:
    the execution identity, which is distinct by requirement, and each request's
    ``requested_range``, which ends at that run's own ``T-1`` and is therefore
    different for two runs eight calendar days apart. Binding either would make
    every legitimate pair unsatisfiable, which is the whole reason this digest is
    defined over the plan's shape rather than over one execution of it.

    **Nothing execution-specific is lost by that exclusion.** The locator binds the
    execution identity, both run instants, every acquisition identity, every
    requested range and every object key, digest, byte count and disposition in its
    own fields -- so the evidence stays bound per execution, and this digest answers
    the one question the pair rule asks. It is taken over the generated requests
    rather than over the plan object, so it binds what will actually be asked for.
    """
    document: dict[str, Any] = {
        "acquisition_mode": AcquisitionMode.QUALIFICATION.value,
        "provider": PROVIDER,
        "source_schema_version": plan.plan.source_schema_version,
        "response_format": plan.plan.response_format.value,
        "profile": plan.plan.profile.value,
        "max_response_bytes": plan.plan.limits.max_response_bytes,
        "max_run_bytes": plan.plan.limits.max_run_bytes,
        "request_count": len(plan.plan.requests()),
        "requests": [
            {
                "dataset": request.dataset.value,
                "subject": request.ticker,
                "page_limit": request.page.limit,
                "page_skip": request.page.skip,
            }
            for request in plan.plan.requests()
        ],
    }
    return sha256_hex(canonical_bytes(document))


def _retrieval_for(outcome: RequestOutcome, request: SharadarRequest, plan: EmpiricalPlan) -> Any:
    """Rebuild the exact :class:`RetrievalMetadata` the publisher used.

    Every input is a value the outcome or the plan already carries, so this is a
    reconstruction rather than a second decision. It exists because the runtime
    keeps its publication result private and reports the summary -- and the locator
    needs the three object identities that publication produced.
    """
    return RetrievalMetadata(
        provider=PROVIDER,
        dataset=request.dataset.value,
        requested_range=request.requested_range,
        retrieved_at=outcome.retrieved_at,
        source_schema_version=plan.plan.source_schema_version,
        ingestion_run_id=outcome.acquisition_id,
        acquisition_mode=AcquisitionMode.QUALIFICATION,
    )


def _disposition(written: bool) -> str:
    return (ObjectDisposition.WRITTEN if written else ObjectDisposition.ALREADY_PRESENT).value


def _entry_document(
    *,
    outcome: RequestOutcome,
    request: SharadarRequest,
    plan: EmpiricalPlan,
    request_ordinal: int,
) -> dict[str, Any]:
    """One locator entry: three exact keys, three digests, three byte counts.

    The claim and the record are rebuilt through the **accepted builders**, so their
    keys and canonical bytes are the publisher's own rather than a second rendering
    of the same idea.

    The payload key is rebuilt through the **ADR-0020 builder**, from the execution
    identity, this request's canonical ordinal and the digest -- the same pure
    function the acquisition router publishes through and the assessment
    reconstructs with. It cannot be rebuilt from its bytes, because the acquisition
    path no longer holds them: the runtime publishes the payload and reports only
    its digest and length.
    """
    retrieval = _retrieval_for(outcome, request, plan)
    digest = outcome.content_sha256

    claim_bytes = canonical_bytes(acquisition_claim(retrieval=retrieval, content_sha256=digest))
    claim_key = acquisition_claim_key(
        payload_digest=digest, run_id=outcome.acquisition_id, claim=claim_bytes
    )
    record_bytes = canonical_bytes(
        acquisition_record(
            retrieval=retrieval, content_sha256=digest, byte_count=outcome.byte_count
        )
    )
    record_key = bronze_acquisition_key(
        retrieval=retrieval, payload_digest=digest, record=record_bytes
    )
    payload_key = qualification_payload_key(
        dataset=request.dataset.value,
        execution_id=plan.plan.execution_id,
        request_ordinal=request_ordinal,
        content_sha256=digest,
    )

    return {
        "acquisition_id": outcome.acquisition_id,
        "dataset": request.dataset.value,
        "subject": request.ticker,
        "requested_range": request.requested_range,
        "page_limit": outcome.page_limit,
        "page_skip": outcome.page_skip,
        "claim_key": claim_key.logical_key,
        "claim_sha256": claim_key.content_sha256,
        "claim_bytes": len(claim_bytes),
        "claim_disposition": _disposition(outcome.claim_written),
        "payload_key": payload_key.logical_key,
        "payload_sha256": digest,
        "payload_bytes": outcome.byte_count,
        "payload_disposition": _disposition(outcome.payload_written),
        "record_key": record_key.logical_key,
        "record_sha256": record_key.content_sha256,
        "record_bytes": len(record_bytes),
        "record_disposition": _disposition(outcome.acquisition_written),
    }


def build_locator_document(
    *,
    plan: EmpiricalPlan,
    result: QualificationRunResult,
    run_started_at: datetime,
    run_completed_at: datetime,
) -> dict[str, Any]:
    """The complete locator document for one execution.

    Entries are produced in the plan's canonical request order, and each is checked
    against the request it claims to describe: an outcome whose dataset, subject or
    page disagrees with the request at its position would mean the result and the
    plan describe different runs, which is exactly the condition an integrity
    control exists to catch.

    Raises:
        LocatorError: ``RESULT_INCONSISTENT`` for a result that is not this plan's,
            or whose completed count does not match its outcomes;
            ``IDENTITY_MISMATCH`` for a mismatched coordinate or a duplicated
            acquisition identity; ``FIELD_MALFORMED`` for a non-UTC instant.
    """
    if type(result) is not QualificationRunResult or type(plan) is not EmpiricalPlan:
        raise _refuse(LocatorDefect.RESULT_INCONSISTENT) from None
    for instant in (run_started_at, run_completed_at):
        if type(instant) is not datetime or instant.tzinfo is None:
            raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    if run_completed_at < run_started_at:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None

    requests = plan.plan.requests()
    if result.planned_requests != len(requests):
        raise _refuse(LocatorDefect.RESULT_INCONSISTENT) from None
    if result.completed_requests != len(result.outcomes):
        raise _refuse(LocatorDefect.RESULT_INCONSISTENT) from None
    if result.completed_requests > len(requests):
        raise _refuse(LocatorDefect.RESULT_INCONSISTENT) from None

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for request_ordinal, (request, outcome) in enumerate(
        zip(requests, result.outcomes, strict=False)
    ):
        if (
            outcome.dataset is not request.dataset
            or outcome.subject != request.ticker
            or outcome.page_limit != request.page.limit
            or outcome.page_skip != request.page.skip
        ):
            raise _refuse(LocatorDefect.IDENTITY_MISMATCH) from None
        if outcome.acquisition_id in seen:
            raise _refuse(LocatorDefect.IDENTITY_MISMATCH) from None
        seen.add(outcome.acquisition_id)
        entries.append(
            _entry_document(
                outcome=outcome, request=request, plan=plan, request_ordinal=request_ordinal
            )
        )

    completeness = (
        Completeness.COMPLETE
        if result.outcome is QualificationOutcome.COMPLETED
        and result.completed_requests == result.planned_requests
        and not result.partial
        else Completeness.PARTIAL
    )

    return {
        "schema_version": LOCATOR_SCHEMA_VERSION,
        "classification": DataClassification.LICENSED.value,
        "provider": PROVIDER,
        "execution_id": plan.plan.execution_id,
        "acquisition_mode": AcquisitionMode.QUALIFICATION.value,
        "profile": PERMITTED_PROFILE.value,
        "plan_digest": plan_digest(plan),
        "inventory_digest": plan.inventory_digest,
        "source_schema_version": plan.plan.source_schema_version,
        "run_started_at": run_started_at.astimezone(UTC).isoformat(),
        "run_completed_at": run_completed_at.astimezone(UTC).isoformat(),
        "completeness": completeness.value,
        "publication_state_unknown": bool(result.publication_state_unknown),
        "planned_request_count": result.planned_requests,
        "completed_request_count": result.completed_requests,
        "entries": entries,
    }


def serialize_locator(document: dict[str, Any]) -> bytes:
    """Canonical bytes for one locator document, refused above the size ceiling.

    **Built once and held**, so every publication retry sends byte-identical
    content. Re-deriving it per attempt would read a new clock and produce a
    different document, which is how a retry stops being idempotent.

    Raises:
        LocatorError: ``TOO_LARGE`` above :data:`MAX_LOCATOR_BYTES`.
    """
    payload = canonical_bytes(document)
    if len(payload) > MAX_LOCATOR_BYTES:
        raise _refuse(LocatorDefect.TOO_LARGE) from None
    return payload


def locator_object_key(*, execution_id: str, payload: bytes) -> ObjectKey:
    """The LICENSED key one locator payload is published under."""
    return ObjectKey.licensed(*locator_key_segments(execution_id), payload=payload)


_DIGEST_LENGTH: Final = 64


def _hex_digest(value: object) -> str:
    if type(value) is not str or len(value) != _DIGEST_LENGTH:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    if any(character not in "0123456789abcdef" for character in value):
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    return value


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    return value


def _instant(value: object) -> datetime:
    text = _text(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    if parsed.tzinfo is None:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    return parsed


@dataclass(frozen=True, slots=True, kw_only=True)
class LocatorEntry:
    """One validated reference triple. Every field is grammar-bound."""

    acquisition_id: str
    dataset: str
    subject: str
    requested_range: str
    page_limit: int
    page_skip: int
    claim_key: str
    claim_sha256: str
    claim_bytes: int
    claim_disposition: ObjectDisposition
    payload_key: str
    payload_sha256: str
    payload_bytes: int
    payload_disposition: ObjectDisposition
    record_key: str
    record_sha256: str
    record_bytes: int
    record_disposition: ObjectDisposition

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a reference cannot be restated after validation."""
        raise TypeError("LocatorEntry may not be subclassed")


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedLocator:
    """A locator that passed its complete closed validation.

    **Producing one of these is the gate.** No object byte is read until an
    instance exists, which is what makes the validation a gate rather than a
    formality -- and a ``PARTIAL`` locator produces one too, so the accounting
    survives while :meth:`assessable` still says no.
    """

    execution_id: str
    #: The stable plan digest -- see :func:`plan_digest`. Two runs of one plan share
    #: it, which is exactly what the combined assessment's pair rule compares.
    plan_digest: str
    inventory_digest: str
    source_schema_version: str
    completeness: Completeness
    publication_state_unknown: bool
    planned_request_count: int
    completed_request_count: int
    entries: tuple[LocatorEntry, ...]
    #: When the acquisition execution phase started and ended, as the locator
    #: recorded them. Both were already validated as aware instants; they are
    #: carried onto the validated object because the **combined** assessment has to
    #: order Run A before Run B and measure the eight-calendar-day separation
    #: between them, and it may not learn either fact by listing or by guessing.
    run_started_at: datetime
    run_completed_at: datetime

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could override :meth:`assessable`."""
        raise TypeError("ValidatedLocator may not be subclassed")

    @property
    def run_date(self) -> date:
        """The UTC calendar date this execution's acquisition phase started.

        The separation between two runs is stated in **calendar days**, so it is
        measured on calendar dates rather than on elapsed seconds -- eight days
        apart is a claim about the provider having had eight chances to change
        something, not about 691,200 seconds having passed.
        """
        return self.run_started_at.astimezone(UTC).date()

    @property
    def assessable(self) -> bool:
        """Whether this locator may be evaluated at all.

        ``COMPLETE``, no ambiguity, and every planned request accounted for. A
        ``PARTIAL``, ambiguous or short locator **fails closed**: there is no
        fallback that reconstructs the missing part by listing, probing or
        guessing, because adding one would reintroduce the capability this
        architecture removes.
        """
        return (
            self.completeness is Completeness.COMPLETE
            and not self.publication_state_unknown
            and self.completed_request_count == self.planned_request_count
            and len(self.entries) == self.planned_request_count
        )


def _entry_from(raw: object) -> LocatorEntry:
    if type(raw) is not dict:
        raise _refuse(LocatorDefect.ENTRY_MALFORMED) from None
    names = set(raw)
    if names - LOCATOR_ENTRY_FIELDS:
        raise _refuse(LocatorDefect.FIELD_UNKNOWN) from None
    if LOCATOR_ENTRY_FIELDS - names:
        raise _refuse(LocatorDefect.FIELD_MISSING) from None

    dispositions: list[ObjectDisposition] = []
    for field in ("claim_disposition", "payload_disposition", "record_disposition"):
        try:
            dispositions.append(ObjectDisposition(_text(raw[field])))
        except ValueError:
            raise _refuse(LocatorDefect.FIELD_MALFORMED) from None

    return LocatorEntry(
        acquisition_id=_text(raw["acquisition_id"]),
        dataset=_text(raw["dataset"]),
        subject=_text(raw["subject"]),
        requested_range=_text(raw["requested_range"]),
        page_limit=_count(raw["page_limit"]),
        page_skip=_count(raw["page_skip"]),
        claim_key=_text(raw["claim_key"]),
        claim_sha256=_hex_digest(raw["claim_sha256"]),
        claim_bytes=_count(raw["claim_bytes"]),
        claim_disposition=dispositions[0],
        payload_key=_text(raw["payload_key"]),
        payload_sha256=_hex_digest(raw["payload_sha256"]),
        payload_bytes=_count(raw["payload_bytes"]),
        payload_disposition=dispositions[1],
        record_key=_text(raw["record_key"]),
        record_sha256=_hex_digest(raw["record_sha256"]),
        record_bytes=_count(raw["record_bytes"]),
        record_disposition=dispositions[2],
    )


def validate_locator_document(document: object, *, execution_id: str) -> ValidatedLocator:
    """Validate a decoded locator against its closed schema. **Reads nothing.**

    ``execution_id`` is the identity the assessor asked for, and it must be the one
    the document claims. A locator retrieved under one identity that describes
    another is either a collision or a mistake, and neither is resolved by reading
    it anyway.

    Raises:
        LocatorError: for a malformed document, an unknown or missing field, a
            wrong schema version, provider, classification, mode or profile, a
            malformed field, a duplicated entry, or counts the entries contradict.
    """
    if type(document) is not dict:
        raise _refuse(LocatorDefect.DOCUMENT_MALFORMED) from None
    names = set(document)
    if names - LOCATOR_FIELDS:
        raise _refuse(LocatorDefect.FIELD_UNKNOWN) from None
    if LOCATOR_FIELDS - names:
        raise _refuse(LocatorDefect.FIELD_MISSING) from None

    if document["schema_version"] != LOCATOR_SCHEMA_VERSION:
        raise _refuse(LocatorDefect.SCHEMA_VERSION_UNKNOWN) from None
    if document["classification"] != DataClassification.LICENSED.value:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    if document["provider"] != PROVIDER:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    if document["acquisition_mode"] != AcquisitionMode.QUALIFICATION.value:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    if document["profile"] != PERMITTED_PROFILE.value:
        # PUBLIC_PIT is not expressible anywhere in this package, and a locator
        # claiming it would be a claim about the provider nobody may make.
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    if document["execution_id"] != execution_id:
        raise _refuse(LocatorDefect.IDENTITY_MISMATCH) from None

    started = _instant(document["run_started_at"])
    completed = _instant(document["run_completed_at"])
    if completed < started:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None

    try:
        completeness = Completeness(_text(document["completeness"]))
    except ValueError:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None
    unknown_state = document["publication_state_unknown"]
    if type(unknown_state) is not bool:
        raise _refuse(LocatorDefect.FIELD_MALFORMED) from None

    planned = _count(document["planned_request_count"])
    completed_count = _count(document["completed_request_count"])
    if completed_count > planned:
        raise _refuse(LocatorDefect.RESULT_INCONSISTENT) from None

    raw_entries = document["entries"]
    if type(raw_entries) is not list:
        raise _refuse(LocatorDefect.DOCUMENT_MALFORMED) from None
    if len(raw_entries) != completed_count:
        raise _refuse(LocatorDefect.ENTRY_COUNT_INCONSISTENT) from None

    entries = tuple(_entry_from(raw) for raw in raw_entries)
    identities = {entry.acquisition_id for entry in entries}
    if len(identities) != len(entries):
        raise _refuse(LocatorDefect.ENTRY_DUPLICATED) from None
    keys = [entry.record_key for entry in entries]
    if len(set(keys)) != len(keys):
        # Two entries naming one acquisition record would mean two retrievals
        # sharing one durable identity, which is the defect the identity model
        # exists to remove.
        raise _refuse(LocatorDefect.ENTRY_DUPLICATED) from None
    if completeness is Completeness.COMPLETE and completed_count != planned:
        raise _refuse(LocatorDefect.RESULT_INCONSISTENT) from None

    return ValidatedLocator(
        execution_id=execution_id,
        plan_digest=_hex_digest(document["plan_digest"]),
        inventory_digest=_hex_digest(document["inventory_digest"]),
        source_schema_version=_text(document["source_schema_version"]),
        completeness=completeness,
        publication_state_unknown=unknown_state,
        planned_request_count=planned,
        completed_request_count=completed_count,
        entries=entries,
        run_started_at=started,
        run_completed_at=completed,
    )


def decode_locator(payload: bytes, *, execution_id: str) -> ValidatedLocator:
    """Decode and validate retrieved locator bytes. **Strict UTF-8, size-capped.**

    Raises:
        LocatorError: ``TOO_LARGE``, ``ENCODING_INVALID``, ``DOCUMENT_MALFORMED``,
            or any defect :func:`validate_locator_document` raises.
    """
    if type(payload) is not bytes:
        raise _refuse(LocatorDefect.DOCUMENT_MALFORMED) from None
    if len(payload) > MAX_LOCATOR_BYTES:
        raise _refuse(LocatorDefect.TOO_LARGE) from None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(LocatorDefect.ENCODING_INVALID) from None
    try:
        document = json.loads(text)
    except Exception:
        raise _refuse(LocatorDefect.DOCUMENT_MALFORMED) from None
    return validate_locator_document(document, execution_id=execution_id)


__all__ = [
    "LOCATOR_ENTRY_FIELDS",
    "LOCATOR_FIELDS",
    "LOCATOR_SCHEMA_VERSION",
    "LOCATOR_SEGMENTS",
    "MAX_LOCATOR_BYTES",
    "Completeness",
    "LocatorDefect",
    "LocatorEntry",
    "LocatorError",
    "ObjectDisposition",
    "ValidatedLocator",
    "build_locator_document",
    "decode_locator",
    "locator_key_segments",
    "locator_object_key",
    "plan_digest",
    "serialize_locator",
    "validate_locator_document",
]
