"""The quality plan is executed, not declared.

A versioned plan made the report closed. What it could not do is establish that
anything happened: ``checks_run`` was a tuple of strings a caller supplied, so a
caller who wrote out every check id satisfied the plan completely without a
single check having been invoked. That is the failure the plan itself was built
to close, one level up.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.errors import QualityGateError
from kalpamani.data.contracts.vocabulary import InformationSetProfile
from kalpamani.data.curate.build import build_gold_dataset
from kalpamani.data.curate.publication import publish_gold_dataset
from kalpamani.data.curate.resolution_run import resolve_run_inputs
from kalpamani.data.quality.plan import (
    PHASE3A_QUALITY_PLAN,
    CheckRequirement,
    PlannedCheck,
    QualityPlan,
)
from kalpamani.data.quality.report import CheckNotRun, report_from_findings
from kalpamani.data.quality.runner import (
    CHECK_REGISTRY,
    QualityContext,
    report_is_runner_produced,
    run_quality_plan,
)
from kalpamani.data.storage import LocalTableStore

pytestmark = pytest.mark.unit

PUBLIC = InformationSetProfile.PUBLIC_PIT


def _context(**overrides: object) -> QualityContext:
    dataset = phase3a.gold_dataset()
    base = phase3a.quality_context(dataset)
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def _run(**kwargs: object) -> object:
    return run_quality_plan(
        _context(),
        datasets_covered=phase3a.QUALITY_COVERAGE,
        partitions_covered=tuple(s.isoformat() for s in phase3a.SNAPSHOT_SESSIONS),
        policy_versions={"lag": phase3a.LAG_POLICY_VERSION},
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# checks_run comes from invocation
# ---------------------------------------------------------------------------


def test_the_complete_synthetic_plan_runs_end_to_end() -> None:
    """NEGATIVE CONTROL. Every REQUIRED check is invoked and the report is publishable."""
    outcome = _run()
    report = outcome.report  # type: ignore[attr-defined]
    required = {
        check.check_id
        for check in PHASE3A_QUALITY_PLAN.checks
        if check.requirement is CheckRequirement.REQUIRED
    }
    assert required <= set(report.checks_run)
    assert report.passed
    assert report_is_runner_produced(report)


def test_a_registered_check_is_observably_invoked() -> None:
    """Not "the id appeared in a list" -- the function was called."""
    calls: list[str] = []

    def counting(context: QualityContext) -> list[object]:
        calls.append(context.dataset.dataset_version)
        return []

    registry = dict(CHECK_REGISTRY)
    registry["ticker_history"] = dataclasses.replace(
        registry["ticker_history"],
        invoke=counting,  # type: ignore[arg-type]
    )
    outcome = _run(registry=registry)
    assert calls == [phase3a.DATASET_VERSION], (
        "The implementation ran exactly once, and the counter proves it rather than the "
        "report's own account of itself."
    )
    assert "ticker_history" in outcome.invoked  # type: ignore[attr-defined]


def test_checks_not_run_come_only_from_a_computed_applicability_decision() -> None:
    """A skip is the runner's finding about the build, never a caller's request."""
    outcome = _run()
    report = outcome.report  # type: ignore[attr-defined]
    skipped = {item.check_name: item.reason for item in report.checks_not_run}
    assert "4.5_adjusted_artifacts" in skipped
    assert "materialised no adjusted bar artifacts" in skipped["4.5_adjusted_artifacts"]
    assert "7_cross_provider_reconciliation" in skipped
    assert skipped["7_cross_provider_reconciliation"].strip()


def test_the_conditional_cross_provider_check_records_a_governed_reason() -> None:
    """It cannot run: reconciliation needs a second independently licensed source."""
    outcome = _run()
    report = outcome.report  # type: ignore[attr-defined]
    (entry,) = [
        item
        for item in report.checks_not_run
        if item.check_name == "7_cross_provider_reconciliation"
    ]
    assert "no implementation exists in this slice" in entry.reason
    planned = PHASE3A_QUALITY_PLAN.check("7_cross_provider_reconciliation")
    assert planned is not None
    assert planned.requirement is CheckRequirement.CONDITIONAL


def test_an_adjusted_artifact_makes_its_check_applicable() -> None:
    """The applicability decision follows the build, not a preference."""
    without = _run()
    assert "adjusted_artifact_hash" not in without.invoked  # type: ignore[attr-defined]

    artifact = phase3a.adjusted_artifact()
    outcome = run_quality_plan(
        _context(adjusted_artifacts=(artifact,)),
        datasets_covered=phase3a.QUALITY_COVERAGE,
        policy_versions={"lag": phase3a.LAG_POLICY_VERSION},
    )
    assert "adjusted_artifact_hash" in outcome.invoked
    assert "4.5_adjusted_artifacts" in outcome.report.checks_run


# ---------------------------------------------------------------------------
# a plan that cannot be run is a refusal
# ---------------------------------------------------------------------------


def test_a_required_check_with_no_registered_implementation_refuses() -> None:
    """Finding that out at publication beats finding out it never ran."""
    registry = {key: value for key, value in CHECK_REGISTRY.items() if key != "ticker_history"}
    with pytest.raises(QualityGateError, match="which this runner does not have"):
        _run(registry=registry)


def test_a_plan_marking_a_check_required_with_no_implementation_is_refused() -> None:
    """A required check nothing implements can only ever be declared."""
    with pytest.raises(QualityGateError, match="names no implementation"):
        QualityPlan(
            plan_version="test/unimplementable.1",
            required_policy_version_keys=(),
            checks=(
                PlannedCheck(
                    check_id="1_something",
                    requirement=CheckRequirement.REQUIRED,
                    applies_to=("price_bar",),
                    finding_ids=(),
                    implementations=(),
                ),
            ),
        )


def test_a_required_check_whose_implementation_does_not_apply_refuses() -> None:
    """Recording it as not-run would say, accurately, that the build was unchecked."""

    def never(context: QualityContext) -> str | None:
        return "declared inapplicable for this test"

    registry = dict(CHECK_REGISTRY)
    registry["ticker_history"] = dataclasses.replace(registry["ticker_history"], applicable=never)
    with pytest.raises(QualityGateError, match="REQUIRED, and the runner could not invoke"):
        _run(registry=registry)


# ---------------------------------------------------------------------------
# publication accepts only what was run
# ---------------------------------------------------------------------------


def _publish(store: LocalTableStore, dataset: object, report: object) -> object:
    return publish_gold_dataset(
        store,
        dataset,  # type: ignore[arg-type]
        quality_report=report,  # type: ignore[arg-type]
        quality_plan=PHASE3A_QUALITY_PLAN,
        code_commit_sha=phase3a.CODE_COMMIT_SHA,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
    )


def test_a_report_claiming_every_check_ran_without_the_runner_refuses(
    tmp_path: Path,
) -> None:
    """The exact evidence the runner exists to make impossible.

    Plan-perfect: every expected check accounted for, nothing duplicated, every
    table covered, every policy version present, no findings. It satisfies the
    plan completely, and not one check was invoked.
    """
    claimed = report_from_findings(
        (),
        plan_version=PHASE3A_QUALITY_PLAN.plan_version,
        policy_versions={
            "lag": phase3a.LAG_POLICY_VERSION,
            "market": "market-checks/a1.1",
            "survivorship": "survivorship/a1.1",
        },
        checks_run=tuple(
            check.check_id
            for check in PHASE3A_QUALITY_PLAN.checks
            if check.requirement is CheckRequirement.REQUIRED
        ),
        checks_not_run=tuple(
            CheckNotRun(check_name=check.check_id, reason="not in this slice")
            for check in PHASE3A_QUALITY_PLAN.checks
            if check.requirement is CheckRequirement.CONDITIONAL
        ),
        datasets_covered=phase3a.QUALITY_COVERAGE,
        produced_at=phase3a.BUILD_TIME,
    )
    assert (
        PHASE3A_QUALITY_PLAN.disagreements(claimed, published_tables=phase3a.QUALITY_COVERAGE) == []
    ), "It satisfies the plan completely, which is exactly the problem."
    assert not report_is_runner_produced(claimed)

    with pytest.raises(QualityGateError, match="was not produced by the quality runner"):
        _publish(LocalTableStore(tmp_path), phase3a.gold_dataset(), claimed)


def test_a_runner_produced_report_publishes(tmp_path: Path) -> None:
    """NEGATIVE CONTROL for the refusal above."""
    dataset = phase3a.gold_dataset()
    _publish(LocalTableStore(tmp_path), dataset, phase3a.quality_report(dataset))


def test_the_plan_is_checked_before_the_provenance(tmp_path: Path) -> None:
    """A wrong report fails for being wrong, not for where it came from."""
    thin = report_from_findings(
        (),
        plan_version=PHASE3A_QUALITY_PLAN.plan_version,
        policy_versions={"lag": "x", "market": "y", "survivorship": "z"},
        checks_run=("5_market_data",),
        datasets_covered=phase3a.QUALITY_COVERAGE,
        produced_at=phase3a.BUILD_TIME,
    )
    with pytest.raises(QualityGateError, match="the plan expects checks"):
        _publish(LocalTableStore(tmp_path), phase3a.gold_dataset(), thin)


# ---------------------------------------------------------------------------
# findings come from the implementations that ran
# ---------------------------------------------------------------------------


def test_a_finding_from_a_check_that_did_not_run_never_reaches_the_report() -> None:
    """The runner routes findings by id, so an unrun check contributes none.

    A hand-built report could put one there; the plan refuses that. What this
    establishes is the other direction: the runner cannot produce such a report
    even if an implementation misbehaves, because a check the runner did not
    invoke contributes nothing to its own entry.
    """
    outcome = _run()
    report = outcome.report  # type: ignore[attr-defined]
    ran = set(report.checks_run)
    for finding in report.findings:
        owner = PHASE3A_QUALITY_PLAN.owner_of(finding.check_name)
        assert owner is not None, finding.check_name
        assert owner.check_id in ran


def test_the_runner_finds_a_real_defect_nobody_told_it_about() -> None:
    """The whole point: evidence produced by looking, not by being informed."""
    resolved = resolve_run_inputs(
        phase3a.datasets_with_a_blocking_defect(),
        config=phase3a.resolution(),
        approvals=phase3a.approvals(),
    )
    dataset = build_gold_dataset(
        resolved,
        dataset_version=phase3a.DATASET_VERSION,
        build_time=phase3a.BUILD_TIME,
        coverage_start=phase3a.COVERAGE_START,
        coverage_end=phase3a.COVERAGE_END,
        universe_definition=phase3a.universe_definition(),
        universe_sessions=phase3a.SNAPSHOT_SESSIONS,
        evaluation_cutoffs=phase3a.evaluation_cutoffs(),
        approvals=phase3a.approvals(),
        artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
        ingestion_time=phase3a.INGESTION_TIME,
    )
    report = phase3a.quality_report(dataset)
    assert any(
        finding.check_name == "5.2_non_positive_price_or_negative_volume"
        for finding in report.blocking
    )
    assert not report.passed


def test_the_universe_rebuild_check_actually_rebuilds() -> None:
    """Taking the rebuilt hash from a caller would make drift detection a formality."""
    outcome = _run()
    assert "universe_rebuild" in outcome.invoked  # type: ignore[attr-defined]
    report = outcome.report  # type: ignore[attr-defined]
    assert not any(
        finding.check_name == "6.5_universe_rebuild_drift" for finding in report.findings
    ), "The reference build rebuilds identically, which is what the check is for."


def test_every_registered_implementation_is_named_by_the_plan() -> None:
    """An implementation nothing plans is an implementation nothing runs."""
    planned = {
        implementation_id
        for check in PHASE3A_QUALITY_PLAN.checks
        for implementation_id in check.implementations
    }
    assert set(CHECK_REGISTRY) == planned


def test_the_reference_report_carries_the_findings_the_checks_found() -> None:
    """Two genuine warnings: both securities are listed on the half day and have no bar."""
    report = phase3a.quality_report()
    warnings = {
        (finding.check_name, finding.security_id, finding.session_date)
        for finding in report.warnings
    }
    assert warnings == {
        ("5.4_missing_bar_in_a_listed_range", phase3a.SEC_CONTINUOUS, date(2019, 7, 3)),
        ("5.4_missing_bar_in_a_listed_range", phase3a.SEC_RENAMED, date(2019, 7, 3)),
    }
    assert report.passed, "A warning labels; it does not block."
