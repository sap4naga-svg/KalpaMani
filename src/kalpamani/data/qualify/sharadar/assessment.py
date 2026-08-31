"""The combined assessment: validate both locators, read exactly, evaluate, report.

**One assessment covers both acquisition executions, and it runs after Run B.** A
single-execution assessment cannot reach P1's accepted ``TESTED`` ceiling, because
one observation cannot show that anything changed -- so the canonical assessment in
this architecture reads two locators and the evidence both name, and produces one
private report addressed by both execution identities in fixed Run A / Run B order.

**Both locators and the pair relationship are validated before any acquisition
record or payload is read.** That ordering is the control, not a convenience: a pair
that is the same run twice, the wrong way round, from a different plan or inventory,
or fewer than eight calendar days apart, is refused with **zero payload reads**. A
refusal costs at most two locator reads and nothing else.


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

**Exactly ``E * (2R + 1)`` reads** for ``E`` executions of ``R`` planned requests --
194 for the accepted two runs of 48 -- one report write, and zero to one metadata
resolution. Nothing here loops, retries a read or fetches anything a locator did not
name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.qualify.sharadar.evaluator import (
    CrossRunSubjectEvidence,
    SubjectEvidence,
    TestResult,
    evaluate_combined,
    excluded_cross_run_pair_count,
)
from kalpamani.data.qualify.sharadar.locator import (
    LocatorEntry,
    ValidatedLocator,
    decode_locator,
    locator_key_segments,
)
from kalpamani.data.qualify.sharadar.parser import PagePair, ParsedPage, parse_payload
from kalpamani.data.qualify.sharadar.plan import EMPIRICAL_REQUEST_COUNT
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

#: How many acquisition executions one combined assessment covers. ``E`` in the
#: accepted read arithmetic ``E * (2R + 1)``.
EXECUTIONS_PER_ASSESSMENT: Final = 2

#: The minimum separation between the two accepted run dates, in **calendar days**.
#: Two observations a day apart could not show the provider revising anything; eight
#: days is what the accepted architecture requires, and it is checked here rather
#: than left to whoever scheduled the runs.
MIN_RUN_SEPARATION_DAYS: Final = 8

#: A locator's own byte count is not known before it is read, so the reference used
#: to retrieve it declares this ceiling and the reader refuses anything above it.
#: The digest is not known either -- the locator is **the one object addressed by
#: name** -- so its integrity is established by its closed schema validation after
#: retrieval rather than by a digest before it.
_LOCATOR_READ_CEILING: Final = 256 * 1024


class AssessmentStatus(StrEnum):
    """How one assessment ended. Closed, and **never a verdict about the provider**.

    ``COMPLETED``
        Both locators validated, the pair validated, every referenced object verified
        and parsed, the nine tests evaluated, and the private report published.
    ``REFUSED_LOCATOR``
        A locator was missing, unreadable, malformed, oversize, identity-mismatched
        or ``PARTIAL``, **or the two do not form an admissible pair** -- identical,
        reversed, from a different plan or inventory, of different lengths, or fewer
        than eight calendar days apart. **No payload was read.**
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
    """The observed operation accounting of one combined assessment run.

    :meth:`__post_init__` refuses a set of counts no assessment could have produced.
    For ``E`` ``COMPLETE`` locators over ``R`` planned requests each, the reads are
    exactly ``E * (2R + 1)``: ``E`` locators, ``E * R`` acquisition records and
    ``E * R`` payloads, and **zero claims**. At the accepted two runs of 48 that is
    194 reads, one report write and zero to one metadata resolution -- 195 or 196
    operations.

    **``R`` is the compiled ``EMPIRICAL_REQUEST_COUNT``, and an admitted accounting
    that claims any other inventory is refused here** -- a second line behind
    :func:`validate_locator_pair`, so a future caller that bypassed or misordered the
    pair validation still cannot produce an accounting scaled above the fixed
    architectural bound.
    """

    executions: int
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
            self.executions,
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
        if self.executions > EXECUTIONS_PER_ASSESSMENT:
            raise ValueError("a combined assessment covers exactly two acquisition executions")
        if self.executions == 0:
            # **The refused-pair envelope.** Nothing was admitted, so the only reads
            # that can have happened are the at most two locator retrievals that
            # discovered the refusal, and no record, payload or report may exist.
            if self.get_object_count > EXECUTIONS_PER_ASSESSMENT:
                raise ValueError("a refused pair reads at most the two locators")
            if self.put_object_count or self.head_object_count:
                raise ValueError("a refused pair publishes no report")
            if self.planned_requests:
                raise ValueError("a refused pair admits no request inventory")
        else:
            # **The read ceiling may not be scaled by its own evidence.** ``R`` is the
            # compiled inventory, never a number a locator supplied: an admitted
            # assessment covering some other count would derive a larger
            # ``E * (2R + 1)`` and call it lawful, which is how the accepted 194 reads
            # and 195-196 operations stop being fixed. Refused, not clamped -- a
            # clamped count would report 48 for evidence that was not 48.
            if self.planned_requests != EMPIRICAL_REQUEST_COUNT:
                raise ValueError("an admitted assessment covers exactly the compiled inventory")
            if self.get_object_count > self.executions * (2 * self.planned_requests + 1):
                raise ValueError(
                    "an assessment reads at most E locators, E*R records and E*R payloads"
                )
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
    *,
    reader: LicensedObjectReader,
    execution_id: str,
    raw: bytes,
    require_assessable: bool = True,
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
    if require_assessable and not locator.assessable:
        # A PARTIAL locator preserves accounting and grants no evaluation: a P-test
        # conclusion drawn from a subset nobody chose is a conclusion about a
        # different experiment.
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    return locator


def _request_inventory(locator: ValidatedLocator) -> tuple[tuple[str, str, int, int], ...]:
    """The locator's request coordinates, in canonical order and free of digests.

    Subject, dataset, page limit and page offset -- what was *asked for*, not what
    came back. Two executions of one plan must have asked for exactly the same
    things; the payloads are expected to differ, and comparing them here would refuse
    every pair that has anything to say.
    """
    return tuple(
        sorted(
            (entry.subject, entry.dataset, entry.page_limit, entry.page_skip)
            for entry in locator.entries
        )
    )


def validate_locator_pair(first: ValidatedLocator, second: ValidatedLocator) -> int:
    """Admit two locators as one cross-run pair, and return their separation in days.

    Every rule is a reason the comparison would otherwise be meaningless:

    - **distinct identities** -- one run twice is not two observations;
    - **both assessable** -- a ``PARTIAL`` or ambiguous locator grants no evaluation
      on its own, and pairing it with a complete one does not repair it;
    - **the same plan digest, inventory digest and source schema version** -- two
      runs of *different* plans measure two different things. The accepted locator
      carries exactly one plan digest, and it is defined over the plan's stable
      shape precisely so that a legitimate pair can share it: it binds neither the
      execution identity nor each run's own ``T-1`` window, both of which differ
      across a pair eight days apart by requirement;
    - **exactly ``EMPIRICAL_REQUEST_COUNT`` planned and completed requests in each,
      and matching request inventories** -- a comparison needs the same questions
      asked twice, and it needs them to be *the accepted* questions. Run-to-run
      agreement alone is not that rule: two locators agreeing on some other count
      agree about a run nobody authorized, and the read arithmetic scales off the
      number they supply;
    - **Run A ordered strictly before Run B**, and **at least eight calendar days**
      between the accepted run dates.

    Returns:
        The separation in calendar days, which the private report records.

    Raises:
        AssessmentError: ``REFUSED_LOCATOR`` for any violation. Called **before any
        acquisition record or payload is read**, so a refusal reads no payload.
    """
    if first.execution_id == second.execution_id:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    if not first.assessable or not second.assessable:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    if first.plan_digest != second.plan_digest:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    if first.inventory_digest != second.inventory_digest:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    if first.source_schema_version != second.source_schema_version:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    for locator in (first, second):
        # **The fixed inventory, not merely an agreed one.** Two runs that agree with
        # each other are still not the accepted experiment: a self-consistent pair
        # claiming any other count would be admitted by a run-to-run comparison and
        # would then scale the read arithmetic ``E * (2R + 1)`` off its own number,
        # carrying the accepted 194 reads and 195-196 operations past the fixed
        # architectural bound. The accepted plan issues exactly
        # ``EMPIRICAL_REQUEST_COUNT`` requests, so that constant -- and not the
        # locator -- is what a pair is held to. Being stated against the compiled
        # constant, this subsumes the run-to-run agreement rule it replaces.
        if (
            locator.planned_request_count != EMPIRICAL_REQUEST_COUNT
            or locator.completed_request_count != EMPIRICAL_REQUEST_COUNT
        ):
            raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    if _request_inventory(first) != _request_inventory(second):
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None

    separation = (second.run_date - first.run_date).days
    if separation < MIN_RUN_SEPARATION_DAYS:
        # Covers reversal too, and deliberately with the same refusal: a reversed
        # pair has a negative separation, and both "too close together" and "the
        # wrong way round" mean the same thing here -- these two observations do not
        # support a cross-run claim.
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    return separation


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


def _group_evidence_by_subject(
    parsed: list[tuple[LocatorEntry, ParsedPage]],
) -> dict[str, dict[SharadarDataset, PagePair]]:
    """Assemble page pairs by subject and dataset, in delivered page order.

    Keyed by the locator's own subject values, which **never leave this module**: the
    evaluator receives datasets and pages, aggregates across subjects and emits
    counts, so no security name travels into a result or a report. The key exists
    only so the two executions can be matched subject to subject, which is exactly
    what a cross-run comparison needs and the one thing an unkeyed grouping could
    not provide.
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
    return by_subject


def _load_locator_by_name(*, reader: LicensedObjectReader, execution_id: str) -> ValidatedLocator:
    """Retrieve and validate one locator. **Exactly one ``GetObject``.**

    Raises:
        AssessmentError: ``REFUSED_LOCATOR`` for a retrieval failure or any locator
            defect. **No payload is read on a refusal.**
    """
    try:
        raw = reader.read_locator_by_name(
            logical_key=locator_logical_key(execution_id),
            max_bytes=_LOCATOR_READ_CEILING,
        )
    except Exception:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None
    # Assessability is decided by the **pair** check, not here, so both locators are
    # always retrieved before anything is judged. That keeps the refused-pair
    # envelope at a deterministic two reads rather than one or two depending on
    # which locator happened to be the bad one.
    return load_locator(reader=reader, execution_id=execution_id, raw=raw, require_assessable=False)


def _read_execution(
    *, reader: LicensedObjectReader, locator: ValidatedLocator
) -> list[tuple[LocatorEntry, ParsedPage]]:
    """Verify and parse every object one locator names. **Exactly ``2R`` reads.**

    Record then payload, per entry, and **never a claim**: the claim is a write-time
    uniqueness reservation carrying no evidence about the provider's data, and the
    record -- written last -- is what marks an acquisition complete. Retrieving 48
    claims would re-derive a fact the record already carries at the cost of 48 more
    reads of licensed material, and minimising licensed byte reads is a control.

    Raises:
        AssessmentError: ``REFUSED_INTEGRITY`` for a retrieval or cross-check
            failure, ``REFUSED_EVIDENCE`` for a payload the strict parser refuses.
    """
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
    return parsed


def _matched_cross_run_evidence(
    first: list[tuple[LocatorEntry, ParsedPage]],
    second: list[tuple[LocatorEntry, ParsedPage]],
) -> tuple[CrossRunSubjectEvidence, ...]:
    """Pair the two executions' evidence subject by subject, in a stable order.

    Matched on the locators' own subject values, which **never leave this
    function**: the evaluator receives datasets and pages, aggregates across
    subjects and emits counts, so no security name travels into a result or a
    report. A subject present in only one run contributes nothing rather than
    contributing half a comparison.

    The order is the sorted subject order rather than delivery order, so two runs
    that happened to complete in different orders still line up -- and so the
    evidence handed to the evaluator is deterministic for one pair of locators.
    """
    grouped_first = _group_evidence_by_subject(first)
    grouped_second = _group_evidence_by_subject(second)
    shared = sorted(set(grouped_first) & set(grouped_second))
    return tuple(
        CrossRunSubjectEvidence(
            first=SubjectEvidence(pairs=grouped_first[subject]),
            second=SubjectEvidence(pairs=grouped_second[subject]),
        )
        for subject in shared
    )


def run_combined_assessment(
    *,
    reader: LicensedObjectReader,
    run_a_execution_id: str,
    run_b_execution_id: str,
    assessment_id: str,
    clock: Any,
) -> AssessmentResult:
    """Retrieve, verify, parse, evaluate and publish exactly one private report.

    The enforced order is the security property, and it is stricter here than in a
    single-execution assessment: **both** locators are retrieved and validated, and
    **the pair** is validated, before any acquisition record or payload is requested.
    Then every object's digest and byte count are verified before it is parsed, and
    the report is published last.

    Read arithmetic, on success: ``E * (2R + 1)`` -- two locators, 96 acquisition
    records, 96 payloads, **zero claims** -- which is 194 for the accepted plan, plus
    one report write and zero to one metadata resolution. On a refused pair: at most
    two locator reads and **nothing else**.

    **No provider request and no credential retrieval happens here, and none can.**
    This module imports no transport, no credential source and no secrets boundary,
    and the role this process runs as can reach neither -- so a provider failure
    cannot be converted into an assessment result.

    Raises:
        AssessmentError: one closed :class:`AssessmentStatus`. Every underlying cause
            is suppressed.
    """
    if type(reader) is not LicensedObjectReader:
        raise _refuse(AssessmentStatus.REFUSED_LOCATOR) from None

    # 1-2. Both locators, by name, before anything else is read.
    run_a = _load_locator_by_name(reader=reader, execution_id=run_a_execution_id)
    run_b = _load_locator_by_name(reader=reader, execution_id=run_b_execution_id)

    # 3. The pair. **Still zero payload reads at this point**, which is what makes a
    #    refusal here cost two reads rather than 194.
    separation = validate_locator_pair(run_a, run_b)

    # 4. The evidence, one execution at a time.
    parsed_a = _read_execution(reader=reader, locator=run_a)
    parsed_b = _read_execution(reader=reader, locator=run_b)

    evidence = _matched_cross_run_evidence(parsed_a, parsed_b)
    results = evaluate_combined(evidence)

    digests = sorted({page.schema_digest for _, page in (*parsed_a, *parsed_b)})
    document = build_report_document(
        evidence=ReportEvidence(
            run_a_execution_id=run_a_execution_id,
            run_b_execution_id=run_b_execution_id,
            assessment_id=assessment_id,
            run_a_plan_digest=run_a.plan_digest,
            run_b_plan_digest=run_b.plan_digest,
            inventory_digest=run_a.inventory_digest,
            source_schema_version=run_a.source_schema_version,
            planned_request_count=run_a.planned_request_count,
            run_a_completed_request_count=run_a.completed_request_count,
            run_b_completed_request_count=run_b.completed_request_count,
            run_a_date=run_a.run_date.isoformat(),
            run_b_date=run_b.run_date.isoformat(),
            separation_days=separation,
            objects_read=reader.get_object_count,
            excluded_pair_count=excluded_cross_run_pair_count(evidence),
            observed_schema_digests=tuple(digests),
        ),
        results=results,
        created_at=clock.now(),
    )
    payload_bytes = serialize_report(document)
    try:
        reader.publish_report(
            key=report_object_key(
                run_a_execution_id=run_a_execution_id,
                run_b_execution_id=run_b_execution_id,
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
            executions=EXECUTIONS_PER_ASSESSMENT,
            planned_requests=run_a.planned_request_count,
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
    "EXECUTIONS_PER_ASSESSMENT",
    "MIN_RUN_SEPARATION_DAYS",
    "AssessmentError",
    "AssessmentOperationCounts",
    "AssessmentResult",
    "AssessmentStatus",
    "load_locator",
    "locator_logical_key",
    "run_combined_assessment",
    "validate_locator_pair",
]
