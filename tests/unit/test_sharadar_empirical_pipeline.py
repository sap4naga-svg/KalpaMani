"""Acquisition and assessment end to end, against synthetic fakes only.

**Nothing here contacts Sharadar, AWS or any network.** The credential is a
self-labelled synthetic string, the bucket is a synthetic name, the transport is a
dictionary that returns invented CSV, and the S3 client is a dictionary with the
conditional-write semantics the real backend enforces.

The point of this file is the *numbers*. Every operation count in the accepted
arithmetic is produced by running the real code and read off counters, so a change
that quietly issues an extra request, an extra write or a single object-byte read on
the acquisition path fails here rather than in production.

**Time is driven, never waited for.** The acquisition deadline runs on an injected
monotonic clock that a test advances -- through the pacer's sleep, through a scripted
per-request cost and through a scripted per-S3-operation cost -- so the 1,800-second
budget is exercised in microseconds against the real arithmetic.
"""

from __future__ import annotations

import json
from dataclasses import replace as dataclass_replace
from datetime import timedelta
from typing import Any

import pytest

from fixtures.sharadar_empirical import (
    EXECUTION_ID,
    EXECUTION_ID_A,
    EXECUTION_ID_B,
    RUN_B_INSTANT,
    RUN_INSTANT,
    SYNTHETIC_BUCKET,
    SYNTHETIC_SUBJECTS,
    FakeMonotonic,
    FakeS3Client,
    FixedClock,
    PagedTransport,
    client_error,
    credential,
    synthetic_inventory,
)
from kalpamani.data.qualify.sharadar.acquisition import (
    NO_RETRY_POLICY,
    AcquisitionStatus,
    run_empirical_acquisition,
)
from kalpamani.data.qualify.sharadar.assessment import (
    EXECUTIONS_PER_ASSESSMENT,
    MIN_RUN_SEPARATION_DAYS,
    AssessmentError,
    AssessmentOperationCounts,
    AssessmentStatus,
    locator_logical_key,
    run_combined_assessment,
    validate_locator_pair,
)
from kalpamani.data.qualify.sharadar.evaluator import (
    STATUS_RANK,
    TEST_CEILINGS,
    EvidenceScope,
    ProviderTest,
)
from kalpamani.data.qualify.sharadar.evaluator import (
    TestStatus as PerTestStatus,  # aliased: pytest tries to collect a Test* class
)
from kalpamani.data.qualify.sharadar.locator import (
    decode_locator,
    locator_key_segments,
    serialize_locator,
)
from kalpamani.data.qualify.sharadar.operations import OBJECTS_PER_ACQUISITION
from kalpamani.data.qualify.sharadar.plan import (
    ACQUISITION_DEADLINE_SECONDS,
    EMPIRICAL_REQUEST_COUNT,
    LOCATOR_TERMINAL_RESERVE_SECONDS,
    MIN_REQUEST_INTERVAL_SECONDS,
    PROVIDER_REQUEST_ADMISSION_SECONDS,
    S3_OPERATION_CEILING_SECONDS,
    TIMEOUT_SECONDS,
    compiled_request_phase_seconds,
)
from kalpamani.data.qualify.sharadar.read import LicensedObjectReader

ASSESSMENT_ID = "synthetic-assess-a"

#: The accepted read arithmetic for one combined assessment: two locators, 96
#: acquisition records, 96 payloads. Derived from its factors rather than written as
#: 194, so a change to either factor cannot leave the total stale.
COMBINED_READS = EXECUTIONS_PER_ASSESSMENT * (2 * EMPIRICAL_REQUEST_COUNT + 1)


def _acquire(
    *,
    s3: FakeS3Client | None = None,
    transport: PagedTransport | None = None,
    execution_id: str = EXECUTION_ID,
    instant: Any = RUN_INSTANT,
    monotonic: FakeMonotonic | None = None,
) -> tuple[FakeS3Client, PagedTransport, Any]:
    clock = monotonic if monotonic is not None else FakeMonotonic()
    client = s3 if s3 is not None else FakeS3Client()
    # **The byte variant follows the execution identity**, so any two runs written
    # into one store are byte-distinct without every call site having to say so.
    # ADR-0019 halts a run at the first occupied Bronze name, and a Run B that
    # re-published Run A's bytes would write to names Run A already holds. A caller
    # that supplies its own transport chooses its own variant, and
    # ``test_a_second_run_republishing_identical_bytes_halts_with_bronze_name_occupied``
    # deliberately supplies one that does not.
    wire = (
        transport if transport is not None else PagedTransport(byte_variant=_variant(execution_id))
    )
    result = run_empirical_acquisition(
        credential=credential(),
        transport=wire,
        monotonic=clock,
        sleeper=clock.sleep,
        s3_client=client,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(instant),
        inventory=synthetic_inventory(),
        execution_id=execution_id,
    )
    return client, wire, result


def _variant(execution_id: str) -> str:
    """The byte variant a run publishes under, derived from its execution identity."""
    return "B" if execution_id == EXECUTION_ID_B else "A"


def _acquire_pair() -> FakeS3Client:
    """Both accepted runs into one store, nine calendar days apart.

    The two runs use **different byte variants**, and that is a requirement rather
    than a fixture flourish: ADR-0019 halts a run at the first occupied Bronze name,
    the payload object is content-addressed per dataset, and a second run that
    re-published byte-identical responses would write to names the first run already
    holds. The variants change no parsed field -- same header names, same rows, same
    schema digest -- so every assertion downstream is about what it was always about.
    ``test_a_second_run_republishing_identical_bytes_halts_with_bronze_name_occupied``
    models the other case.
    """
    s3 = FakeS3Client()
    _acquire(s3=s3, execution_id=EXECUTION_ID_A, instant=RUN_INSTANT)
    _acquire(s3=s3, execution_id=EXECUTION_ID_B, instant=RUN_B_INSTANT)
    return s3


def _reader(s3: FakeS3Client) -> LicensedObjectReader:
    return LicensedObjectReader(client=s3, licensed_bucket=SYNTHETIC_BUCKET)


def _assess(
    s3: FakeS3Client,
    *,
    reader: LicensedObjectReader | None = None,
    run_a: str = EXECUTION_ID_A,
    run_b: str = EXECUTION_ID_B,
    assessment_id: str = ASSESSMENT_ID,
) -> Any:
    return run_combined_assessment(
        reader=reader if reader is not None else _reader(s3),
        run_a_execution_id=run_a,
        run_b_execution_id=run_b,
        assessment_id=assessment_id,
        clock=FixedClock(),
    )


def _report_key(run_a: str = EXECUTION_ID_A, run_b: str = EXECUTION_ID_B) -> str:
    return f"qualification/sharadar/reports/{run_a}/{run_b}/{ASSESSMENT_ID}.json"


# -- acquisition: the accepted numbers ----------------------------------------


def test_a_complete_acquisition_issues_exactly_forty_eight_provider_requests() -> None:
    _, transport, result = _acquire()
    assert transport.call_count == 48
    assert result.counts.provider_request_count == 48
    assert result.status is AcquisitionStatus.COMPLETED


def test_requests_are_issued_sequentially_in_the_plan_s_canonical_order() -> None:
    _, transport, _ = _acquire()
    # tickers, then stocks, then actions; each dataset's subjects in sorted order.
    datasets = [
        next(name for name in ("tickers", "stocks", "actions") if f"/{name}?" in url)
        for url in transport.urls
    ]
    assert datasets == ["tickers"] * 16 + ["stocks"] * 16 + ["actions"] * 16


def test_the_retry_policy_permits_exactly_one_attempt() -> None:
    assert NO_RETRY_POLICY.max_attempts == 1
    assert NO_RETRY_POLICY.backoff_seconds == ()


def test_a_complete_acquisition_writes_three_bronze_objects_per_request_plus_one_locator() -> None:
    s3, _, result = _acquire()
    assert result.counts.put_object_count == 3 * 48 + 1 == 145
    assert result.locator_attempts == 1
    assert len(s3.put_calls) == 145


def test_the_acquisition_path_performs_no_object_byte_read_listing_or_control_call() -> None:
    s3, _, result = _acquire()
    assert s3.get_calls == []
    assert result.counts.get_object_count == 0
    assert result.counts.list_operation_count == 0
    assert result.counts.control_operation_count == 0
    assert not hasattr(s3, "list_objects_v2")


def test_the_head_object_count_stays_inside_its_bound() -> None:
    s3, _, result = _acquire()
    assert result.counts.head_object_count == len(s3.head_calls)
    assert result.counts.head_object_count <= 3 * 48 + 1


def test_the_total_s3_operations_are_inside_the_accepted_envelope() -> None:
    _, _, result = _acquire()
    assert 145 <= result.counts.total_s3_operations <= 292


def test_every_written_object_is_licensed_and_none_is_control() -> None:
    s3, _, _ = _acquire()
    for key in s3.objects:
        assert key.startswith(("bronze/", "qualification/"))
        assert "control" not in key.lower()


def test_the_acquisition_writes_no_local_file(tmp_path: Any) -> None:
    before = set(tmp_path.iterdir())
    _acquire()
    assert set(tmp_path.iterdir()) == before


def test_a_provider_failure_halts_and_publishes_a_partial_locator() -> None:
    s3, _, result = _acquire(transport=PagedTransport(fail_after=10))
    assert result.status is AcquisitionStatus.PARTIAL
    assert result.counts.completed_requests == 10
    assert result.counts.put_object_count == 3 * 10 + 1
    document = json.loads(s3.objects["/".join(locator_key_segments(EXECUTION_ID))])
    assert document["completeness"] == "PARTIAL"
    assert document["completed_request_count"] == 10
    assert document["planned_request_count"] == 48


def test_a_locator_that_cannot_be_published_leaves_the_evidence_unaddressable() -> None:
    locator_key = "/".join(locator_key_segments(EXECUTION_ID))
    # A client-shaped error, so the real backend classifier is what turns it into
    # a definitive refusal. Raising an already-classified refusal would bypass the
    # classifier and prove nothing about it.
    s3 = FakeS3Client(fail_puts={locator_key: client_error("AccessDenied")})
    _, _, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.LOCATOR_NOT_PUBLISHED
    assert result.addressable is False
    assert locator_key not in s3.objects


def test_the_public_result_carries_no_subject_key_digest_or_bucket() -> None:
    _, _, result = _acquire()
    rendered = f"{result!r} {result.counts!r}"
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert SYNTHETIC_BUCKET not in rendered
    assert "licensed/" not in rendered


# -- the acquisition deadline: a stopwatch, not arithmetic ---------------------
#
# Every scenario below is priced in seconds the fakes actually spend on the
# injected monotonic clock, so the halt point is produced by the real admission
# arithmetic rather than asserted. With a 30-second request, a one-second pacing gap
# and 5 seconds per S3 invocation, one completed request costs 30 + 15 + 1 = 46, and
# the run halts when the remaining budget can no longer cover a whole request plus
# its downstream obligation.


def _pressed() -> tuple[FakeS3Client, PagedTransport, Any, FakeMonotonic]:
    """A run under real time pressure: 30s per request, 5s per S3 invocation."""
    monotonic = FakeMonotonic()
    transport = PagedTransport(monotonic=monotonic, seconds_per_request=30.0)
    s3 = FakeS3Client(monotonic=monotonic, seconds_per_operation=5.0)
    client, wire, result = _acquire(s3=s3, transport=transport, monotonic=monotonic)
    return client, wire, result, monotonic


def test_the_deadline_runs_on_an_injected_monotonic_clock_and_not_on_a_calendar() -> None:
    # The calendar clock is fixed for the whole run, so if any deadline arithmetic
    # read it, no budget could ever be consumed and the run would complete. A run
    # that halts on the budget therefore proves the budget is measured elsewhere.
    _, _, result, _ = _pressed()
    assert result.status is AcquisitionStatus.RUN_DEADLINE_EXHAUSTED
    assert result.deadline_exhausted is True


def test_moving_calendar_time_does_not_change_the_deadline_outcome() -> None:
    monotonic = FakeMonotonic()
    transport = PagedTransport(monotonic=monotonic, seconds_per_request=30.0)
    s3 = FakeS3Client(monotonic=monotonic, seconds_per_operation=5.0)
    # A calendar a decade earlier than the other scenario's, and a decade later.
    _, _, early = _acquire(
        s3=s3,
        transport=transport,
        monotonic=monotonic,
        instant=RUN_INSTANT.replace(year=RUN_INSTANT.year - 10),
    )
    monotonic_late = FakeMonotonic()
    _, _, late = _acquire(
        s3=FakeS3Client(monotonic=monotonic_late, seconds_per_operation=5.0),
        transport=PagedTransport(monotonic=monotonic_late, seconds_per_request=30.0),
        monotonic=monotonic_late,
        instant=RUN_INSTANT.replace(year=RUN_INSTANT.year + 10),
        execution_id=EXECUTION_ID_B,
    )
    assert early.status is AcquisitionStatus.RUN_DEADLINE_EXHAUSTED
    assert late.status is AcquisitionStatus.RUN_DEADLINE_EXHAUSTED
    assert early.counts.completed_requests == late.counts.completed_requests


def test_stages_one_to_ten_consume_none_of_the_acquisition_budget() -> None:
    # The monotonic clock is advanced only by the pacer and by the scripted fakes,
    # all of which are reached after arming. With neither fake scripted, the only
    # thing that moves the clock is pacing -- 47 gaps between 48 requests -- so the
    # authorization, inventory, identity, binding, credential, dependency and
    # offline-preflight stages provably contributed nothing.
    monotonic = FakeMonotonic()
    _, _, result = _acquire(monotonic=monotonic)
    assert result.status is AcquisitionStatus.COMPLETED
    assert monotonic() == pytest.approx(47.0)


def test_pacing_is_admitted_separately_and_is_never_truncated() -> None:
    monotonic = FakeMonotonic()
    _, _, result = _acquire(monotonic=monotonic)
    assert result.status is AcquisitionStatus.COMPLETED
    # Every recorded sleep is the full interval. Not one is shortened to fit.
    assert monotonic.sleep_calls == [pytest.approx(1.0)] * 47


def test_the_request_admission_requirement_omits_the_pacing_interval() -> None:
    # Stated as arithmetic against the compiled terms: the admission requirement is
    # the request ceiling plus the Bronze obligation plus the locator reserve, and
    # the pacing interval is **not** a term in it, because it has already elapsed.
    # ADR-0019: the per-request S3 obligation is ``3 * T_s3`` -- three Bronze writes
    # and **no** conditional resolution, because there is no metadata read to make.
    assert PROVIDER_REQUEST_ADMISSION_SECONDS == pytest.approx(
        TIMEOUT_SECONDS + 3 * S3_OPERATION_CEILING_SECONDS + LOCATOR_TERMINAL_RESERVE_SECONDS
    )
    assert PROVIDER_REQUEST_ADMISSION_SECONDS < (
        TIMEOUT_SECONDS
        + MIN_REQUEST_INTERVAL_SECONDS
        + 3 * S3_OPERATION_CEILING_SECONDS
        + LOCATOR_TERMINAL_RESERVE_SECONDS
    )
    # And the retired ADR-0018 term is genuinely gone rather than merely unused.
    assert PROVIDER_REQUEST_ADMISSION_SECONDS != pytest.approx(
        TIMEOUT_SECONDS + 6 * S3_OPERATION_CEILING_SECONDS + LOCATOR_TERMINAL_RESERVE_SECONDS
    )


def test_no_provider_request_begins_without_its_complete_downstream_reserve() -> None:
    _, wire, result, monotonic = _pressed()
    assert result.status is AcquisitionStatus.RUN_DEADLINE_EXHAUSTED
    assert wire.call_count < 48
    # The refused request was never sent, so it was never counted.
    assert result.counts.provider_request_count == wire.call_count
    # And the budget at the halt really was below the admission requirement.
    assert ACQUISITION_DEADLINE_SECONDS - monotonic() < PROVIDER_REQUEST_ADMISSION_SECONDS


def test_the_halt_point_is_the_one_the_admission_arithmetic_predicts() -> None:
    """The model is rebuilt from the compiled terms, and it models pacing correctly.

    One completed request under ``_pressed`` costs 30 seconds of request and three
    Bronze writes at 5 -- 45 in all, and **no** conditional resolution, because
    ADR-0019 left no metadata read to make. Forty-five seconds is far more than the
    one-second minimum interval, so the pacer owes nothing and sleeps nothing: an
    earlier model added a pacing second per request that never elapses, and it agreed
    with the observed count only by accident under the retired arithmetic.

    Everything below is computed from ``PROVIDER_REQUEST_ADMISSION_SECONDS`` and the
    fixture's own scripted costs. Nothing is transcribed.
    """
    _, wire, result, _ = _pressed()
    request_seconds = 30.0
    operation_seconds = 5.0
    predicted = 0
    elapsed = 0.0
    previous_request_at: float | None = None
    while True:
        # The pacer owes the remainder of the minimum interval since the previous
        # request began, and owes nothing at all when more than that has passed.
        owed = (
            0.0
            if previous_request_at is None
            else max(0.0, MIN_REQUEST_INTERVAL_SECONDS - (elapsed - previous_request_at))
        )
        after_pacing = elapsed + owed
        if ACQUISITION_DEADLINE_SECONDS - after_pacing < PROVIDER_REQUEST_ADMISSION_SECONDS:
            break
        predicted += 1
        previous_request_at = after_pacing
        elapsed = after_pacing + request_seconds + OBJECTS_PER_ACQUISITION * operation_seconds
    assert wire.call_count == predicted
    assert result.counts.completed_requests == predicted
    assert 0 < predicted < 48


def test_a_deadline_halt_keeps_every_completed_request_and_is_not_a_rollback() -> None:
    s3, _, result, _ = _pressed()
    completed = result.counts.completed_requests
    assert completed > 0
    document = json.loads(s3.objects["/".join(locator_key_segments(EXECUTION_ID))])
    assert document["completeness"] == "PARTIAL"
    assert document["completed_request_count"] == completed
    assert document["planned_request_count"] == 48


def test_the_locator_is_still_published_when_the_deadline_halts_the_run() -> None:
    s3, _, result, _ = _pressed()
    assert result.status is AcquisitionStatus.RUN_DEADLINE_EXHAUSTED
    assert result.addressable is True
    assert "/".join(locator_key_segments(EXECUTION_ID)) in s3.objects
    assert result.locator_attempts == 1


def test_no_bronze_operation_begins_without_sufficient_budget() -> None:
    # A transport that jumps the clock to one second before the deadline. The first
    # request was admitted while the whole budget was available; its Bronze writes
    # then cannot be admitted, because a Bronze write must leave the locator reserve
    # behind. Nothing is written, and the run halts.
    monotonic = FakeMonotonic()

    class _BudgetEater(PagedTransport):
        def get(self, **kwargs: Any) -> Any:
            response = super().get(**kwargs)
            monotonic.reading = ACQUISITION_DEADLINE_SECONDS - 1.0
            return response

    s3, _, result = _acquire(transport=_BudgetEater(), monotonic=monotonic)
    assert result.deadline_exhausted is True
    assert result.counts.completed_requests == 0
    assert s3.put_calls == []


def test_locator_not_published_when_the_terminal_reserve_cannot_complete() -> None:
    monotonic = FakeMonotonic()

    class _BudgetEater(PagedTransport):
        def get(self, **kwargs: Any) -> Any:
            response = super().get(**kwargs)
            monotonic.reading = ACQUISITION_DEADLINE_SECONDS - 1.0
            return response

    s3, _, result = _acquire(transport=_BudgetEater(), monotonic=monotonic)
    # Below the construction threshold, so no attempt is started and the result must
    # not claim a locator exists.
    assert result.status is AcquisitionStatus.LOCATOR_NOT_PUBLISHED
    assert result.locator_attempts == 0
    assert result.addressable is False
    assert "/".join(locator_key_segments(EXECUTION_ID)) not in s3.objects


def test_a_deadline_halt_authorizes_no_retry_and_publishes_no_second_locator() -> None:
    s3, _, result, _ = _pressed()
    assert result.locator_attempts == 1
    locators = [key for key in s3.objects if "/locators/" in key]
    assert len(locators) == 1


def test_the_forty_eight_request_inventory_is_a_maximum_and_not_a_guarantee() -> None:
    # The compiled worst case for the requests alone, plus the Bronze and locator
    # obligation they create, already exceeds the deadline -- which is exactly why
    # the deadline is a safety bound rather than a completion promise.
    request_phase = compiled_request_phase_seconds()
    bronze_and_locator = 48 * 6 * S3_OPERATION_CEILING_SECONDS + LOCATOR_TERMINAL_RESERVE_SECONDS
    assert request_phase + bronze_and_locator > ACQUISITION_DEADLINE_SECONDS


def test_provider_retries_stay_at_zero_under_a_deadline_halt() -> None:
    _, wire, result, _ = _pressed()
    assert wire.call_count == result.counts.provider_request_count
    assert NO_RETRY_POLICY.max_attempts == 1
    assert NO_RETRY_POLICY.backoff_seconds == ()


def test_a_deadline_halt_carries_no_subject_key_bucket_or_timing_trace() -> None:
    _, _, result, _ = _pressed()
    rendered = f"{result!r} {result.counts!r} {result.status.value}"
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert SYNTHETIC_BUCKET not in rendered
    assert "licensed/" not in rendered
    assert "1800" not in rendered


# -- assessment: the exact combined formulas ----------------------------------


def test_a_complete_combined_assessment_reads_e_times_two_r_plus_one_objects() -> None:
    s3 = _acquire_pair()
    result = _assess(s3)
    assert result.status is AssessmentStatus.COMPLETED
    assert result.counts.get_object_count == COMBINED_READS == 194
    assert result.counts.put_object_count == 1
    assert result.counts.head_object_count == 0
    assert result.counts.total_s3_operations == 195
    assert 195 <= result.counts.total_s3_operations <= 196


def test_the_combined_assessment_reads_exactly_two_locators_and_no_claim() -> None:
    s3 = _acquire_pair()
    _assess(s3)
    locator_reads = sorted(key for key in s3.get_calls if "/locators/" in key)
    assert locator_reads == sorted(
        [
            "/".join(locator_key_segments(EXECUTION_ID_A)),
            "/".join(locator_key_segments(EXECUTION_ID_B)),
        ]
    )
    assert [key for key in s3.get_calls if "_acquisition_claims" in key] == []


def test_the_combined_assessment_makes_no_provider_request_and_retrieves_no_credential() -> None:
    result = _assess(_acquire_pair())
    assert result.counts.provider_request_count == 0
    assert result.counts.credential_retrieval_count == 0


def test_the_combined_assessment_performs_no_listing_and_no_control_operation() -> None:
    s3 = _acquire_pair()
    result = _assess(s3)
    assert result.counts.list_operation_count == 0
    assert result.counts.control_operation_count == 0
    assert not hasattr(s3, "list_objects_v2")


def test_the_assessment_counters_are_the_real_client_invocations() -> None:
    """The accounting is a measurement, not a declaration.

    Each counter is compared against the number of times the fake client's own method
    was actually entered, so the envelope describes invocations that happened. That is
    the fact a hidden SDK retry would corrupt: it would turn one counted invocation
    into several attempts nobody counted, which is why both commands pin
    ``total_max_attempts`` to one rather than inheriting the SDK's default.
    """
    s3 = _acquire_pair()
    before = (len(s3.get_calls), len(s3.put_calls), len(s3.head_calls))
    reader = _reader(s3)
    result = _assess(s3, reader=reader)

    gets, puts, heads = (
        len(s3.get_calls) - before[0],
        len(s3.put_calls) - before[1],
        len(s3.head_calls) - before[2],
    )
    assert gets == reader.get_object_count == result.counts.get_object_count == 194
    assert puts == reader.put_object_count == result.counts.put_object_count == 1
    assert heads == reader.head_object_count == result.counts.head_object_count == 0
    assert result.counts.total_s3_operations == gets + puts + heads == 195
    assert 195 <= result.counts.total_s3_operations <= 196


def test_a_failed_report_write_is_not_retried() -> None:
    # One conditional PutObject for the report, and no second attempt. The remedy for
    # a failed report is a new assessment identity -- a re-run makes zero provider
    # requests -- and a retry here would be an operation the envelope never counted.
    s3 = FakeS3Client(fail_puts={_report_key(): client_error("InternalError")})
    _acquire(s3=s3, execution_id=EXECUTION_ID_A, instant=RUN_INSTANT)
    _acquire(s3=s3, execution_id=EXECUTION_ID_B, instant=RUN_B_INSTANT)
    before = len(s3.put_calls)

    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_REPORT
    report_attempts = [key for key in s3.put_calls[before:] if "/reports/" in key]
    assert report_attempts == [_report_key()]
    assert reader.put_object_count == 1
    assert reader.head_object_count == 0
    assert _report_key() not in s3.objects


def test_the_combined_assessment_publishes_exactly_one_private_report() -> None:
    s3 = _acquire_pair()
    _assess(s3)
    reports = [key for key in s3.objects if key.startswith("qualification/sharadar/reports/")]
    assert reports == [_report_key()]


def test_the_report_is_addressed_run_a_then_run_b_then_assessment() -> None:
    s3 = _acquire_pair()
    _assess(s3)
    key = _report_key()
    assert key.split("/")[3:] == [EXECUTION_ID_A, EXECUTION_ID_B, f"{ASSESSMENT_ID}.json"]
    assert key in s3.objects


def test_the_published_report_carries_the_nine_tests_and_no_verdict() -> None:
    s3 = _acquire_pair()
    _assess(s3)
    document = json.loads(s3.objects[_report_key()])
    assert [entry["test"] for entry in document["tests"]] == [f"P{i}" for i in range(1, 10)]
    assert document["evidence"]["run_a_execution_id"] == EXECUTION_ID_A
    assert document["evidence"]["run_b_execution_id"] == EXECUTION_ID_B
    assert document["evidence"]["separation_days"] == 9
    rendered = json.dumps(document)
    for forbidden in ("PROCEED", "APPROVED", "QUALIFIED", "recommendation", "readiness"):
        assert forbidden not in rendered
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered


def test_p1_reaches_tested_only_from_valid_cross_run_evidence() -> None:
    result = _assess(_acquire_pair())
    p1 = next(entry for entry in result.results if entry.test is ProviderTest.P1)
    assert p1.evidence_scope is EvidenceScope.COMBINED
    assert p1.status is PerTestStatus.TESTED


def test_every_other_p_test_ceiling_is_unchanged_by_the_combined_assessment() -> None:
    results = _assess(_acquire_pair()).results
    for entry in results:
        assert entry.ceiling is TEST_CEILINGS[entry.test]
        assert STATUS_RANK[entry.status] <= STATUS_RANK[entry.ceiling]
    by_test = {entry.test: entry.status for entry in results}
    assert by_test[ProviderTest.P2] is PerTestStatus.PARTIALLY_TESTED
    assert by_test[ProviderTest.P4] is PerTestStatus.DOCUMENTATION_RESOLVED
    assert by_test[ProviderTest.P6] is PerTestStatus.DEFERRED
    assert by_test[ProviderTest.P9] is PerTestStatus.DOCUMENTATION_RESOLVED


def test_the_locator_is_addressed_from_the_execution_identity_alone() -> None:
    assert locator_logical_key(EXECUTION_ID_A) == (
        f"licensed/qualification/sharadar/locators/{EXECUTION_ID_A}.json"
    )


# -- assessment refusals fail closed ------------------------------------------


def _refused(
    s3: FakeS3Client, *, run_a: str = EXECUTION_ID_A, run_b: str = EXECUTION_ID_B
) -> tuple[AssessmentError, LicensedObjectReader]:
    reader = _reader(s3)
    with pytest.raises(AssessmentError) as raised:
        _assess(s3, reader=reader, run_a=run_a, run_b=run_b)
    return raised.value, reader


def _assert_refused_pair_envelope(reader: LicensedObjectReader, s3: FakeS3Client) -> None:
    """The refused-pair ceiling: 0-2 locator reads, and nothing else at all."""
    assert reader.get_object_count <= EXECUTIONS_PER_ASSESSMENT
    assert reader.put_object_count == 0
    assert reader.head_object_count == 0
    assert [key for key in s3.get_calls if "/locators/" not in key] == []
    assert [key for key in s3.objects if "/reports/" in key] == []


def test_a_missing_locator_refuses_and_reads_no_payload() -> None:
    s3 = FakeS3Client()
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.get_object_count == 1
    _assert_refused_pair_envelope(reader, s3)


def test_duplicate_execution_identities_are_refused() -> None:
    s3 = _acquire_pair()
    failure, reader = _refused(s3, run_a=EXECUTION_ID_A, run_b=EXECUTION_ID_A)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    _assert_refused_pair_envelope(reader, s3)


def test_reversed_execution_identities_are_refused_before_any_payload_read() -> None:
    s3 = _acquire_pair()
    failure, reader = _refused(s3, run_a=EXECUTION_ID_B, run_b=EXECUTION_ID_A)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.get_object_count == 2
    _assert_refused_pair_envelope(reader, s3)


def test_runs_closer_than_the_minimum_separation_are_refused() -> None:
    s3 = FakeS3Client()
    _acquire(s3=s3, execution_id=EXECUTION_ID_A, instant=RUN_INSTANT)
    _acquire(s3=s3, execution_id=EXECUTION_ID_B, instant=RUN_INSTANT + timedelta(days=2))
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.get_object_count == 2
    _assert_refused_pair_envelope(reader, s3)


def test_exactly_the_minimum_separation_is_admitted() -> None:
    s3 = FakeS3Client()
    _acquire(s3=s3, execution_id=EXECUTION_ID_A, instant=RUN_INSTANT)
    _acquire(
        s3=s3,
        execution_id=EXECUTION_ID_B,
        instant=RUN_INSTANT + timedelta(days=MIN_RUN_SEPARATION_DAYS),
    )
    result = _assess(s3)
    assert result.status is AssessmentStatus.COMPLETED


def test_one_day_short_of_the_minimum_separation_is_refused() -> None:
    s3 = FakeS3Client()
    _acquire(s3=s3, execution_id=EXECUTION_ID_A, instant=RUN_INSTANT)
    _acquire(
        s3=s3,
        execution_id=EXECUTION_ID_B,
        instant=RUN_INSTANT + timedelta(days=MIN_RUN_SEPARATION_DAYS - 1),
    )
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    _assert_refused_pair_envelope(reader, s3)


def test_the_pair_rule_compares_the_one_accepted_plan_digest() -> None:
    """ADR-0018 asks for *the same plan digest*, and that is what is compared.

    Both locators are decoded and their recorded ``plan_digest`` values are read
    back: two runs of one plan share it, which is precisely why the digest is
    defined over the plan's stable shape. The unauthorized second digest the
    candidate had added is gone, and this is the check that replaces it.
    """
    from dataclasses import fields as dataclass_fields

    from kalpamani.data.qualify.sharadar.locator import decode_locator

    s3 = _acquire_pair()
    locators = [
        decode_locator(
            s3.objects["/".join(locator_key_segments(execution))], execution_id=execution
        )
        for execution in (EXECUTION_ID_A, EXECUTION_ID_B)
    ]
    run_a, run_b = locators
    assert run_a.execution_id != run_b.execution_id
    assert run_a.plan_digest == run_b.plan_digest
    names = {field.name for field in dataclass_fields(run_a)}
    assert "plan_digest" in names
    assert "plan_shape_digest" not in names
    assert _assess(s3).status is AssessmentStatus.COMPLETED


def test_a_matching_plan_digest_alone_admits_nothing() -> None:
    """Every other pair rule still refuses, with the plan digests equal.

    The digest answers one question -- *were these two runs of the same plan?* -- and
    the combined assessor asks nine more. Each case below holds the plan digest
    constant and violates exactly one of the others, so a digest comparison can never
    stand in for the rest of the admission.
    """
    from dataclasses import replace as dataclass_replace

    from kalpamani.data.qualify.sharadar.assessment import validate_locator_pair
    from kalpamani.data.qualify.sharadar.locator import Completeness, decode_locator

    s3 = _acquire_pair()
    run_a, run_b = (
        decode_locator(
            s3.objects["/".join(locator_key_segments(execution))], execution_id=execution
        )
        for execution in (EXECUTION_ID_A, EXECUTION_ID_B)
    )
    assert run_a.plan_digest == run_b.plan_digest
    assert validate_locator_pair(run_a, run_b) >= MIN_RUN_SEPARATION_DAYS

    variants = (
        # identity: one run twice is not two observations
        (run_a, run_a),
        # inventory: two runs over different private inventories
        (run_a, dataclass_replace(run_b, inventory_digest="f" * 64)),
        # schema: two runs recorded under different source schemas
        (run_a, dataclass_replace(run_b, source_schema_version="sharadar-empirical-v2")),
        # completeness: a PARTIAL locator grants no evaluation
        (run_a, dataclass_replace(run_b, completeness=Completeness.PARTIAL)),
        # ambiguity: an unknown publication state refuses
        (run_a, dataclass_replace(run_b, publication_state_unknown=True)),
        # counts: a different planned count is a different question asked
        (run_a, dataclass_replace(run_b, planned_request_count=47)),
        # counts: completed short of planned is not a complete run
        (run_a, dataclass_replace(run_b, completed_request_count=47)),
        # ordering, and therefore separation: Run B before Run A
        (run_b, run_a),
    )
    for first, second in variants:
        assert first.plan_digest == second.plan_digest
        with pytest.raises(AssessmentError) as raised:
            validate_locator_pair(first, second)
        assert raised.value.status is AssessmentStatus.REFUSED_LOCATOR


def test_a_differing_plan_digest_refuses_before_a_record_or_payload_is_read() -> None:
    # Two runs of two different plans: Run B asks for a different subject inventory,
    # so its stable plan digest differs. The refusal costs two locator reads and
    # nothing else -- no acquisition record, no payload, no report.
    s3 = FakeS3Client()
    _acquire(s3=s3, execution_id=EXECUTION_ID_A, instant=RUN_INSTANT)
    other = tuple(f"ZZ-OTHER-{index:02d}" for index in range(1, 9))
    monotonic = FakeMonotonic()
    run_empirical_acquisition(
        credential=credential(),
        transport=PagedTransport(),
        monotonic=monotonic,
        sleeper=monotonic.sleep,
        s3_client=s3,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(RUN_B_INSTANT),
        inventory=synthetic_inventory(other),
        execution_id=EXECUTION_ID_B,
    )
    from kalpamani.data.qualify.sharadar.locator import decode_locator

    run_a, run_b = (
        decode_locator(
            s3.objects["/".join(locator_key_segments(execution))], execution_id=execution
        )
        for execution in (EXECUTION_ID_A, EXECUTION_ID_B)
    )
    # The digests genuinely differ, so the refusal below is this rule's and not
    # another's arriving first.
    assert run_a.plan_digest != run_b.plan_digest

    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.get_object_count == 2
    _assert_refused_pair_envelope(reader, s3)
    assert [key for key in s3.get_calls if "/objects/sha256/" in key] == []
    assert [key for key in s3.get_calls if "/acquisitions/" in key] == []


def test_a_mismatched_pair_from_different_inventories_is_refused() -> None:
    s3 = FakeS3Client()
    _acquire(s3=s3, execution_id=EXECUTION_ID_A, instant=RUN_INSTANT)
    # Run B against a different private inventory: different subjects, so its
    # inventory digest differs -- and the inventory rule refuses on that alone.
    other = tuple(f"ZZ-OTHER-{index:02d}" for index in range(1, 9))
    monotonic = FakeMonotonic()
    run_empirical_acquisition(
        credential=credential(),
        transport=PagedTransport(),
        monotonic=monotonic,
        sleeper=monotonic.sleep,
        s3_client=s3,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(RUN_B_INSTANT),
        inventory=synthetic_inventory(other),
        execution_id=EXECUTION_ID_B,
    )
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.get_object_count == 2
    _assert_refused_pair_envelope(reader, s3)


def test_a_partial_locator_is_refused_and_no_payload_is_read() -> None:
    s3 = FakeS3Client()
    _acquire(
        s3=s3,
        transport=PagedTransport(fail_after=10, byte_variant=_variant(EXECUTION_ID_A)),
        execution_id=EXECUTION_ID_A,
    )
    _acquire(s3=s3, execution_id=EXECUTION_ID_B, instant=RUN_B_INSTANT)
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.get_object_count == 2
    _assert_refused_pair_envelope(reader, s3)


def test_an_assessment_for_another_execution_identity_is_refused() -> None:
    s3 = _acquire_pair()
    failure, _ = _refused(s3, run_b="synthetic-empirical-c")
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR


def test_a_tampered_payload_refuses_on_integrity_before_it_is_parsed() -> None:
    s3 = _acquire_pair()
    payload_keys = [key for key in s3.objects if "/objects/sha256/" in key]
    s3.objects[payload_keys[0]] = b"ticker,date,close\nTAMPERED,1998-01-05,1\n"
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_INTEGRITY
    assert reader.put_object_count == 0


def test_a_record_contradicting_its_locator_entry_refuses_on_integrity() -> None:
    s3 = _acquire_pair()
    record_keys = sorted(key for key in s3.objects if "/acquisitions/" in key)
    original = json.loads(s3.objects[record_keys[0]])
    original["dataset"] = "actions"
    # Re-published under the same name with different content: the digest check in
    # the reader is what catches it, before any interpretation happens.
    s3.objects[record_keys[0]] = json.dumps(original).encode("utf-8")
    failure, _ = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_INTEGRITY


def test_an_unparseable_payload_refuses_on_evidence_and_publishes_no_report() -> None:
    # Published through the real acquisition path, so every digest, record and
    # locator entry stays mutually consistent and the **parser** is genuinely what
    # refuses. Editing a stored object afterwards would trip the integrity check
    # one stage earlier and prove nothing about the parser.
    ragged = b"ticker,date,close" + b"\n" + b"Z,1998-01-05" + b"\n"
    s3 = FakeS3Client()
    _acquire(
        s3=s3,
        transport=PagedTransport(body_override=ragged, byte_variant=_variant(EXECUTION_ID_A)),
        execution_id=EXECUTION_ID_A,
    )
    _acquire(
        s3=s3,
        transport=PagedTransport(body_override=ragged, byte_variant=_variant(EXECUTION_ID_B)),
        execution_id=EXECUTION_ID_B,
        instant=RUN_B_INSTANT,
    )
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_EVIDENCE
    assert reader.put_object_count == 0


def test_no_assessment_refusal_carries_a_key_subject_or_bucket() -> None:
    failure, _ = _refused(FakeS3Client())
    rendered = f"{failure} {failure!r} {failure.args}"
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert SYNTHETIC_BUCKET not in rendered
    assert "licensed/" not in rendered


def test_an_unaddressable_run_b_leaves_the_pair_unassessable() -> None:
    locator_key = "/".join(locator_key_segments(EXECUTION_ID_B))
    s3 = FakeS3Client(fail_puts={locator_key: client_error("AccessDenied")})
    _acquire(s3=s3, execution_id=EXECUTION_ID_A, instant=RUN_INSTANT)
    _, _, result = _acquire(s3=s3, execution_id=EXECUTION_ID_B, instant=RUN_B_INSTANT)
    assert result.status is AcquisitionStatus.LOCATOR_NOT_PUBLISHED
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.put_object_count == 0


# -- the fixed request inventory: 48, and never a number a locator supplied ----


def _locator_document(s3: FakeS3Client, execution_id: str) -> dict[str, Any]:
    key = "/".join(locator_key_segments(execution_id))
    document = json.loads(s3.objects[key].decode("utf-8"))
    assert type(document) is dict
    return document


def _rescale_entries(entries: list[Any], *, count: int) -> list[Any]:
    """``count`` entries, all distinct, from a real ``entries`` list of any length.

    Trimmed when ``count`` is smaller, and extended by cloning under a fresh
    acquisition identity and record key when it is larger -- the locator schema
    refuses a duplicated identity or record key, so a fabricated extra request has to
    look like a genuinely separate one. A clone keeps its source's subject, dataset,
    page limit and page skip, so two runs rescaled the same way still present matching
    request inventories and the inventory rule cannot be what refuses.
    """
    rescaled = [dict(entry) for entry in entries[:count]]
    while len(rescaled) < count:
        clone = dict(entries[len(rescaled) % len(entries)])
        clone["acquisition_id"] = f"{clone['acquisition_id']}-extra-{len(rescaled)}"
        clone["record_key"] = f"{clone['record_key']}-extra-{len(rescaled)}"
        rescaled.append(clone)
    return rescaled


def _rescale_locator_in_store(s3: FakeS3Client, execution_id: str, *, count: int) -> None:
    """Republish one stored locator as a **self-consistent** ``count``-request run.

    Counts, entry list and completeness all agree, so the locator is ``assessable``
    and every other pair rule still passes: the only thing wrong with it is that
    ``count`` is not the accepted inventory. That is exactly the pair a run-to-run
    comparison admits and the fixed-count precondition refuses.
    """
    document = _locator_document(s3, execution_id)
    document["entries"] = _rescale_entries(list(document["entries"]), count=count)
    document["planned_request_count"] = count
    document["completed_request_count"] = count
    s3.objects["/".join(locator_key_segments(execution_id))] = serialize_locator(document)


def _rescaled_pair(count: int) -> FakeS3Client:
    """Both accepted runs, republished at ``count`` requests each."""
    s3 = _acquire_pair()
    for execution_id in (EXECUTION_ID_A, EXECUTION_ID_B):
        _rescale_locator_in_store(s3, execution_id, count=count)
    return s3


def _decoded_pair(s3: FakeS3Client) -> tuple[Any, Any]:
    first, second = (
        decode_locator(
            s3.objects["/".join(locator_key_segments(execution_id))],
            execution_id=execution_id,
        )
        for execution_id in (EXECUTION_ID_A, EXECUTION_ID_B)
    )
    return first, second


def test_the_accepted_pair_satisfies_the_fixed_request_count_precondition() -> None:
    """The real thing passes, and it passes *at the compiled constant*.

    Pinned against ``EMPIRICAL_REQUEST_COUNT`` rather than a bare literal, so a plan
    whose factors changed cannot leave this assertion describing the old inventory --
    and against the literal 48 as well, because 48 is the accepted architecture and a
    silent change to the constant is exactly what a literal is here to catch.
    """
    s3 = _acquire_pair()
    run_a, run_b = _decoded_pair(s3)
    for locator in (run_a, run_b):
        assert locator.planned_request_count == EMPIRICAL_REQUEST_COUNT == 48
        assert locator.completed_request_count == EMPIRICAL_REQUEST_COUNT == 48
    assert validate_locator_pair(run_a, run_b) >= MIN_RUN_SEPARATION_DAYS
    assert _assess(s3).status is AssessmentStatus.COMPLETED


@pytest.mark.parametrize("count", [1, 24, 47, 49, 96])
def test_a_self_consistent_pair_at_any_other_count_is_refused(count: int) -> None:
    """Run-to-run agreement is not the rule. **The compiled inventory is.**

    Each pair below agrees with itself perfectly: the same count in both runs,
    completed equal to planned, an entry list of exactly that length, the same plan
    digest, the same inventory digest, the same schema, matching request inventories,
    nine calendar days apart. Every rule that existed before this precondition admits
    it. It is refused because 48 is the accepted experiment and this is not it.
    """
    assert count != EMPIRICAL_REQUEST_COUNT
    run_a, run_b = _decoded_pair(_rescaled_pair(count))
    for locator in (run_a, run_b):
        # Genuinely self-consistent: the pre-existing rules have nothing to object to.
        assert locator.assessable
        assert locator.planned_request_count == locator.completed_request_count == count
        assert len(locator.entries) == count
    assert run_a.plan_digest == run_b.plan_digest
    assert run_a.inventory_digest == run_b.inventory_digest
    assert run_a.source_schema_version == run_b.source_schema_version
    assert (run_b.run_date - run_a.run_date).days >= MIN_RUN_SEPARATION_DAYS

    with pytest.raises(AssessmentError) as raised:
        validate_locator_pair(run_a, run_b)
    assert raised.value.status is AssessmentStatus.REFUSED_LOCATOR


@pytest.mark.parametrize("count", [47, 49])
def test_one_run_at_the_accepted_count_and_one_at_another_is_refused(count: int) -> None:
    """A mismatched pair is refused in **both** orders, whichever run is the wrong one."""
    assert count != EMPIRICAL_REQUEST_COUNT
    s3 = _acquire_pair()
    _rescale_locator_in_store(s3, EXECUTION_ID_B, count=count)
    accepted, other = _decoded_pair(s3)
    assert accepted.planned_request_count == EMPIRICAL_REQUEST_COUNT
    assert other.planned_request_count == count

    for first, second in ((accepted, other), (other, accepted)):
        with pytest.raises(AssessmentError) as raised:
            validate_locator_pair(first, second)
        assert raised.value.status is AssessmentStatus.REFUSED_LOCATOR


def test_completed_short_of_the_accepted_count_never_reaches_evaluation() -> None:
    """Planned 48 with completed below 48 is refused, and by two rules rather than one.

    A short run cannot be ``assessable`` -- that rule predates this correction and
    reaches it first -- and the fixed-count precondition refuses the same evidence
    independently, which is what the self-consistent form below demonstrates. Neither
    reading admits it.
    """
    run_a, run_b = _decoded_pair(_acquire_pair())
    short = dataclass_replace(
        run_b,
        completed_request_count=EMPIRICAL_REQUEST_COUNT - 1,
        entries=run_b.entries[: EMPIRICAL_REQUEST_COUNT - 1],
    )
    assert short.planned_request_count == EMPIRICAL_REQUEST_COUNT
    assert short.completed_request_count < EMPIRICAL_REQUEST_COUNT
    assert not short.assessable
    with pytest.raises(AssessmentError) as raised:
        validate_locator_pair(run_a, short)
    assert raised.value.status is AssessmentStatus.REFUSED_LOCATOR

    # The same shortfall made self-consistent -- assessable now, and still refused,
    # this time by the fixed-count precondition alone.
    self_consistent = dataclass_replace(short, planned_request_count=EMPIRICAL_REQUEST_COUNT - 1)
    assert self_consistent.assessable
    with pytest.raises(AssessmentError) as raised:
        validate_locator_pair(run_a, self_consistent)
    assert raised.value.status is AssessmentStatus.REFUSED_LOCATOR


@pytest.mark.parametrize("count", [47, 49])
def test_a_non_accepted_inventory_refuses_before_any_record_or_payload_read(count: int) -> None:
    """The precondition runs **before** the evidence is touched, end to end.

    Driven through ``run_combined_assessment`` rather than the validator alone, so the
    ordering exercised is the real one. The 49-request form is the sharper case: its
    fabricated entry names a record object that was never published, so a build that
    read first and validated afterwards would refuse on *integrity* after issuing
    reads. Observing ``REFUSED_LOCATOR`` at two locator reads is therefore evidence
    about order, and not only about outcome.
    """
    s3 = _rescaled_pair(count)
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.get_object_count == EXECUTIONS_PER_ASSESSMENT == 2
    assert [key for key in s3.get_calls if "/acquisitions/" in key] == []
    assert [key for key in s3.get_calls if "/objects/sha256/" in key] == []
    _assert_refused_pair_envelope(reader, s3)


@pytest.mark.parametrize("count", [47, 49])
def test_a_non_accepted_inventory_publishes_no_report(count: int) -> None:
    s3 = _rescaled_pair(count)
    before = len(s3.put_calls)
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.put_object_count == 0
    assert reader.head_object_count == 0
    assert len(s3.put_calls) == before
    assert [key for key in s3.objects if "/reports/" in key] == []


@pytest.mark.parametrize("count", [47, 49])
def test_the_refused_inventory_envelope_is_at_most_two_locator_reads(count: int) -> None:
    """0-2 locator reads, 0 records, 0 payloads, 0 report operations."""
    s3 = _rescaled_pair(count)
    failure, reader = _refused(s3)
    assert failure.status is AssessmentStatus.REFUSED_LOCATOR
    assert 0 <= reader.get_object_count <= EXECUTIONS_PER_ASSESSMENT
    assert [key for key in s3.get_calls if "/locators/" not in key] == []
    assert reader.put_object_count == 0
    assert reader.head_object_count == 0
    assert reader.get_object_count + reader.put_object_count + reader.head_object_count <= 2


def test_a_refusal_on_the_fixed_inventory_discloses_neither_the_count_nor_a_subject() -> None:
    """The refusal is one closed member. **The number it saw is not in it.**"""
    s3 = _rescaled_pair(96)
    failure, _ = _refused(s3)
    rendered = f"{failure} {failure!r} {failure.args}"
    assert "96" not in rendered
    assert "48" not in rendered
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert SYNTHETIC_BUCKET not in rendered
    assert "licensed/" not in rendered
    assert EXECUTION_ID_A not in rendered
    assert EXECUTION_ID_B not in rendered


# -- the defensive accounting boundary ----------------------------------------


def _counts(**overrides: int) -> Any:
    """One accepted combined accounting, with the named fields overridden."""
    fields: dict[str, int] = {
        "executions": EXECUTIONS_PER_ASSESSMENT,
        "planned_requests": EMPIRICAL_REQUEST_COUNT,
        "get_object_count": COMBINED_READS,
        "put_object_count": 1,
        "head_object_count": 0,
        "list_operation_count": 0,
        "control_operation_count": 0,
        "provider_request_count": 0,
        "credential_retrieval_count": 0,
        "claim_read_count": 0,
    }
    fields.update(overrides)
    return AssessmentOperationCounts(**fields)


def test_the_accepted_assessment_accounting_is_constructible() -> None:
    counts = _counts()
    assert counts.get_object_count == 194
    assert counts.total_s3_operations == 195
    assert _counts(head_object_count=1).total_s3_operations == 196


@pytest.mark.parametrize("count", [0, 1, 24, 47, 49, 96])
def test_an_admitted_accounting_refuses_any_inventory_but_the_compiled_one(count: int) -> None:
    """The read ceiling may not be scaled by the evidence it is meant to bound.

    Each case supplies exactly the reads ``E * (2R + 1)`` would permit for its own
    ``R``, so every one of them satisfied the previous ceiling precisely. At ``R = 96``
    that is 386 reads called lawful -- nearly twice the accepted 194 -- which is the
    failure this boundary stops even if a future caller skipped or misordered the pair
    validation.
    """
    assert count != EMPIRICAL_REQUEST_COUNT
    with pytest.raises(ValueError):
        _counts(
            planned_requests=count,
            get_object_count=EXECUTIONS_PER_ASSESSMENT * (2 * count + 1),
        )


def test_an_admitted_accounting_is_refused_and_never_clamped_to_the_accepted_count() -> None:
    """Invalid evidence is refused. It does not become 48 by being reported as 48."""
    with pytest.raises(ValueError):
        _counts(planned_requests=96, get_object_count=COMBINED_READS)
    with pytest.raises(ValueError):
        _counts(planned_requests=47)


def test_the_refused_pair_accounting_admits_no_request_inventory() -> None:
    """Nothing was admitted, so no inventory may be claimed -- and nothing beyond the
    two locator reads may be counted."""
    refused = _counts(
        executions=0,
        planned_requests=0,
        get_object_count=EXECUTIONS_PER_ASSESSMENT,
        put_object_count=0,
    )
    assert refused.total_s3_operations == 2
    with pytest.raises(ValueError):
        _counts(
            executions=0,
            planned_requests=EMPIRICAL_REQUEST_COUNT,
            get_object_count=EXECUTIONS_PER_ASSESSMENT,
            put_object_count=0,
        )
    with pytest.raises(ValueError):
        _counts(executions=0, planned_requests=0, get_object_count=3, put_object_count=0)


def test_a_complete_assessment_still_reports_the_accepted_operation_envelope() -> None:
    """Two locators, 96 records, 96 payloads, one report -- unchanged by the fix.

    The decomposition is read off the fake client's own call log, so it is what the
    real code asked for rather than what the accounting declared.
    """
    s3 = _acquire_pair()
    before = len(s3.get_calls)
    result = _assess(s3)
    reads = s3.get_calls[before:]

    locator_reads = [key for key in reads if "/locators/" in key]
    record_reads = [key for key in reads if "/acquisitions/" in key]
    payload_reads = [key for key in reads if "/objects/sha256/" in key]
    assert len(locator_reads) == EXECUTIONS_PER_ASSESSMENT == 2
    assert len(record_reads) == EXECUTIONS_PER_ASSESSMENT * EMPIRICAL_REQUEST_COUNT == 96
    assert len(payload_reads) == EXECUTIONS_PER_ASSESSMENT * EMPIRICAL_REQUEST_COUNT == 96
    assert len(reads) == COMBINED_READS == 194

    assert result.status is AssessmentStatus.COMPLETED
    assert result.counts.planned_requests == EMPIRICAL_REQUEST_COUNT == 48
    assert result.counts.get_object_count == 194
    assert result.counts.put_object_count == 1
    assert 0 <= result.counts.head_object_count <= 1
    assert 195 <= result.counts.total_s3_operations <= 196


# -- the ADR-0017 surface is untouched ----------------------------------------


def test_the_earlier_authenticated_entry_point_is_not_imported_or_reused() -> None:
    from pathlib import Path

    import kalpamani.data.qualify.sharadar.acquisition as acquisition_module
    import kalpamani.data.qualify.sharadar.assessment as assessment_module

    for module in (acquisition_module, assessment_module):
        assert module.__file__ is not None
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "sharadar_authenticated_qualification" not in source
        assert "sharadar_private_qualification" not in source
