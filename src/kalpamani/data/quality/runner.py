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

**Nothing an implementation found is dropped on the way to the report.** Routing
findings by id means a finding whose id belongs to no planned check has nowhere to
go, and the obvious implementation of that is to skip it -- which would silently
discard a BLOCKING defect because the plan's vocabulary had not caught up with the
code. Every produced finding must be claimed by the implementation that emitted it
**and** owned by a planned check, or the run refuses.

**What the report says it covered is derived from what was examined.**
``datasets_covered`` used to come from the plan's ``applies_to`` -- the *scope* a
check declares -- which is a statement of intent. A check whose implementation
never received a snapshot header still reported ``universe_snapshot_header``
covered, and for two entities that was exactly the case: headers and adjusted
artifacts were absent from the context's derived rows entirely, so nothing
examined them and the report said otherwise. Coverage now comes from the objects
each implementation was actually handed.

**The whole context is bound.** The checks read a profile resolution, approved
bounds, evaluation cutoffs, universe thresholds, market thresholds and a
survivorship policy -- all supplied by the caller, none of it in the report's
identity. Two runs under the same plan with different thresholds produced
interchangeable evidence. ``quality_context_hash`` covers every standard the run
was judged against, plus the build itself, and enters both the report's identity
and the dataset manifest's.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.dataset import GoldDataset
from kalpamani.data.contracts.entities import AdjustedBarArtifact, MarketSession, PriceBar
from kalpamani.data.contracts.errors import QualityGateError
from kalpamani.data.contracts.profiles import ProfileResolutionConfig
from kalpamani.data.contracts.resolution import BoundApprovals, PitRecord, is_eligible
from kalpamani.data.contracts.serde import (
    encode_corporate_action,
    encode_derived_envelope,
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
    build_snapshot_header,
    build_universe_snapshot,
    current_listings,
    definition_hash,
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
        """Every derived row the build holds -- **including** the headers and artifacts.

        Membership rows alone was the whole of it, so the envelope, temporal and
        profile checks never once examined a snapshot header or an adjusted
        artifact while the plan reported both covered. Two entities the report
        claimed and nothing looked at.
        """
        rows: list[PitRecord] = []
        for members in self.dataset.universe.values():
            rows.extend(members)
        rows.extend(self.dataset.universe_headers.values())
        rows.extend(self.adjusted_artifacts)
        return tuple(rows)

    def derived_subjects(self) -> tuple[str, ...]:
        """Which derived entities were actually available to be examined."""
        found: set[str] = set()
        if self.dataset.universe:
            found.add("universe_membership")
        if self.dataset.universe_headers:
            found.add("universe_snapshot_header")
        if self.adjusted_artifacts:
            found.add("adjusted_bar_artifact")
        return tuple(sorted(found))

    def source_subjects(self) -> tuple[str, ...]:
        """Which source entities the build actually holds rows for."""
        return tuple(
            sorted(
                name
                for name, rows in (
                    ("market_session", self.dataset.sessions),
                    ("listing", self.dataset.listings),
                    ("security_attribute", self.dataset.attributes),
                    ("ticker_history", self.dataset.tickers),
                    ("price_bar", self.dataset.bars),
                    ("corporate_action", self.dataset.actions),
                )
                if rows
            )
        )

    def context_hash(self) -> str:
        """Every standard this build was judged against, and the build itself.

        A report says which checks ran and what they found. It did not say what
        they were *measured with*: the same plan over the same build with a
        different minimum price, a different approved bound or a different
        survivorship threshold produced interchangeable evidence. All of it is
        caller-supplied, so all of it is bound.
        """
        return content_hash(
            {
                "build_identity": self.dataset.build_identity,
                "requested_profile": self.config.requested_profile.value,
                "resolved_profile": self.config.resolved_profile.value,
                "global_profile_resolution": self.config.global_profile_resolution.value,
                "resolution_policy_version": self.config.resolution_policy_version,
                "resolution_map": [list(entry) for entry in self.config.canonical_map()],
                "approvals": [
                    [
                        dataset,
                        sorted(item.value for item in policy.public),
                        sorted(item.value for item in policy.provider),
                        sorted(item.value for item in policy.announcement),
                    ]
                    for dataset, policy in sorted(self.approvals.by_dataset.items())
                ],
                "evaluation_cutoffs": [
                    [session.isoformat(), cutoff.isoformat()]
                    for session, cutoff in sorted(self.evaluation_cutoffs.items())
                ],
                "universe_definition": definition_hash(self.universe_definition),
                "as_of": self.as_of,
                "market_thresholds": [
                    self.market_thresholds.version,
                    str(self.market_thresholds.split_discontinuity_fraction),
                ],
                "survivorship_policy": [
                    self.survivorship_policy.version,
                    self.survivorship_policy.deep_history_years,
                    self.survivorship_policy.minimum_eligible_snapshots,
                ],
                "adjusted_artifacts": sorted(
                    artifact.artifact_id for artifact in self.adjusted_artifacts
                ),
            }
        )

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
    #: The entities this implementation actually examined, given this context.
    #: Not the plan's ``applies_to``, which is a declared *scope*: a check whose
    #: implementation never received a snapshot header still reported one
    #: covered, and for two entities that was exactly what happened.
    subjects: Callable[[QualityContext], tuple[str, ...]]


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
    for header in dataset.universe_headers.values():
        found.extend(
            check_stored_envelope_shape(
                encode_derived_envelope(header.envelope), dataset="universe_snapshot_header"
            )
        )
    for artifact in context.adjusted_artifacts:
        found.extend(
            check_stored_envelope_shape(
                encode_derived_envelope(artifact.envelope), dataset="adjusted_bar_artifact"
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


def _session_dates_by_instant(
    sessions: Sequence[MarketSession],
) -> dict[datetime, date]:
    """Every instant a bar may legitimately end on, mapped to its session date.

    The daily close **and** every minute endpoint in the regular session. Mapping
    only opens and closes reported every minute bar as belonging to no calendar
    session -- the check's own words -- which is a defect in the mapping, not in
    the bars.
    """
    out: dict[datetime, date] = {}
    for session in sessions:
        if session.is_holiday:
            continue
        out[session.regular_close] = session.session_date
        point = session.regular_open + timedelta(minutes=1)
        while point <= session.regular_close:
            out[point] = session.session_date
            point += timedelta(minutes=1)
    return out


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
    session_dates = _session_dates_by_instant(dataset.sessions)

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
    """Rebuild every snapshot **and its header**, and compare the whole identity.

    Comparing membership content alone left everything else in the header
    unchecked: the considered listings that produced no row, the required-domain
    coverage, the evaluation cutoff, the universe rule's actual thresholds. A
    build could change any of them and the drift check would say the snapshot
    reproduced -- because the rows did.

    The check takes two hashes, and the runner produces the second itself.
    Accepting it from a caller would make drift detection a formality: the caller
    would supply the stored hash and the comparison would pass by construction.
    """
    dataset = context.dataset
    inputs = UniverseBuildInputs(
        listings=dataset.listings,
        attributes=dataset.attributes,
        bars=dataset.bars,
    )
    uncovered = sorted(
        session for session in dataset.universe_headers if session not in context.evaluation_cutoffs
    )
    if uncovered:
        # Skipping them silently reported 6_identity_and_universe as run while
        # leaving those snapshots unrebuilt -- a check covering less than it
        # claims, which is worse than one that did not run.
        raise QualityGateError(
            f"Snapshots {[session.isoformat() for session in uncovered]} have no declared "
            "evaluation cutoff, so the rebuild check cannot reproduce them. A check that "
            "silently covers less than it claims converts an unknown into a false assurance."
        )

    found: list[QualityFinding] = []
    for session, header in sorted(dataset.universe_headers.items()):
        cutoff = context.evaluation_cutoffs[session]
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
        rebuilt_header = build_snapshot_header(
            rebuilt.rows,
            session_date=session,
            definition=context.universe_definition,
            resolved_profile=dataset.resolved_profile,
            evaluation_cutoff=cutoff,
            considered_listings=rebuilt.considered_listings,
            required_domain_coverage=rebuilt.required_domain_coverage,
            artifact_first_built_time=header.envelope.artifact_first_built_time,
            ingestion_time=header.envelope.ingestion_time,
            dataset_version=dataset.dataset_version,
        )
        found.extend(
            check_universe_rebuild(header.header_identity_hash, rebuilt_header.header_identity_hash)
        )
    return found


def _always_applicable(context: QualityContext) -> str | None:
    return None


def _all_subjects(context: QualityContext) -> tuple[str, ...]:
    """Every entity the build actually holds rows for, source and derived."""
    return tuple(sorted({*context.source_subjects(), *context.derived_subjects()}))


def _price_bar_subject(context: QualityContext) -> tuple[str, ...]:
    # The table, not its rows. This implementation is handed the whole bar
    # collection and traverses it, so it examined the entity even when the
    # traversal found nothing -- an empty table honestly checked is checked.
    # Contrast the artifacts below, whose implementation is skipped outright.
    return ("price_bar",)


def _ticker_subject(context: QualityContext) -> tuple[str, ...]:
    return ("ticker_history",)


def _universe_subjects(context: QualityContext) -> tuple[str, ...]:
    return ("universe_membership", "universe_snapshot_header")


def _adjusted_subject(context: QualityContext) -> tuple[str, ...]:
    return ("adjusted_bar_artifact",) if context.adjusted_artifacts else ()


def _run_subject(context: QualityContext) -> tuple[str, ...]:
    """The whole-run pseudo-entity, plus whatever the profile check examined."""
    return tuple(sorted({"run", *_all_subjects(context)}))


#: Every implementation this runner can invoke, by id.
CHECK_REGISTRY: Final[Mapping[str, CheckImplementation]] = {
    implementation.implementation_id: implementation
    for implementation in (
        CheckImplementation(
            implementation_id="envelope_conformance",
            subjects=_all_subjects,
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
            subjects=_all_subjects,
            emits=(
                "4.0.0_origin_outside_the_closed_vocabulary",
                "4.0A.5_missing_system_first_seen_time",
                "4.0B.1_derived_artifact_carrying_source_timing",
                "4.0B.4_derived_artifact_declares_a_source_temporal_class",
                "4.0_mixed_source_and_derived_envelope",
            ),
            invoke=_run_stored_shape,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="temporal_invariants",
            subjects=_all_subjects,
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
            subjects=_run_subject,
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
            subjects=lambda context: ("run",),
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
            subjects=_price_bar_subject,
            emits=(
                "3.1_duplicate_price_bar_key",
                # The bar checks also decide two temporal properties, because
                # both are about a bar's relationship to the calendar. The plan
                # assigns them to 4.1, so this implementation serves that check
                # too rather than the findings being routed nowhere.
                "4.1.12_bar_outside_any_known_session",
                "4.1.12_session_date_derived_by_utc_truncation",
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
            subjects=_adjusted_subject,
            emits=("4.5.1_adjusted_cache_does_not_reproduce",),
            invoke=_run_adjusted_artifacts,
            applicable=_adjusted_applicable,
        ),
        CheckImplementation(
            implementation_id="ticker_history",
            subjects=_ticker_subject,
            emits=("6.1_ticker_history_overlap",),
            invoke=_run_ticker_history,
            applicable=_always_applicable,
        ),
        CheckImplementation(
            implementation_id="universe_snapshots",
            subjects=_universe_subjects,
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
            subjects=_universe_subjects,
            emits=("6.5_universe_rebuild_drift",),
            invoke=_run_universe_rebuild,
            applicable=_always_applicable,
        ),
    )
}


class RunnerOutcome:
    """What the runner did, alongside the report it produced.

    Deliberately **not** a dataclass, and deliberately not constructible outside
    this module. The report's ``produced_by`` token was the whole seal, and it sat
    in a public dataclass field: ``dataclasses.replace`` copies such a field, so a
    fabricated report could be handed the real one's token and publication would
    accept a report nothing had run. A token in a readable field is a value, and a
    value can be moved.

    Publication takes this object instead. There is no field to copy: the only
    route to one is :func:`run_quality_plan`, which builds it after the checks
    have actually been invoked.
    """

    __slots__ = (
        "_invoked",
        "_plan_version",
        "_quality_context_hash",
        "_registry_identity",
        "_report",
        "_runner_version",
        "_sealed",
        "_skipped",
    )

    # Declared for the type checker: every assignment goes through
    # object.__setattr__ because __setattr__ itself refuses.
    _report: QualityReport
    _invoked: tuple[str, ...]
    _skipped: tuple[tuple[str, str], ...]
    _plan_version: str
    _runner_version: str
    _quality_context_hash: str
    _registry_identity: str
    _sealed: bool

    def __init__(
        self,
        *,
        report: QualityReport,
        invoked: tuple[str, ...],
        skipped: tuple[tuple[str, str], ...],
        plan_version: str,
        runner_version: str,
        quality_context_hash: str,
        registry_identity: str,
        sealed: bool,
        token: object,
    ) -> None:
        if token is not _RUNNER_TOKEN:
            raise QualityGateError(
                "A RunnerOutcome may only be produced by running the quality plan. "
                "Constructing one directly would recreate exactly the hole this type "
                "closes: evidence of a run, without the run."
            )
        object.__setattr__(self, "_report", report)
        object.__setattr__(self, "_invoked", invoked)
        object.__setattr__(self, "_skipped", skipped)
        object.__setattr__(self, "_plan_version", plan_version)
        object.__setattr__(self, "_runner_version", runner_version)
        object.__setattr__(self, "_quality_context_hash", quality_context_hash)
        object.__setattr__(self, "_registry_identity", registry_identity)
        object.__setattr__(self, "_sealed", sealed)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(
            "A RunnerOutcome is what one run produced and cannot be edited afterwards. "
            "Editing it would separate the evidence from the run."
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError("A RunnerOutcome is what one run produced.")

    @property
    def report(self) -> QualityReport:
        """The report these checks produced."""
        return self._report

    @property
    def invoked(self) -> tuple[str, ...]:
        """Implementations actually invoked, in id order."""
        return self._invoked

    @property
    def skipped(self) -> tuple[tuple[str, str], ...]:
        """Implementations not invoked, each with its governed reason."""
        return self._skipped

    @property
    def plan_version(self) -> str:
        """The plan this run executed."""
        return self._plan_version

    @property
    def runner_version(self) -> str:
        """The runner that executed it."""
        return self._runner_version

    @property
    def quality_context_hash(self) -> str:
        """Identity of every standard the build was judged against."""
        return self._quality_context_hash

    @property
    def registry_identity(self) -> str:
        """Identity of the implementations that ran, by id and declared findings."""
        return self._registry_identity

    @property
    def sealed(self) -> bool:
        """Whether the canonical registry ran. A substituted one is never sealed."""
        return self._sealed


def registry_identity(registry: Mapping[str, CheckImplementation]) -> str:
    """Canonical identity of a registry: which implementations, emitting what.

    Part of the context hash, so a report cannot be evidence of one set of
    implementations while having been produced by another.
    """
    return content_hash(
        {
            "implementations": sorted(
                [ident, sorted(implementation.emits)] for ident, implementation in registry.items()
            )
        }
    )


def run_quality_plan(
    context: QualityContext,
    *,
    plan: QualityPlan = PHASE3A_QUALITY_PLAN,
    registry: Mapping[str, CheckImplementation] = CHECK_REGISTRY,
    produced_at: datetime | None = None,
    policy_versions: Mapping[str, str] | None = None,
) -> RunnerOutcome:
    """Execute ``plan`` against ``context`` and build the report from what ran.

    ``registry`` exists so a test can substitute an implementation and observe
    that it ran. A report produced with anything other than :data:`CHECK_REGISTRY`
    is **not sealed**, and publication refuses it: otherwise a registry of no-op
    implementations would yield a genuinely runner-produced, plan-satisfying,
    publishable report that checked nothing at all.

    Raises:
        QualityGateError: if a check the plan marks REQUIRED has no registered
            implementation or did not apply; if an implementation declares a
            finding id no planned check owns; or if an implementation produces a
            finding it did not declare. Each would mean the report is not a
            faithful account of what the checks found.
    """
    _require_registry_agrees(plan, registry)
    sealed = registry is CHECK_REGISTRY or dict(registry) == dict(CHECK_REGISTRY)
    identity = registry_identity(registry)
    context_hash_value = content_hash(
        {
            "context": context.context_hash(),
            "plan_version": plan.plan_version,
            "runner_version": QUALITY_RUNNER_VERSION,
            "registry_identity": identity,
        }
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
        produced = list(implementation.invoke(context))
        undeclared = sorted(
            {
                finding.check_name
                for finding in produced
                if finding.check_name not in implementation.emits
            }
        )
        if undeclared:
            raise QualityGateError(
                f"Implementation {implementation_id!r} produced findings {undeclared} it does "
                "not declare. Findings are routed to planned checks by id, so an undeclared one "
                "has nowhere to go -- and dropping it would discard a defect because the "
                "registry had not caught up with the code."
            )
        invoked[implementation_id] = produced

    checks_run: list[str] = []
    checks_not_run: list[CheckNotRun] = []
    findings: list[QualityFinding] = []
    covered: set[str] = set()
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
            covered.update(registry[ident].subjects(context))
        for ident in check.implementations:
            findings.extend(
                finding for finding in invoked[ident] if finding.check_name in check.finding_ids
            )

    _require_nothing_dropped(invoked, findings, checks_run, plan)

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
        quality_context_hash=context_hash_value,
        runner_version=QUALITY_RUNNER_VERSION,
        implementations_invoked=tuple(sorted(invoked)),
        implementations_not_run=tuple(sorted(skipped.items())),
        policy_versions=versions,
        checks_run=tuple(checks_run),
        checks_not_run=tuple(checks_not_run),
        datasets_covered=tuple(sorted(covered)),
        partitions_covered=tuple(
            session.isoformat() for session in sorted(context.evaluation_cutoffs)
        ),
        produced_at=produced_at if produced_at is not None else context.dataset.build_time,
        produced_by=_RUNNER_TOKEN if sealed else None,
    )
    return RunnerOutcome(
        report=report,
        invoked=tuple(sorted(invoked)),
        skipped=tuple(sorted(skipped.items())),
        plan_version=plan.plan_version,
        runner_version=QUALITY_RUNNER_VERSION,
        quality_context_hash=context_hash_value,
        registry_identity=identity,
        sealed=sealed,
        token=_RUNNER_TOKEN,
    )


def _require_registry_agrees(
    plan: QualityPlan, registry: Mapping[str, CheckImplementation]
) -> None:
    """The plan and the registry must describe the same checks.

    Two separate failures, both of which make the report unfaithful: an
    implementation the plan names but nothing provides cannot run, and an
    implementation that emits a finding id no planned check owns produces evidence
    with nowhere to go.
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
    named = {ident for check in plan.checks for ident in check.implementations}
    unowned = sorted(
        {
            finding_id
            for ident in named
            for finding_id in registry[ident].emits
            if plan.owner_of(finding_id) is None
        }
    )
    if unowned:
        raise QualityGateError(
            f"Implementations declare findings {unowned} that plan {plan.plan_version} assigns "
            "to no check. A finding with no owner is routed nowhere, so a defect it reports "
            "would never reach the report."
        )


def _require_nothing_dropped(
    invoked: Mapping[str, Sequence[QualityFinding]],
    routed: Sequence[QualityFinding],
    checks_run: Sequence[str],
    plan: QualityPlan,
) -> None:
    """Every finding an invoked implementation produced reached the report.

    The only legitimate way a produced finding does not appear is if its owning
    check did not run -- which cannot happen, because an implementation is only
    invoked on behalf of checks that then count as run. Anything else is a defect
    silently discarded.
    """
    produced = [finding for findings in invoked.values() for finding in findings]
    if len(_deduplicate(produced)) == len(_deduplicate(list(routed))):
        return
    routed_keys = {(finding.check_name, finding.dataset, finding.detail) for finding in routed}
    lost = sorted(
        {
            f"{finding.check_name} ({finding.severity.value})"
            for finding in produced
            if (finding.check_name, finding.dataset, finding.detail) not in routed_keys
        }
    )
    raise QualityGateError(
        f"Findings {lost} were produced by an invoked check and did not reach the report. "
        f"Plan {plan.plan_version} ran {sorted(checks_run)}; a finding that is produced and "
        "then dropped is a defect the evidence does not mention."
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


def require_sealed_outcome(
    outcome: RunnerOutcome, *, dataset_version: str, build_identity: str
) -> None:
    """Refuse an outcome nobody ran, one run over something else, or one restated.

    Four separate claims, and a report alone establishes none of them
    structurally. The seal establishes that the canonical implementations were the
    ones invoked; the subject establishes what they were invoked over; the context
    hash establishes what they were measured with; and the outcome's own identity
    establishes that the report inside it is the one that run produced.

    Raises:
        QualityGateError: if a substituted registry ran, if the report names a
            different build, or if the report's recorded context or runner does
            not match the run that produced it.
    """
    if not isinstance(outcome, RunnerOutcome):
        raise QualityGateError(
            f"Publication of {dataset_version} was offered a {type(outcome).__name__} where a "
            "sealed RunnerOutcome is required. A quality report on its own is a description of "
            "a run; only the runner's own outcome is a product of one."
        )
    if not outcome.sealed:
        raise QualityGateError(
            f"The quality outcome offered for {dataset_version} was produced with a "
            f"substituted check registry, not {QUALITY_RUNNER_VERSION}'s. A registry of "
            "no-op implementations yields a genuinely runner-produced, plan-satisfying "
            "report that checked nothing at all."
        )
    report = outcome.report
    if report.subject_build_identity != build_identity:
        raise QualityGateError(
            f"The quality report offered for {dataset_version} was run over build "
            f"{report.subject_build_identity} and this build is {build_identity}. The checks "
            "really did run, and they ran over something else -- so every finding they did not "
            "make is a finding about a different set of rows."
        )
    if report.quality_context_hash != outcome.quality_context_hash:
        raise QualityGateError(
            f"The quality report offered for {dataset_version} records context "
            f"{report.quality_context_hash} and the run that produced it measured against "
            f"{outcome.quality_context_hash}. A report substituted into an outcome is a "
            "different report than the one those checks produced."
        )
    if report.runner_version != outcome.runner_version:
        raise QualityGateError(
            f"The quality report offered for {dataset_version} names runner "
            f"{report.runner_version!r} and this run was {outcome.runner_version!r}."
        )


__all__ = [
    "CHECK_REGISTRY",
    "QUALITY_RUNNER_VERSION",
    "CheckImplementation",
    "QualityContext",
    "RunnerOutcome",
    "registry_identity",
    "require_sealed_outcome",
    "run_quality_plan",
]
