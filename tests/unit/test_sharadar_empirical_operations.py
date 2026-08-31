"""Operation counting and the locator retry matrix, driven rather than asserted.

The accepted arithmetic is a set of numbers, and this file produces them by running
the real code against fakes that count every call. Where a bound depends on a
condition -- "a retry-triggering attempt sends no ``HeadObject``" -- the condition is
driven both ways, because a bound proven in one direction is half a bound.
"""

from __future__ import annotations

import pytest

from fixtures.sharadar_empirical import (
    EXECUTION_ID,
    SYNTHETIC_BUCKET,
    FakeMonotonic,
    FakeS3Client,
    FixedClock,
    PagedTransport,
    credential,
    synthetic_inventory,
)
from kalpamani.data.contracts.errors import ObjectAlreadyExistsError, ObjectStoreBackendError
from kalpamani.data.contracts.vocabulary import ObjectStoreFailure, ObjectStoreOperation
from kalpamani.data.objectstore import ObjectKey, PutOutcome
from kalpamani.data.qualify.sharadar.acquisition import run_empirical_acquisition
from kalpamani.data.qualify.sharadar.operations import (
    ADDRESSABLE_STATUSES,
    MAX_LOCATOR_ATTEMPTS,
    OBJECTS_PER_ACQUISITION,
    RETRYABLE_LOCATOR_FAILURES,
    AcquisitionDeadline,
    AcquisitionOperationCounts,
    CountingS3Client,
    DeadlineExhaustedError,
    DeadlinePhase,
    DeadlineStage,
    LocatorPublication,
    LocatorPublicationStatus,
    publish_locator,
)
from kalpamani.data.qualify.sharadar.plan import (
    ACQUISITION_DEADLINE_SECONDS,
    BRONZE_OPERATION_ADMISSION_SECONDS,
    LOCATOR_ATTEMPT_ADMISSION_SECONDS,
    LOCATOR_OPERATION_ADMISSION_SECONDS,
    MIN_REQUEST_INTERVAL_SECONDS,
    PROVIDER_REQUEST_ADMISSION_SECONDS,
    EmpiricalPlanError,
)


def _armed(
    monotonic: FakeMonotonic | None = None, *, locator_phase: bool = True
) -> AcquisitionDeadline:
    """An armed deadline with the whole budget available, in the locator phase.

    Most of this file exercises locator publication, which really does run in the
    locator phase, so that is the default. Passing ``locator_phase=False`` leaves it
    in the acquisition phase, where a Bronze write must also leave the reserve.
    """
    deadline = AcquisitionDeadline(monotonic=monotonic or FakeMonotonic())
    deadline.arm()
    if locator_phase:
        deadline.begin_locator_phase()
    return deadline


PAYLOAD = b"synthetic-locator-bytes"
KEY = ObjectKey.licensed("qualification", "sharadar", "locators", "x.json", payload=PAYLOAD)


class _ScriptedStore:
    """A store that replays a queued sequence of outcomes and counts attempts."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.attempts = 0

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        self.attempts += 1
        if not self._outcomes:
            raise AssertionError("the scripted store ran out of queued outcomes")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, PutOutcome)
        return outcome


def _stored() -> PutOutcome:
    return PutOutcome(key=KEY, stored=True, byte_count=len(PAYLOAD))


def _already() -> PutOutcome:
    return PutOutcome(key=KEY, stored=False, byte_count=len(PAYLOAD))


def _backend(failure: ObjectStoreFailure, operation: ObjectStoreOperation) -> Exception:
    return ObjectStoreBackendError(operation=operation, failure=failure)


def _publish(
    outcomes: list[object], *, deadline: AcquisitionDeadline | None = None
) -> tuple[LocatorPublication, int]:
    store = _ScriptedStore(outcomes)
    publication = publish_locator(
        store=store, key=KEY, payload=PAYLOAD, deadline=deadline or _armed()
    )
    return publication, store.attempts


# -- the retry matrix, both directions ---------------------------------------


def test_a_first_attempt_that_writes_needs_no_retry() -> None:
    publication, attempts = _publish([_stored()])
    assert publication.status is LocatorPublicationStatus.PUBLISHED
    assert publication.attempts == attempts == 1


def test_identical_content_already_present_is_an_ordinary_idempotent_outcome() -> None:
    publication, attempts = _publish([_already()])
    assert publication.status is LocatorPublicationStatus.ALREADY_PRESENT
    assert attempts == 1
    assert publication.addressable is True


@pytest.mark.parametrize("failure", [ObjectStoreFailure.THROTTLED, ObjectStoreFailure.TRANSIENT])
def test_an_unresolved_condition_is_retried_and_can_succeed(
    failure: ObjectStoreFailure,
) -> None:
    publication, attempts = _publish([_backend(failure, ObjectStoreOperation.PUT), _stored()])
    assert publication.status is LocatorPublicationStatus.PUBLISHED
    assert publication.attempts == attempts == 2


def test_at_most_two_retries_are_permitted_after_the_first_attempt() -> None:
    publication, attempts = _publish(
        [_backend(ObjectStoreFailure.THROTTLED, ObjectStoreOperation.PUT)] * 3
    )
    assert attempts == MAX_LOCATOR_ATTEMPTS == 3
    assert publication.attempts == 3
    assert publication.status is LocatorPublicationStatus.NOT_PUBLISHED


def test_a_retry_that_finds_an_earlier_attempt_committed_reports_already_present() -> None:
    publication, attempts = _publish(
        [_backend(ObjectStoreFailure.TRANSIENT, ObjectStoreOperation.PUT), _already()]
    )
    assert publication.status is LocatorPublicationStatus.ALREADY_PRESENT
    assert attempts == 2


@pytest.mark.parametrize(
    "failure",
    [
        ObjectStoreFailure.ACCESS_DENIED,
        ObjectStoreFailure.NOT_FOUND,
        ObjectStoreFailure.INVALID_CONFIGURATION,
    ],
)
def test_a_definitive_refusal_is_never_retried(failure: ObjectStoreFailure) -> None:
    publication, attempts = _publish([_backend(failure, ObjectStoreOperation.PUT)])
    assert attempts == 1
    assert publication.status is LocatorPublicationStatus.NOT_PUBLISHED


@pytest.mark.parametrize(
    "failure", [ObjectStoreFailure.INVALID_RESPONSE, ObjectStoreFailure.UNKNOWN]
)
def test_an_ambiguous_result_is_never_retried_and_reports_state_unknown(
    failure: ObjectStoreFailure,
) -> None:
    publication, attempts = _publish([_backend(failure, ObjectStoreOperation.PUT)])
    assert attempts == 1
    assert publication.status is LocatorPublicationStatus.STATE_UNKNOWN
    assert publication.addressable is False


def test_a_genuine_collision_is_never_retried() -> None:
    publication, attempts = _publish([ObjectAlreadyExistsError("different content")])
    assert attempts == 1
    assert publication.status is LocatorPublicationStatus.COLLISION
    assert publication.addressable is False


def test_a_post_412_metadata_failure_does_not_restore_retry_permission() -> None:
    # The condition was resolved by the 412, so a THROTTLED refusal of the *metadata*
    # resolution arrives too late to be retryable -- and the operation says so.
    publication, attempts = _publish(
        [_backend(ObjectStoreFailure.THROTTLED, ObjectStoreOperation.HEAD)]
    )
    assert attempts == 1
    assert publication.status is LocatorPublicationStatus.NOT_PUBLISHED


def test_an_unclassified_exception_is_state_unknown_and_not_retried() -> None:
    publication, attempts = _publish([RuntimeError("a store this module did not write")])
    assert attempts == 1
    assert publication.status is LocatorPublicationStatus.STATE_UNKNOWN


def test_only_two_failure_categories_are_retryable() -> None:
    assert RETRYABLE_LOCATOR_FAILURES == {
        ObjectStoreFailure.THROTTLED,
        ObjectStoreFailure.TRANSIENT,
    }


def test_only_two_statuses_leave_the_locator_addressable() -> None:
    assert ADDRESSABLE_STATUSES == {
        LocatorPublicationStatus.PUBLISHED,
        LocatorPublicationStatus.ALREADY_PRESENT,
    }


def test_every_retry_sends_byte_identical_content() -> None:
    seen: list[bytes] = []

    class _Recording:
        def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
            seen.append(payload)
            if len(seen) < 3:
                raise _backend(ObjectStoreFailure.THROTTLED, ObjectStoreOperation.PUT)
            return _stored()

    publish_locator(store=_Recording(), key=KEY, payload=PAYLOAD, deadline=_armed())
    assert len(seen) == 3
    assert seen[0] == seen[1] == seen[2] == PAYLOAD


# -- the counting wrapper ----------------------------------------------------


def test_the_counting_client_counts_invocations_including_failed_ones() -> None:
    class _Raising:
        def put_object(self, **kwargs: object) -> object:
            raise RuntimeError("synthetic")

        def head_object(self, **kwargs: object) -> object:
            raise RuntimeError("synthetic")

    counting = CountingS3Client(_Raising(), deadline=_armed())
    for method in (counting.put_object, counting.head_object):
        with pytest.raises(RuntimeError):
            method()
    assert counting.put_object_count == 1
    assert counting.head_object_count == 1


def test_the_counting_client_exposes_no_read_surface() -> None:
    counting = CountingS3Client(FakeS3Client(), deadline=_armed())
    for forbidden in ("get_object", "list_objects_v2", "delete_object", "copy_object"):
        assert not hasattr(counting, forbidden)


def test_the_counting_client_repr_names_no_bucket_or_key() -> None:
    rendered = repr(CountingS3Client(FakeS3Client(), deadline=_armed()))
    assert SYNTHETIC_BUCKET not in rendered
    assert "put_object=0" in rendered


def test_a_client_that_cannot_serve_the_two_operations_is_refused() -> None:
    with pytest.raises(ObjectStoreBackendError):
        CountingS3Client(object(), deadline=_armed())


# -- the accounting invariants ------------------------------------------------


def _counts(**overrides: int) -> AcquisitionOperationCounts:
    base = {
        "completed_requests": 48,
        "put_object_count": 145,
        "head_object_count": 21,
        "get_object_count": 0,
        "list_operation_count": 0,
        "control_operation_count": 0,
        "locator_put_attempts": 1,
        "provider_request_count": 48,
    }
    base.update(overrides)
    return AcquisitionOperationCounts(**base)


def test_the_nominal_complete_run_accounting_is_accepted() -> None:
    counts = _counts()
    assert counts.put_object_count == OBJECTS_PER_ACQUISITION * 48 + 1 == 145
    assert counts.total_s3_operations == 166


def test_put_object_below_three_per_completed_acquisition_is_refused() -> None:
    with pytest.raises(ValueError):
        _counts(put_object_count=144)


def test_at_most_one_incomplete_publication_may_exceed_the_per_request_writes() -> None:
    # A halted run can leave one publication part-written -- one or two of its three
    # conditional writes really happened and are really counted, while its request
    # never became a completed acquisition. Two extra writes is the ceiling; three
    # would be a second incomplete publication, which the runtime cannot produce
    # because it stops at the first terminal failure.
    assert _counts(completed_requests=47, put_object_count=143).put_object_count == 143
    with pytest.raises(ValueError):
        _counts(completed_requests=47, put_object_count=145)


def test_a_retried_locator_raises_put_object_to_at_most_one_hundred_and_forty_seven() -> None:
    counts = _counts(locator_put_attempts=3, put_object_count=147)
    assert counts.put_object_count == 147


def test_more_than_three_locator_attempts_is_refused() -> None:
    with pytest.raises(ValueError):
        _counts(locator_put_attempts=4, put_object_count=148)


def test_head_object_is_bounded_by_the_bronze_writes_plus_one_locator() -> None:
    assert _counts(head_object_count=145).head_object_count == 145
    with pytest.raises(ValueError):
        _counts(head_object_count=146)


def test_the_head_bound_does_not_rise_with_locator_retries() -> None:
    # The extra PutObject invocations a retry buys are exactly the ones that sent no
    # HeadObject, so 147 PutObject still permits at most 145 HeadObject.
    with pytest.raises(ValueError):
        _counts(locator_put_attempts=3, put_object_count=147, head_object_count=146)


def test_any_object_byte_read_on_the_acquisition_path_is_refused() -> None:
    with pytest.raises(ValueError):
        _counts(get_object_count=1)


def test_any_listing_operation_is_refused() -> None:
    with pytest.raises(ValueError):
        _counts(list_operation_count=1)


def test_any_control_operation_is_refused() -> None:
    with pytest.raises(ValueError):
        _counts(control_operation_count=1)


def test_the_accounting_may_not_be_subclassed() -> None:
    with pytest.raises(TypeError):

        class _Restated(AcquisitionOperationCounts):
            pass


# -- the same numbers, produced by a real run --------------------------------


def test_a_complete_run_produces_the_accepted_nominal_arithmetic() -> None:
    s3 = FakeS3Client()
    monotonic = FakeMonotonic()
    result = run_empirical_acquisition(
        credential=credential(),
        transport=PagedTransport(),
        monotonic=monotonic,
        sleeper=monotonic.sleep,
        s3_client=s3,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(),
        inventory=synthetic_inventory(),
        execution_id=EXECUTION_ID,
    )
    counts = result.counts
    assert counts.provider_request_count == 48
    assert counts.completed_requests == 48
    assert counts.put_object_count == 145
    assert 144 <= counts.put_object_count <= 147
    assert counts.head_object_count <= 145
    assert counts.get_object_count == 0
    assert counts.list_operation_count == 0
    assert counts.control_operation_count == 0
    assert 145 <= counts.total_s3_operations <= 290
    assert result.locator_attempts == 1
    # And the fake was asked for exactly what the counters report.
    assert len(s3.put_calls) == counts.put_object_count
    assert len(s3.head_calls) == counts.head_object_count
    assert s3.get_calls == []


# -- the acquisition deadline, driven directly --------------------------------
#
# The end-to-end behaviour is exercised in the pipeline suite. What is proven here
# is the admission arithmetic itself: which threshold applies in which phase, what
# happens exactly at a boundary, and what happens one tick short of it.


def test_an_unarmed_deadline_has_the_whole_budget_and_no_elapsed_time() -> None:
    deadline = AcquisitionDeadline(monotonic=FakeMonotonic())
    assert deadline.armed is False
    assert deadline.phase is DeadlinePhase.UNARMED
    assert deadline.elapsed == 0.0
    assert deadline.remaining == ACQUISITION_DEADLINE_SECONDS


def test_stages_before_arming_consume_nothing_however_long_they_take() -> None:
    monotonic = FakeMonotonic()
    deadline = AcquisitionDeadline(monotonic=monotonic)
    monotonic.advance(10_000.0)
    # An hour of pre-arm work, and the budget is untouched.
    assert deadline.remaining == ACQUISITION_DEADLINE_SECONDS
    deadline.arm()
    assert deadline.elapsed == 0.0
    assert deadline.remaining == ACQUISITION_DEADLINE_SECONDS


def test_a_deadline_may_be_armed_only_once() -> None:
    deadline = AcquisitionDeadline(monotonic=FakeMonotonic())
    deadline.arm()
    with pytest.raises(RuntimeError):
        deadline.arm()


def test_the_locator_phase_requires_an_armed_deadline() -> None:
    with pytest.raises(RuntimeError):
        AcquisitionDeadline(monotonic=FakeMonotonic()).begin_locator_phase()


def test_a_deadline_needs_a_callable_monotonic_source() -> None:
    with pytest.raises(TypeError):
        AcquisitionDeadline(monotonic=object())  # type: ignore[arg-type]


def test_a_deadline_configuration_that_cannot_hold_is_refused_at_construction() -> None:
    with pytest.raises(EmpiricalPlanError):
        AcquisitionDeadline(monotonic=FakeMonotonic(), deadline_seconds=10.0)


def test_the_deadline_reads_only_the_injected_monotonic_source() -> None:
    # Every answer is a function of the injected reading and nothing else: two
    # deadlines on two readings disagree, and neither consults a calendar.
    first, second = FakeMonotonic(), FakeMonotonic()
    early, late = AcquisitionDeadline(monotonic=first), AcquisitionDeadline(monotonic=second)
    early.arm()
    late.arm()
    first.advance(100.0)
    assert early.remaining == ACQUISITION_DEADLINE_SECONDS - 100.0
    assert late.remaining == ACQUISITION_DEADLINE_SECONDS


def test_a_provider_request_is_admitted_exactly_at_its_requirement() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic, locator_phase=False)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS - PROVIDER_REQUEST_ADMISSION_SECONDS)
    assert deadline.remaining == pytest.approx(PROVIDER_REQUEST_ADMISSION_SECONDS)
    deadline.admit_provider_request()
    assert deadline.exhausted is False


def test_a_provider_request_one_tick_short_of_its_requirement_is_refused() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic, locator_phase=False)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS - PROVIDER_REQUEST_ADMISSION_SECONDS + 0.001)
    with pytest.raises(DeadlineExhaustedError) as raised:
        deadline.admit_provider_request()
    assert raised.value.stage is DeadlineStage.PROVIDER_REQUEST
    assert deadline.exhausted is True


def test_the_provider_admission_requirement_does_not_include_the_pacing_interval() -> None:
    # Set the budget to exactly one pacing interval plus the admission requirement,
    # then spend the pacing. The request that follows must still be admitted -- which
    # it is only if pacing is counted once.
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic, locator_phase=False)
    monotonic.advance(
        ACQUISITION_DEADLINE_SECONDS
        - PROVIDER_REQUEST_ADMISSION_SECONDS
        - MIN_REQUEST_INTERVAL_SECONDS
    )
    deadline.admit_pacing(MIN_REQUEST_INTERVAL_SECONDS)
    monotonic.advance(MIN_REQUEST_INTERVAL_SECONDS)
    deadline.admit_provider_request()
    assert deadline.exhausted is False


def test_pacing_is_admitted_on_its_own_real_interval_and_never_truncated() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic, locator_phase=False)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS - 0.5)
    # Half a second left, a one-second interval owed. There is no shortened sleep to
    # return -- the only outcomes are admitted or refused.
    with pytest.raises(DeadlineExhaustedError) as raised:
        deadline.admit_pacing(1.0)
    assert raised.value.stage is DeadlineStage.PACING
    assert deadline.exhausted is True


def test_a_zero_or_negative_pacing_delay_is_admitted_without_consuming_budget() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic, locator_phase=False)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS - 0.5)
    deadline.admit_pacing(0.0)
    assert deadline.exhausted is False


def test_a_pacing_delay_that_is_not_a_number_is_refused() -> None:
    deadline = _armed(locator_phase=False)
    with pytest.raises(DeadlineExhaustedError) as raised:
        deadline.admit_pacing(float("nan"))
    assert raised.value.stage is DeadlineStage.PACING


def test_a_bronze_operation_must_leave_the_locator_reserve_behind() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic, locator_phase=False)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS - BRONZE_OPERATION_ADMISSION_SECONDS)
    deadline.admit_s3_operation()
    monotonic.advance(0.001)
    with pytest.raises(DeadlineExhaustedError) as raised:
        deadline.admit_s3_operation()
    assert raised.value.stage is DeadlineStage.BRONZE_OPERATION


def test_a_locator_operation_spends_the_reserve_and_holds_nothing_further_back() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS - LOCATOR_OPERATION_ADMISSION_SECONDS)
    # Below the Bronze threshold, and still admissible in the locator phase.
    assert deadline.remaining < BRONZE_OPERATION_ADMISSION_SECONDS
    deadline.admit_s3_operation()
    monotonic.advance(0.001)
    with pytest.raises(DeadlineExhaustedError) as raised:
        deadline.admit_s3_operation()
    assert raised.value.stage is DeadlineStage.LOCATOR_OPERATION


def test_an_unarmed_deadline_admits_no_bronze_operation_at_all() -> None:
    deadline = AcquisitionDeadline(monotonic=FakeMonotonic())
    with pytest.raises(DeadlineExhaustedError) as raised:
        deadline.admit_s3_operation()
    assert raised.value.stage is DeadlineStage.BRONZE_OPERATION


def test_locator_construction_is_permitted_exactly_at_its_threshold() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS - LOCATOR_ATTEMPT_ADMISSION_SECONDS)
    assert deadline.permits_locator_construction() is True
    monotonic.advance(0.001)
    assert deadline.permits_locator_construction() is False


def test_a_locator_publication_with_no_budget_left_reports_not_published() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS)
    publication, attempts = _publish([_stored()], deadline=deadline)
    assert publication.status is LocatorPublicationStatus.NOT_PUBLISHED
    assert publication.attempts == 0
    # Nothing was attempted, so the store was never asked.
    assert attempts == 0


def test_a_locator_retry_that_no_longer_fits_reports_state_unknown() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic)

    class _ThrottleThenExpire:
        attempts = 0

        def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
            self.attempts += 1
            # The first attempt leaves the condition unresolved and spends the rest
            # of the reserve, so the retry cannot be started.
            monotonic.advance(ACQUISITION_DEADLINE_SECONDS)
            raise _backend(ObjectStoreFailure.THROTTLED, ObjectStoreOperation.PUT)

    store = _ThrottleThenExpire()
    publication = publish_locator(store=store, key=KEY, payload=PAYLOAD, deadline=deadline)
    assert publication.status is LocatorPublicationStatus.STATE_UNKNOWN
    assert publication.attempts == 1
    assert store.attempts == 1


def test_locator_publication_requires_the_acquisition_deadline() -> None:
    with pytest.raises(TypeError):
        publish_locator(
            store=_ScriptedStore([_stored()]),
            key=KEY,
            payload=PAYLOAD,
            deadline=object(),  # type: ignore[arg-type]
        )


def test_a_counting_client_requires_the_acquisition_deadline() -> None:
    with pytest.raises(ObjectStoreBackendError):
        CountingS3Client(FakeS3Client(), deadline=object())  # type: ignore[arg-type]


def test_a_refused_s3_operation_is_never_counted_because_it_never_started() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic)
    counting = CountingS3Client(FakeS3Client(), deadline=deadline)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS)
    with pytest.raises(DeadlineExhaustedError):
        counting.put_object(Key="k", Body=b"x")
    assert counting.put_object_count == 0


def test_no_deadline_refusal_carries_a_time_value_or_an_identifier() -> None:
    monotonic = FakeMonotonic()
    deadline = _armed(monotonic, locator_phase=False)
    monotonic.advance(ACQUISITION_DEADLINE_SECONDS)
    with pytest.raises(DeadlineExhaustedError) as raised:
        deadline.admit_provider_request()
    rendered = f"{raised.value} {raised.value!r} {raised.value.args} {deadline!r}"
    assert "1800" not in rendered
    assert SYNTHETIC_BUCKET not in rendered
    assert str(ACQUISITION_DEADLINE_SECONDS) not in rendered
