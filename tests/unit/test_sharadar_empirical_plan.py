"""The bounded 48-request plan: the accepted numbers, checked rather than repeated.

Every ceiling in the accepted architecture is asserted here against the compiled
constant, and the two that are *forced* rather than merely configured -- zero provider
retries and the wall-clock bound -- are proven by driving the mechanism that forces
them rather than by reading the value back.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from fixtures.sharadar_empirical import RUN_INSTANT, SYNTHETIC_SUBJECTS, synthetic_inventory
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.ingest.sharadar.qualification import (
    MAX_PAGES_PER_REQUEST,
    MAX_REQUESTS,
    MAX_RETRY_BUDGET,
    QualificationPlanError,
    refuse_retry_budget,
)
from kalpamani.data.ingest.sharadar.qualification import (
    MAX_RUN_BYTES as COMPILED_MAX_RUN_BYTES,
)
from kalpamani.data.qualify.sharadar.plan import (
    ACQUISITION_DEADLINE_SECONDS,
    ACTIONS_PAGE_LIMIT,
    EMPIRICAL_DATASETS,
    EMPIRICAL_MAX_PAGES,
    EMPIRICAL_REQUEST_COUNT,
    EMPIRICAL_SCHEMA_VERSION,
    HISTORY_START,
    MAX_RESPONSE_BYTES,
    MAX_RUN_BYTES,
    MIN_REQUEST_INTERVAL_SECONDS,
    PROVIDER_MAX_ATTEMPTS,
    STOCKS_PAGE_LIMIT,
    TICKERS_PAGE_LIMIT,
    TIMEOUT_SECONDS,
    EmpiricalPlan,
    EmpiricalPlanError,
    PlanDefect,
    build_empirical_plan,
    compiled_request_phase_seconds,
    empirical_window,
    validate_deadline_constants,
)

EXECUTION = "synthetic-plan-a"


def _plan() -> EmpiricalPlan:
    return build_empirical_plan(
        inventory=synthetic_inventory(), execution_id=EXECUTION, instant=RUN_INSTANT
    )


def test_the_plan_generates_exactly_forty_eight_requests() -> None:
    plan = _plan()
    assert EMPIRICAL_REQUEST_COUNT == 48
    assert plan.plan.request_count == 48
    assert len(plan.plan.requests()) == 48


def test_forty_eight_is_eight_subjects_times_three_datasets_times_two_pages() -> None:
    assert len(SYNTHETIC_SUBJECTS) * len(EMPIRICAL_DATASETS) * EMPIRICAL_MAX_PAGES == 48


def test_the_request_count_is_at_or_below_the_compiled_ceiling() -> None:
    assert EMPIRICAL_REQUEST_COUNT <= MAX_REQUESTS


def test_the_three_datasets_are_the_stage_3a_ones_and_no_fourth() -> None:
    assert set(EMPIRICAL_DATASETS) == {
        SharadarDataset.TICKERS,
        SharadarDataset.STOCKS,
        SharadarDataset.ACTIONS,
    }


def test_every_dataset_is_requested_for_every_subject_over_two_pages() -> None:
    requests = _plan().plan.requests()
    by_pair: dict[tuple[str, str], list[int]] = {}
    for request in requests:
        by_pair.setdefault((request.ticker, request.dataset.value), []).append(request.page.skip)
    assert len(by_pair) == 24
    for skips in by_pair.values():
        assert len(skips) == EMPIRICAL_MAX_PAGES
        assert sorted(skips) == skips


def test_the_snapshot_dataset_carries_no_window_and_the_others_do() -> None:
    for request in _plan().plan.requests():
        if request.dataset is SharadarDataset.TICKERS:
            assert request.window is None
            assert request.requested_range == "SNAPSHOT"
        else:
            assert request.window is not None
            assert request.window.start == HISTORY_START


def test_the_window_runs_from_the_documented_depth_to_utc_t_minus_one() -> None:
    window = empirical_window(RUN_INSTANT)
    assert window.start == date(1998, 1, 1)
    assert window.end == (RUN_INSTANT - timedelta(days=1)).date()


def test_the_window_comes_from_the_injected_clock_and_moves_with_it() -> None:
    later = RUN_INSTANT + timedelta(days=10)
    assert empirical_window(later).end == (later - timedelta(days=1)).date()


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(EmpiricalPlanError) as raised:
        empirical_window(datetime(2026, 8, 30, 12, 0, 0))
    assert raised.value.defect is PlanDefect.CLOCK_MALFORMED


def test_a_clock_before_the_documented_depth_is_refused() -> None:
    with pytest.raises(EmpiricalPlanError) as raised:
        empirical_window(datetime(1997, 6, 1, tzinfo=UTC))
    assert raised.value.defect is PlanDefect.WINDOW_UNSATISFIABLE


def test_the_page_limits_are_the_accepted_per_dataset_values() -> None:
    assert (TICKERS_PAGE_LIMIT, STOCKS_PAGE_LIMIT, ACTIONS_PAGE_LIMIT) == (100, 10_000, 10_000)
    limits = {(request.dataset, request.page.limit) for request in _plan().plan.requests()}
    assert limits == {
        (SharadarDataset.TICKERS, 100),
        (SharadarDataset.STOCKS, 10_000),
        (SharadarDataset.ACTIONS, 10_000),
    }


def test_two_pages_is_at_or_below_the_compiled_page_ceiling() -> None:
    assert EMPIRICAL_MAX_PAGES == 2
    assert EMPIRICAL_MAX_PAGES <= MAX_PAGES_PER_REQUEST


def test_the_second_page_offset_is_one_page_limit_and_there_is_no_third() -> None:
    for request in _plan().plan.requests():
        assert request.page.skip in (0, request.page.limit)


def test_the_byte_ceilings_are_the_accepted_values_and_inside_the_compiled_ones() -> None:
    assert MAX_RESPONSE_BYTES == 4 * 1024 * 1024
    assert MAX_RUN_BYTES == 64 * 1024 * 1024
    assert MAX_RUN_BYTES <= COMPILED_MAX_RUN_BYTES
    limits = _plan().plan.limits
    assert limits.max_response_bytes == MAX_RESPONSE_BYTES
    assert limits.max_run_bytes == MAX_RUN_BYTES


def test_zero_provider_retries_is_forced_by_the_retry_budget_arithmetic() -> None:
    # One attempt is admitted at 48 requests...
    refuse_retry_budget(
        request_count=EMPIRICAL_REQUEST_COUNT, max_attempts=1, budget=MAX_RETRY_BUDGET
    )
    # ...and two is refused, because 48 x 1 exceeds the compiled budget of 32.
    assert EMPIRICAL_REQUEST_COUNT > MAX_RETRY_BUDGET
    with pytest.raises(QualificationPlanError):
        refuse_retry_budget(
            request_count=EMPIRICAL_REQUEST_COUNT, max_attempts=2, budget=MAX_RETRY_BUDGET
        )


def test_the_declared_attempt_policy_is_one() -> None:
    assert PROVIDER_MAX_ATTEMPTS == 1


def test_the_timeout_and_pacing_are_the_accepted_values() -> None:
    assert TIMEOUT_SECONDS == 30.0
    assert MIN_REQUEST_INTERVAL_SECONDS >= 1.0


def test_the_request_phase_figure_is_documentation_and_not_the_deadline() -> None:
    # It covers the requests and their pacing and nothing else -- no Bronze write,
    # no conditional resolution, no locator -- which is exactly why comparing it
    # against 1,800 proved nothing and is no longer done anywhere.
    phase = compiled_request_phase_seconds()
    assert phase == 48 * 30.0 + 47 * 1.0
    assert phase == 1_487.0
    assert phase < ACQUISITION_DEADLINE_SECONDS == 1_800.0


def test_the_request_phase_figure_counts_gaps_and_not_requests() -> None:
    # One request has no gap before it; the figure must not invent one.
    assert compiled_request_phase_seconds(request_count=1) == 30.0
    assert compiled_request_phase_seconds(request_count=0) == 0.0


def test_forty_eight_requests_are_not_guaranteed_to_fit_inside_the_deadline() -> None:
    # The honest consequence, as arithmetic. The requests and their pacing leave 313
    # seconds for 144 Bronze writes, up to 144 conditional resolutions and the
    # locator -- so the deadline is a safety bound, not a completion promise.
    from kalpamani.data.qualify.sharadar.plan import (
        BRONZE_OPERATIONS_PER_REQUEST,
        LOCATOR_TERMINAL_RESERVE_SECONDS,
        S3_OPERATION_CEILING_SECONDS,
    )

    downstream = (
        48 * BRONZE_OPERATIONS_PER_REQUEST * S3_OPERATION_CEILING_SECONDS
        + LOCATOR_TERMINAL_RESERVE_SECONDS
    )
    assert compiled_request_phase_seconds() + downstream > ACQUISITION_DEADLINE_SECONDS


def test_the_deadline_constants_satisfy_every_accepted_constraint() -> None:
    from kalpamani.data.qualify.sharadar.plan import (
        BRONZE_OPERATIONS_PER_REQUEST,
        LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS,
        LOCATOR_OPERATIONS_ALLOWED,
        LOCATOR_TERMINAL_RESERVE_SECONDS,
        S3_CONNECT_TIMEOUT_SECONDS,
        S3_OPERATION_CEILING_SECONDS,
        S3_READ_TIMEOUT_SECONDS,
    )

    t_s3 = S3_OPERATION_CEILING_SECONDS
    c = LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS
    ceiling = LOCATOR_TERMINAL_RESERVE_SECONDS
    assert t_s3 > 0
    assert c >= 0
    assert ceiling >= LOCATOR_OPERATIONS_ALLOWED * t_s3 + c
    assert ceiling < ACQUISITION_DEADLINE_SECONDS
    assert (
        TIMEOUT_SECONDS
        + MIN_REQUEST_INTERVAL_SECONDS
        + BRONZE_OPERATIONS_PER_REQUEST * t_s3
        + ceiling
    ) <= ACQUISITION_DEADLINE_SECONDS
    # The SDK bound is conservative: one attempt may spend both socket timeouts in
    # sequence, so the operation ceiling is at least their sum.
    assert t_s3 >= S3_CONNECT_TIMEOUT_SECONDS + S3_READ_TIMEOUT_SECONDS
    # And the real configuration passes its own validator.
    validate_deadline_constants()


def test_a_deadline_configuration_that_cannot_hold_is_refused_and_never_clamped() -> None:
    # Each call violates exactly one rule, and every one of them raises rather than
    # returning an adjusted value: there is no return value to adjust.
    for kwargs in (
        {"s3_operation_seconds": 0.0},
        {"s3_operation_seconds": 10.0},  # below connect + read
        {"construction_seconds": -1.0},
        {"locator_reserve_seconds": 10.0},  # below 4 * T_s3 + C
        {"locator_reserve_seconds": 1_800.0},  # not below D
        {"deadline_seconds": 100.0},  # one cycle plus the reserve does not fit
        {"deadline_seconds": float("nan")},
        {"request_timeout_seconds": float("inf")},
    ):
        with pytest.raises(EmpiricalPlanError) as raised:
            validate_deadline_constants(**kwargs)
        assert raised.value.defect is PlanDefect.DEADLINE_UNSATISFIABLE


def test_the_sdk_configuration_disables_retries_and_states_finite_timeouts() -> None:
    from kalpamani.data.qualify.sharadar.plan import (
        S3_CONNECT_TIMEOUT_SECONDS,
        S3_READ_TIMEOUT_SECONDS,
        s3_client_config_kwargs,
    )

    config = s3_client_config_kwargs()
    assert config["connect_timeout"] == S3_CONNECT_TIMEOUT_SECONDS
    assert config["read_timeout"] == S3_READ_TIMEOUT_SECONDS
    # ``max_attempts`` counts total attempts in standard mode, so one means no retry.
    assert config["retries"] == {"max_attempts": 1, "mode": "standard"}
    for value in (config["connect_timeout"], config["read_timeout"]):
        assert isinstance(value, float)
        assert 0 < value < float("inf")


def test_the_plan_carries_the_inventory_digest_and_the_deadline() -> None:
    plan = _plan()
    assert plan.inventory_digest == synthetic_inventory().digest
    assert plan.deadline_seconds == ACQUISITION_DEADLINE_SECONDS


def test_the_schema_version_is_this_package_s_own() -> None:
    assert _plan().plan.source_schema_version == EMPIRICAL_SCHEMA_VERSION
    assert EMPIRICAL_SCHEMA_VERSION == "sharadar-empirical-v1"


def test_a_non_inventory_is_refused_before_anything_is_built() -> None:
    with pytest.raises(EmpiricalPlanError) as raised:
        build_empirical_plan(
            inventory=object(),  # type: ignore[arg-type]
            execution_id=EXECUTION,
            instant=RUN_INSTANT,
        )
    assert raised.value.defect is PlanDefect.INVENTORY_MALFORMED


@pytest.mark.parametrize("execution_id", ["", "Has Capitals", "with space", "x" * 40])
def test_a_malformed_execution_identity_is_refused(execution_id: str) -> None:
    with pytest.raises(EmpiricalPlanError) as raised:
        build_empirical_plan(
            inventory=synthetic_inventory(), execution_id=execution_id, instant=RUN_INSTANT
        )
    assert raised.value.defect is PlanDefect.INVENTORY_MALFORMED


def test_a_plan_refusal_never_names_a_subject() -> None:
    with pytest.raises(EmpiricalPlanError) as raised:
        build_empirical_plan(
            inventory=synthetic_inventory(), execution_id="NOT VALID", instant=RUN_INSTANT
        )
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered


def test_the_request_order_is_canonical_and_independent_of_inventory_order() -> None:
    forward = _plan().plan.requests()
    shuffled = build_empirical_plan(
        inventory=synthetic_inventory(tuple(reversed(SYNTHETIC_SUBJECTS))),
        execution_id=EXECUTION,
        instant=RUN_INSTANT,
    ).plan.requests()
    assert [(r.dataset, r.ticker, r.page.skip) for r in forward] == [
        (r.dataset, r.ticker, r.page.skip) for r in shuffled
    ]


def test_every_request_derives_a_distinct_acquisition_identity() -> None:
    from kalpamani.data.ingest.sharadar.qualification import acquisition_id

    plan = _plan().plan
    identities = {
        acquisition_id(execution_id=plan.execution_id, request=request)
        for request in plan.requests()
    }
    assert len(identities) == EMPIRICAL_REQUEST_COUNT
