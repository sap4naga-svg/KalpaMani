"""The assessment composition: validate the locator, read exactly, evaluate, report.

**This process cannot contact a provider, and that is enforced twice.** There is no
credential source in this module and no provider transport in its import graph, and
the role it will eventually run as can reach neither the secret nor the provider. *A
provider failure cannot be converted into an assessment result* therefore holds as a
property of the identity system and not only of the code. A static test proves the
import half.

**The locator is a gate, not a formality.** No object byte is requested until the
locator has passed its complete closed validation, and a ``PARTIAL``, ambiguous,
malformed, oversize or identity-mismatched locator is refused with **no payload
read at all**. There is no fallback that reconstructs the missing part by listing,
probing or guessing, because adding one would reintroduce the capability this
architecture removes.

**Claims are validated structurally and never retrieved.** The claim is a write-time
uniqueness reservation whose content carries no evidence about the provider's data,
and the acquisition record -- written last -- is what marks an acquisition complete.
Retrieving 48 claim objects would re-derive a fact the record already carries, at the
cost of 48 additional reads of licensed material. Minimising licensed byte reads is a
control, not an optimisation.

**Records are retrieved, and cross-checked.** The record is content-addressed and its
digest is bound by the locator, whereas the locator itself is addressed by name.
Reading each record and checking it against its locator entry is the control that
detects a locator describing a different run.

**Exactly ``2R + 1`` reads for R planned requests**, one report write, and zero to one
metadata resolution. Nothing here loops, retries a read or fetches anything the
locator did not name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.qualify.sharadar.evaluator import (
    SubjectEvidence,
    TestResult,
    evaluate,
    excluded_subject_count,
)
from kalpamani.data.qualify.sharadar.locator import (
    LocatorEntry,
    ValidatedLocator,
    decode_locator,
    locator_key_segments,
)
from kalpamani.data.qualify.sharadar.parser import PagePair, ParsedPage, parse_payload
from kalpamani.data.qualify.sharadar.read import (
    ExactObjectReference,
    LicensedObjectReader,
)
from kalpamani.data.qualify.sharadar.report import (
    ReportEvidence,
    build_report_document,
    report_object_key,
    serialize_report,
)

#: The two pages of one subject-and-dataset pair, by page offset order.
_PAGES_PER_PAIR: Final = 2

#: A locator's own byte count is not known before it is read, so the reference used
#: to retrieve it declares this ceiling and the reader refuses anything above it.
#: The digest is not known either -- the locator is **the one object addressed by
#: name** -- so its integrity is established by its closed schema validation after
#: retrieval rather than by a digest before it.
_LOCATOR_READ_CEILING: Final = 256 * 1024


class AssessmentStatus(StrEnum):
    """How one assessment ended. Closed, and **never a verdict about the provider**.

    ``COMPLETED``
        The locator validated, every referenced object verified and parsed, the nine
        tests evaluated, and the private report published.
    ``REFUSED_LOCATOR``
        The locator was missing, unreadable, malformed, oversize, identity-mismatched
        or ``PARTIAL``. **No payload was read.**
    ``REFUSED_INTEGRITY``
        A referenced object's byte count or digest was not the one the locator
        expects, or a record contradicted its entry.
    ``REFUSED_EVIDENCE``
        A retrieved payload could not be parsed under the strict contract.
    ``REFUSED_REPORT``
        Everything was evaluated and the report could not be published. **The
        remedy is a new assessment identity, not a retry.**
    """

    COMPLETED = "COMPLETED"
    REFUSED_LOCATOR = "REFUSED_LOCATOR"
    REFUSED_INTEGRITY = "REFUSED_INTEGRITY"
    REFUSED_EVIDENCE = "REFUSED_EVIDENCE"
    REFUSED_REPORT = "REFUSED_REPORT"


class AssessmentError(Exception):
    """A refusal carrying exactly one :class:`AssessmentStatus`, raised ``from None``.

    A backend exception quotes the bucket and the key, a parser refusal can be about
    a vendor row, and a locator refusal is about private material. None of it may
    reach a traceback, so none of it has a parameter here.
    """

    __slots__ = ("status",)

    def __init__(self, status: AssessmentStatus) -> None:
        """Bind the status. The message is the member's token, nothing more."""
        if type(status) is not AssessmentStatus:  # pragma: no cover - type guard
            raise TypeError("a status must be an exact AssessmentStatus member")
        super().__init__(status.value)
        self.status = status


def _refuse(status: AssessmentStatus) -> AssessmentError:
    return AssessmentError(status)


@dataclass(frozen=True, slots=True, kw_only=True)
class AssessmentOperationCounts:
    """The observed operation accounting of one assessment run.

    :meth:`__post_init__` refuses a set of counts no assessment could have produced.
    For a ``COMPLETE`` locator over ``R`` planned requests the reads are exactly
    ``2R + 1``: one locator, ``R`` acquisition records and ``R`` payloads, and
    **zero claims**.
    """

    planned_requests: int
    get_object_count: int
    put_object_count: int
    head_object_count: int
    list_operation_count: int
    control_operation_count: int
    provider_request_count: int
    credential_retrieval_count: int
    claim_read_count: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so an accounting cannot be restated after the fact."""
        raise TypeError("AssessmentOperationCounts may not be subclassed")

    def __post_init__(self) -> None:
        """Refuse counts that contradict the accepted arithmetic."""
        for value in (
            self.planned_requests,
            self.get_object_count,
            self.put_object_count,
            self.head_object_count,
            self.list_operation_count,
            self.control_operation_count,
            self.provider_request_count,
            self.credential_retrieval_count,
            self.claim_read_count,
        ):
            if type(value) is not int or value < 0:
                raise ValueError("every operation count must be an exact non-negative int")
        if self.get_object_count > 2 * self.planned_requests + 1:
            raise ValueError("an assessment reads at most one locator, R records and R payloads")
        if self.put_object_count > 1:
            raise ValueError("an assessment publishes at most one report, and never retries it")
        if self.head_object_count > 1:
            raise ValueError("at most one metadata resolution, for the one conditional write")
        if self.claim_read_count:
            raise ValueError("acquisition claims are validated structurally and never retrieved")
        if self.provider_request_count or self.credential_retrieval_count:
            raise ValueError("the assessment process reaches no provider and no credential")
        if self.list_operation_count:
            raise ValueError("no listing exists anywhere in this architecture")
        if self.control_operation_count:
            raise ValueError("CONTROL publication is deferred and forbidden")

    @property
    def total_s3_operations(self) -> int:
        """Every S3 invocation this assessment made."""
        return self.get_object_count + self.put_object_count + self.head_object_count


@dataclass(frozen=True, slots=True, kw_only=True)
class AssessmentResult:
    """The closed record of one assessment. **No finding, and no verdict.**

    ``results`` holds the nine per-test results, which are structured evidence for
    the owner's private review -- they are written into the private report and are
    **never emitted publicly**. The entry point maps this object onto one allowlisted
    sentence and a set of counts, and nothing else escapes.
    """

    status: AssessmentStatus
    counts: AssessmentOperationCounts
    results: tuple[TestResult, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a result cannot be restated after the fact."""
        raise TypeError("AssessmentResult may not be subclassed")


def locator_logical_key(execution_id: str) -> str:
    """The logical key of one locator, derived from the execution identity alone.

    **No listing is involved and none is possible.** The owner knows one thing they
    already chose -- the execution identity -- and that is enough to name the object.
    A locator's content address is deliberately *not* part of this: knowing it would
    require the bytes, which is the exact asymmetry the locator exists to resolve.
    """
    return "/".join(("licensed", *locator_key_segments(execution_id)))


def load_locator(
    *, reader: LicensedObjectReader, execution_id: str, raw: bytes
) -> ValidatedLocator:
    """Validate already-retrieved locator bytes, or refuse without reading anything.

    ``raw`` is passed in rather than fetched here so the one by-name read stays in
    the caller, where the operation accounting is assembled and where a failure is
    counted once.

    Raises:
        AssessmentError: ``REFUSED_LOCATOR`` for any locator defect, and for a
            locator that validated but is not assessable -- ``PARTIAL``, ambiguous
            or short. **No payload is read on a refusal.**
    """
    if type(reader) is not LicensedObjectReader:  # pragma: no cover - type guard
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    try:
        locator = decode_locator(raw, execution_id=execution_id)
    except Exception:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    if not locator.assessable:
        # A PARTIAL locator preserves accounting and grants no evaluation: a P-test
        # conclusion drawn from a subset nobody chose is a conclusion about a
        # different experiment.
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    return locator


def _record_reference(entry: LocatorEntry) -> ExactObjectReference:
    return ExactObjectReference(
        logical_key=entry.record_key,
        expected_sha256=entry.record_sha256,
        expected_bytes=entry.record_bytes,
    )


def _payload_reference(entry: LocatorEntry) -> ExactObjectReference:
    return ExactObjectReference(
        logical_key=entry.payload_key,
        expected_sha256=entry.payload_sha256,
        expected_bytes=entry.payload_bytes,
    )


def _check_record(raw: bytes, entry: LocatorEntry) -> None:
    """Cross-check one acquisition record against the locator entry naming it.

    The record is the durable evidence written by the acquisition; the entry is the
    locator's description of it. A disagreement means the locator describes a
    different run, which is precisely what this control exists to detect.

    Raises:
        AssessmentError: ``REFUSED_INTEGRITY`` on any disagreement or on a record
            that is not decodable JSON.
    """
    try:
        record = json.loads(raw.decode("utf-8"))
    except Exception:
        raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None
    if type(record) is not dict:
        raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None
    if record.get("ingestion_run_id") != entry.acquisition_id:
        raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None
    if record.get("dataset") != entry.dataset:
        raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None
    if record.get("content_sha256") != entry.payload_sha256:
        raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None
    if record.get("byte_count") != entry.payload_bytes:
        raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None
    if record.get("requested_range") != entry.requested_range:
        raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None


def _group_evidence(parsed: list[tuple[LocatorEntry, ParsedPage]]) -> tuple[SubjectEvidence, ...]:
    """Assemble page pairs by subject and dataset, in delivered order.

    Grouped by the locator's own subject values, which never leave this function: the
    evaluator receives datasets and pages, aggregates across subjects and emits
    counts, so no security name travels into a result or a report.
    """
    grouped: dict[tuple[str, str], list[tuple[int, ParsedPage]]] = {}
    for entry, page in parsed:
        grouped.setdefault((entry.subject, entry.dataset), []).append((entry.page_skip, page))

    by_subject: dict[str, dict[SharadarDataset, PagePair]] = {}
    for (subject, dataset_name), pages in grouped.items():
        if len(pages) != _PAGES_PER_PAIR:
            # A pair that is not two pages cannot answer the completeness question
            # the second page exists to answer, so it contributes no evidence rather
            # than contributing half of it.
            continue
        ordered = [page for _, page in sorted(pages, key=lambda item: item[0])]
        by_subject.setdefault(subject, {})[SharadarDataset(dataset_name)] = PagePair(
            dataset=SharadarDataset(dataset_name), first=ordered[0], second=ordered[1]
        )
    return tuple(SubjectEvidence(pairs=pairs) for pairs in by_subject.values())


def run_assessment(
    *,
    reader: LicensedObjectReader,
    execution_id: str,
    assessment_id: str,
    clock: Any,
) -> AssessmentResult:
    """Retrieve, verify, parse, evaluate and publish exactly one private report.

    The enforced order is the security property: the locator is validated before any
    payload is requested, every object's digest and byte count are verified before it
    is parsed, and the report is published last.

    Raises:
        AssessmentError: one closed :class:`AssessmentStatus`. Every underlying cause
            is suppressed.
    """
    if type(reader) is not LicensedObjectReader:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None

    try:
        raw_locator = reader.read_locator_by_name(
            logical_key=locator_logical_key(execution_id),
            max_bytes=_LOCATOR_READ_CEILING,
        )
    except Exception:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    locator = load_locator(reader=reader, execution_id=execution_id, raw=raw_locator)

    parsed: list[tuple[LocatorEntry, ParsedPage]] = []
    for entry in locator.entries:
        try:
            record = reader.read_exact(_record_reference(entry))
        except Exception:
            raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None
        _check_record(record, entry)

        try:
            payload = reader.read_exact(_payload_reference(entry))
        except Exception:
            raise _refuse(AssessmentStatus.REFUSED_INTEGRITY) from None
        try:
            page = parse_payload(payload, dataset=SharadarDataset(entry.dataset))
        except Exception:
            raise _refuse(AssessmentStatus.REFUSED_EVIDENCE) from None
        parsed.append((entry, page))

    evidence = _group_evidence(parsed)
    results = evaluate(evidence)

    digests = sorted({page.schema_digest for _, page in parsed})
    document = build_report_document(
        evidence=ReportEvidence(
            execution_id=execution_id,
            assessment_id=assessment_id,
            plan_digest=locator.plan_digest,
            inventory_digest=locator.inventory_digest,
            source_schema_version=locator.source_schema_version,
            planned_request_count=locator.planned_request_count,
            completed_request_count=locator.completed_request_count,
            objects_read=reader.get_object_count,
            excluded_pair_count=excluded_subject_count(evidence),
            observed_schema_digests=tuple(digests),
        ),
        results=results,
        created_at=clock.now(),
    )
    payload_bytes = serialize_report(document)
    try:
        reader.publish_report(
            key=report_object_key(
                execution_id=execution_id,
                assessment_id=assessment_id,
                payload=payload_bytes,
            ),
            payload=payload_bytes,
        )
    except Exception:
        # Not retried, deliberately. A failed report costs only a re-run of a process
        # that makes zero provider requests, so the cheap remedy is a new assessment
        # identity rather than a repeat that could collide.
        raise _refuse(AssessmentStatus.REFUSED_REPORT) from None

    return AssessmentResult(
        status=AssessmentStatus.COMPLETED,
        counts=AssessmentOperationCounts(
            planned_requests=locator.planned_request_count,
            get_object_count=reader.get_object_count,
            put_object_count=reader.put_object_count,
            head_object_count=reader.head_object_count,
            # Structural, not measured: no listing, CONTROL, provider or credential
            # surface exists anywhere in this process to have counted, and claims are
            # validated from the locator rather than retrieved.
            list_operation_count=0,
            control_operation_count=0,
            provider_request_count=0,
            credential_retrieval_count=0,
            claim_read_count=0,
        ),
        results=results,
    )


__all__ = [
    "AssessmentError",
    "AssessmentOperationCounts",
    "AssessmentResult",
    "AssessmentStatus",
    "load_locator",
    "locator_logical_key",
    "run_assessment",
]
