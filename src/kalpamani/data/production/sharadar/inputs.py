"""The acquisition and build input contracts (ADR-0036 §2.6).

A task can reach no file on the owner's workstation, and no private value may
enter argv or a task-definition environment variable. Each actor therefore has
**one fixed-name input parameter** -- advanced tier, at most 8 KiB, refused above
that **before parsing** -- validated by a closed schema of its own:

| | acquisition input | build input |
|---|---|---|
| identity | one single-use ``run_identity`` | one ``build_identity`` |
| content | the slice and the plan digest | the ordered run identities, each with its ledger row |
| integrity | ``plan_digest`` equals the compiled one | ``ledger_digest`` is the rows' SHA-256 |
| validity | ``issued_at <= now < expires_at``, ``expires_at - issued_at <= 24 h`` | the same |
| ceiling | -- | at most 32 run identities, each distinct |

**The plan digest is verified against the compiled plan, not against a supplied
number.** :func:`parse_acquisition_input` admits the slice's shape and the digest's
grammar; :func:`kalpamani.data.production.sharadar.plan.bind_plan` then compiles
the plan **from that slice** and refuses the input unless the compiled digest
equals the one the input carries. A document cannot supply the comparison value.

**A spent or unknowable run identity refuses.** The registry is injected and
answers ``UNSPENT``, ``SPENT`` or ``UNAVAILABLE``; only the first admits the input.
That is the preliminary check -- the durable guard is the conditional claim write
(see :mod:`kalpamani.data.production.sharadar.identities`).

**The input digest is over the delivered bytes.** The placement release binds
``input_digest`` to "the SHA-256 of the input document the launch tool
materialized", so the digest is computed over the exact bytes read, before any
decoding, and never over a re-serialization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.production.sharadar.documents import (
    DocumentDefect,
    DocumentError,
    decode_document,
    exact_int,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.identities import (
    SpentIdentityRegistry,
    SpentStatus,
    spent_status_of,
)
from kalpamani.data.production.sharadar.keys import PRODUCTION_DATASETS, RUN_ID_RE
from kalpamani.data.production.sharadar.vocabulary import (
    MAX_ADVANCED_PARAMETER_BYTES,
    ProductionActor,
    constants_for,
)

#: The one schema version either input admits.
INPUT_SCHEMA_VERSION: Final = 1

#: The longest an input may be valid for, and the most runs one build may cover.
MAX_INPUT_VALIDITY: Final = timedelta(hours=24)
MAX_BUILD_RUNS: Final = 32

#: A request count and a response ceiling a slice may declare. The request ceiling
#: is the empirical package's two-run maximum; the byte ceiling is the transport's hard cap.
MAX_SLICE_REQUESTS: Final = 96
MAX_RESPONSE_BYTES: Final = 256 * 1024 * 1024

#: The ledger outcome a build may read from. A run that did not complete has no
#: complete locator, and a build that read one would be reading a subset nobody
#: chose.
LEDGER_OUTCOME_COMPLETED: Final = "COMPLETED"
LEDGER_OUTCOMES: Final[frozenset[str]] = frozenset(
    {LEDGER_OUTCOME_COMPLETED, "MISPLACED", "REFUSED", "HALTED"}
)

_ACQUISITION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "run_identity",
        "slice",
        "plan_digest",
        "issued_at",
        "expires_at",
    }
)
_BUILD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "build_identity",
        "runs",
        "ledger_digest",
        "issued_at",
        "expires_at",
    }
)
_SLICE_FIELDS: Final[frozenset[str]] = frozenset(
    {"acquisition_mode", "datasets", "windows", "request_count", "max_response_bytes"}
)

#: The two modes a production slice may declare (ADR-0035 §3.1). Declared by the
#: plan, recorded in every record, never inferred -- and never a qualification.
SLICE_MODES: Final[frozenset[str]] = frozenset(
    {AcquisitionMode.BACKFILL.value, AcquisitionMode.UPDATE.value}
)
_ROW_FIELDS: Final[frozenset[str]] = frozenset(
    {"run_identity", "slice", "plan_digest", "outcome", "launched_at", "completed_at"}
)

#: A named window: ``SNAPSHOT``, or ``YYYY-MM-DD/YYYY-MM-DD``. Shape only; the
#: calendar semantics belong to the plan that produced the slice.
_WINDOW_RE: Final = re.compile(r"SNAPSHOT|\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}")


class InputDefect(StrEnum):
    """Why an input was refused. Closed, structural, and carrying no value."""

    UNREADABLE = "UNREADABLE"
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
    IDENTITY_MALFORMED = "IDENTITY_MALFORMED"
    IDENTITY_SPENT = "IDENTITY_SPENT"
    IDENTITY_STATUS_UNAVAILABLE = "IDENTITY_STATUS_UNAVAILABLE"
    IDENTITY_DUPLICATED = "IDENTITY_DUPLICATED"
    SLICE_MALFORMED = "SLICE_MALFORMED"
    PLAN_DIGEST_MISMATCH = "PLAN_DIGEST_MISMATCH"
    PLAN_NOT_COMPILABLE = "PLAN_NOT_COMPILABLE"
    VALIDITY_MALFORMED = "VALIDITY_MALFORMED"
    VALIDITY_TOO_LONG = "VALIDITY_TOO_LONG"
    NOT_YET_VALID = "NOT_YET_VALID"
    EXPIRED = "EXPIRED"
    TOO_MANY_RUNS = "TOO_MANY_RUNS"
    NO_RUNS = "NO_RUNS"
    ROW_MALFORMED = "ROW_MALFORMED"
    ROW_NOT_COMPLETED = "ROW_NOT_COMPLETED"
    LEDGER_DIGEST_MISMATCH = "LEDGER_DIGEST_MISMATCH"


class InputError(Exception):
    """A refusal carrying exactly one :class:`InputDefect`, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: InputDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not InputDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact InputDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: InputDefect) -> InputError:
    return InputError(defect)


#: Total: every document defect has an input defect. A test asserts totality.
_DOCUMENT_DEFECTS: Final[dict[DocumentDefect, InputDefect]] = {
    DocumentDefect.EMPTY: InputDefect.EMPTY,
    DocumentDefect.TOO_LARGE: InputDefect.TOO_LARGE,
    DocumentDefect.ENCODING_INVALID: InputDefect.ENCODING_INVALID,
    DocumentDefect.DOCUMENT_MALFORMED: InputDefect.DOCUMENT_MALFORMED,
    DocumentDefect.DUPLICATE_KEY: InputDefect.DUPLICATE_KEY,
}


def input_digest(raw: bytes) -> str:
    """The SHA-256 of the delivered input bytes: what a release must name."""
    if type(raw) is not bytes:
        raise _refuse(InputDefect.DOCUMENT_MALFORMED) from None
    return sha256_hex(raw)


def decode_input(raw: object) -> dict[str, Any]:
    """The closed object of one input parameter, refused above 8 KiB before parsing."""
    try:
        return decode_document(raw, max_bytes=MAX_ADVANCED_PARAMETER_BYTES)
    except DocumentError as error:
        raise _refuse(_DOCUMENT_DEFECTS[error.defect]) from None


@dataclass(frozen=True, slots=True, kw_only=True)
class Slice:
    """What one acquisition run covers: mode, datasets, their windows, two ceilings."""

    acquisition_mode: str
    datasets: tuple[str, ...]
    windows: tuple[tuple[str, str], ...]
    request_count: int
    max_response_bytes: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("Slice may not be subclassed")

    def canonical(self) -> dict[str, Any]:
        """The slice as the closed document it came from, for exact comparison."""
        return {
            "acquisition_mode": self.acquisition_mode,
            "datasets": list(self.datasets),
            "windows": dict(self.windows),
            "request_count": self.request_count,
            "max_response_bytes": self.max_response_bytes,
        }


def parse_slice(raw: object) -> Slice:
    """Validate one slice object. Datasets are the provider's, sorted and distinct.

    Raises:
        InputError: ``SLICE_MALFORMED`` for any structural defect.
    """
    if type(raw) is not dict or set(raw) != _SLICE_FIELDS:
        raise _refuse(InputDefect.SLICE_MALFORMED) from None
    mode = exact_str(raw["acquisition_mode"])
    if mode is None or mode not in SLICE_MODES:
        raise _refuse(InputDefect.SLICE_MALFORMED) from None
    datasets = raw["datasets"]
    if type(datasets) is not list or not datasets:
        raise _refuse(InputDefect.SLICE_MALFORMED) from None
    for dataset in datasets:
        if type(dataset) is not str or dataset not in PRODUCTION_DATASETS:
            raise _refuse(InputDefect.SLICE_MALFORMED) from None
    if datasets != sorted(set(datasets)):
        raise _refuse(InputDefect.SLICE_MALFORMED) from None
    windows = raw["windows"]
    if type(windows) is not dict or set(windows) != set(datasets):
        raise _refuse(InputDefect.SLICE_MALFORMED) from None
    for window in windows.values():
        if type(window) is not str or not _WINDOW_RE.fullmatch(window):
            raise _refuse(InputDefect.SLICE_MALFORMED) from None
    request_count = exact_int(raw["request_count"])
    if request_count is None or not 1 <= request_count <= MAX_SLICE_REQUESTS:
        raise _refuse(InputDefect.SLICE_MALFORMED) from None
    ceiling = exact_int(raw["max_response_bytes"])
    if ceiling is None or not 1 <= ceiling <= MAX_RESPONSE_BYTES:
        raise _refuse(InputDefect.SLICE_MALFORMED) from None
    return Slice(
        acquisition_mode=mode,
        datasets=tuple(datasets),
        windows=tuple((dataset, windows[dataset]) for dataset in datasets),
        request_count=request_count,
        max_response_bytes=ceiling,
    )


def _identity(value: object) -> str:
    text = exact_str(value)
    if text is None or not RUN_ID_RE.match(text):
        raise _refuse(InputDefect.IDENTITY_MALFORMED) from None
    return text


def _validity(document: dict[str, Any], *, now: datetime) -> tuple[datetime, datetime]:
    if type(now) is not datetime or now.tzinfo is None:
        raise _refuse(InputDefect.VALIDITY_MALFORMED) from None
    issued_at = instant(document["issued_at"])
    expires_at = instant(document["expires_at"])
    if issued_at is None or expires_at is None or expires_at <= issued_at:
        raise _refuse(InputDefect.VALIDITY_MALFORMED) from None
    if expires_at - issued_at > MAX_INPUT_VALIDITY:
        raise _refuse(InputDefect.VALIDITY_TOO_LONG) from None
    if now < issued_at:
        raise _refuse(InputDefect.NOT_YET_VALID) from None
    if now >= expires_at:
        raise _refuse(InputDefect.EXPIRED) from None
    return issued_at, expires_at


def _envelope(document: dict[str, Any], *, fields: frozenset[str], contract_id: str) -> None:
    names = set(document)
    if names - fields:
        raise _refuse(InputDefect.FIELD_UNKNOWN) from None
    if fields - names:
        raise _refuse(InputDefect.FIELD_MISSING) from None
    version = document["schema_version"]
    if type(version) is not int:
        raise _refuse(InputDefect.FIELD_MALFORMED) from None
    if version != INPUT_SCHEMA_VERSION:
        raise _refuse(InputDefect.SCHEMA_VERSION_UNKNOWN) from None
    contract = exact_str(document["contract_id"])
    if contract is None:
        raise _refuse(InputDefect.FIELD_MALFORMED) from None
    if contract != contract_id:
        raise _refuse(InputDefect.CONTRACT_ID_UNKNOWN) from None


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionInput:
    """One validated acquisition input: a single-use run identity and its slice."""

    run_identity: str
    slice: Slice
    plan_digest: str
    issued_at: datetime
    expires_at: datetime

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("AcquisitionInput may not be subclassed")

    def __repr__(self) -> str:
        """Counts only. **Never the identity, and never the digest.**"""
        return f"AcquisitionInput(requests={self.slice.request_count})"


def parse_acquisition_input(
    document: object,
    *,
    now: datetime,
    registry: SpentIdentityRegistry,
) -> AcquisitionInput:
    """Validate an already-decoded acquisition input. **Reads nothing.**

    The plan digest is admitted here for grammar only; whether it is the digest of
    the plan compiled from this slice is decided by
    :func:`kalpamani.data.production.sharadar.plan.bind_plan`, which every caller
    that goes on to acquire must call. ``registry`` answers whether the run identity
    has been used: ``SPENT`` refuses as ``IDENTITY_SPENT``, and ``UNAVAILABLE`` --
    including a registry that raises or answers with a non-member -- refuses as
    ``IDENTITY_STATUS_UNAVAILABLE``.

    Raises:
        InputError: one closed :class:`InputDefect`; never a value.
    """
    if type(document) is not dict:
        raise _refuse(InputDefect.DOCUMENT_MALFORMED) from None
    constants = constants_for(ProductionActor.ACQUISITION)
    _envelope(document, fields=_ACQUISITION_FIELDS, contract_id=constants.input_contract_id)
    run_identity = _identity(document["run_identity"])
    covered = parse_slice(document["slice"])
    plan_digest = hex_digest(document["plan_digest"])
    if plan_digest is None:
        raise _refuse(InputDefect.FIELD_MALFORMED) from None
    issued_at, expires_at = _validity(document, now=now)
    status = spent_status_of(registry, run_identity)
    if status is SpentStatus.SPENT:
        raise _refuse(InputDefect.IDENTITY_SPENT) from None
    if status is not SpentStatus.UNSPENT:
        raise _refuse(InputDefect.IDENTITY_STATUS_UNAVAILABLE) from None
    return AcquisitionInput(
        run_identity=run_identity,
        slice=covered,
        plan_digest=plan_digest,
        issued_at=issued_at,
        expires_at=expires_at,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerRow:
    """The owner's slice-ledger row for one completed acquisition run."""

    run_identity: str
    slice: Slice
    plan_digest: str
    outcome: str
    launched_at: datetime
    completed_at: datetime

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("LedgerRow may not be subclassed")

    def __repr__(self) -> str:
        """The outcome only. **Never the identity, and never the digest.**"""
        return f"LedgerRow(outcome={self.outcome!r})"


def _row(raw: object) -> LedgerRow:
    if type(raw) is not dict or set(raw) != _ROW_FIELDS:
        raise _refuse(InputDefect.ROW_MALFORMED) from None
    try:
        run_identity = _identity(raw["run_identity"])
        covered = parse_slice(raw["slice"])
    except InputError:
        raise _refuse(InputDefect.ROW_MALFORMED) from None
    plan_digest = hex_digest(raw["plan_digest"])
    outcome = exact_str(raw["outcome"])
    launched_at = instant(raw["launched_at"])
    completed_at = instant(raw["completed_at"])
    if (
        plan_digest is None
        or outcome is None
        or outcome not in LEDGER_OUTCOMES
        or launched_at is None
        or completed_at is None
        or completed_at < launched_at
    ):
        raise _refuse(InputDefect.ROW_MALFORMED) from None
    if outcome != LEDGER_OUTCOME_COMPLETED:
        raise _refuse(InputDefect.ROW_NOT_COMPLETED) from None
    return LedgerRow(
        run_identity=run_identity,
        slice=covered,
        plan_digest=plan_digest,
        outcome=outcome,
        launched_at=launched_at,
        completed_at=completed_at,
    )


def ledger_digest(rows: object) -> str:
    """The SHA-256 of the canonical serialization of the embedded ledger rows.

    Computed over the rows **as delivered** -- the raw list -- so a task and the
    launch tool that wrote the input agree byte for byte, and a row reordered or
    altered in transit changes the digest.
    """
    return sha256_hex(canonical_bytes(rows))


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildInput:
    """One validated build input: an identity and the ordered runs to build from."""

    build_identity: str
    runs: tuple[LedgerRow, ...]
    ledger_digest: str
    issued_at: datetime
    expires_at: datetime

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("BuildInput may not be subclassed")

    def __repr__(self) -> str:
        """The run count only. **Never an identity, and never a digest.**"""
        return f"BuildInput(runs={len(self.runs)})"

    def row_for(self, run_identity: str) -> LedgerRow | None:
        """The embedded row for one run identity, or ``None``."""
        for row in self.runs:
            if row.run_identity == run_identity:
                return row
        return None


def parse_build_input(document: object, *, now: datetime) -> BuildInput:
    """Validate an already-decoded build input. **Reads nothing.**

    Raises:
        InputError: one closed :class:`InputDefect`; never a value.
    """
    if type(document) is not dict:
        raise _refuse(InputDefect.DOCUMENT_MALFORMED) from None
    constants = constants_for(ProductionActor.BUILD)
    _envelope(document, fields=_BUILD_FIELDS, contract_id=constants.input_contract_id)
    build_identity = _identity(document["build_identity"])
    raw_rows = document["runs"]
    if type(raw_rows) is not list:
        raise _refuse(InputDefect.FIELD_MALFORMED) from None
    if not raw_rows:
        raise _refuse(InputDefect.NO_RUNS) from None
    if len(raw_rows) > MAX_BUILD_RUNS:
        raise _refuse(InputDefect.TOO_MANY_RUNS) from None
    rows = tuple(_row(raw) for raw in raw_rows)
    identities = [row.run_identity for row in rows]
    if len(set(identities)) != len(identities):
        raise _refuse(InputDefect.IDENTITY_DUPLICATED) from None
    declared = hex_digest(document["ledger_digest"])
    if declared is None:
        raise _refuse(InputDefect.FIELD_MALFORMED) from None
    if declared != ledger_digest(raw_rows):
        raise _refuse(InputDefect.LEDGER_DIGEST_MISMATCH) from None
    issued_at, expires_at = _validity(document, now=now)
    return BuildInput(
        build_identity=build_identity,
        runs=rows,
        ledger_digest=declared,
        issued_at=issued_at,
        expires_at=expires_at,
    )


__all__ = [
    "INPUT_SCHEMA_VERSION",
    "LEDGER_OUTCOMES",
    "LEDGER_OUTCOME_COMPLETED",
    "MAX_BUILD_RUNS",
    "MAX_INPUT_VALIDITY",
    "MAX_RESPONSE_BYTES",
    "MAX_SLICE_REQUESTS",
    "SLICE_MODES",
    "AcquisitionInput",
    "BuildInput",
    "InputDefect",
    "InputError",
    "LedgerRow",
    "Slice",
    "decode_input",
    "input_digest",
    "ledger_digest",
    "parse_acquisition_input",
    "parse_build_input",
    "parse_slice",
]
