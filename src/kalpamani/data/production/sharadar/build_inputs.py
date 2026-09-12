"""Verified build inputs: only what a validated run locator names, verified before it is parsed.

**The build actor reads by name and never by listing** (ADR-0036 §2.3 and §2.4). For every
ledger row of the admitted build input, in the input's order, the run locator is
retrieved by the exact name its run identity derives, decoded, and validated by the
accepted validator against that row -- identity binding, prefix allowlist, exact
compiled-request coordinates, completeness -- **before any object it names is read**.
Then every payload and acquisition record it names is read through the accepted
exact reader, which verifies the full-object SHA-256 and the byte count against the
locator's reference before a byte is returned. The build actor's read surface takes
keys from validated locators and from nowhere else.

**The acquisition record is cross-checked against the locator entry and the run.**
It must name this run, this dataset, this payload digest and byte count, this
request window, the locator's acquisition mode, the production source-schema
version, the provider and the LICENSED classification, and its retrieval instant
must lie inside the run's own start/completion interval. Any disagreement is
contradictory provenance and refuses the run -- the record is the durable evidence,
the locator its description, and the build may consume only bytes both agree on.

**Bounds are enforced while reading, not after.** Object counts, cumulative bytes
and per-payload size are checked before each read is admitted; a run that would
exceed a ceiling refuses before the read that exceeds it. Parsing work is bounded
by the accepted parser's own ceilings, applied later by normalization.

**No secret, no provider, no listing, no write.** This module holds a get-only
reader and nothing else; the build actor has no credential to retrieve and no
provider to ask, and this module offers no way to ask for one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.vocabulary import DataClassification
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.production.sharadar.inputs import BuildInput, LedgerRow
from kalpamani.data.production.sharadar.locator import (
    MAX_LOCATOR_BYTES,
    ProductionLocatorReader,
    RunLocatorEntry,
    RunLocatorError,
    ValidatedRunLocator,
)
from kalpamani.data.production.sharadar.processing import SOURCE_SCHEMA_VERSION
from kalpamani.data.qualify.sharadar.parser import MAX_PARSE_BYTES
from kalpamani.data.qualify.sharadar.read import LicensedReadError, ReadFailure

#: The most objects one build may read across every run it consumes: two per
#: request, at the input's run ceiling and the plan's request ceiling.
MAX_BUILD_OBJECTS: Final = 2 * 32 * 96

#: The most bytes one build may read in total. A ceiling on work, not on a run.
MAX_BUILD_INPUT_BYTES: Final = 2 * 1024 * 1024 * 1024

#: The largest payload the build will read. The accepted parser refuses anything
#: larger, so reading it would be work that cannot end in a row.
MAX_BUILD_PAYLOAD_BYTES: Final = MAX_PARSE_BYTES

#: The largest acquisition record the build will read. A closed document of ten
#: short fields; anything approaching this is not one.
MAX_RECORD_BYTES: Final = 16 * 1024

_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "provider",
        "dataset",
        "requested_range",
        "retrieved_at",
        "source_schema_version",
        "ingestion_run_id",
        "content_sha256",
        "byte_count",
        "acquisition_mode",
        "classification",
    }
)


class BuildInputDefect(StrEnum):
    """Why the build inputs were refused. Closed; never a key, a digest or a value."""

    LOCATOR_UNREADABLE = "LOCATOR_UNREADABLE"
    LOCATOR_INVALID = "LOCATOR_INVALID"
    OBJECT_UNREADABLE = "OBJECT_UNREADABLE"
    OBJECT_INTEGRITY = "OBJECT_INTEGRITY"
    OBJECT_COUNT_EXCEEDED = "OBJECT_COUNT_EXCEEDED"
    INPUT_BYTES_EXCEEDED = "INPUT_BYTES_EXCEEDED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    RECORD_TOO_LARGE = "RECORD_TOO_LARGE"
    RECORD_MALFORMED = "RECORD_MALFORMED"
    PROVENANCE_CONTRADICTORY = "PROVENANCE_CONTRADICTORY"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
    RUN_DUPLICATED = "RUN_DUPLICATED"
    DEADLINE_EXHAUSTED = "DEADLINE_EXHAUSTED"


class BuildInputError(Exception):
    """One closed defect, raised ``from None``. Nothing private has a parameter."""

    __slots__ = ("defect",)

    def __init__(self, defect: BuildInputDefect) -> None:
        if type(defect) is not BuildInputDefect:
            raise TypeError("defect must be an exact BuildInputDefect member")
        self.defect = defect
        super().__init__(f"build inputs refused: {defect.value}")


def _refuse(defect: BuildInputDefect) -> BuildInputError:
    return BuildInputError(defect)


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquiredPage:
    """One verified payload with the provenance the build carries on every row.

    **Private material.** ``payload`` holds vendor bytes and is never rendered.
    """

    run_id: str
    ordinal: int
    dataset: str
    window: str
    page_offset: int
    page_limit: int
    acquisition_mode: str
    retrieved_at: datetime
    payload: bytes
    payload_sha256: str
    payload_bytes: int
    record_sha256: str
    run_started_at: datetime
    run_completed_at: datetime

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass could render the payload."""
        raise TypeError("AcquiredPage may not be subclassed")

    def __repr__(self) -> str:
        """Ordinal, dataset and byte count. **Never bytes, never a digest.**"""
        return (
            f"AcquiredPage(ordinal={self.ordinal}, dataset={self.dataset!r}, "
            f"bytes={self.payload_bytes})"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedRun:
    """One run's validated locator and every page it named, verified and cross-checked."""

    row: LedgerRow
    locator: ValidatedRunLocator
    pages: tuple[AcquiredPage, ...]

    def __repr__(self) -> str:
        """Page count only."""
        return f"VerifiedRun(pages={len(self.pages)})"


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedBuildInputs:
    """Every run of one build input, verified, in the input's order."""

    build_identity: str
    ledger_digest: str
    runs: tuple[VerifiedRun, ...]
    object_count: int
    input_bytes: int

    def __repr__(self) -> str:
        """Counts only. **Never the identity.**"""
        return (
            f"VerifiedBuildInputs(runs={len(self.runs)}, objects={self.object_count}, "
            f"bytes={self.input_bytes})"
        )

    def pages(self) -> Iterator[AcquiredPage]:
        """Every verified page, run by run, ordinal by ordinal."""
        for run in self.runs:
            yield from run.pages


def _record(raw: bytes) -> dict[str, Any]:
    """Decode one acquisition record: strict UTF-8 JSON, exactly the closed field set."""
    if len(raw) > MAX_RECORD_BYTES:
        raise _refuse(BuildInputDefect.RECORD_TOO_LARGE)
    try:
        document = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, ValueError):
        raise _refuse(BuildInputDefect.RECORD_MALFORMED) from None
    if type(document) is not dict or set(document) != _RECORD_FIELDS:
        raise _refuse(BuildInputDefect.RECORD_MALFORMED)
    return document


def _instant(value: object) -> datetime:
    if type(value) is not str:
        raise _refuse(BuildInputDefect.RECORD_MALFORMED)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _refuse(BuildInputDefect.RECORD_MALFORMED) from None
    if parsed.tzinfo is None:
        raise _refuse(BuildInputDefect.RECORD_MALFORMED)
    return parsed


def cross_check_record(
    record: dict[str, Any], *, entry: RunLocatorEntry, locator: ValidatedRunLocator
) -> datetime:
    """The record's retrieval instant, once the record agrees with the entry and the run.

    Raises:
        BuildInputError: ``SCHEMA_INCOMPATIBLE`` for a record under a source-schema
            version this build does not normalize; ``PROVENANCE_CONTRADICTORY`` for
            any disagreement with the locator entry or the run; ``RECORD_MALFORMED``
            for a value of the wrong shape.
    """
    if record["source_schema_version"] != SOURCE_SCHEMA_VERSION:
        raise _refuse(BuildInputDefect.SCHEMA_INCOMPATIBLE)
    expected = {
        "provider": PROVIDER,
        "dataset": entry.dataset,
        "requested_range": entry.window,
        "ingestion_run_id": locator.run_id,
        "content_sha256": entry.payload.expected_sha256,
        "byte_count": entry.payload.expected_bytes,
        "acquisition_mode": locator.acquisition_mode,
        "classification": DataClassification.LICENSED.value,
    }
    for field, value in expected.items():
        observed = record[field]
        if type(observed) is not type(value) or observed != value:
            raise _refuse(BuildInputDefect.PROVENANCE_CONTRADICTORY)
    retrieved_at = _instant(record["retrieved_at"])
    if not locator.started_at <= retrieved_at <= locator.completed_at:
        raise _refuse(BuildInputDefect.PROVENANCE_CONTRADICTORY)
    return retrieved_at


class _Budget:
    """Object-count and byte ceilings, charged before each read is admitted."""

    __slots__ = ("bytes", "objects")

    def __init__(self) -> None:
        self.objects = 0
        self.bytes = 0

    def admit(self, expected_bytes: int, *, ceiling: int, defect: BuildInputDefect) -> None:
        if expected_bytes > ceiling:
            raise _refuse(defect)
        if self.objects + 1 > MAX_BUILD_OBJECTS:
            raise _refuse(BuildInputDefect.OBJECT_COUNT_EXCEEDED)
        if self.bytes + expected_bytes > MAX_BUILD_INPUT_BYTES:
            raise _refuse(BuildInputDefect.INPUT_BYTES_EXCEEDED)
        self.objects += 1
        self.bytes += expected_bytes


def _read(reader: ProductionLocatorReader, reference: Any) -> bytes:
    try:
        return reader.read_exact(reference)
    except LicensedReadError as error:
        if error.failure in (ReadFailure.INTEGRITY_MISMATCH, ReadFailure.TOO_LARGE):
            # A digest that does not match, or a body longer than the reference says:
            # the accepted reader refuses the second while reading, and both are the
            # object not being what the locator described.
            raise _refuse(BuildInputDefect.OBJECT_INTEGRITY) from None
        raise _refuse(BuildInputDefect.OBJECT_UNREADABLE) from None


def _verify_run(reader: ProductionLocatorReader, row: LedgerRow, *, budget: _Budget) -> VerifiedRun:
    # The locator is charged at its ceiling before it is read: its size is not
    # known until it is, and a conservative charge can only refuse sooner.
    budget.admit(
        MAX_LOCATOR_BYTES, ceiling=MAX_LOCATOR_BYTES, defect=BuildInputDefect.LOCATOR_INVALID
    )
    try:
        locator = reader.read_run_locator(run_id=row.run_identity, ledger_row=row)
    except LicensedReadError:
        raise _refuse(BuildInputDefect.LOCATOR_UNREADABLE) from None
    except RunLocatorError:
        raise _refuse(BuildInputDefect.LOCATOR_INVALID) from None
    pages: list[AcquiredPage] = []
    for entry in locator.entries:
        # The budget is charged for the payload and the record before either is
        # read, so a run that would exceed a ceiling refuses before the read.
        budget.admit(
            entry.payload.expected_bytes,
            ceiling=MAX_BUILD_PAYLOAD_BYTES,
            defect=BuildInputDefect.PAYLOAD_TOO_LARGE,
        )
        budget.admit(
            entry.record.expected_bytes,
            ceiling=MAX_RECORD_BYTES,
            defect=BuildInputDefect.RECORD_TOO_LARGE,
        )
        payload = _read(reader, entry.payload)
        record_raw = _read(reader, entry.record)
        retrieved_at = cross_check_record(_record(record_raw), entry=entry, locator=locator)
        pages.append(
            AcquiredPage(
                run_id=locator.run_id,
                ordinal=entry.ordinal,
                dataset=entry.dataset,
                window=entry.window,
                page_offset=entry.page_offset,
                page_limit=entry.page_limit,
                acquisition_mode=locator.acquisition_mode,
                retrieved_at=retrieved_at,
                payload=payload,
                payload_sha256=entry.payload.expected_sha256,
                payload_bytes=entry.payload.expected_bytes,
                record_sha256=entry.record.expected_sha256,
                run_started_at=locator.started_at,
                run_completed_at=locator.completed_at,
            )
        )
    return VerifiedRun(row=row, locator=locator, pages=tuple(pages))


def verify_build_inputs(
    admitted: BuildInput, *, reader: ProductionLocatorReader
) -> VerifiedBuildInputs:
    """Read and verify everything the admitted input's ledger rows authorize, and nothing else.

    Runs are read in the input's order; a refusal on any run refuses the whole
    input, and every read up to the refusal is counted by the reader.

    Raises:
        BuildInputError: one closed defect.
    """
    if type(admitted) is not BuildInput:
        raise TypeError("admitted must be an exact BuildInput")
    if type(reader) is not ProductionLocatorReader:
        raise TypeError("reader must be an exact ProductionLocatorReader")
    seen: set[str] = set()
    budget = _Budget()
    runs: list[VerifiedRun] = []
    for row in admitted.runs:
        if row.run_identity in seen:
            raise _refuse(BuildInputDefect.RUN_DUPLICATED)
        seen.add(row.run_identity)
        runs.append(_verify_run(reader, row, budget=budget))
    return VerifiedBuildInputs(
        build_identity=admitted.build_identity,
        ledger_digest=admitted.ledger_digest,
        runs=tuple(runs),
        object_count=budget.objects,
        input_bytes=budget.bytes,
    )


__all__ = [
    "MAX_BUILD_INPUT_BYTES",
    "MAX_BUILD_OBJECTS",
    "MAX_BUILD_PAYLOAD_BYTES",
    "MAX_RECORD_BYTES",
    "AcquiredPage",
    "BuildInputDefect",
    "BuildInputError",
    "VerifiedBuildInputs",
    "VerifiedRun",
    "cross_check_record",
    "verify_build_inputs",
]
