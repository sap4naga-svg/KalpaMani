"""The production run locator and its four validation clauses (ADR-0036 §2.4).

Every acquisition run publishes, **last** and conditionally, one run locator at
``licensed/bronze/sharadar/_indexes/<run-id>.json`` (at most 256 KiB, closed
schema, no free text). The build actor derives that key from a run identity in
its build input, retrieves it **by exact name**, validates it, and reads only what
it names -- the assessment's exact-read discipline applied to production, with the
full-object SHA-256 and byte count verified before any parse.

**Locator validation, before any object it names is read.** Every clause is a
refusal, and a refused locator reads nothing further:

1. **Identity binding** -- ``run_id`` equals the run identity that derived the key;
   ``plan_digest`` and ``slice`` equal the build input's ledger row for that run.
2. **Prefix allowlist** -- every key lies under the ADR-0037 production payload or
   record prefix of a dataset the slice declares, and every record key ends in
   this locator's own run identity and the entry's own ordinal. No claim, index,
   qualification, general-Bronze, Silver, Gold or manifest key is admissible,
   whatever IAM would permit.
3. **Request scope** -- the completed-request count equals the slice's request
   count; each ordinal appears exactly once; every payload key rebuilds exactly
   from the recorded dataset and digest; byte counts are within the slice's
   response ceiling.
4. **Completeness** -- ``COMPLETE``, ``publication_state_unknown = false``, a known
   schema version, and a size within the ceiling (checked before decoding).

**There is no fallback** that reconstructs by listing, probing or guessing.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.vocabulary import AcquisitionMode, DataClassification
from kalpamani.data.ingest.publication import BRONZE_NAMESPACE
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.production.sharadar.documents import (
    DocumentDefect,
    DocumentError,
    decode_document,
    exact_int,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.inputs import LedgerRow, Slice, parse_slice
from kalpamani.data.production.sharadar.keys import (
    ACQUISITIONS_SEGMENT,
    DIGEST_SEGMENT,
    OBJECTS_SEGMENT,
    PRODUCTION_SEGMENT,
    RUN_ID_RE,
    ProductionKeyError,
    production_acquisition_key_for_digest,
    production_payload_key_for_digest,
    request_ordinal_segment,
    run_locator_key_segments,
    run_locator_logical_key,
)
from kalpamani.data.qualify.sharadar.read import (
    MAX_READ_BYTES,
    ExactObjectReference,
    LicensedObjectReader,
    LicensedReadError,
    ReadFailure,
    ReadOperation,
    classified_read_failure,
    read_bounded_body,
)

#: The one schema version, matched exactly, and the size ceiling.
LOCATOR_SCHEMA_VERSION: Final = "kalpamani-production-run-locator/v1"
MAX_LOCATOR_BYTES: Final = 256 * 1024

#: The two production acquisition modes a run locator may record. A production
#: run is never a qualification.
PRODUCTION_MODES: Final[frozenset[str]] = frozenset(
    {AcquisitionMode.BACKFILL.value, AcquisitionMode.UPDATE.value}
)

_LICENSED: Final = DataClassification.LICENSED.value.lower()

LOCATOR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "run_id",
        "plan_digest",
        "slice",
        "acquisition_mode",
        "started_at",
        "completed_at",
        "completeness",
        "publication_state_unknown",
        "planned_requests",
        "completed_requests",
        "entries",
    }
)
ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "ordinal",
        "dataset",
        "payload_key",
        "payload_sha256",
        "payload_bytes",
        "payload_disposition",
        "record_key",
        "record_sha256",
        "record_bytes",
        "request",
    }
)
REQUEST_FIELDS: Final[frozenset[str]] = frozenset({"window", "page_offset", "page_limit"})


class Completeness(StrEnum):
    """Whether every planned request completed. ``PARTIAL`` grants no build."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class PayloadDisposition(StrEnum):
    """What one conditional payload write did to its content-addressed name.

    ``WRITTEN``
        This run's conditional ``PutObject`` created the object.
    ``ALREADY_PRESENT``
        The conditional write found the content-addressed name occupied. ADR-0035
        §3.1 treats identical bytes as an idempotent no-op on the payload; the
        acquisition actor reads nothing (ADR-0019), so what occupies the name is
        recorded as *undetermined by this run* and is proven -- or refused -- by the
        build actor's ``read_exact``, which verifies the digest before any byte is
        used. The claim and the record for the request are still written by this
        run, under names that carry the request ordinal.
    """

    WRITTEN = "WRITTEN"
    ALREADY_PRESENT = "ALREADY_PRESENT"


class RunLocatorDefect(StrEnum):
    """Why a run locator was refused. Closed, structural, and carrying no value."""

    EMPTY = "EMPTY"
    TOO_LARGE = "TOO_LARGE"
    ENCODING_INVALID = "ENCODING_INVALID"
    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    SCHEMA_VERSION_UNKNOWN = "SCHEMA_VERSION_UNKNOWN"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    ENTRY_MALFORMED = "ENTRY_MALFORMED"
    MODE_UNEXPECTED = "MODE_UNEXPECTED"
    INSTANTS_INCONSISTENT = "INSTANTS_INCONSISTENT"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    PLAN_DIGEST_MISMATCH = "PLAN_DIGEST_MISMATCH"
    SLICE_MISMATCH = "SLICE_MISMATCH"
    PREFIX_NOT_ALLOWED = "PREFIX_NOT_ALLOWED"
    DATASET_NOT_IN_SLICE = "DATASET_NOT_IN_SLICE"
    REQUEST_COUNT_MISMATCH = "REQUEST_COUNT_MISMATCH"
    ORDINAL_INCONSISTENT = "ORDINAL_INCONSISTENT"
    KEY_DIGEST_MISMATCH = "KEY_DIGEST_MISMATCH"
    BYTES_OVER_CEILING = "BYTES_OVER_CEILING"
    INCOMPLETE = "INCOMPLETE"
    PUBLICATION_STATE_UNKNOWN = "PUBLICATION_STATE_UNKNOWN"
    NO_LEDGER_ROW = "NO_LEDGER_ROW"


class RunLocatorError(Exception):
    """A refusal carrying exactly one :class:`RunLocatorDefect`, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: RunLocatorDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not RunLocatorDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact RunLocatorDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: RunLocatorDefect) -> RunLocatorError:
    return RunLocatorError(defect)


#: Total: every document defect has a locator defect. A test asserts totality.
_DOCUMENT_DEFECTS: Final[dict[DocumentDefect, RunLocatorDefect]] = {
    DocumentDefect.EMPTY: RunLocatorDefect.EMPTY,
    DocumentDefect.TOO_LARGE: RunLocatorDefect.TOO_LARGE,
    DocumentDefect.ENCODING_INVALID: RunLocatorDefect.ENCODING_INVALID,
    DocumentDefect.DOCUMENT_MALFORMED: RunLocatorDefect.DOCUMENT_MALFORMED,
    DocumentDefect.DUPLICATE_KEY: RunLocatorDefect.DUPLICATE_KEY,
}


def decode_run_locator(raw: object) -> dict[str, Any]:
    """The closed object of one locator, refused above 256 KiB **before decoding**."""
    try:
        return decode_document(raw, max_bytes=MAX_LOCATOR_BYTES)
    except DocumentError as error:
        raise _refuse(_DOCUMENT_DEFECTS[error.defect]) from None


@dataclass(frozen=True, slots=True, kw_only=True)
class RunLocatorEntry:
    """One completed request: two exact references and the request coordinates."""

    ordinal: int
    dataset: str
    payload: ExactObjectReference
    payload_disposition: PayloadDisposition
    record: ExactObjectReference
    window: str
    page_offset: int
    page_limit: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("RunLocatorEntry may not be subclassed")

    def __repr__(self) -> str:
        """Ordinal and dataset. **Never a key or a digest.**"""
        return f"RunLocatorEntry(ordinal={self.ordinal}, dataset={self.dataset!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedRunLocator:
    """A run locator every clause admitted. Only this may name a read."""

    run_id: str
    plan_digest: str
    slice: Slice
    acquisition_mode: str
    started_at: datetime
    completed_at: datetime
    entries: tuple[RunLocatorEntry, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("ValidatedRunLocator may not be subclassed")

    def __repr__(self) -> str:
        """Counts only. **Never the identity, and never a digest.**"""
        return f"ValidatedRunLocator(entries={len(self.entries)})"

    @property
    def object_count(self) -> int:
        """How many objects this locator names: two per entry."""
        return 2 * len(self.entries)

    def exact_references(self) -> tuple[ExactObjectReference, ...]:
        """Every reference this locator names, payload then record, in ordinal order."""
        references: list[ExactObjectReference] = []
        for entry in self.entries:
            references.append(entry.payload)
            references.append(entry.record)
        return tuple(references)


def _allowed_prefix(key: str, *, dataset: str, run_id: str, ordinal: str, kind: str) -> None:
    """Clause 2 for one key: under the production prefix of this dataset, and no other."""
    base = f"{_LICENSED}/{BRONZE_NAMESPACE}/{PROVIDER}/{dataset}/{PRODUCTION_SEGMENT}/"
    if kind == "payload":
        prefix = f"{base}{OBJECTS_SEGMENT}/{DIGEST_SEGMENT}/"
        if not key.startswith(prefix):
            raise _refuse(RunLocatorDefect.PREFIX_NOT_ALLOWED) from None
        return
    prefix = f"{base}{ACQUISITIONS_SEGMENT}/"
    if not key.startswith(prefix) or not key.endswith(f"/{run_id}.{ordinal}.json"):
        raise _refuse(RunLocatorDefect.PREFIX_NOT_ALLOWED) from None


def _entry(raw: object, *, covered: Slice, run_id: str) -> RunLocatorEntry:
    if type(raw) is not dict or set(raw) != ENTRY_FIELDS:
        raise _refuse(RunLocatorDefect.ENTRY_MALFORMED) from None
    ordinal = exact_int(raw["ordinal"])
    dataset = exact_str(raw["dataset"])
    payload_key = exact_str(raw["payload_key"])
    payload_digest = hex_digest(raw["payload_sha256"])
    payload_bytes = exact_int(raw["payload_bytes"])
    disposition = exact_str(raw["payload_disposition"])
    record_key = exact_str(raw["record_key"])
    record_digest = hex_digest(raw["record_sha256"])
    record_bytes = exact_int(raw["record_bytes"])
    request = raw["request"]
    if (
        ordinal is None
        or dataset is None
        or payload_key is None
        or payload_digest is None
        or payload_bytes is None
        or disposition is None
        or disposition not in {member.value for member in PayloadDisposition}
        or record_key is None
        or record_digest is None
        or record_bytes is None
        or type(request) is not dict
        or set(request) != REQUEST_FIELDS
    ):
        raise _refuse(RunLocatorDefect.ENTRY_MALFORMED) from None
    window = exact_str(request["window"])
    page_offset = exact_int(request["page_offset"])
    page_limit = exact_int(request["page_limit"])
    if window is None or page_offset is None or page_limit is None or page_limit < 1:
        raise _refuse(RunLocatorDefect.ENTRY_MALFORMED) from None

    # Clause 2: the prefix allowlist, before any exact reconstruction.
    if dataset not in covered.datasets:
        raise _refuse(RunLocatorDefect.DATASET_NOT_IN_SLICE) from None
    try:
        ordinal_segment = request_ordinal_segment(ordinal)
    except ProductionKeyError:
        raise _refuse(RunLocatorDefect.ENTRY_MALFORMED) from None
    _allowed_prefix(
        payload_key, dataset=dataset, run_id=run_id, ordinal=ordinal_segment, kind="payload"
    )
    _allowed_prefix(
        record_key, dataset=dataset, run_id=run_id, ordinal=ordinal_segment, kind="record"
    )
    if dict(covered.windows)[dataset] != window:
        raise _refuse(RunLocatorDefect.SLICE_MISMATCH) from None

    # Clause 3, per entry: the key embeds exactly the recorded digest, rebuilt
    # through the one production key builder rather than parsed out of the string.
    try:
        expected_payload = production_payload_key_for_digest(
            dataset=dataset, content_sha256=payload_digest
        ).logical_key
        expected_record = production_acquisition_key_for_digest(
            dataset=dataset,
            payload_digest=payload_digest,
            run_id=run_id,
            ordinal=ordinal,
            content_sha256=record_digest,
        ).logical_key
    except ProductionKeyError:
        raise _refuse(RunLocatorDefect.KEY_DIGEST_MISMATCH) from None
    if payload_key != expected_payload or record_key != expected_record:
        raise _refuse(RunLocatorDefect.KEY_DIGEST_MISMATCH) from None
    if payload_bytes > covered.max_response_bytes or record_bytes > MAX_READ_BYTES:
        raise _refuse(RunLocatorDefect.BYTES_OVER_CEILING) from None

    try:
        payload = ExactObjectReference(
            logical_key=payload_key, expected_sha256=payload_digest, expected_bytes=payload_bytes
        )
        record = ExactObjectReference(
            logical_key=record_key, expected_sha256=record_digest, expected_bytes=record_bytes
        )
    except LicensedReadError:
        raise _refuse(RunLocatorDefect.ENTRY_MALFORMED) from None
    return RunLocatorEntry(
        ordinal=ordinal,
        dataset=dataset,
        payload=payload,
        payload_disposition=PayloadDisposition(disposition),
        record=record,
        window=window,
        page_offset=page_offset,
        page_limit=page_limit,
    )


def validate_run_locator(
    document: object, *, run_id: str, ledger_row: LedgerRow | None
) -> ValidatedRunLocator:
    """Every clause of §2.4 over an already-decoded locator. **Reads nothing.**

    The clauses run in the order the ADR states them, after the closed shape:
    identity binding, then the per-entry prefix allowlist and request scope, then
    completeness. A build input without a ledger row for this run cannot bind the
    locator and refuses before any clause.

    Raises:
        RunLocatorError: one closed :class:`RunLocatorDefect`; never a value.
    """
    if type(run_id) is not str or not RUN_ID_RE.match(run_id):
        raise _refuse(RunLocatorDefect.IDENTITY_MISMATCH) from None
    if type(ledger_row) is not LedgerRow:
        raise _refuse(RunLocatorDefect.NO_LEDGER_ROW) from None
    if ledger_row.run_identity != run_id:
        raise _refuse(RunLocatorDefect.NO_LEDGER_ROW) from None
    if type(document) is not dict:
        raise _refuse(RunLocatorDefect.DOCUMENT_MALFORMED) from None
    names = set(document)
    if names - LOCATOR_FIELDS:
        raise _refuse(RunLocatorDefect.FIELD_UNKNOWN) from None
    if LOCATOR_FIELDS - names:
        raise _refuse(RunLocatorDefect.FIELD_MISSING) from None
    schema = exact_str(document["schema_version"])
    if schema is None:
        raise _refuse(RunLocatorDefect.FIELD_MALFORMED) from None
    if schema != LOCATOR_SCHEMA_VERSION:
        raise _refuse(RunLocatorDefect.SCHEMA_VERSION_UNKNOWN) from None

    declared_run = exact_str(document["run_id"])
    plan_digest = hex_digest(document["plan_digest"])
    mode = exact_str(document["acquisition_mode"])
    started_at = instant(document["started_at"])
    completed_at = instant(document["completed_at"])
    completeness = exact_str(document["completeness"])
    unknown = document["publication_state_unknown"]
    planned = exact_int(document["planned_requests"])
    completed = exact_int(document["completed_requests"])
    entries = document["entries"]
    if (
        declared_run is None
        or plan_digest is None
        or mode is None
        or started_at is None
        or completed_at is None
        or completeness is None
        or completeness not in {member.value for member in Completeness}
        or type(unknown) is not bool
        or planned is None
        or completed is None
        or type(entries) is not list
    ):
        raise _refuse(RunLocatorDefect.FIELD_MALFORMED) from None
    if mode not in PRODUCTION_MODES:
        raise _refuse(RunLocatorDefect.MODE_UNEXPECTED) from None
    if completed_at < started_at:
        raise _refuse(RunLocatorDefect.INSTANTS_INCONSISTENT) from None
    try:
        covered = parse_slice(document["slice"])
    except Exception:
        raise _refuse(RunLocatorDefect.FIELD_MALFORMED) from None

    if mode != covered.acquisition_mode:
        raise _refuse(RunLocatorDefect.MODE_UNEXPECTED) from None

    # Clause 1: identity binding.
    if declared_run != run_id:
        raise _refuse(RunLocatorDefect.IDENTITY_MISMATCH) from None
    if plan_digest != ledger_row.plan_digest:
        raise _refuse(RunLocatorDefect.PLAN_DIGEST_MISMATCH) from None
    if covered.canonical() != ledger_row.slice.canonical():
        raise _refuse(RunLocatorDefect.SLICE_MISMATCH) from None

    # Clauses 2 and 3, per entry, then the counts.
    parsed = tuple(_entry(raw, covered=covered, run_id=run_id) for raw in entries)
    if not (planned == completed == covered.request_count == len(parsed)):
        raise _refuse(RunLocatorDefect.REQUEST_COUNT_MISMATCH) from None
    if sorted(entry.ordinal for entry in parsed) != list(range(len(parsed))):
        raise _refuse(RunLocatorDefect.ORDINAL_INCONSISTENT) from None

    # Clause 4: completeness.
    if completeness != Completeness.COMPLETE.value:
        raise _refuse(RunLocatorDefect.INCOMPLETE) from None
    if unknown:
        raise _refuse(RunLocatorDefect.PUBLICATION_STATE_UNKNOWN) from None

    return ValidatedRunLocator(
        run_id=run_id,
        plan_digest=plan_digest,
        slice=covered,
        acquisition_mode=mode,
        started_at=started_at,
        completed_at=completed_at,
        entries=tuple(sorted(parsed, key=lambda entry: entry.ordinal)),
    )


# ---------------------------------------------------------------------------
# The build actor's read surface: one by-name read, then exact reads only
# ---------------------------------------------------------------------------


class GetOnlyS3Client(Protocol):
    """The **one** S3 operation the build actor's reads use. No put, head, list."""

    def get_object(self, **kwargs: Any) -> Any:
        """Read one object."""
        ...


class _GetOnlyView:
    """Adapts a get-only client to the accepted reader's shape without widening it.

    The accepted :class:`LicensedObjectReader` binds a client carrying ``put_object``
    and ``head_object`` because the assessment publishes a report. The build
    actor's reads never do, so the two write-shaped methods here **refuse**: they
    exist to satisfy the binding check, and a call to either is a defect.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: GetOnlyS3Client) -> None:
        self._inner = inner

    def get_object(self, **kwargs: Any) -> Any:
        return self._inner.get_object(**kwargs)

    def put_object(self, **kwargs: Any) -> Any:
        raise LicensedReadError(operation=ReadOperation.PUT, failure=ReadFailure.ACCESS_DENIED)

    def head_object(self, **kwargs: Any) -> Any:
        raise LicensedReadError(operation=ReadOperation.HEAD, failure=ReadFailure.ACCESS_DENIED)


class ProductionLocatorReader:
    """One by-name locator read, then exact reads of only what it names.

    ``read_exact`` **is** the accepted reader's: the same byte-count and digest
    verification before any byte is returned, reached through a get-only view of
    the injected client. The by-name read is restricted to the run-locator prefix
    and bounded while reading, on the same discipline as the assessment locator.
    """

    __slots__ = ("_bucket", "_client", "_reader")

    def __init__(self, *, client: GetOnlyS3Client, licensed_bucket: str) -> None:
        """Bind an injected get-only client to one licensed bucket."""
        if not callable(getattr(client, "get_object", None)):
            raise LicensedReadError(
                operation=ReadOperation.BIND, failure=ReadFailure.INVALID_CONFIGURATION
            )
        self._client = client
        self._reader = LicensedObjectReader(
            client=_GetOnlyView(client), licensed_bucket=licensed_bucket
        )
        self._bucket = licensed_bucket

    @property
    def get_object_count(self) -> int:
        """Every ``GetObject`` issued through this reader, locator included."""
        return self._reader.get_object_count

    def read_run_locator_bytes(self, run_id: str) -> bytes:
        """The bytes of the one object addressed by the run identity, bounded while reading.

        Raises:
            LicensedReadError: ``GET: INVALID_KEY`` for an identity that cannot name
                a locator; ``GET: TOO_LARGE`` above 256 KiB; the closed backend
                categories for anything the store refused.
        """
        try:
            segments = run_locator_key_segments(run_id)
        except ProductionKeyError:
            raise LicensedReadError(
                operation=ReadOperation.GET, failure=ReadFailure.INVALID_KEY
            ) from None
        self._reader.get_object_count += 1
        try:
            response = self._client.get_object(Bucket=self._bucket, Key="/".join(segments))
        except Exception as exception:
            raise classified_read_failure(exception, ReadOperation.GET) from None
        return read_bounded_body(response, ceiling=MAX_LOCATOR_BYTES)

    def read_run_locator(self, *, run_id: str, ledger_row: LedgerRow | None) -> ValidatedRunLocator:
        """Retrieve, decode and validate one run locator. Every clause, before any read."""
        raw = self.read_run_locator_bytes(run_id)
        return validate_run_locator(decode_run_locator(raw), run_id=run_id, ledger_row=ledger_row)

    def read_exact(self, reference: ExactObjectReference) -> bytes:
        """The verified bytes of one referenced object -- the accepted reader's read."""
        return self._reader.read_exact(reference)

    def iter_locator_objects(
        self, locator: ValidatedRunLocator
    ) -> Iterator[tuple[RunLocatorEntry, bytes, bytes]]:
        """Every entry's verified payload and record bytes, in ordinal order.

        Keys come from the validated locator and from nowhere else; a caller that
        wanted another object has no way to ask for it here.
        """
        if type(locator) is not ValidatedRunLocator:
            raise LicensedReadError(operation=ReadOperation.GET, failure=ReadFailure.INVALID_KEY)
        for entry in locator.entries:
            yield entry, self.read_exact(entry.payload), self.read_exact(entry.record)


__all__ = [
    "ENTRY_FIELDS",
    "LOCATOR_FIELDS",
    "LOCATOR_SCHEMA_VERSION",
    "MAX_LOCATOR_BYTES",
    "PRODUCTION_MODES",
    "REQUEST_FIELDS",
    "Completeness",
    "GetOnlyS3Client",
    "PayloadDisposition",
    "ProductionLocatorReader",
    "RunLocatorDefect",
    "RunLocatorEntry",
    "RunLocatorError",
    "ValidatedRunLocator",
    "decode_run_locator",
    "run_locator_logical_key",
    "validate_run_locator",
]
