"""The quality plan: what was supposed to be checked, declared before it ran.

A report says what the checks found. On its own that is not a gate, because
nothing in it says what *should* have run. A report listing one harmless check
and no findings looks exactly like a report from a complete pass -- both are
"checks ran, nothing blocking" -- and the difference between them is the whole
difference between evidence and the appearance of evidence.

The plan closes that. It is versioned, it names every check the build is
expected to account for, and validation is a **closed** comparison:

``checks_run`` and ``checks_not_run`` together must be **exactly** the expected
set -- no extras, no omissions, no id in both, no id twice. A check that could
not run is declared and justified, and a check the plan marks ``REQUIRED``
cannot be declared away at all: NOT_RUN is permitted only where the plan says
this slice genuinely cannot run it.

Findings are held to the same closure. Every finding must belong to a check that
**ran** -- a finding from a check the report says did not run means one of the
two statements is false -- and must fall inside that check's declared scope, so a
check cannot quietly report on datasets it never covered.

Coverage is checked against the publication, not against the report's own claim:
every table the build published must appear in ``datasets_covered``. And every
policy version the plan depends on must be recorded, because a threshold-driven
check whose thresholds are unnamed is not reproducible.

The plan is looked up **by version on read**, so a publication naming a plan this
code does not have refuses rather than being validated against whatever plan
happens to be current.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final

from kalpamani.data.contracts.errors import QualityGateError

if TYPE_CHECKING:  # pragma: no cover - only the type checker needs this
    from kalpamani.data.quality.report import QualityReport


class CheckRequirement(Enum):
    """Whether a check may be declared not-run, and on what terms."""

    #: Must run. NOT_RUN is a refusal, not a declaration.
    REQUIRED = "REQUIRED"
    #: May be declared not-run **with a reason**, because this slice cannot run it.
    CONDITIONAL = "CONDITIONAL"


#: Every source dataset a Phase-3A check may report against. Closed on purpose:
#: a finding against a dataset nothing published is a finding about nothing.
SOURCE_SCOPE: Final[tuple[str, ...]] = (
    "corporate_action",
    "listing",
    "market_session",
    "price_bar",
    "security_attribute",
    "ticker_history",
)
DERIVED_SCOPE: Final[tuple[str, ...]] = (
    "adjusted_bar_artifact",
    "universe_membership",
    "universe_snapshot_header",
)
#: The pseudo-dataset a whole-run finding names. A profile violation is not a
#: property of one table.
RUN_SCOPE: Final[tuple[str, ...]] = ("run",)


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedCheck:
    """One check the plan expects a build to account for."""

    check_id: str
    requirement: CheckRequirement
    #: Datasets this check is declared to cover. A finding outside them is refused.
    applies_to: tuple[str, ...]
    #: The exact finding ids this check may emit. A closed vocabulary, so an
    #: unrecognised finding cannot be attributed to a check that never emits it.
    finding_ids: tuple[str, ...]
    #: The runner implementations that produce this check's findings. A check
    #: counts as run when every one of them has been invoked, which is what makes
    #: ``checks_run`` a record of work rather than a list somebody wrote.
    #: Empty means this slice has no implementation -- permitted only where the
    #: check is CONDITIONAL, and enforced below.
    implementations: tuple[str, ...] = ()

    @property
    def may_be_skipped(self) -> bool:
        """Whether NOT_RUN is a permitted outcome for this check."""
        return self.requirement is CheckRequirement.CONDITIONAL


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityPlan:
    """A versioned statement of what a build's quality evidence must contain."""

    plan_version: str
    checks: tuple[PlannedCheck, ...]
    required_policy_version_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        ids = [check.check_id for check in self.checks]
        if len(set(ids)) != len(ids):
            raise QualityGateError(
                f"Quality plan {self.plan_version} names a check twice. A plan that cannot say "
                "how many checks it expects cannot be compared against a report."
            )
        if not ids:
            raise QualityGateError(
                f"Quality plan {self.plan_version} expects no checks. A plan that expects "
                "nothing is satisfied by nothing."
            )
        unimplemented = sorted(
            check.check_id
            for check in self.checks
            if not check.implementations and check.requirement is CheckRequirement.REQUIRED
        )
        if unimplemented:
            raise QualityGateError(
                f"Quality plan {self.plan_version} marks {unimplemented} REQUIRED and names no "
                "implementation for them. A required check nothing implements can only ever be "
                "declared, and a declared check is the thing this plan exists to stop."
            )

    @property
    def expected_ids(self) -> frozenset[str]:
        """Every check id a report must account for, run or not run."""
        return frozenset(check.check_id for check in self.checks)

    def check(self, check_id: str) -> PlannedCheck | None:
        """The planned check with this id, or ``None`` if the plan has none."""
        for check in self.checks:
            if check.check_id == check_id:
                return check
        return None

    def owner_of(self, finding_id: str) -> PlannedCheck | None:
        """The check that may emit ``finding_id``, or ``None`` if no check may."""
        for check in self.checks:
            if finding_id in check.finding_ids:
                return check
        return None

    def validate(self, report: QualityReport, *, published_tables: Sequence[str]) -> None:
        """Refuse a report that does not close against this plan.

        Raises:
            QualityGateError: listing every problem at once. A caller fixing one
                omission should not have to rediscover the next three one
                publication at a time.
        """
        problems = self.disagreements(report, published_tables=published_tables)
        if problems:
            raise QualityGateError(
                f"The quality report does not satisfy plan {self.plan_version}:\n  - "
                + "\n  - ".join(problems)
                + "\nA report that does not close against a plan is not a gate: one harmless "
                "check finding nothing is indistinguishable from a complete pass."
            )

    def disagreements(
        self,
        report: QualityReport,
        *,
        published_tables: Sequence[str],
    ) -> list[str]:
        """Every way ``report`` fails to satisfy this plan."""
        problems: list[str] = []

        if report.plan_version != self.plan_version:
            problems.append(
                f"the report declares plan {report.plan_version!r}; this is plan "
                f"{self.plan_version!r}"
            )

        run = list(report.checks_run)
        not_run = [item.check_name for item in report.checks_not_run]
        problems.extend(_duplicates(run, "checks_run"))
        problems.extend(_duplicates(not_run, "checks_not_run"))

        both = sorted(set(run) & set(not_run))
        if both:
            problems.append(
                f"checks {both} are recorded as both run and not run; a check did one or the other"
            )

        accounted = set(run) | set(not_run)
        unexpected = sorted(accounted - self.expected_ids)
        if unexpected:
            problems.append(
                f"checks {unexpected} are not in the plan; an unplanned check cannot be "
                "compared against anything"
            )
        unaccounted = sorted(self.expected_ids - accounted)
        if unaccounted:
            problems.append(
                f"the plan expects checks {unaccounted}, which the report neither ran nor "
                "declared; silence is not a result"
            )

        for item in report.checks_not_run:
            planned = self.check(item.check_name)
            if planned is None:
                continue
            if not planned.may_be_skipped:
                problems.append(
                    f"check {item.check_name!r} is REQUIRED and was declared not-run "
                    f"({item.reason!r}); a required check cannot be declared away"
                )
            elif not item.reason.strip():
                problems.append(
                    f"check {item.check_name!r} was declared not-run with no reason; a blank "
                    "reason records that we did not check, not why we could not"
                )

        ran = set(run)
        for finding in report.findings:
            owner = self.owner_of(finding.check_name)
            if owner is None:
                problems.append(
                    f"finding {finding.check_name!r} belongs to no planned check; a finding no "
                    "check emits came from somewhere the plan does not describe"
                )
                continue
            if owner.check_id not in ran:
                problems.append(
                    f"finding {finding.check_name!r} belongs to check {owner.check_id!r}, "
                    "which the report says did not run"
                )
            if finding.dataset not in owner.applies_to:
                problems.append(
                    f"finding {finding.check_name!r} reports against dataset "
                    f"{finding.dataset!r}, outside check {owner.check_id!r} declared scope "
                    f"{list(owner.applies_to)}"
                )

        covered = set(report.datasets_covered)
        uncovered = sorted(set(published_tables) - covered)
        if uncovered:
            problems.append(
                f"published tables {uncovered} are not in datasets_covered; a table nothing "
                "checked was published unchecked"
            )

        missing_policy = sorted(
            set(self.required_policy_version_keys) - set(report.policy_versions)
        )
        if missing_policy:
            problems.append(
                f"policy versions {missing_policy} are required by the plan and absent from "
                "the report; a threshold-driven check whose thresholds are unnamed is not "
                "reproducible"
            )
        return problems


def _duplicates(values: Sequence[str], field_name: str) -> list[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    if not repeated:
        return []
    return [f"{field_name} lists {sorted(repeated)} more than once"]


PHASE3A_QUALITY_PLAN: Final = QualityPlan(
    plan_version="phase3a.quality-plan.1",
    required_policy_version_keys=("lag", "market", "survivorship"),
    checks=(
        PlannedCheck(
            check_id="3.1_ingestion_identity",
            implementations=("price_bar_structure",),
            requirement=CheckRequirement.REQUIRED,
            applies_to=SOURCE_SCOPE,
            finding_ids=("3.1_duplicate_price_bar_key",),
        ),
        PlannedCheck(
            check_id="4.0_envelope_conformance",
            implementations=("envelope_conformance", "stored_envelope_shape"),
            requirement=CheckRequirement.REQUIRED,
            applies_to=SOURCE_SCOPE + DERIVED_SCOPE,
            finding_ids=(
                "4.0.0_origin_outside_the_closed_vocabulary",
                "4.0A.10_derivation_disagrees_with_origin",
                "4.0A.11_class_without_a_resolved_fact_anchor",
                "4.0A.1_public_fact_without_resolvable_public_time",
                "4.0A.2_proprietary_fact_carrying_public_timing",
                "4.0A.4_system_observed_carrying_vendor_timing",
                "4.0A.5_missing_system_first_seen_time",
                "4.0A.6_exact_derivation_without_exact_value",
                "4.0A.7_approximation_written_into_exact_field",
                "4.0A.8_bound_precedes_the_exact_time_it_bounds",
                "4.0A.9_unapproved_provider_bound",
                "4.0A.9_unapproved_public_bound",
                "4.0B.1_derived_artifact_carrying_source_timing",
                "4.0B.2_incomplete_lineage",
                "4.0B.3_missing_derived_envelope_fields",
                "4.0B.4_derived_artifact_declares_a_source_temporal_class",
                "4.0B.5_output_validity_without_its_field",
                "4.0_mixed_source_and_derived_envelope",
            ),
        ),
        PlannedCheck(
            check_id="4.1_temporal_invariants",
            # Two implementations: the row-by-row temporal checks, and the bar
            # checks, which decide 4.1.12 because it is about a bar's
            # relationship to the calendar.
            implementations=("temporal_invariants", "price_bar_structure"),
            requirement=CheckRequirement.REQUIRED,
            applies_to=SOURCE_SCOPE + DERIVED_SCOPE,
            finding_ids=(
                "4.1.12_bar_outside_any_known_session",
                "4.1.12_session_date_derived_by_utc_truncation",
                "4.1.1_held_before_public",
                "4.1.2_held_before_provider_supplied",
                "4.1.3_row_written_before_first_seen",
                "4.1.4_provider_ahead_of_public_for_the_same_fact",
                "4.1.9_future_dated_availability",
            ),
        ),
        PlannedCheck(
            check_id="4.3_profile_service",
            implementations=("profile_service", "run_identity"),
            requirement=CheckRequirement.REQUIRED,
            applies_to=SOURCE_SCOPE + DERIVED_SCOPE + RUN_SCOPE,
            finding_ids=(
                "4.3.10_bound_applied_to_a_system_observed_row",
                "4.3.11_downgrade_not_carried_through",
                "4.3.12_dataset_absent_from_the_resolution_map",
                "4.3.13_resolution_map_not_in_run_id",
                "4.3.13_resolution_policy_version_not_in_run_id",
                "4.3.1_mixed_profiles_in_one_result",
                "4.3.2_unresolved_provider_availability",
                "4.3.3_public_timing_substituted_for_absent_provider_timing",
                "4.3.5_ineligible_row_served",
                "4.3.9_backfill_admitted_too_early",
            ),
        ),
        PlannedCheck(
            check_id="4.5_adjusted_artifacts",
            implementations=("adjusted_artifact_hash",),
            # Conditional because a build that materialised no adjusted artifact
            # has no cache to reproduce. The runner computes that from the build,
            # so it is not a skip a caller can ask for.
            requirement=CheckRequirement.CONDITIONAL,
            applies_to=("adjusted_bar_artifact",),
            finding_ids=("4.5.1_adjusted_cache_does_not_reproduce",),
        ),
        PlannedCheck(
            check_id="5_market_data",
            implementations=("price_bar_structure",),
            requirement=CheckRequirement.REQUIRED,
            applies_to=("price_bar",),
            finding_ids=(
                "5.1_impossible_ohlc",
                "5.2_non_positive_price_or_negative_volume",
                "5.4_missing_bar_in_a_listed_range",
                "5.5_split_discontinuity",
            ),
        ),
        PlannedCheck(
            check_id="6_identity_and_universe",
            implementations=("ticker_history", "universe_snapshots", "universe_rebuild"),
            requirement=CheckRequirement.REQUIRED,
            applies_to=SOURCE_SCOPE + DERIVED_SCOPE,
            finding_ids=(
                "6.1_ticker_history_overlap",
                "6.3_survivorship_leakage",
                "6.4_delisted_absence",
                "6.5_universe_rebuild_drift",
                "6.6_eligibility_from_inadmissible_data",
                "6.8_profile_free_or_mismatched_universe",
            ),
        ),
        PlannedCheck(
            check_id="7_cross_provider_reconciliation",
            # The one check this slice genuinely cannot run: reconciliation needs
            # two independently licensed sources, and no provider is selected.
            requirement=CheckRequirement.CONDITIONAL,
            applies_to=SOURCE_SCOPE,
            finding_ids=(),
        ),
    ),
)

#: Plans this code can validate against, by version. A publication naming a plan
#: that is not here refuses on read rather than being validated against whatever
#: plan happens to be current.
QUALITY_PLANS: Final[Mapping[str, QualityPlan]] = {
    PHASE3A_QUALITY_PLAN.plan_version: PHASE3A_QUALITY_PLAN,
}


def plan_for(plan_version: str) -> QualityPlan:
    """The plan a publication names.

    Raises:
        QualityGateError: if this code does not have that plan. Validating
            against a different plan than the build declared would compare the
            evidence to the wrong expectation and call it agreement.
    """
    plan = QUALITY_PLANS.get(plan_version)
    if plan is None:
        raise QualityGateError(
            f"Quality plan {plan_version!r} is unknown to this code (known: "
            f"{sorted(QUALITY_PLANS)}). A build gated on a plan nothing here has cannot be "
            "re-verified, and validating it against the current plan would compare the "
            "evidence to the wrong expectation."
        )
    return plan


__all__ = [
    "DERIVED_SCOPE",
    "PHASE3A_QUALITY_PLAN",
    "QUALITY_PLANS",
    "RUN_SCOPE",
    "SOURCE_SCOPE",
    "CheckRequirement",
    "PlannedCheck",
    "QualityPlan",
    "plan_for",
]
