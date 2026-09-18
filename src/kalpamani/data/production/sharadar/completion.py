"""Pagination-v2 completion evidence: what one data coordinate proved, and how (ADR-0053 §13.3).

**One data coordinate per group; a probe is a bounded verification, never a page.** Each
planned group of a run -- one dataset, one exact window or predicate -- is acquired by
exactly one governed data request at offset 0 and limit ``L``. The acquisition actor
parses that response with the accepted parser (bounded by the §13.2 ceilings) to count
its rows and compute its schema digest, and then:

- ``0 <= rows < L`` -- the group is **complete without a probe**: ``SHORT_PAGE_COMPLETE``,
  with the observed row count and the governed limit recorded as the reason no probe was
  required;
- ``rows == L`` -- exactly one completion probe at offset ``L`` (same dataset, window,
  predicate, limit) is required; it must parse, prove **zero** rows and carry the same
  schema digest: ``PROBE_PASSED``. A data-bearing, refused, malformed or schema-mismatched
  probe fails the group closed -- no write for the group, no ``COMPLETE`` locator;
- ``rows > L`` -- the data response is malformed (``PAGE_OVER_LIMIT``) and refused.

The probe's body is **never a Bronze payload** and is not written; what is retained --
here, in the group's acquisition record and in its locator entry -- is the probe's
request-shape digest, offset and limit, response SHA-256, byte count, row count, schema
digest, parser outcome and outcome. Provider-operation counts include probes actually
issued; S3 write arithmetic counts planned data coordinates only.

**Closed parsing, both ways.** :func:`parse_pagination_evidence` admits exactly the
document :meth:`PaginationEvidence.document` renders, held to the group's governed limit,
and refuses everything else with one closed defect -- so a record and a locator entry
cannot disagree about what a probe proved without one of them being refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import exact_int, exact_str, hex_digest

#: The one evidence contract. Matched exactly by every reader.
COMPLETION_CONTRACT_ID: Final = "kalpamani-pagination-v2-completion/v1"

#: The one probe policy every v2 plan declares: a probe only for an exactly-full page.
PROBE_POLICY: Final = "CONDITIONAL_ON_FULL_PAGE"


class CompletionOutcome(StrEnum):
    """How one data coordinate was proved complete. Closed."""

    SHORT_PAGE_COMPLETE = "SHORT_PAGE_COMPLETE"
    PROBE_PASSED = "PROBE_PASSED"


class ProbeOutcome(StrEnum):
    """What an issued completion probe established. Closed.

    Only ``PROBE_PASSED`` can appear in a written record or a locator entry: every other
    member halts the run before the group's writes and appears only in the run report.
    """

    PROBE_PASSED = "PROBE_PASSED"
    PROBE_DATA_BEARING = "PROBE_DATA_BEARING"
    PROBE_REFUSED = "PROBE_REFUSED"
    PROBE_MALFORMED = "PROBE_MALFORMED"
    PROBE_SCHEMA_MISMATCH = "PROBE_SCHEMA_MISMATCH"


class ParserOutcome(StrEnum):
    """Whether the accepted parser admitted a body. Closed."""

    PARSED = "PARSED"


class CompletionDefect(StrEnum):
    """Why an evidence document was refused. Closed; never a value."""

    EVIDENCE_MALFORMED = "EVIDENCE_MALFORMED"
    CONTRACT_UNKNOWN = "CONTRACT_UNKNOWN"
    LIMIT_MISMATCH = "LIMIT_MISMATCH"
    ROW_COUNT_OVER_LIMIT = "ROW_COUNT_OVER_LIMIT"
    PROBE_EVIDENCE_MISSING = "PROBE_EVIDENCE_MISSING"
    PROBE_UNEXPECTED = "PROBE_UNEXPECTED"
    PROBE_FAILED = "PROBE_FAILED"
    OUTCOME_INCONSISTENT = "OUTCOME_INCONSISTENT"


class CompletionError(Exception):
    """One closed defect, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: CompletionDefect) -> None:
        if type(defect) is not CompletionDefect:
            raise TypeError("defect must be an exact CompletionDefect member")
        self.defect = defect
        super().__init__(defect.value)


def _refuse(defect: CompletionDefect) -> CompletionError:
    return CompletionError(defect)


PROBE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "request_shape_sha256",
        "page_offset",
        "page_limit",
        "response_sha256",
        "byte_count",
        "row_count",
        "schema_digest",
        "parser_outcome",
        "outcome",
    }
)
EVIDENCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "contract_id",
        "governed_limit",
        "row_count",
        "schema_digest",
        "parser_outcome",
        "completion",
        "probe",
    }
)


def request_shape_digest(
    *,
    dataset: str,
    window: str,
    predicate: tuple[tuple[str, str], ...],
    page_offset: int,
    page_limit: int,
) -> str:
    """The digest of one request's immutable shape: dataset, window, predicate, page, format.

    Never the credential, never a host: the shape is the coordinate, and two requests
    with one shape digest ask the provider for exactly one thing.
    """
    return sha256_hex(
        canonical_bytes(
            {
                "dataset": dataset,
                "window": window,
                "predicate": dict(predicate),
                "page_offset": page_offset,
                "page_limit": page_limit,
                "format": "csv",
            }
        )
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeEvidence:
    """What one issued completion probe established. Retained; never a payload."""

    request_shape_sha256: str
    page_offset: int
    page_limit: int
    response_sha256: str
    byte_count: int
    row_count: int
    schema_digest: str
    parser_outcome: ParserOutcome
    outcome: ProbeOutcome

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("ProbeEvidence may not be subclassed")

    def document(self) -> dict[str, Any]:
        """The closed probe document."""
        return {
            "request_shape_sha256": self.request_shape_sha256,
            "page_offset": self.page_offset,
            "page_limit": self.page_limit,
            "response_sha256": self.response_sha256,
            "byte_count": self.byte_count,
            "row_count": self.row_count,
            "schema_digest": self.schema_digest,
            "parser_outcome": self.parser_outcome.value,
            "outcome": self.outcome.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PaginationEvidence:
    """What one data coordinate proved: rows, schema, completion, and the probe if issued."""

    governed_limit: int
    row_count: int
    schema_digest: str
    parser_outcome: ParserOutcome
    completion: CompletionOutcome
    probe: ProbeEvidence | None

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("PaginationEvidence may not be subclassed")

    def __post_init__(self) -> None:
        """An evidence value must describe one possible outcome (the closed state machine)."""
        _check(self)

    def document(self) -> dict[str, Any]:
        """The closed evidence document the record and the locator entry both carry."""
        return {
            "contract_id": COMPLETION_CONTRACT_ID,
            "governed_limit": self.governed_limit,
            "row_count": self.row_count,
            "schema_digest": self.schema_digest,
            "parser_outcome": self.parser_outcome.value,
            "completion": self.completion.value,
            "probe": None if self.probe is None else self.probe.document(),
        }

    @property
    def probe_issued(self) -> bool:
        """Whether a completion probe was issued for this coordinate."""
        return self.probe is not None


def _check(evidence: PaginationEvidence) -> None:
    """The v2 state machine over one evidence value. Every branch is a closed refusal."""
    if evidence.row_count > evidence.governed_limit:
        raise _refuse(CompletionDefect.ROW_COUNT_OVER_LIMIT) from None
    if evidence.row_count < evidence.governed_limit:
        if evidence.completion is not CompletionOutcome.SHORT_PAGE_COMPLETE:
            raise _refuse(CompletionDefect.OUTCOME_INCONSISTENT) from None
        if evidence.probe is not None:
            raise _refuse(CompletionDefect.PROBE_UNEXPECTED) from None
        return
    # Exactly full: a probe is required, and it must have passed.
    if evidence.probe is None:
        raise _refuse(CompletionDefect.PROBE_EVIDENCE_MISSING) from None
    if evidence.completion is not CompletionOutcome.PROBE_PASSED:
        raise _refuse(CompletionDefect.OUTCOME_INCONSISTENT) from None
    probe = evidence.probe
    if (
        probe.outcome is not ProbeOutcome.PROBE_PASSED
        or probe.row_count != 0
        or probe.parser_outcome is not ParserOutcome.PARSED
    ):
        raise _refuse(CompletionDefect.PROBE_FAILED) from None
    if probe.schema_digest != evidence.schema_digest:
        raise _refuse(CompletionDefect.PROBE_FAILED) from None
    if probe.page_offset != evidence.governed_limit or probe.page_limit != evidence.governed_limit:
        raise _refuse(CompletionDefect.OUTCOME_INCONSISTENT) from None


def parse_pagination_evidence(raw: object, *, governed_limit: int) -> PaginationEvidence:
    """The one evidence value a closed document describes, held to ``governed_limit``.

    Raises:
        CompletionError: one closed defect for a document that is not exactly the
            rendered shape, names another contract, declares another limit, or
            describes an outcome the state machine refuses.
    """
    if type(raw) is not dict or set(raw) != EVIDENCE_FIELDS:
        raise _refuse(CompletionDefect.EVIDENCE_MALFORMED) from None
    contract = exact_str(raw["contract_id"])
    if contract is None:
        raise _refuse(CompletionDefect.EVIDENCE_MALFORMED) from None
    if contract != COMPLETION_CONTRACT_ID:
        raise _refuse(CompletionDefect.CONTRACT_UNKNOWN) from None
    limit = exact_int(raw["governed_limit"])
    rows = exact_int(raw["row_count"])
    schema = hex_digest(raw["schema_digest"])
    parser = exact_str(raw["parser_outcome"])
    completion = exact_str(raw["completion"])
    if (
        limit is None
        or rows is None
        or rows < 0
        or schema is None
        or parser is None
        or parser not in {m.value for m in ParserOutcome}
        or completion is None
        or completion not in {m.value for m in CompletionOutcome}
    ):
        raise _refuse(CompletionDefect.EVIDENCE_MALFORMED) from None
    if limit != governed_limit:
        raise _refuse(CompletionDefect.LIMIT_MISMATCH) from None
    probe_raw = raw["probe"]
    probe: ProbeEvidence | None = None
    if probe_raw is not None:
        if type(probe_raw) is not dict or set(probe_raw) != PROBE_FIELDS:
            raise _refuse(CompletionDefect.EVIDENCE_MALFORMED) from None
        shape = hex_digest(probe_raw["request_shape_sha256"])
        offset = exact_int(probe_raw["page_offset"])
        probe_limit = exact_int(probe_raw["page_limit"])
        response = hex_digest(probe_raw["response_sha256"])
        byte_count = exact_int(probe_raw["byte_count"])
        probe_rows = exact_int(probe_raw["row_count"])
        probe_schema = hex_digest(probe_raw["schema_digest"])
        probe_parser = exact_str(probe_raw["parser_outcome"])
        outcome = exact_str(probe_raw["outcome"])
        if (
            shape is None
            or offset is None
            or probe_limit is None
            or response is None
            or byte_count is None
            or byte_count < 0
            or probe_rows is None
            or probe_rows < 0
            or probe_schema is None
            or probe_parser is None
            or probe_parser not in {m.value for m in ParserOutcome}
            or outcome is None
            or outcome not in {m.value for m in ProbeOutcome}
        ):
            raise _refuse(CompletionDefect.EVIDENCE_MALFORMED) from None
        probe = ProbeEvidence(
            request_shape_sha256=shape,
            page_offset=offset,
            page_limit=probe_limit,
            response_sha256=response,
            byte_count=byte_count,
            row_count=probe_rows,
            schema_digest=probe_schema,
            parser_outcome=ParserOutcome(probe_parser),
            outcome=ProbeOutcome(outcome),
        )
    return PaginationEvidence(
        governed_limit=limit,
        row_count=rows,
        schema_digest=schema,
        parser_outcome=ParserOutcome(parser),
        completion=CompletionOutcome(completion),
        probe=probe,
    )


__all__ = [
    "COMPLETION_CONTRACT_ID",
    "EVIDENCE_FIELDS",
    "PROBE_FIELDS",
    "PROBE_POLICY",
    "CompletionDefect",
    "CompletionError",
    "CompletionOutcome",
    "PaginationEvidence",
    "ParserOutcome",
    "ProbeEvidence",
    "ProbeOutcome",
    "parse_pagination_evidence",
    "request_shape_digest",
]
