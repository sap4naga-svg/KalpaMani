"""What a qualification plan will and will not agree to describe.

**Every test here is offline and synthetic.** Constructing, validating and
rendering a plan reaches nothing: no client, no transport, no store, no
credential, no bucket. That is not incidental to the tests, it is the property
several of them exist to establish.

The plan is where a run's whole cost is decided, so the interesting cases are the
refusals: an out-of-phase dataset, a missing subject, an unbounded window, a
ceiling a caller tried to raise. A plan that admitted any of those would be a
plan whose bound was decided somewhere else, later, by something with less
review.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from typing import Any

import pytest

from fixtures.sharadar_runtime import (
    EXECUTION_ID,
    SUBJECT_A,
    SUBJECT_B,
    subjects,
    window,
)
from kalpamani.data.contracts.vocabulary import InformationSetProfile
from kalpamani.data.ingest.sharadar.datasets import (
    MAX_PAGE_LIMIT,
    DateWindow,
    Page,
    ResponseFormat,
    SharadarDataset,
)
from kalpamani.data.ingest.sharadar.qualification import (
    CANONICAL_DATASET_ORDER,
    MAX_PAGES_PER_REQUEST,
    MAX_REQUESTS,
    MAX_RETRY_BUDGET,
    MAX_RUN_BYTES,
    MAX_SUBJECTS,
    OUT_OF_PHASE_DATASETS,
    PERMITTED_PROFILE,
    PLAN_PARAMETER_ALLOWLIST,
    REFUSED_PROFILE,
    DatasetPlan,
    QualificationDefect,
    QualificationLimits,
    QualificationPlan,
    QualificationPlanError,
    QualificationSubject,
    acquisition_id,
    refuse_public_pit,
    refuse_retry_budget,
    refuse_unsupported_parameters,
)

pytestmark = pytest.mark.unit


def snapshot(**overrides: Any) -> QualificationPlan:
    fields: dict[str, Any] = {
        "subjects": subjects(SUBJECT_A),
        "datasets": (DatasetPlan(dataset=SharadarDataset.TICKERS),),
        "execution_id": EXECUTION_ID,
    }
    fields.update(overrides)
    return QualificationPlan(**fields)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_a_subject_is_frozen_and_exact() -> None:
    subject = QualificationSubject(SUBJECT_A)
    with pytest.raises(FrozenInstanceError):
        subject.ticker = SUBJECT_B  # type: ignore[misc]
    assert subject.ticker == SUBJECT_A
    assert type(subject.ticker) is str


def test_a_subject_refuses_a_hostile_string_subclass() -> None:
    """A ``str`` subclass can override ``__eq__`` after passing a grammar check."""

    class Hostile(str):
        def __eq__(self, other: object) -> bool:
            return True

        __hash__ = str.__hash__

    with pytest.raises(QualificationPlanError) as caught:
        QualificationSubject(Hostile(SUBJECT_A))
    assert caught.value.defect is QualificationDefect.SUBJECT_MALFORMED


@pytest.mark.parametrize(
    "cls", [QualificationSubject, DatasetPlan, QualificationLimits, QualificationPlan]
)
def test_every_plan_type_refuses_subclassing(cls: type) -> None:
    """A subclass could present an identity that was never validated."""
    with pytest.raises(QualificationPlanError):
        type("Sneaky", (cls,), {})


def test_the_plan_copies_its_subject_tuple() -> None:
    """A caller-held list could otherwise change the plan after validation."""
    supplied = subjects(SUBJECT_A, SUBJECT_B)
    plan = snapshot(subjects=supplied)
    assert plan.subjects == supplied
    assert type(plan.subjects) is tuple
    assert all(type(subject) is QualificationSubject for subject in plan.subjects)


@pytest.mark.parametrize("supplied", [[], list(subjects(SUBJECT_A)), None, "ZZQA"])
def test_a_non_tuple_subject_collection_is_refused(supplied: Any) -> None:
    with pytest.raises(QualificationPlanError):
        snapshot(subjects=supplied)


# ---------------------------------------------------------------------------
# Datasets: three, and the refusal of the fourth is the point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(OUT_OF_PHASE_DATASETS))
def test_an_out_of_phase_dataset_is_refused_by_name(name: str) -> None:
    """These are real vendor tables owned by a later phase, not typos."""
    with pytest.raises(QualificationPlanError) as caught:
        DatasetPlan(dataset=name)  # type: ignore[arg-type]
    assert caught.value.defect is QualificationDefect.DATASET_OUT_OF_PHASE


@pytest.mark.parametrize("name", ["", "TICKERS", "tickers ", "unknown-table", 7, None, ["tickers"]])
def test_an_unknown_dataset_is_refused(name: Any) -> None:
    with pytest.raises(QualificationPlanError) as caught:
        DatasetPlan(dataset=name)
    assert caught.value.defect is QualificationDefect.DATASET_UNKNOWN


def test_the_plan_admits_exactly_the_three_stage_3a_datasets() -> None:
    for dataset in SharadarDataset:
        window_needed = dataset is not SharadarDataset.TICKERS
        DatasetPlan(dataset=dataset, window=window() if window_needed else None)
    assert set(CANONICAL_DATASET_ORDER) == set(SharadarDataset)


def test_a_duplicate_dataset_is_refused() -> None:
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(
            datasets=(
                DatasetPlan(dataset=SharadarDataset.TICKERS),
                DatasetPlan(dataset=SharadarDataset.TICKERS),
            )
        )
    assert caught.value.defect is QualificationDefect.DATASET_DUPLICATED


def test_two_windows_for_one_dataset_are_refused_as_conflicting() -> None:
    """Not a duplicate: a plan that names one table over two ranges does not say
    what range it covers."""
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(
            datasets=(
                DatasetPlan(dataset=SharadarDataset.STOCKS, window=window()),
                DatasetPlan(
                    dataset=SharadarDataset.STOCKS,
                    window=DateWindow(start=date(2020, 1, 2), end=date(2020, 6, 30)),
                ),
            )
        )
    assert caught.value.defect is QualificationDefect.WINDOW_CONFLICTING


def test_a_plan_with_no_dataset_is_refused() -> None:
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(datasets=())
    assert caught.value.defect is QualificationDefect.DATASET_MISSING


# ---------------------------------------------------------------------------
# Subjects and windows
# ---------------------------------------------------------------------------


def test_a_plan_with_no_subject_is_refused() -> None:
    """A run whose subject nobody chose is a run nobody authorized."""
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(subjects=())
    assert caught.value.defect is QualificationDefect.SUBJECT_MISSING


def test_a_duplicate_subject_is_refused() -> None:
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(subjects=subjects(SUBJECT_A, SUBJECT_A))
    assert caught.value.defect is QualificationDefect.SUBJECT_DUPLICATED


@pytest.mark.parametrize("ticker", ["", "zzqa", "1ZZ", "ZZ QA", "Z" * 17, "ZZ$A"])
def test_a_malformed_subject_is_refused(ticker: str) -> None:
    with pytest.raises(QualificationPlanError) as caught:
        QualificationSubject(ticker)
    assert caught.value.defect is QualificationDefect.SUBJECT_MALFORMED


def test_a_windowed_dataset_requires_an_explicit_window() -> None:
    """The vendor defaults `from` to a year ago and `to` to yesterday, so an
    omitted window silently means something narrower than it looks."""
    for dataset in (SharadarDataset.STOCKS, SharadarDataset.ACTIONS):
        with pytest.raises(QualificationPlanError) as caught:
            DatasetPlan(dataset=dataset)
        assert caught.value.defect is QualificationDefect.WINDOW_REQUIRED


def test_the_snapshot_dataset_refuses_a_window() -> None:
    """`tickers` has no time axis, so a range on it is a parameter that means nothing."""
    with pytest.raises(QualificationPlanError) as caught:
        DatasetPlan(dataset=SharadarDataset.TICKERS, window=window())
    assert caught.value.defect is QualificationDefect.WINDOW_FORBIDDEN


@pytest.mark.parametrize("bad", ["2024-01-02/2024-03-28", 20240102, object()])
def test_a_non_datewindow_window_is_refused(bad: Any) -> None:
    with pytest.raises(QualificationPlanError) as caught:
        DatasetPlan(dataset=SharadarDataset.STOCKS, window=bad)
    assert caught.value.defect is QualificationDefect.WINDOW_MALFORMED


# ---------------------------------------------------------------------------
# Ceilings: downward only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,ceiling",
    [
        ("max_subjects", MAX_SUBJECTS),
        ("max_requests", MAX_REQUESTS),
        ("max_pages_per_request", MAX_PAGES_PER_REQUEST),
        ("max_run_bytes", MAX_RUN_BYTES),
        ("retry_budget", MAX_RETRY_BUDGET),
    ],
)
def test_no_limit_may_exceed_its_compiled_ceiling(field: str, ceiling: int) -> None:
    """The worst a misconfigured plan can do is ask for less."""
    with pytest.raises(QualificationPlanError) as caught:
        QualificationLimits(**{field: ceiling + 1})
    assert caught.value.defect is QualificationDefect.LIMIT_EXCEEDS_CEILING


@pytest.mark.parametrize(
    "field,ceiling",
    [
        ("max_subjects", MAX_SUBJECTS),
        ("max_requests", MAX_REQUESTS),
        ("max_pages_per_request", MAX_PAGES_PER_REQUEST),
        ("max_run_bytes", MAX_RUN_BYTES),
    ],
)
def test_every_limit_may_be_lowered(field: str, ceiling: int) -> None:
    limits = QualificationLimits(**{field: 1})
    assert getattr(limits, field) == 1
    assert getattr(QualificationLimits(), field) == ceiling


def test_a_retry_budget_of_zero_is_a_legitimate_choice() -> None:
    """Zero retries is a decision; zero subjects is a plan that cannot do anything."""
    assert QualificationLimits(retry_budget=0).retry_budget == 0
    with pytest.raises(QualificationPlanError) as caught:
        QualificationLimits(max_subjects=0)
    assert caught.value.defect is QualificationDefect.LIMIT_MALFORMED


@pytest.mark.parametrize("value", [True, 1.0, "8", None, -1])
def test_a_non_exact_int_limit_is_refused(value: Any) -> None:
    """`True` is an int in Python, and a max_subjects of True silently means one."""
    with pytest.raises(QualificationPlanError):
        QualificationLimits(max_subjects=value)


def test_too_many_subjects_is_refused_against_the_plan_limit() -> None:
    too_many = subjects(*(f"ZZ{index:02d}" for index in range(MAX_SUBJECTS + 1)))
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(subjects=too_many)
    assert caught.value.defect is QualificationDefect.LIMIT_EXCEEDS_CEILING


def test_too_many_pages_is_refused() -> None:
    with pytest.raises(QualificationPlanError) as caught:
        DatasetPlan(dataset=SharadarDataset.TICKERS, max_pages=MAX_PAGES_PER_REQUEST + 1)
    assert caught.value.defect is QualificationDefect.LIMIT_EXCEEDS_CEILING


def test_a_lowered_page_ceiling_binds_the_dataset_plan() -> None:
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(
            datasets=(DatasetPlan(dataset=SharadarDataset.TICKERS, max_pages=2),),
            limits=QualificationLimits(max_pages_per_request=1),
        )
    assert caught.value.defect is QualificationDefect.LIMIT_EXCEEDS_CEILING


def test_a_lowered_request_ceiling_binds_the_whole_plan() -> None:
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(
            subjects=subjects(SUBJECT_A, SUBJECT_B),
            limits=QualificationLimits(max_requests=1),
        )
    assert caught.value.defect is QualificationDefect.LIMIT_EXCEEDS_CEILING


def test_the_page_limit_cannot_exceed_the_vendors_documented_maximum() -> None:
    with pytest.raises(QualificationPlanError) as caught:
        DatasetPlan(dataset=SharadarDataset.TICKERS, page_limit=MAX_PAGE_LIMIT + 1)
    assert caught.value.defect is QualificationDefect.LIMIT_MALFORMED


def test_the_request_ceiling_is_the_product_of_the_other_three() -> None:
    """Stated as a constant rather than computed at the call site, so the number a
    reviewer checks is the number the code enforces."""
    assert MAX_REQUESTS == MAX_SUBJECTS * 3 * MAX_PAGES_PER_REQUEST


# ---------------------------------------------------------------------------
# Unsupported parameters
# ---------------------------------------------------------------------------


#: Names outside the allowlist. The last three matter most: a denylist would have
#: admitted every one of them.
@pytest.mark.parametrize(
    "name",
    [
        "years",
        "fields",
        "sort",
        "columns",
        "order",
        "lastupdated",
        "lastupdated.gte",
        "qopts",
        "api_key",
        "future_vendor_option",
        "anything_at_all",
        "",
    ],
)
def test_every_name_outside_the_allowlist_is_refused(name: str) -> None:
    with pytest.raises(QualificationPlanError) as caught:
        refuse_unsupported_parameters((name,))
    assert caught.value.defect is QualificationDefect.PARAMETER_UNSUPPORTED


def test_an_unknown_future_name_is_refused_which_a_denylist_would_have_admitted() -> None:
    """The whole reason this is an allowlist."""
    assert "future_vendor_option" not in PLAN_PARAMETER_ALLOWLIST
    with pytest.raises(QualificationPlanError):
        refuse_unsupported_parameters(["future_vendor_option"])


def test_the_credential_parameter_is_never_a_plan_parameter() -> None:
    """`api_key` is a request parameter injected into the client. A plan that
    could name it would be a plan that could carry a credential."""
    assert "api_key" not in PLAN_PARAMETER_ALLOWLIST
    with pytest.raises(QualificationPlanError):
        refuse_unsupported_parameters(("api_key",))


@pytest.mark.parametrize("name", ["YEARS", "Ticker", "TICKER", "From", "LIMIT", "ticker "])
def test_admission_is_by_exact_spelling(name: str) -> None:
    """Case folding here would decide two spellings mean one thing, which is a
    judgement a boundary should not make on a caller's behalf."""
    with pytest.raises(QualificationPlanError):
        refuse_unsupported_parameters((name,))


def test_the_six_plan_controlled_names_are_admitted() -> None:
    refuse_unsupported_parameters(("format", "ticker", "from", "to", "limit", "skip"))
    assert PLAN_PARAMETER_ALLOWLIST == {"format", "ticker", "from", "to", "limit", "skip"}


def test_a_string_subclass_parameter_is_refused() -> None:
    """A subclass can override `__eq__` and `__hash__`, so a membership test could
    be made to answer True for a value that is not in the allowlist."""

    class Sneaky(str):
        def __eq__(self, other: object) -> bool:
            return True

        __hash__ = str.__hash__

    with pytest.raises(QualificationPlanError) as caught:
        refuse_unsupported_parameters((Sneaky("years"),))
    assert caught.value.defect is QualificationDefect.PLAN_MALFORMED


@pytest.mark.parametrize("supplied", [None, "years", 7, {"years": 1}])
def test_a_malformed_parameter_collection_is_refused(supplied: Any) -> None:
    with pytest.raises(QualificationPlanError):
        refuse_unsupported_parameters(supplied)


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


def test_requests_are_generated_in_one_canonical_order() -> None:
    plan = QualificationPlan(
        subjects=subjects(SUBJECT_B, SUBJECT_A),
        datasets=(
            DatasetPlan(dataset=SharadarDataset.ACTIONS, window=window()),
            DatasetPlan(dataset=SharadarDataset.TICKERS),
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window()),
        ),
        execution_id=EXECUTION_ID,
    )
    shape = [(request.dataset.value, request.ticker) for request in plan.requests()]
    assert shape == [
        ("tickers", SUBJECT_A),
        ("tickers", SUBJECT_B),
        ("stocks", SUBJECT_A),
        ("stocks", SUBJECT_B),
        ("actions", SUBJECT_A),
        ("actions", SUBJECT_B),
    ]


def test_input_order_does_not_change_the_generated_order() -> None:
    """Two plans holding the same content emit byte-identical sequences, which is
    what makes a resumed run comparable to the run it resumes."""
    forward = QualificationPlan(
        subjects=subjects(SUBJECT_A, SUBJECT_B),
        datasets=(
            DatasetPlan(dataset=SharadarDataset.TICKERS),
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window()),
        ),
        execution_id=EXECUTION_ID,
    )
    reversed_plan = QualificationPlan(
        subjects=subjects(SUBJECT_B, SUBJECT_A),
        datasets=(
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window()),
            DatasetPlan(dataset=SharadarDataset.TICKERS),
        ),
        execution_id=EXECUTION_ID,
    )
    assert forward.requests() == reversed_plan.requests()
    # And the derived identities, which is the property that actually matters:
    # two plans holding the same content must reconcile with the same durable
    # evidence.
    assert [acquisition_id(execution_id=EXECUTION_ID, request=r) for r in forward.requests()] == [
        acquisition_id(execution_id=EXECUTION_ID, request=r) for r in reversed_plan.requests()
    ]


def test_pages_walk_in_ascending_offset_order() -> None:
    plan = snapshot(datasets=(DatasetPlan(dataset=SharadarDataset.TICKERS, max_pages=3),))
    skips = [request.page.skip for request in plan.requests()]
    assert skips == [0, 500, 1000]


def test_a_dataset_plans_pages_are_deterministic() -> None:
    plan = DatasetPlan(dataset=SharadarDataset.TICKERS, page_limit=10, max_pages=3)
    assert plan.pages() == (
        Page(limit=10, skip=0),
        Page(limit=10, skip=10),
        Page(limit=10, skip=20),
    )


def test_the_request_count_matches_what_requests_yields() -> None:
    plan = QualificationPlan(
        subjects=subjects(SUBJECT_A, SUBJECT_B),
        datasets=(
            DatasetPlan(dataset=SharadarDataset.TICKERS, max_pages=2),
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window(), max_pages=3),
        ),
        execution_id=EXECUTION_ID,
    )
    assert plan.request_count == len(plan.requests()) == 10


# ---------------------------------------------------------------------------
# Point-in-time consequences, bound into the type
# ---------------------------------------------------------------------------


def test_the_only_permitted_profile_is_provider_realistic_pit() -> None:
    assert PERMITTED_PROFILE is InformationSetProfile.PROVIDER_REALISTIC_PIT
    assert refuse_public_pit(PERMITTED_PROFILE) is PERMITTED_PROFILE


def test_public_pit_is_refused() -> None:
    """Q7 is publicly unresolved; an unresolved origin has one safe classification."""
    assert REFUSED_PROFILE is InformationSetProfile.PUBLIC_PIT
    with pytest.raises(QualificationPlanError) as caught:
        refuse_public_pit(InformationSetProfile.PUBLIC_PIT)
    assert caught.value.defect is QualificationDefect.PROFILE_REFUSED


@pytest.mark.parametrize(
    "profile",
    [
        InformationSetProfile.PUBLIC_PIT,
        InformationSetProfile.FORWARD_SYSTEM,
        "PUBLIC_PIT",
        "PROVIDER_REALISTIC_PIT",
        None,
        7,
    ],
)
def test_only_the_exact_permitted_profile_member_is_admitted(profile: Any) -> None:
    """A bare string is refused too: `closed_member` normalises, and anything that
    does not normalise to the one permitted member is not it."""
    if profile == "PROVIDER_REALISTIC_PIT":
        assert refuse_public_pit(profile) is PERMITTED_PROFILE
        return
    with pytest.raises(QualificationPlanError):
        refuse_public_pit(profile)


def test_a_plan_cannot_be_built_with_public_pit() -> None:
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(profile=InformationSetProfile.PUBLIC_PIT)
    assert caught.value.defect is QualificationDefect.PROFILE_REFUSED


def test_a_plans_profile_defaults_to_the_permitted_one() -> None:
    assert snapshot().profile is PERMITTED_PROFILE


# ---------------------------------------------------------------------------
# Retry budget
# ---------------------------------------------------------------------------


def test_a_retry_budget_bounds_the_worst_case_across_the_run() -> None:
    """Three attempts per request means two retries each; ten requests is twenty."""
    refuse_retry_budget(request_count=10, max_attempts=3, budget=20)
    with pytest.raises(QualificationPlanError) as caught:
        refuse_retry_budget(request_count=10, max_attempts=3, budget=19)
    assert caught.value.defect is QualificationDefect.RETRY_BUDGET_EXCEEDED


def test_a_single_attempt_policy_needs_no_budget() -> None:
    refuse_retry_budget(request_count=96, max_attempts=1, budget=0)


@pytest.mark.parametrize("attempts", [0, 6, True, 1.0, "3"])
def test_a_malformed_attempt_count_is_refused(attempts: Any) -> None:
    with pytest.raises(QualificationPlanError) as caught:
        refuse_retry_budget(request_count=1, max_attempts=attempts, budget=32)
    assert caught.value.defect is QualificationDefect.LIMIT_MALFORMED


# ---------------------------------------------------------------------------
# Run identity, and the absence of defaults that matter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("identity", ["", "Has-Upper", "has space", "x" * 33, 7, None])
def test_a_malformed_execution_identity_is_refused(identity: Any) -> None:
    with pytest.raises(QualificationPlanError) as caught:
        snapshot(execution_id=identity)
    assert caught.value.defect is QualificationDefect.IDENTITY_MALFORMED


def test_the_execution_identity_has_no_default() -> None:
    """A reusable default made two attempts share an acquisition identity.

    A run nobody named is a run whose evidence cannot be told apart from the last
    one's, so the field is required rather than defaulted.
    """
    import dataclasses

    fields = {f.name: f for f in dataclasses.fields(QualificationPlan)}
    assert fields["execution_id"].default is dataclasses.MISSING
    assert fields["execution_id"].default_factory is dataclasses.MISSING
    with pytest.raises(TypeError):
        QualificationPlan(  # type: ignore[call-arg]
            subjects=subjects(SUBJECT_A),
            datasets=(DatasetPlan(dataset=SharadarDataset.TICKERS),),
        )


def test_the_plan_carries_no_caller_controlled_backfill_flag() -> None:
    """A raw boolean would have let a caller label qualification evidence as a
    production backfill, turning a metadata field into an authorization claim."""
    import dataclasses

    assert "is_backfill" not in {f.name for f in dataclasses.fields(QualificationPlan)}
    with pytest.raises(TypeError):
        snapshot(is_backfill=True)


def test_no_real_ticker_is_compiled_into_the_plan_module() -> None:
    """A default symbol would mean a run nobody chose the subject of."""
    import inspect

    from kalpamani.data.ingest.sharadar import qualification

    source = inspect.getsource(qualification)
    for real in ("AAPL", "MSFT", "SPY", "TSLA", "GOOGL", "AMZN", "NVDA", "IBM"):
        assert real not in source


def test_the_response_format_is_stated_not_guessed() -> None:
    assert snapshot().response_format is ResponseFormat.CSV
    assert snapshot(response_format=ResponseFormat.JSON).response_format is ResponseFormat.JSON
    with pytest.raises(QualificationPlanError):
        snapshot(response_format="xml")


# ---------------------------------------------------------------------------
# Dormancy
# ---------------------------------------------------------------------------


def test_building_and_rendering_a_plan_performs_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plan is a description. Constructing one must reach nothing at all."""
    import socket

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the plan model must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    plan = QualificationPlan(
        subjects=subjects(SUBJECT_A, SUBJECT_B),
        datasets=(
            DatasetPlan(dataset=SharadarDataset.TICKERS),
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window()),
        ),
        execution_id=EXECUTION_ID,
    )
    assert len(plan.requests()) == 4
    assert repr(plan)


def test_a_plan_error_carries_only_a_closed_defect() -> None:
    """No ticker, window, URL or payload has a parameter to arrive through."""
    error = QualificationPlanError(QualificationDefect.SUBJECT_MISSING)
    assert str(error) == "sharadar qualification plan refused: SUBJECT_MISSING"
    assert error.__cause__ is None
    assert set(QualificationPlanError.__slots__) == {"defect"}


def test_a_plan_error_normalises_a_hostile_defect() -> None:
    """Classification runs inside error handling; it must not fail there."""
    assert QualificationPlanError("not-a-defect").defect is QualificationDefect.PLAN_MALFORMED  # type: ignore[arg-type]
