"""The quality runner: the plan is executed, not declared.

A versioned plan made the report *closed* -- run and not-run had to account for
exactly the expected checks, findings had to belong to checks that ran, every
published table had to be covered. What it could not do is establish that any of
it happened. ``checks_run`` was a tuple of strings a caller supplied, so a caller
who wrote out every check id got a report that satisfied the plan completely
without a single check having been invoked.

That is the same failure the plan itself was built to close, one level up: the
evidence was a claim about the work rather than a product of it.

**Nothing here takes a caller's word for what ran.** The runner holds a registry
of implementations, invokes them, and constructs the :class:`QualityReport`
itself:

- ``checks_run`` is derived from **actual invocation**. An implementation that
  was not called cannot put its check in the list.
- ``checks_not_run`` comes only from an **applicability decision the runner
  computed** -- "this build materialised no adjusted artifacts", "reconciliation
  needs a second licensed source" -- never from a caller declaring a skip.
- ``findings`` are whatever the invoked implementations returned, and the plan
  routes each to the check that owns its id.
- a check the plan marks ``REQUIRED`` with **no registered implementation** is a
  refusal. A plan naming a check nothing implements is a plan that cannot be run,
  and discovering that at publication time is better than discovering it never
  ran at all.

**The report carries proof of its origin.** Only this module holds the token a
``QualityReport`` needs to call itself runner-produced, so a hand-built report is
still constructible -- tests need to build invalid ones -- but publication can
tell the two apart. Publication checks the plan first and the seal second, so a
report that fails the plan fails for the reason it is wrong rather than for its
provenance.

**One implementation may serve several planned checks.** ``check_price_bars``
emits duplicate-key, session-derivation and market-data findings together, and
splitting it to match the plan's vocabulary would change working code to suit a
registry. Each implementation instead declares the finding ids it can emit, and a
planned check counts as run when every implementation owning its ids has been
invoked.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from kalpamani.data.contracts.dataset import GoldDataset
from kalpamani.data.contracts.entities import AdjustedBarArtifact, PriceBar
from kalpamani.data.contracts.errors import QualityGateError
from kalpamani.data.contracts.profiles import ProfileResolutionConfig
from kalpamani.data.contracts.resolution import BoundApprovals, PitRecord, is_eligible
from kalpamani.data.contracts.serde import (
    encode_corporate_action,
    encode_listing,
    encode_market_session,
    encode_price_bar,
    encode_security_attribute,
    encode_ticker_history,
    encode_universe_membership,
)
from kalpamani.data.contracts.vocabulary import ListingFactKind
from kalpamani.data.curate.adjustment import series_content_hash
from kalpamani.data.curate.universe import (
    UniverseBuildInputs,
    UniverseDefinition,
    build_universe_snapshot,
    current_listings,
    snapshot_content_hash,
)
from kalpamani.data.quality.checks import (
    DEFAULT_MARKET_THRESHOLDS,
    DEFAULT_SURVIVORSHIP_POLICY,
    MarketDataThresholds,
    QualityFinding,
    SurvivorshipPolicy,
    check_adjusted_artifact_hash,
    check_envelope,
    check_price_bars,
    check_profile_service,
    check_run_identity_inputs,
    check_stored_envelope_shape,
    check_temporal_invariants,
    check_ticker_history,
    check_universe_rebuild,
    check_universe_snapshots,
)
from kalpamani.data.quality.plan import PHASE3A_QUALITY_PLAN, CheckRequirement, QualityPlan
from kalpamani.data.quality.report import CheckNotRun, QualityReport, report_from_findings

#: The runner's own version. Part of the seal, so a report produced by a
#: different runner is not silently accepted as though this one had produced it.
QUALITY_RUNNER_VERSION: Final = "phase3a.quality-runner.1"

#: Held by this module alone. A ``QualityReport`` carrying it was produced here.
#: A hand-built report stays constructible -- adversarial tests need one -- but
#: publication can tell the two apart.
_RUNNER_TOKEN: Final = object()


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityContext:
    """Everything the Phase-3A checks read, assembled once.

    The runner builds each implementation's arguments from this, so no caller
    chooses what a check sees. A check that reads less than it should is a bug in
    its registration, which is inspectable, rather than an argument somebody
    forgot to pass.
    """

    dataset: GoldDataset
    config: ProfileResolutionConfig
    approvals: BoundApprovals
    evaluation_cutoffs: Mapping[date, datetime]
    universe_definition: UniverseDefinition
    #: The cutoff the profile-service check evaluates against: the build's own
    #: time, so the check asks what this build was entitled to serve.
    as_of: datetime
    adjusted_artifacts: tuple[AdjustedBarArtifact, ...] = ()
    market_thresholds: MarketDataThresholds = DEFAULT_MARKET_THRESHOLDS
    survivorship_policy: SurvivorshipPolicy = DEFAULT_SURVIVORSHIP_POLICY

    def source_records(self) -> tuple[PitRecord, ...]:
        """Every source row the build holds, in canonical entity order."""
        return (
            *self.dataset.sessions,
            *self.dataset.listings,
            *self.dataset.attributes,
            *self.dataset.tickers,
            *self.dataset.bars,
            *self.dataset.actions,
        )

    def derived_records(self) -> tuple[PitRecord, ...]:
        """Every derived row the build holds."""
        rows: list[PitRecord] = []
        for members in self.dataset.universe.values():
            rows.extend(members)
        return tuple(rows)

    def run_id_inputs(self) -> dict[str, Any]:
        """The build's own identity inputs, for the run-identity check.

        Built here rather than accepted from a caller: the check exists to
        establish that the resolution map and its policy version reach the run's
        identity, and asking the caller to supply that identity would let them
        supply one that does.
        """
        return {
            "dataset_version": self.dataset.dataset_version,
            "resolved_profile": self.dataset.resolved_profile.value,
            "resolution_policy_version": self.config.resolution_policy_version,
            "dataset_provider_gap_resolutions": list(self.config.canonical_map()),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckImplementation:
    """One executable check, and the finding vocabulary it owns."""

    implementation_id: str
    #: The finding ids this implementation can emit. The plan routes findings to
    #: planned checks by id, so this is what ties code to vocabulary.
    emits: tuple[str, ...]
    invoke: Callable[[QualityContext], Sequence[QualityFinding]]
    #: Returns ``None`` when the check applies, or the governed reason it does
    #: not. Computed from the context, never declared by a caller.
    applicable: Callable[[QualityContext], str | None]


def _run_envelope(context: QualityContext) -> list[QualityFinding]:
    found: list[QualityFinding] = []
    for record in (*context.source_records(), *context.derived_records()):
        found.extend(check_envelope(record, approvals=context.approvals))
    return found


#: How each stored entity is encoded for the read-back shape check.
_ENCODERS: Final[tuple[tuple[str, Callable[[Any], Mapping[str, Any]]], ...]] = (
    ("market_session", encode_market_session),
    ("listing", encode_listing),
    ("security_attribute", encode_security_attribute),
    ("ticker_history", encode_ticker_history),
    ("price_bar", encode_price_bar),
    ("corporate_action", encode_corporate_action),
)


def _run_stored_shape(context: QualityContext) -> list[QualityFinding]:
    dataset = context.dataset
    groups: tuple[tuple[str, Sequence[Any]], ...] = (
        ("market_session", dataset.sessions),
        ("listing", dataset.listings),
        ("security_attribute", dataset.attributes),
        ("ticker_history", dataset.tickers),
        ("price_bar", dataset.bars),
        ("corporate_action", dataset.actions),
    )
    encoders = dict(_ENCODERS)
    found: list[QualityFinding] = []
    for name, rows in groups:
        encode = encoders[name]
        for row in rows:
            # The check is about the *envelope* shape, and an encoded entity
            # nests its envelope. Handing it the whole row made every stored row
            # look like one whose information_origin is outside the vocabulary,
            # because at the top level there is no such key at all.
            found.extend(check_stored_envelope_shape(encode(row)["envelope"], dataset=name))
    for members in dataset.universe.values():
        for member in members:
            found.extend(
                check_stored_envelope_shape(
                    encode_universe_membership(member)["envelope"],
                    dataset="universe_membership",
                )
            )
    return found


def _run_temporal(context: QualityContext) -> list[QualityFinding]:
    found: list[QualityFinding] = []
    for record in (*context.source_records(), *context.derived_records()):
        found.extend(
            check_temporal_invariants(
                record,
                resolved_profile=context.dataset.resolved_profile,
                approvals=context.approvals,
                dataset_build_time=context.dataset.build_time,
            )
        )
    return found


def _run_profile_service(context: QualityContext) -> list[QualityFinding]:
    """The 4.3 properties, over the rows this build would actually serve.

    Not over every stored row, and the difference is not a narrowing. Gold
    deliberately stores rows the resolved profile cannot serve -- the fixture's
    provider-aggregated bars are exactly that -- and filters them at query time.
    Handing the whole build to a check whose subject is "rows in a result" reports
    every one of them as an ineligible row served, which is the opposite of true:
    storing a row is not serving it.

    What the check does establish here is that everything the build *would* serve
    resolves, is in the resolution map, is keyed to one profile, and was not
    admitted before it was knowable.
    """
    resolved = context.dataset.resolved_profile
    servable = tuple(
        record
        for record in (*context.source_records(), *context.derived_records())
        if is_eligible(record, resolved)
    )
    return list(
        check_profile_service(
            servable,
            resolved_profile=resolved,
            approvals=context.approvals,
            config=context.config,
            as_of=context.as_of,
        )
    )


def _run_run_identity(context: QualityContext) -> list[QualityFinding]:
    return list(check_run_identity_inputs(context.config, context.run_id_inputs()))


def _listed_sessions(context: QualityContext, security_id: str) -> list[date]:
    """The sessions this security's own venue traded and it was listed on.

    Per security and per exchange, because "no bar on this session" is only a
    finding for a security that was listed on it. Handing every security the whole
    calendar reported a missing bar for every session each of them was not listed
    for -- eleven of them in the reference fixture, none of them true.
    """
    listings = [
        listing
        for listing in current_listings(context.dataset.listings)
        if listing.security_id == security_id and listing.listing_fact_kind is ListingFactKind.STATE
    ]
    if not listings:
        return []
    return sorted(
        session.session_date
        for session in context.dataset.sessions
        if not session.is_holiday
        and any(
            listing.exchange is session.exchange and listing.is_listed_on(session.session_date)
            for listing in listings
        )
    )


def _run_price_bars(context: QualityContext) -> list[QualityFinding]:
    """Structural and market-data checks, one security at a time.

    Per security because the coverage sub-check needs that security's own listed
    sessions. The bar key includes the security, so nothing cross-security is lost
    by splitting the pass.
    """
    dataset = context.dataset
    session_dates: dict[datetime, date] = {}
    for session in dataset.sessions:
        session_dates[session.regular_close] = session.session_date
        session_dates[session.regular_open] = session.session_date

    by_security: dict[str, list[PriceBar]] = {}
    for bar in dataset.bars:
        by_security.setdefault(bar.security_id, []).append(bar)

    found: list[QualityFinding] = []
    for security_id, bars in sorted(by_security.items()):
        found.extend(
            check_price_bars(
                bars,
                session_dates_by_instant=session_dates,
                actions=[action for action in dataset.actions if action.security_id == security_id],
                expected_sessions=_listed_sessions(context, security_id),
                thresholds=context.market_thresholds,
            )
        )
    return found


def _run_adjusted_artifacts(context: QualityContext) -> list[QualityFinding]:
    found: list[QualityFinding] = []
    for artifact in context.adjusted_artifacts:
        found.extend(check_adjusted_artifact_hash(artifact, series_content_hash(artifact.series)))
    return found


def _adjusted_applicable(context: QualityContext) -> str | None:
    if context.adjusted_artifacts:
        return None
    return (
        "this build materialised no adjusted bar artifacts, so there is no cache to "
        "reproduce. The decision is the runner's, computed from the build"
    )


def _run_ticker_history(context: QualityContext) -> list[QualityFinding]:
    return list(check_ticker_history(context.dataset.tickers))


def _run_universe_snapshots(context: QualityContext) -> list[QualityFinding]:
    return list(
        check_universe_snapshots(
            context.dataset,
            approvals=context.approvals,
            evaluation_cutoffs=context.evaluation_cutoffs,
            survivorship_policy=context.survivorship_policy,
        )
    )


def _run_universe_rebuild(context: QualityContext) -> list[QualityFinding]:
    """Rebuild every stored snapshot and compare, rather than trusting a hash.

    The check takes two hashes. Accepting the rebuilt one from a caller would make
    the drift check a formality -- the caller would supply the stored hash and the
    comparison would pass by construction -- so the runner does the rebuild.
    """
    dataset = context.dataset
    inputs = UniverseBuildInputs(
        listings=dataset.listings,
        attributes=dataset.attributes,
        bars=dataset.bars,
    )
    found: list[QualityFinding] = []
    for session, header in sorted(dataset.universe_headers.items()):
        cutoff = context.evaluation_cutoffs.get(session)
        if cutoff is None:
            continue
        rebuilt = build_universe_snapshot(
            inputs,
            session_date=session,
            evaluation_cutoff=cutoff,
            definition=context.universe_definition,
            resolved_profile=dataset.resolved_profile,
            approvals=context.approvals,
            artifact_first_built_time=header.envelope.artifact_first_built_time,
            ingestion_time=header.envelope.ingestion_time,
            dataset_version=dataset.dataset_version,
        )
        found.extend(
            check_universe_rebuild(
                header.snapshot_content_hash, snapshot_content_hash(rebuilt.rows)
            )
        )
    return found


def _always_applicable(context: QualityContext) -> str | None:
    return None


#: Every implementation this runner can invoke, by id.
CHECK_REGISTRY: Final[Mapping[str, CheckImplementation]] = {
    implementation.implementation_id: implementation
    for implementation in (
        CheckImplementation(
            implementation_id="envelope_conformance",
            emits=(
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
            invoke=_run_envelope,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="stored_envelope_shape",
            emits=(),
            invoke=_run_stored_shape,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="temporal_invariants",
            emits=(
                "4.1.12_bar_outside_any_known_session",
                "4.1.12_session_date_derived_by_utc_truncation",
                "4.1.1_held_before_public",
                "4.1.2_held_before_provider_supplied",
                "4.1.3_row_written_before_first_seen",
                "4.1.4_provider_ahead_of_public_for_the_same_fact",
                "4.1.9_future_dated_availability",
            ),
            invoke=_run_temporal,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="profile_service",
            emits=(
                "4.3.10_bound_applied_to_a_system_observed_row",
                "4.3.12_dataset_absent_from_the_resolution_map",
                "4.3.1_mixed_profiles_in_one_result",
                "4.3.2_unresolved_provider_availability",
                "4.3.3_public_timing_substituted_for_absent_provider_timing",
                "4.3.5_ineligible_row_served",
                "4.3.9_backfill_admitted_too_early",
            ),
            invoke=_run_profile_service,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="run_identity",
            emits=(
                "4.3.11_downgrade_not_carried_through",
                "4.3.13_resolution_map_not_in_run_id",
                "4.3.13_resolution_policy_version_not_in_run_id",
            ),
            invoke=_run_run_identity,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="price_bar_structure",
            emits=(
                "3.1_duplicate_price_bar_key",
                "5.1_impossible_ohlc",
                "5.2_non_positive_price_or_negative_volume",
                "5.4_missing_bar_in_a_listed_range",
                "5.5_split_discontinuity",
            ),
            invoke=_run_price_bars,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="adjusted_artifact_hash",
            emits=("4.5.1_adjusted_cache_does_not_reproduce",),
            invoke=_run_adjusted_artifacts,
            applicable=_adjusted_applicable,
        ),
        CheckImplementation(
            implementation_id="ticker_history",
            emits=("6.1_ticker_history_overlap",),
            invoke=_run_ticker_history,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="universe_snapshots",
            emits=(
                "6.3_survivorship_leakage",
                "6.4_delisted_absence",
                "6.6_eligibility_from_inadmissible_data",
                "6.8_profile_free_or_mismatched_universe",
            ),
            invoke=_run_universe_snapshots,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="universe_rebuild",
            emits=("6.5_universe_rebuild_drift",),
            invoke=_run_universe_rebuild,
            applicable=_always_applicable,
        ),
    )
}


@dataclass(frozen=True, slots=True, kw_only=True)
class RunnerOutcome:
    """What the runner did, alongside the report it produced.

    Kept separate from the report because it is about the *execution* -- which
    implementations were invoked, in what order -- and the report is about the
    build. A test asserting that an implementation actually ran reads this.
    """

    report: QualityReport
    invoked: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]


def run_quality_plan(
    context: QualityContext,
    *,
    plan: QualityPlan = PHASE3A_QUALITY_PLAN,
    registry: Mapping[str, CheckImplementation] = CHECK_REGISTRY,
    produced_at: datetime | None = None,
    datasets_covered: Sequence[str],
    partitions_covered: Sequence[str] = (),
    policy_versions: Mapping[str, str] | None = None,
) -> RunnerOutcome:
    """Execute ``plan`` against ``context`` and build the report from what ran.

    Raises:
        QualityGateError: if a check the plan marks REQUIRED has no registered
            implementation, or an implementation it needs decided it did not
            apply. A required check that cannot run is a refusal at publication
            time rather than a silent absence in the evidence.
    """
    unimplemented = sorted(
        implementation_id
        for check in plan.checks
        for implementation_id in check.implementations
        if implementation_id not in registry
    )
    if unimplemented:
        raise QualityGateError(
            f"Quality plan {plan.plan_version} names implementations {unimplemented}, which "
            "this runner does not have. A plan naming a check nothing implements cannot be "
            "run, and finding that out at publication is better than finding out it never ran."
        )

    invoked: dict[str, list[QualityFinding]] = {}
    skipped: dict[str, str] = {}
    for implementation_id in sorted(
        {ident for check in plan.checks for ident in check.implementations}
    ):
        implementation = registry[implementation_id]
        reason = implementation.applicable(context)
        if reason is not None:
            skipped[implementation_id] = reason
            continue
        invoked[implementation_id] = list(implementation.invoke(context))

    checks_run: list[str] = []
    checks_not_run: list[CheckNotRun] = []
    findings: list[QualityFinding] = []
    for check in sorted(plan.checks, key=lambda item: item.check_id):
        if not check.implementations:
            checks_not_run.append(
                CheckNotRun(
                    check_name=check.check_id,
                    reason=(
                        "no implementation exists in this slice; the plan declares it "
                        "conditional for that reason"
                    ),
                )
            )
            continue
        missing = [ident for ident in check.implementations if ident not in invoked]
        if missing:
            checks_not_run.append(
                CheckNotRun(
                    check_name=check.check_id,
                    reason="; ".join(skipped[ident] for ident in missing),
                )
            )
            continue
        checks_run.append(check.check_id)
        for ident in check.implementations:
            findings.extend(
                finding for finding in invoked[ident] if finding.check_name in check.finding_ids
            )

    blocked = [
        item.check_name
        for item in checks_not_run
        if (planned := plan.check(item.check_name)) is not None
        and planned.requirement is CheckRequirement.REQUIRED
    ]
    if blocked:
        raise QualityGateError(
            f"Quality plan {plan.plan_version} marks {sorted(blocked)} REQUIRED, and the "
            "runner could not invoke them. A required check that did not run is a refusal: "
            "recording it as not-run would produce evidence that says, accurately, that the "
            "build was never checked."
        )

    versions = dict(policy_versions or {})
    versions.setdefault("market", context.market_thresholds.version)
    versions.setdefault("survivorship", context.survivorship_policy.version)

    report = report_from_findings(
        _deduplicate(findings),
        plan_version=plan.plan_version,
        subject_build_identity=context.dataset.build_identity,
        policy_versions=versions,
        checks_run=tuple(checks_run),
        checks_not_run=tuple(checks_not_run),
        datasets_covered=tuple(datasets_covered),
        partitions_covered=tuple(partitions_covered),
        produced_at=produced_at if produced_at is not None else context.dataset.build_time,
        produced_by=_RUNNER_TOKEN,
    )
    return RunnerOutcome(
        report=report,
        invoked=tuple(sorted(invoked)),
        skipped=tuple(sorted(skipped.items())),
    )


def _deduplicate(findings: Sequence[QualityFinding]) -> list[QualityFinding]:
    """One finding per (check, dataset, detail, scope).

    Several implementations can legitimately report the same defect -- an envelope
    problem shows up per row -- and counting it twice would misstate how much is
    wrong.
    """
    seen: set[tuple[str, str, str, str | None, date | None]] = set()
    out: list[QualityFinding] = []
    for finding in findings:
        key = (
            finding.check_name,
            finding.dataset,
            finding.detail,
            finding.security_id,
            finding.session_date,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def report_is_runner_produced(report: QualityReport) -> bool:
    """Whether this exact report object came out of :func:`run_quality_plan`.

    Identity, not a recomputable hash. A seal a caller could compute is a seal a
    caller can forge, and the whole point is telling a produced report from a
    described one.
    """
    return report.produced_by is _RUNNER_TOKEN


def require_runner_produced(
    report: QualityReport, *, dataset_version: str, build_identity: str
) -> None:
    """Refuse a report nobody ran, or one that was run over something else.

    Both halves are needed. The seal establishes that the checks were invoked; the
    subject establishes what they were invoked over. A report with the first and
    not the second is a genuine clean pass over a **different build**, which is
    the same failure as a fabricated report reached from the other direction.

    Raises:
        QualityGateError: if the report was not produced by this runner, or names
            a different build than the one being published.
    """
    if not report_is_runner_produced(report):
        raise QualityGateError(
            f"The quality report offered for {dataset_version} was not produced by the quality "
            f"runner ({QUALITY_RUNNER_VERSION}). Its checks_run list is a claim about work "
            "rather than a product of it: a caller who writes out every check id satisfies the "
            "plan completely without a single check having been invoked."
        )
    if report.subject_build_identity != build_identity:
        raise QualityGateError(
            f"The quality report offered for {dataset_version} was run over build "
            f"{report.subject_build_identity} and this build is {build_identity}. The checks "
            "really did run, and they ran over something else -- so every finding they did not "
            "make is a finding about a different set of rows."
        )


__all__ = [
    "CHECK_REGISTRY",
    "QUALITY_RUNNER_VERSION",
    "CheckImplementation",
    "QualityContext",
    "RunnerOutcome",
    "report_is_runner_produced",
    "require_runner_produced",
    "run_quality_plan",
]
