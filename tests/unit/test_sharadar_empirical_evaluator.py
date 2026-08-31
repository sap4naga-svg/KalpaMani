"""P1-P9 ceilings, insufficiency, and the aggregate verdict that does not exist.

The most consequential tests here are negative ones. A ceiling that can be exceeded is
not a ceiling, insufficiency that decays into a softer positive is worse than no result
at all, and an aggregate verdict anywhere in this package would be a program answering
a question that belongs to a person.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path

import pytest

from fixtures.sharadar_empirical import ACTIONS_CSV, STOCKS_CSV, TICKERS_CSV
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.qualify.sharadar import evaluator as evaluator_module
from kalpamani.data.qualify.sharadar.evaluator import (
    SINGLE_EXECUTION_CEILINGS,
    STATUS_RANK,
    TEST_CEILINGS,
    Limb,
    LimbResult,
    LimbStatus,
    Measurement,
    MeasurementKind,
    MeasurementName,
    ProviderTest,
    Reason,
    SubjectEvidence,
    evaluate,
    excluded_subject_count,
)
from kalpamani.data.qualify.sharadar.evaluator import (
    TestResult as PerTestResult,
)
from kalpamani.data.qualify.sharadar.evaluator import (
    TestStatus as Status,
)
from kalpamani.data.qualify.sharadar.parser import PagePair, parse_payload

_BODIES = {
    SharadarDataset.TICKERS: TICKERS_CSV,
    SharadarDataset.STOCKS: STOCKS_CSV,
    SharadarDataset.ACTIONS: ACTIONS_CSV,
}


def _pair(
    dataset: SharadarDataset, *, first: bytes | None = None, second: bytes | None = None
) -> PagePair:
    body = first if first is not None else _BODIES[dataset]
    probe = second if second is not None else body.split(b"\n", 1)[0] + b"\n"
    return PagePair(
        dataset=dataset,
        first=parse_payload(body, dataset=dataset),
        second=parse_payload(probe, dataset=dataset),
    )


def _evidence(
    count: int = 8, overrides: Mapping[SharadarDataset, PagePair] | None = None
) -> tuple[SubjectEvidence, ...]:
    subjects = []
    for _ in range(count):
        pairs = {dataset: _pair(dataset) for dataset in SharadarDataset}
        pairs.update(overrides or {})
        subjects.append(SubjectEvidence(pairs=pairs))
    return tuple(subjects)


def _by_test(results: tuple[PerTestResult, ...]) -> dict[ProviderTest, PerTestResult]:
    return {result.test: result for result in results}


# -- the ceilings ------------------------------------------------------------


def test_the_compiled_ceilings_are_the_accepted_ones() -> None:
    assert TEST_CEILINGS == {
        ProviderTest.P1: Status.TESTED,
        ProviderTest.P2: Status.PARTIALLY_TESTED,
        ProviderTest.P3: Status.TESTED,
        ProviderTest.P4: Status.DOCUMENTATION_RESOLVED,
        ProviderTest.P5: Status.PARTIALLY_TESTED,
        ProviderTest.P6: Status.DEFERRED,
        ProviderTest.P7: Status.DEFERRED,
        ProviderTest.P8: Status.DEFERRED,
        ProviderTest.P9: Status.DOCUMENTATION_RESOLVED,
    }


def test_every_test_has_a_ceiling_and_a_single_execution_ceiling() -> None:
    assert set(TEST_CEILINGS) == set(ProviderTest)
    assert set(SINGLE_EXECUTION_CEILINGS) == set(ProviderTest)


def test_no_single_execution_ceiling_exceeds_its_architectural_ceiling() -> None:
    for test in ProviderTest:
        assert STATUS_RANK[SINGLE_EXECUTION_CEILINGS[test]] <= STATUS_RANK[TEST_CEILINGS[test]]


def test_the_status_rank_is_total_over_the_vocabulary() -> None:
    assert set(STATUS_RANK) == set(Status)


def test_no_evaluated_status_exceeds_either_ceiling() -> None:
    for result in evaluate(_evidence()):
        assert STATUS_RANK[result.status] <= STATUS_RANK[result.ceiling]
        assert STATUS_RANK[result.status] <= STATUS_RANK[result.single_execution_ceiling]


def test_a_result_above_its_ceiling_cannot_be_constructed() -> None:
    with pytest.raises(ValueError):
        PerTestResult(
            test=ProviderTest.P2,
            status=Status.TESTED,
            ceiling=TEST_CEILINGS[ProviderTest.P2],
            single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P2],
            limbs=(),
        )


def test_a_result_carrying_another_test_s_ceiling_cannot_be_constructed() -> None:
    with pytest.raises(ValueError):
        PerTestResult(
            test=ProviderTest.P2,
            status=Status.PARTIALLY_TESTED,
            ceiling=TEST_CEILINGS[ProviderTest.P1],
            single_execution_ceiling=SINGLE_EXECUTION_CEILINGS[ProviderTest.P2],
            limbs=(),
        )


def test_a_result_may_not_be_subclassed() -> None:
    with pytest.raises(TypeError):

        class _Raised(PerTestResult):
            pass


# -- per-test behaviour -------------------------------------------------------


def test_p1_is_capped_at_partially_tested_for_one_execution() -> None:
    result = _by_test(evaluate(_evidence()))[ProviderTest.P1]
    assert result.status is Status.PARTIALLY_TESTED
    assert result.ceiling is Status.TESTED
    assert result.single_execution_ceiling is Status.PARTIALLY_TESTED


def test_p1_information_time_stays_bounded_regardless_of_outcome() -> None:
    limbs = {limb.limb: limb for limb in _by_test(evaluate(_evidence()))[ProviderTest.P1].limbs}
    resolution = limbs[Limb.P1_INFORMATION_TIME_RESOLUTION]
    assert resolution.status is LimbStatus.BOUNDED
    assert resolution.reason is Reason.DATE_GRANULAR_SOURCE


def test_p1_cross_run_change_detection_is_explicitly_insufficient() -> None:
    limbs = {limb.limb: limb for limb in _by_test(evaluate(_evidence()))[ProviderTest.P1].limbs}
    cross_run = limbs[Limb.P1_CROSS_RUN_CHANGE_DETECTION]
    assert cross_run.status is LimbStatus.INSUFFICIENT
    assert cross_run.reason is Reason.CROSS_RUN_EVIDENCE_ABSENT


def test_p2_can_never_exceed_partially_tested() -> None:
    result = _by_test(evaluate(_evidence()))[ProviderTest.P2]
    assert result.ceiling is Status.PARTIALLY_TESTED
    assert result.status is Status.PARTIALLY_TESTED


def test_p2_population_survivorship_is_permanently_bounded() -> None:
    limbs = {limb.limb: limb for limb in _by_test(evaluate(_evidence()))[ProviderTest.P2].limbs}
    population = limbs[Limb.P2_POPULATION_SURVIVORSHIP]
    assert population.status is LimbStatus.BOUNDED
    assert population.reason is Reason.SAMPLED_NOT_POPULATION


def test_p3_reaches_tested_only_when_the_announcement_column_is_delivered() -> None:
    without = _by_test(evaluate(_evidence()))[ProviderTest.P3]
    assert without.status is Status.PARTIALLY_TESTED

    announced = (
        ACTIONS_CSV.replace(b"date,action", b"announcedate,date,action")
        .replace(b"\n2011", b"\n2011-06-01,2011")
        .replace(b"\n2012", b"\n2012-02-01,2012")
        .replace(b"\n2015", b"\n2015-06-01,2015")
    )
    announced_pair = _pair(SharadarDataset.ACTIONS, first=announced)
    with_column = _by_test(
        evaluate(_evidence(overrides={SharadarDataset.ACTIONS: announced_pair}))
    )[ProviderTest.P3]
    assert with_column.status is Status.TESTED


def test_p4_is_documentation_resolved_and_no_rows_can_lift_it() -> None:
    result = _by_test(evaluate(_evidence()))[ProviderTest.P4]
    assert result.status is Status.DOCUMENTATION_RESOLVED
    limbs = {limb.limb: limb for limb in result.limbs}
    assert limbs[Limb.P4_CLASSIFICATION_HISTORY].reason is Reason.SNAPSHOT_HAS_NO_TIME_AXIS


def test_p5_spinoff_limb_stays_inconclusive_while_semantics_are_undocumented() -> None:
    result = _by_test(evaluate(_evidence()))[ProviderTest.P5]
    limbs = {limb.limb: limb for limb in result.limbs}
    spinoff = limbs[Limb.P5_SPINOFF_RECONCILIATION]
    assert spinoff.status is LimbStatus.INCONCLUSIVE
    assert spinoff.reason is Reason.PROVIDER_SEMANTICS_UNDOCUMENTED
    assert result.status is Status.PARTIALLY_TESTED


def test_p6_p7_and_p8_are_deferred() -> None:
    results = _by_test(evaluate(_evidence()))
    for test in (ProviderTest.P6, ProviderTest.P7, ProviderTest.P8):
        assert results[test].status is Status.DEFERRED


def test_p9_price_origin_stays_provider_derived_and_public_pit_is_unreachable() -> None:
    result = _by_test(evaluate(_evidence()))[ProviderTest.P9]
    assert result.status is Status.DOCUMENTATION_RESOLVED
    limbs = {limb.limb: limb for limb in result.limbs}
    assert limbs[Limb.P9_BAR_CONSTRUCTION_ORIGIN].reason is Reason.PRICE_ORIGIN_PROVIDER_DERIVED


def test_public_pit_is_not_expressible_anywhere_in_the_evaluator() -> None:
    source = Path(evaluator_module.__file__).read_text(encoding="utf-8")
    assert "PUBLIC_PIT" not in source


# -- insufficiency never decays into a pass -----------------------------------


def test_no_evidence_at_all_yields_insufficiency_rather_than_a_weaker_pass() -> None:
    results = _by_test(evaluate(()))
    assert results[ProviderTest.P1].status is Status.INSUFFICIENT_EVIDENCE
    assert results[ProviderTest.P2].status is Status.INSUFFICIENT_EVIDENCE
    assert results[ProviderTest.P3].status is Status.INSUFFICIENT_EVIDENCE
    assert results[ProviderTest.P5].status is Status.INSUFFICIENT_EVIDENCE


def test_a_truncated_pair_is_excluded_before_measurement() -> None:
    truncated = _pair(SharadarDataset.STOCKS, second=STOCKS_CSV)
    evidence = _evidence(overrides={SharadarDataset.STOCKS: truncated})
    assert excluded_subject_count(evidence) == 8
    results = _by_test(evaluate(evidence))
    assert results[ProviderTest.P2].status is Status.INSUFFICIENT_EVIDENCE


def test_a_schema_that_changed_between_pages_is_excluded() -> None:
    unstable = _pair(SharadarDataset.STOCKS, second=b"ticker,date,close\n")
    evidence = _evidence(overrides={SharadarDataset.STOCKS: unstable})
    assert excluded_subject_count(evidence) == 8


def test_a_header_only_delivery_is_insufficient_and_not_a_pass() -> None:
    empty = _pair(SharadarDataset.STOCKS, first=b"ticker,date,close\n")
    results = _by_test(evaluate(_evidence(overrides={SharadarDataset.STOCKS: empty})))
    assert results[ProviderTest.P2].status is Status.INSUFFICIENT_EVIDENCE
    limbs = {limb.limb: limb for limb in results[ProviderTest.P2].limbs}
    assert limbs[Limb.P2_DELISTED_HISTORY_EXISTS].reason is Reason.NO_ROWS_DELIVERED


def test_an_absent_adjusted_close_makes_the_reconciliation_limbs_insufficient() -> None:
    unadjusted = _pair(
        SharadarDataset.STOCKS,
        first=b"ticker,date,close\nZZ-SYNTH-01,1998-01-05,10.25\n",
        second=b"ticker,date,close\n",
    )
    results = _by_test(evaluate(_evidence(overrides={SharadarDataset.STOCKS: unadjusted})))
    limbs = {limb.limb: limb for limb in results[ProviderTest.P5].limbs}
    assert limbs[Limb.P5_SPLIT_RECONCILIATION].status is LimbStatus.INSUFFICIENT
    assert limbs[Limb.P5_SPLIT_RECONCILIATION].reason is Reason.COLUMN_NOT_DELIVERED


# -- no aggregate verdict, anywhere -------------------------------------------


def test_evaluate_returns_exactly_nine_results_and_no_summary() -> None:
    results = evaluate(_evidence())
    assert len(results) == 9
    assert [result.test for result in results] == list(ProviderTest)


FORBIDDEN_WORDS = (
    "PROCEED",
    "HOLD",
    "REJECT",
    "QUALIFIED",
    "APPROVED",
    "READY",
    "RECOMMEND",
    "SELECT_PROVIDER",
    "OVERALL",
    "AGGREGATE",
    "VERDICT",
    "READINESS",
)


def test_no_forbidden_verdict_word_appears_in_any_vocabulary() -> None:
    vocabularies = (Status, LimbStatus, Reason, MeasurementName, MeasurementKind, Limb)
    values = {member.value for vocabulary in vocabularies for member in vocabulary}
    for word in FORBIDDEN_WORDS:
        assert not any(word in value for value in values)


def test_no_forbidden_verdict_word_appears_in_the_module_source() -> None:
    source = Path(evaluator_module.__file__).read_text(encoding="utf-8")
    executable = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    # Prose in docstrings names these words to explain their absence; what must not
    # exist is a *value* or an identifier spelling one.
    for word in ("PROCEED =", "VERDICT =", "READINESS =", "def verdict", "def recommend"):
        assert word not in executable


def test_no_result_type_carries_a_verdict_selection_or_readiness_field() -> None:
    for dataclass_type in (PerTestResult, LimbResult, Measurement):
        names = {field.name for field in fields(dataclass_type)}
        for forbidden in (
            "verdict",
            "recommendation",
            "provider_selection",
            "readiness",
            "overall",
        ):
            assert forbidden not in names


def test_the_module_exposes_no_aggregating_function() -> None:
    for name, value in vars(evaluator_module).items():
        if (
            inspect.isfunction(value)
            and not name.startswith("_")
            and value.__module__ == evaluator_module.__name__
        ):
            assert name in (
                "evaluate",
                "evaluate_combined",
                "excluded_cross_run_pair_count",
                "excluded_subject_count",
            )


# -- measurements are grammar-bound and name no security ----------------------


def test_every_measurement_is_grammar_bound_to_its_kind() -> None:
    for result in evaluate(_evidence()):
        for limb in result.limbs:
            for measurement in limb.measurements:
                assert type(measurement.name) is MeasurementName
                assert type(measurement.kind) is MeasurementKind


def test_a_count_that_is_not_digits_is_refused() -> None:
    with pytest.raises(ValueError):
        Measurement(
            name=MeasurementName.SUBJECTS_EVALUATED, kind=MeasurementKind.COUNT, value="many"
        )


def test_a_date_measurement_must_be_a_real_calendar_date() -> None:
    with pytest.raises(ValueError):
        Measurement(
            name=MeasurementName.EARLIEST_PRICE_DATE_OBSERVED,
            kind=MeasurementKind.DATE,
            value="2026-13-45",
        )


def test_the_measurement_name_vocabulary_is_a_closed_allowlist() -> None:
    # The control is that a measurement name must be a member of this closed
    # vocabulary, so a free-text label -- which could carry a security symbol --
    # has nowhere to arrive. The substring shape of a member name proves nothing:
    # SUBJECTS_WITH_TICKER_ROWS counts rows of the tickers *dataset*.
    for member in MeasurementName:
        assert member.value.isupper()
    with pytest.raises(ValueError):
        Measurement(
            name="SOME_FREE_TEXT_LABEL",  # type: ignore[arg-type]
            kind=MeasurementKind.COUNT,
            value="1",
        )


def test_no_evaluated_measurement_carries_a_subject() -> None:
    from fixtures.sharadar_empirical import SYNTHETIC_SUBJECTS

    for result in evaluate(_evidence()):
        for limb in result.limbs:
            for measurement in limb.measurements:
                for subject in SYNTHETIC_SUBJECTS:
                    assert subject not in measurement.value


def test_subject_evidence_carries_no_subject_field_and_no_row_in_its_repr() -> None:
    from fixtures.sharadar_empirical import SYNTHETIC_SUBJECTS

    evidence = _evidence(1)[0]
    assert {field.name for field in fields(SubjectEvidence)} == {"pairs"}
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in repr(evidence)


def test_evaluate_refuses_anything_that_is_not_subject_evidence() -> None:
    with pytest.raises(TypeError):
        evaluate([object()])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        evaluate((object(),))  # type: ignore[arg-type]
