"""What a run says it read, what it was judged by, and what it actually did.

Four claims that nothing established.

A price series is not only its bars: the endpoint grid completeness is measured
against comes from listing states and a venue calendar, and the calendar was the
one input never filtered point-in-time. A revision published in 2020 decided what
a 2019 query expected, and neither table appeared anywhere in the run's inventory.

A universe snapshot is one derived artifact, and its availability was computed by
scanning membership rows -- so a security the rule considered and excluded delayed
nothing, and a snapshot holding no rows at all had no availability to speak of.

A quality report recorded the hash of the standard it applied and not the
standard, so an auditor could tell that a threshold had not changed without ever
learning what it was.

And a manifest restated the profiles, the window, the finding counts and the
dataset identity that the run had already established, with nothing comparing the
two halves.

Every test here is a case where the previous code produced an answer.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
)
from kalpamani.data.contracts.errors import (
    ArtifactIntegrityError,
    DatasetPublicationError,
    ExecutionSealError,
    IncompleteCoverageError,
    ManifestRefusedError,
    MissingHistoricalSnapshotError,
    ProfileResolutionError,
    QualityGateError,
)
from kalpamani.data.contracts.manifest import emit_manifest
from kalpamani.data.contracts.resolution import decision_available_time
from kalpamani.data.contracts.vocabulary import (
    RAW,
    AdjustmentPolicy,
    BarResolution,
    CorporateActionType,
    InformationSetProfile,
    LimitationToken,
    PublicBoundDerivation,
    PublicTimeDerivation,
)
from kalpamani.data.curate.adjustment import relevant_actions
from kalpamani.data.pit.accessors import (
    PointInTimeReader,
    SeriesRequirement,
    unapproved_bound_blocked,
)
from kalpamani.data.quality.report import TableCoverage, decode_quality_report
from kalpamani.data.quality.runner import run_quality_plan
from kalpamani.data.storage import LocalTableStore

pytestmark = pytest.mark.integration

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

SECURITY = phase3a.SEC_CONTINUOUS
FIRST = date(2019, 6, 24)
LAST = date(2019, 6, 28)
SETTLED = phase3a.utc(2019, 7, 1, 12, 0)


def _a_split() -> CorporateAction:
    """One split from the fixture, with the ex-date and ratio the arithmetic needs."""
    return next(
        action
        for action in phase3a.corporate_actions()
        if action.ratio is not None and action.ex_date is not None
    )


def _series(reader: PointInTimeReader, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "security_id": SECURITY,
        "start": FIRST,
        "end": LAST,
        "resolution": BarResolution.DAILY,
        "adjustment_mode": RAW,
        "as_of": SETTLED,
        "profile": PUBLIC,
        "requirement": SeriesRequirement.REQUIRED,
        "revision_view": None,
    }
    kwargs.update(overrides)
    return reader.get_price_history(**kwargs)


# ---------------------------------------------------------------------------
# 3 -- the grid's own inputs are point-in-time, and they are recorded
# ---------------------------------------------------------------------------


def test_a_calendar_revision_published_later_cannot_change_an_earlier_grid(
    tmp_path: Path,
) -> None:
    """The calendar was the one grid input nothing filtered.

    Adding a session in a later revision changed which endpoints an earlier query
    expected, so a query that had been complete began reporting a hole -- or, the
    other way round, a genuine gap stopped being one. A grid assembled from facts
    that did not exist yet is look-ahead deciding what counts as missing.
    """
    datasets = phase3a.source_datasets()
    original = next(
        row
        for row in datasets["market_session"]
        if isinstance(row, MarketSession) and row.session_date == date(2019, 6, 26)
    )
    # A 2026 correction: the same session, restated, superseding the 2019 row.
    corrected = dataclasses.replace(
        original,
        is_holiday=True,
        envelope=dataclasses.replace(
            original.envelope,
            revision_sequence=original.envelope.revision_sequence + 1,
            public_available_time=phase3a.utc(2026, 1, 1, 0, 0),
            source_id=original.envelope.source_id + ":r1",
        ),
    )
    datasets["market_session"] = (*datasets["market_session"], corrected)
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)

    early = _series(reader).result
    assert date(2019, 6, 26) in {bar.session_date for bar in early.bars}, (
        "At as_of the correction had not been published, so the session still counts."
    )

    # Once the correction is visible the session is a holiday, the grid no longer
    # expects it, and the bar sitting on it makes calendar and data contradict.
    # The same query, the same rows, a different answer -- decided by when it asked.
    with pytest.raises(IncompleteCoverageError, match="do not expect"):
        _series(reader, as_of=phase3a.utc(2026, 6, 1, 0, 0))


def test_a_calendar_day_the_query_cannot_see_refuses_rather_than_shrinking(
    tmp_path: Path,
) -> None:
    """Refusing only when the *whole* calendar was invisible left the worse half open.

    A partial calendar quietly shrinks the grid to fit what happens to be visible,
    so a query that had been refusing a genuine hole starts returning a shorter
    series that looks complete. That is measuring completeness against a calendar
    edited to agree with the data, reached from the other direction.
    """
    datasets = phase3a.source_datasets()
    victim = next(
        row
        for row in datasets["market_session"]
        if isinstance(row, MarketSession) and row.session_date == date(2019, 6, 26)
    )
    hidden = dataclasses.replace(
        victim,
        envelope=dataclasses.replace(
            victim.envelope,
            # After this query's as_of and well before the build's, so the build
            # itself is sound: the day is simply not one this query could see.
            public_available_time=phase3a.utc(2019, 8, 1, 0, 0),
        ),
    )
    datasets["market_session"] = tuple(
        hidden if row is victim else row for row in datasets["market_session"]
    )
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)
    with pytest.raises(IncompleteCoverageError, match="no calendar row this query was entitled"):
        _series(reader)


def test_a_listing_revision_published_later_cannot_change_an_earlier_grid(
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL for the calendar case, on the other grid input.

    Already point-in-time before this round; asserted here so the two inputs are
    held to one standard rather than one of them happening to be right.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = _series(reader)
    basis_datasets = {entry.dataset for entry in executed.evidence.timing_evidence}
    assert "listing" in basis_datasets
    assert executed.result.bars


def test_a_query_with_no_available_calendar_refuses(tmp_path: Path) -> None:
    """An empty grid would report that the security traded on no session.

    Not the same finding. The synthetic calendar's provider axis is a
    ``FIRST_SEEN_UPPER_BOUND`` derived from when the row was first held, so under
    ``PROVIDER_REALISTIC_PIT`` a 2019 query was never entitled to it -- and until
    the calendar was filtered, every such query measured completeness against
    sessions it could not have seen.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path), requested=PROVIDER)
    with pytest.raises(IncompleteCoverageError, match="no calendar row this query was entitled"):
        _series(reader, profile=PROVIDER, as_of=SETTLED)


def test_the_grid_inputs_carry_their_own_timing_evidence(tmp_path: Path) -> None:
    """Recording only ``price_bar`` left two inputs invisible in the inventory."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    evidence = _series(reader).evidence
    assert evidence.direct_source_datasets == ("listing", "market_session", "price_bar")
    for dataset in ("listing", "market_session", "price_bar"):
        assert evidence.required_bases_for(dataset), dataset
        assert evidence.governing_bases_for(dataset), dataset


def test_the_grid_basis_is_part_of_the_query_identity(tmp_path: Path) -> None:
    """Two runs can expect the same endpoints from different evidence."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = _series(reader)
    assert executed.query.grid_basis_hash
    assert "grid_basis_hash" in executed.query.identity()

    shorter = _series(reader, end=date(2019, 6, 26))
    assert shorter.query.grid_basis_hash != executed.query.grid_basis_hash


# ---------------------------------------------------------------------------
# 4 -- the snapshot header governs the whole snapshot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", [PUBLIC, PROVIDER, FORWARD])
def test_a_zero_row_snapshot_is_unavailable_before_its_header_decided(
    tmp_path: Path, profile: InformationSetProfile
) -> None:
    """A snapshot with no rows had no availability, so it looked available always.

    Scanning membership rows for the latest arrival gives an empty maximum when
    there are no rows. The header is a real derived artifact carrying every
    considered listing, so it has a decision time whether or not the rule selected
    anybody -- which is the whole point of distinguishing "nobody qualified" from
    "we had not looked yet".
    """
    publication = phase3a.zero_row_publication(LocalTableStore(tmp_path), requested=profile)
    reader = PointInTimeReader(
        publication,
        resolution=phase3a.resolution(requested=profile),
        approvals=phase3a.approvals(),
    )
    header = publication.dataset.universe_headers[date(2021, 1, 5)]
    assert not publication.dataset.universe[date(2021, 1, 5)], "Zero rows, deliberately."

    available = decision_available_time(header, profile, phase3a.approvals())
    assert available is not None, (
        "A snapshot with no rows still has a decision time, because the header carries "
        "every listing the rule considered. Scanning rows gave an empty maximum."
    )
    decided = max(available, header.evaluation_cutoff)

    with pytest.raises(MissingHistoricalSnapshotError):
        reader.get_security_universe(as_of=decided - timedelta(seconds=1), profile=profile)

    served = reader.get_security_universe(as_of=phase3a.BUILD_TIME, profile=profile).result
    assert served.members == ()
    assert served.non_members == ()


def test_a_considered_listing_that_produced_no_row_still_delays_the_snapshot() -> None:
    """It produced no membership row, so a row scan could not see it at all.

    A security the rule examined and excluded is part of what the snapshot
    decided. The header carries every considered listing among its inputs, so the
    snapshot is as available as the slowest of them -- including the ones that
    contributed nothing to the answer.
    """
    dataset = phase3a.gold_dataset()
    session = date(2021, 1, 5)
    header = dataset.universe_headers[session]
    rows = dataset.universe[session]

    member_ids = {row.security_id for row in rows}
    non_member_listings = [
        row
        for row in header.inputs
        if isinstance(row, Listing) and row.security_id not in member_ids
    ]
    assert non_member_listings, (
        "The 2021 rule considers the delisted security and it produces no row."
    )

    original = decision_available_time(header, PUBLIC, phase3a.approvals())
    assert original is not None
    latest = original + timedelta(days=365)
    victim = non_member_listings[0]
    slowed = dataclasses.replace(
        victim,
        envelope=dataclasses.replace(
            victim.envelope,
            public_available_time=latest,
            provider_available_time=latest,
        ),
    )
    slower = dataclasses.replace(
        header,
        inputs=tuple(slowed if row is victim else row for row in header.inputs),
    )
    delayed = decision_available_time(slower, PUBLIC, phase3a.approvals())
    assert delayed is not None
    assert delayed > original, (
        "A considered security arriving later moves the whole snapshot, and it "
        "contributed no row for a scan to find."
    )


def test_a_universe_result_records_the_headers_own_timing_evidence(
    tmp_path: Path,
) -> None:
    """Recording only membership rows left a zero-row snapshot with no evidence.

    A served result whose run says nothing about how it was admitted is a result
    nobody can audit, and it is exactly the case where the question matters most.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC)
    datasets = {entry.dataset for entry in executed.evidence.timing_evidence}
    assert "universe_snapshot_header" in datasets
    assert executed.evidence.required_bases_for("universe_snapshot_header")
    assert executed.evidence.consumed_artifacts, "The header is consumed as an artifact too."


def test_a_zero_row_snapshot_still_records_timing_evidence(tmp_path: Path) -> None:
    """The header has a decision time even where no row does."""
    publication = phase3a.zero_row_publication(LocalTableStore(tmp_path), requested=PUBLIC)
    reader = PointInTimeReader(
        publication,
        resolution=phase3a.resolution(requested=PUBLIC),
        approvals=phase3a.approvals(),
    )
    executed = reader.get_security_universe(as_of=phase3a.BUILD_TIME, profile=PUBLIC)
    assert executed.evidence.required_bases_for("universe_snapshot_header")
    assert executed.query.identity()["snapshot_artifact_id"]


def test_an_unapproved_bound_cannot_reach_a_reader_at_all(tmp_path: Path) -> None:
    """``approved=True`` was hard-coded, and its first replacement derived a constant.

    A **served** row cannot have leant on an unapproved bound: an unapproved bound
    resolves no axis, so the row is admitted some other way or not at all. Asking
    "was the bound this row was admitted on approved?" therefore returned ``True``
    for every row that has ever existed -- an assumption with arithmetic in front
    of it, which is the same defect as the hard-coded flag it replaced.

    Establishing where the answer actually lives took running it. A build carrying
    an unapproved bound is refused by the **quality gate**, so it never reaches a
    reader: ``4.0A.9_unapproved_public_bound`` is BLOCKING. The run-level recording
    below is therefore defence in depth for a publication produced some other way,
    and this test says so rather than implying the run is the first line.
    """
    datasets = phase3a.source_datasets()
    bars = datasets["price_bar"]
    victim = next(
        row
        for row in bars
        if isinstance(row, PriceBar)
        and row.security_id == SECURITY
        and row.resolution is BarResolution.DAILY
    )
    # The fixture's bars carry no exact public time and resolve on an approved
    # SESSION_CLOSE_PLUS_LAG bound. Restating the derivation as one this run has
    # not approved leaves the same instant and no way to use it.
    assert victim.envelope.public_available_time is None
    assert victim.envelope.public_available_upper_bound is not None
    blocked = dataclasses.replace(
        victim,
        envelope=dataclasses.replace(
            victim.envelope,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
            public_bound_derivation=PublicBoundDerivation.DATE_PLUS_LAG,
        ),
    )
    assert (
        PublicBoundDerivation.DATE_PLUS_LAG
        not in phase3a.approvals().for_dataset("price_bar").public
    ), "The fixture approves SESSION_CLOSE_PLUS_LAG for bars, and nothing else."

    # The predicate is real and derived: it distinguishes the two rows.
    assert unapproved_bound_blocked(blocked, PUBLIC, phase3a.approvals())
    assert not unapproved_bound_blocked(victim, PUBLIC, phase3a.approvals()), (
        "NEGATIVE CONTROL: the untouched row resolves on a bound this run approves."
    )

    datasets["price_bar"] = tuple(blocked if row is victim else row for row in bars)
    with pytest.raises(QualityGateError, match=r"4\.0A\.9_unapproved_public_bound"):
        phase3a.reader_from(LocalTableStore(tmp_path), datasets)


def test_a_run_with_every_bound_approved_records_none(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. The recording above is not the field being set always."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    assert _series(reader).evidence.unapproved_bounds_relied_upon == ()


# ---------------------------------------------------------------------------
# 6 -- the standard is persisted, not merely hashed
# ---------------------------------------------------------------------------


def test_the_published_report_carries_the_standard_it_applied(tmp_path: Path) -> None:
    """A hash says a threshold did not change. It never says what it was."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    descriptor = publication.quality_report.quality_context

    assert descriptor.identity() == publication.manifest.quality_context_hash
    parameters = dict(descriptor.universe_definition_parameters)
    assert parameters["min_close_price"] == str(phase3a.universe_definition().min_close_price)
    assert descriptor.survivorship_policy_version
    assert dict(descriptor.survivorship_policy)["deep_history_years"]
    assert descriptor.approvals, "The approved bound derivations are readable."
    assert descriptor.evaluation_cutoffs, "So are the cutoffs each snapshot was judged at."
    assert descriptor.build_identity == publication.dataset.build_identity


def test_an_edited_standard_does_not_reconcile_on_read(tmp_path: Path) -> None:
    """A standard editable after the build was judged against it is not a standard."""
    from kalpamani.data.quality.report import encode_quality_report

    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    body = dict(encode_quality_report(publication.quality_report))
    context = dict(body["quality_context"])  # type: ignore[call-overload]
    context["universe_definition_parameters"] = [["min_close_price", "0.01"]]
    body["quality_context"] = context

    with pytest.raises(QualityGateError, match="does not reconcile with its own hash"):
        decode_quality_report(body)


def test_the_stored_report_round_trips_through_the_verified_read(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. The untampered descriptor decodes and reconciles."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    from kalpamani.data.quality.report import encode_quality_report

    restored = decode_quality_report(encode_quality_report(publication.quality_report))
    assert restored.quality_context == publication.quality_report.quality_context
    assert restored.report_hash == publication.quality_report.report_hash


# ---------------------------------------------------------------------------
# 7 -- coverage is literal
# ---------------------------------------------------------------------------


def _coverage(outcome: Any) -> dict[str, str]:
    return {entity: state for entity, state, _ in outcome.report.table_coverage}


def test_a_table_with_rows_and_a_table_without_are_reported_differently() -> None:
    """One bit collapsed "we looked at everything" and "we looked and found nothing"."""
    dataset = phase3a.gold_dataset()
    outcome = run_quality_plan(
        phase3a.quality_context(dataset), policy_versions={"lag": phase3a.LAG_POLICY_VERSION}
    )
    coverage = _coverage(outcome)
    assert coverage["price_bar"] == TableCoverage.EXAMINED_WITH_ROWS.value
    assert set(coverage) >= {
        "corporate_action",
        "listing",
        "market_session",
        "price_bar",
        "security_attribute",
        "ticker_history",
        "universe_membership",
        "universe_snapshot_header",
    }
    published = set(coverage) - {"adjusted_bar_artifact"}
    assert all(coverage[entity] != TableCoverage.GOVERNED_NOT_RUN.value for entity in published), (
        "Every published table of the reference build was examined by something."
    )
    assert coverage["adjusted_bar_artifact"] == TableCoverage.GOVERNED_NOT_RUN.value, (
        "The reference build materialises no artifacts, and the report says so rather "
        "than leaving the entity absent -- which reads the same as covered."
    )


def test_an_empty_published_table_is_recorded_as_examined_empty() -> None:
    """A check that walked an empty table did check it, and must say which it was."""
    dataset = dataclasses.replace(phase3a.gold_dataset(), actions=())
    outcome = run_quality_plan(
        phase3a.quality_context(dataset), policy_versions={"lag": phase3a.LAG_POLICY_VERSION}
    )
    coverage = _coverage(outcome)
    assert coverage["corporate_action"] == TableCoverage.EXAMINED_EMPTY.value
    assert "corporate_action" in outcome.report.datasets_covered, (
        "Traversed and empty is covered. Silently claiming rows were examined is not."
    )


def test_an_empty_ticker_table_is_recorded_under_the_same_policy() -> None:
    """One rule for empty tables, not a special case per entity."""
    dataset = dataclasses.replace(phase3a.gold_dataset(), tickers=())
    outcome = run_quality_plan(
        phase3a.quality_context(dataset), policy_versions={"lag": phase3a.LAG_POLICY_VERSION}
    )
    assert _coverage(outcome)["ticker_history"] == TableCoverage.EXAMINED_EMPTY.value


def test_a_skipped_implementation_leaves_its_entity_not_run() -> None:
    """And the report says why, rather than leaving the absence unexplained."""
    context = dataclasses.replace(phase3a.quality_context(phase3a.gold_dataset()))
    outcome = run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})
    coverage = dict(
        (entity, (state, reason)) for entity, state, reason in outcome.report.table_coverage
    )
    if "adjusted_bar_artifact" in coverage:
        state, reason = coverage["adjusted_bar_artifact"]
        assert state == TableCoverage.GOVERNED_NOT_RUN.value
        assert reason, "A not-run entity states its governed reason."


def test_partitions_covered_are_partitions_something_traversed() -> None:
    """A configured cutoff with no snapshot behind it is a setting, not coverage.

    The reference fixture's cutoffs are exactly its snapshot sessions, so it
    cannot distinguish the two derivations at all: an assertion over it holds
    identically for ``sorted(context.evaluation_cutoffs)``. The extra cutoff below
    is what makes the case exist.
    """
    dataset = phase3a.gold_dataset()
    context = phase3a.quality_context(dataset)
    unvisited = date(2019, 6, 25)
    assert unvisited not in dataset.universe_headers
    context = dataclasses.replace(
        context,
        evaluation_cutoffs={
            **context.evaluation_cutoffs,
            unvisited: phase3a.session_open(unvisited),
        },
    )
    outcome = run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})

    held = {session.isoformat() for session in dataset.universe_headers}
    assert set(outcome.report.partitions_covered) == held, (
        "Every partition claimed is one an implementation actually walked."
    )
    assert unvisited.isoformat() not in outcome.report.partitions_covered, (
        "A cutoff with no snapshot behind it is a setting nobody traversed."
    )


def test_the_adjusted_artifact_check_replays_rather_than_self_compares(
    tmp_path: Path,
) -> None:
    """Comparing a series to its own hash proves the file was not edited. Nothing more.

    A wrong lineage, a wrong key, a wrong convention or arithmetic that never
    reproduced all pass that comparison, and the report claimed
    ``adjusted_bar_artifact`` covered on the strength of it.
    """
    dataset = phase3a.gold_dataset()
    artifact = phase3a.adjusted_artifact()
    tampered = dataclasses.replace(artifact, artifact_id="art-not-derivable-from-lineage")
    context = dataclasses.replace(phase3a.quality_context(dataset), adjusted_artifacts=(tampered,))
    outcome = run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})

    blocking = {finding.check_name for finding in outcome.report.blocking}
    assert "4.5.1_adjusted_cache_does_not_reproduce" in blocking, (
        "The stored numbers still match their own hash; only a replay catches this."
    )
    assert not outcome.report.passed


def test_a_sound_adjusted_artifact_passes_the_replay() -> None:
    """NEGATIVE CONTROL. The refusal above is not the check refusing everything."""
    context = dataclasses.replace(
        phase3a.quality_context(phase3a.gold_dataset()),
        adjusted_artifacts=(phase3a.adjusted_artifact(),),
    )
    outcome = run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})
    assert "adjusted_artifact_hash" in outcome.invoked
    assert _coverage(outcome)["adjusted_bar_artifact"] == TableCoverage.EXAMINED_WITH_ROWS.value
    assert outcome.report.passed


# ---------------------------------------------------------------------------
# 8 -- the manifest's duplicated claims are held to their source
# ---------------------------------------------------------------------------


def test_a_manifest_naming_another_profile_is_refused(tmp_path: Path) -> None:
    """The information set a result was computed in is not a caller's narrative."""
    store = LocalTableStore(tmp_path)
    executed = phase3a.sealed_result(store)
    manifest = phase3a.research_manifest_for(executed)
    emit_manifest(manifest, executed=executed)  # NEGATIVE CONTROL.

    other = dataclasses.replace(manifest, profile_resolution=phase3a.resolution(requested=FORWARD))
    with pytest.raises(ManifestRefusedError, match="resolved_profile"):
        emit_manifest(other, executed=executed)


def test_a_quality_summary_that_disagrees_with_its_report_is_refused(
    tmp_path: Path,
) -> None:
    """Zero warnings beside a report holding two is consistent and false."""
    from kalpamani.data.contracts.manifest import QualitySummary

    store = LocalTableStore(tmp_path)
    executed = phase3a.sealed_result(store)
    manifest = phase3a.research_manifest_for(executed)
    assert manifest.quality.warnings_open, "The reference build has real warnings."

    understated = dataclasses.replace(
        manifest,
        quality=QualitySummary(
            blocking_issues_open=0,
            warnings_open=0,
            checks_not_run=manifest.quality.checks_not_run,
            quality_report_hash=manifest.quality.quality_report_hash,
        ),
    )
    with pytest.raises(ManifestRefusedError, match="warnings_open"):
        emit_manifest(understated, executed=executed)


def test_emit_takes_the_bytes_the_run_sealed(tmp_path: Path) -> None:
    """Resupplying them was one more chance to hand over a different value."""
    store = LocalTableStore(tmp_path)
    executed = phase3a.sealed_result(store)
    manifest = phase3a.research_manifest_for(executed)
    assert emit_manifest(manifest, executed=executed) is manifest

    with pytest.raises(ManifestRefusedError, match="not the ones the run sealed"):
        emit_manifest(manifest, executed=executed, result_bytes=b"{}")


def test_a_dataset_reference_is_derived_from_the_publication(tmp_path: Path) -> None:
    """Five fields the caller restated, and five chances to name another dataset."""
    from kalpamani.data.curate.publication import dataset_reference_for

    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    reference = dataset_reference_for(publication)
    assert reference.dataset_version == publication.manifest.dataset_version
    assert reference.publication_manifest_hash == publication.manifest.manifest_hash
    assert reference.content_hash == publication.dataset.build_identity
    assert reference.resolved_profile is publication.manifest.resolved_profile


def test_a_query_spec_that_does_not_describe_its_result_is_refused() -> None:
    """Both come from one accessor call, so a disagreement is undetectable later."""
    from kalpamani.data.pit.accessors import require_query_describes_result
    from kalpamani.data.pit.query import PriceQuerySpec

    executed = phase3a.sealed_result_in_memory()
    query = executed.query
    assert isinstance(query, PriceQuerySpec)
    require_query_describes_result(query, executed.result)  # NEGATIVE CONTROL.

    with pytest.raises(ExecutionSealError, match="security_id"):
        require_query_describes_result(
            dataclasses.replace(query, security_id="SEC-SOMEONE-ELSE"), executed.result
        )


# ---------------------------------------------------------------------------
# 9 -- revision ties, and only actions that affect the answer
# ---------------------------------------------------------------------------


def test_two_contradictory_rows_at_one_revision_refuse(tmp_path: Path) -> None:
    """``max`` returned whichever tied row it saw first, so input order decided."""
    datasets = phase3a.source_datasets()
    original = _a_split()
    assert original.ratio is not None
    contradiction = dataclasses.replace(
        original,
        ratio=original.ratio * 2,
        envelope=dataclasses.replace(original.envelope, source_id="action:contradiction"),
    )
    datasets["corporate_action"] = (*datasets["corporate_action"], contradiction)
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)

    with pytest.raises(ProfileResolutionError, match="share revision sequence"):
        _series(
            reader,
            security_id=original.security_id,
            adjustment_mode=phase3a.split_adjusted_mode(),
            revision_view=phase3a.AS_KNOWN,
        )


def test_an_identical_duplicate_is_one_row_not_a_contradiction(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. Only a genuine disagreement refuses."""
    from kalpamani.data.contracts.vocabulary import RevisionView
    from kalpamani.data.pit.accessors import select_revision

    listing = phase3a.listings()[0]
    chosen = select_revision(
        [listing, dataclasses.replace(listing)],
        revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
        as_of=SETTLED,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )
    assert chosen == listing


@pytest.mark.parametrize(
    ("label", "shift", "expected"),
    [
        ("after the requested end", timedelta(days=3650), False),
        ("before the requested start", timedelta(days=-3650), True),
    ],
)
def test_only_actions_that_affect_the_series_are_relevant(
    label: str, shift: timedelta, expected: bool
) -> None:
    """Every relevant action is recorded as a read and pushes availability later.

    An action after the interval changes no number in it. One *before* the
    interval does: ``FORWARD_BASE_NORMALIZED`` expresses every bar in the original
    base, so an earlier split scales the whole window -- and dropping it made the
    same bar 104.00 through the reader and 52.00 through the artifact.
    """
    split = _a_split()
    assert split.ex_date is not None
    moved = dataclasses.replace(split, ex_date=split.ex_date + shift)
    kept = relevant_actions(
        [moved],
        security_id_scope=split.security_id,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=FIRST,
        valid_time_end=LAST,
        securities=(split.security_id,),
    )
    assert bool(kept) is expected, label


def test_an_action_type_the_policy_ignores_is_not_evidence() -> None:
    """An ignored input still narrows availability, for a row that changed nothing.

    ``SPLIT_ONLY`` reads no dividend, so a dividend in the lineage would push the
    artifact's availability later and its eligibility narrower without touching a
    single number -- leaving the artifact less available than the values it holds.
    """
    split = _a_split()
    dividend = dataclasses.replace(
        split,
        action_id="CA-DIVIDEND",
        action_type=CorporateActionType.DIVIDEND,
        envelope=dataclasses.replace(split.envelope, source_id="action:CA-DIVIDEND"),
    )
    kept = relevant_actions(
        [dividend],
        security_id_scope=dividend.security_id,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=FIRST,
        valid_time_end=LAST,
        securities=(dividend.security_id,),
    )
    assert kept == ()

    # NEGATIVE CONTROL: the same row, as the type the policy does consume.
    assert relevant_actions(
        [split],
        security_id_scope=split.security_id,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=FIRST,
        valid_time_end=LAST,
        securities=(split.security_id,),
    )


def test_the_reader_and_the_artifact_agree_on_the_relevant_action_set(
    tmp_path: Path,
) -> None:
    """The two paths are compared, not their source text.

    An ``inspect.getsource`` substring check compares the claim to something
    adjacent to it -- whether a name appears in the reader's body -- rather than
    to its subject, which is whether the two produce the same numbers. Swapping
    the interval arguments at the call site, or passing ``securities=()``, leaves
    the substring intact.
    """
    dataset = phase3a.gold_dataset()
    reader = phase3a.reader(LocalTableStore(tmp_path))
    from_reader = reader._admissible_action_revisions(
        SECURITY,
        view=phase3a.AS_KNOWN,
        as_of=SETTLED,
        resolved=PUBLIC,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        start=FIRST,
        end=LAST,
    )
    from_builder = relevant_actions(
        [action for action in dataset.actions if action.security_id == SECURITY],
        security_id_scope=SECURITY,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=FIRST,
        valid_time_end=LAST,
        securities=(SECURITY,),
    )
    assert [action.action_id for action in from_reader] == [
        action.action_id for action in from_builder
    ], "One relevant set, whichever path asks for it."
    assert from_reader, "And a non-empty one, so the comparison is not two empties."


def test_a_ratio_less_split_never_reaches_the_arithmetic() -> None:
    """It adjusts nothing and would push the artifact's availability later anyway."""
    split = next(action for action in phase3a.corporate_actions() if action.ratio is not None)
    phantom = dataclasses.replace(
        split,
        action_id="CA-NO-RATIO",
        ratio=None,
        envelope=dataclasses.replace(split.envelope, source_id="action:CA-NO-RATIO"),
    )
    kept = relevant_actions(
        [phantom],
        security_id_scope=split.security_id,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=FIRST,
        valid_time_end=LAST,
        securities=(split.security_id,),
    )
    assert kept == ()


def test_a_bound_required_limitation_names_a_bound_the_profile_needed(
    tmp_path: Path,
) -> None:
    """The tokens rest on the required set, not on whatever axis happened to win."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = _series(reader)
    tokens = set(executed.result.provenance.limitations)
    required = {
        basis for entry in executed.evidence.timing_evidence for basis in entry.required_bases
    }
    bounded = {"PUBLIC_BOUNDED", "PROVIDER_BOUNDED"} & {basis.value for basis in required}
    if not bounded:
        assert LimitationToken.PUBLIC_TIME_BOUNDED not in tokens
        assert LimitationToken.PROVIDER_TIME_BOUNDED not in tokens
    assert isinstance(ArtifactIntegrityError, type)


def test_a_restated_split_enters_the_arithmetic_once(tmp_path: Path) -> None:
    """The reader collapsed revisions before adjusting. The builder did not.

    Every revision that reaches the arithmetic multiplies into the factor, so a
    corrected split entered a materialised artifact **twice** and the same bar
    came back adjusted by the square of the ratio. The reader had this fixed
    already, which is exactly how the defect stayed invisible: the two paths were
    never asked the same question.
    """
    split = _a_split()
    restated = dataclasses.replace(
        split,
        envelope=dataclasses.replace(
            split.envelope,
            revision_sequence=split.envelope.revision_sequence + 1,
            source_id=split.envelope.source_id + ":r1",
        ),
    )
    kept = relevant_actions(
        (split, restated),
        security_id_scope=split.security_id,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=FIRST,
        valid_time_end=LAST,
        securities=(split.security_id,),
    )
    assert [action.envelope.revision_sequence for action in kept] == [
        restated.envelope.revision_sequence
    ], "One revision, and the one in force."


def test_two_contradictory_action_revisions_refuse_in_the_builder_too() -> None:
    """The same refusal as the reader's, for the same reason: input order decides."""
    split = _a_split()
    assert split.ratio is not None
    one = dataclasses.replace(
        split,
        envelope=dataclasses.replace(split.envelope, revision_sequence=1, source_id="a:1"),
    )
    other = dataclasses.replace(one, ratio=split.ratio * 2)
    with pytest.raises(ArtifactIntegrityError, match="different rows at revision sequence"):
        relevant_actions(
            (one, other),
            security_id_scope=split.security_id,
            policy=AdjustmentPolicy.SPLIT_ONLY,
            valid_time_start=FIRST,
            valid_time_end=LAST,
            securities=(split.security_id,),
        )


def test_the_quality_horizon_is_the_builds_own_time() -> None:
    """A horizon chosen from outside decides how much of the data the checks see.

    ``as_of`` was documented as "the build's own time" and compared to nothing.
    Pushing it past every row's availability leaves
    ``4.3.9_backfill_admitted_too_early`` and ``4.1.9_future_dated_availability``
    unable to fire, and the report records both as run.
    """
    dataset = phase3a.gold_dataset()
    context = phase3a.quality_context(dataset)
    assert context.as_of == dataset.build_time

    with pytest.raises(QualityGateError, match="declares as_of"):
        dataclasses.replace(context, as_of=phase3a.utc(2030, 1, 1, 0, 0))


def test_a_standard_recorded_against_another_information_set_is_refused() -> None:
    """The config is handed in independently of the build, and nothing compared them.

    The descriptor copies its resolution fields verbatim, so a persisted standard
    could name a profile and a policy version the build was never resolved under --
    and every hash over it would agree with itself.
    """
    build = phase3a.gold_dataset(requested=PROVIDER)
    with pytest.raises(QualityGateError, match="A standard recorded against one information set"):
        phase3a.quality_context(build, requested=PUBLIC)

    matched = phase3a.quality_context(build, requested=PROVIDER)
    assert matched.config.resolved_profile is build.resolved_profile


def test_a_reader_approving_other_bounds_than_the_build_is_refused(tmp_path: Path) -> None:
    """The approvals decide which rows resolve at all, so they decide what a query returns.

    The publication records the ones the build was judged under; the reader took
    its own from a parameter nothing compared to them. The standard was persisted
    and verified, and the one component that applies a standard at query time
    ignored it.
    """
    from kalpamani.data.contracts.resolution import ApprovedBoundPolicy, BoundApprovals

    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    with pytest.raises(DatasetPublicationError, match="approves bound derivations"):
        PointInTimeReader(
            publication,
            resolution=phase3a.resolution(),
            approvals=BoundApprovals(by_dataset={"price_bar": ApprovedBoundPolicy()}),
        )
    # NEGATIVE CONTROL: the approvals the build was judged under are accepted.
    PointInTimeReader(publication, resolution=phase3a.resolution(), approvals=phase3a.approvals())


def test_a_manifest_naming_another_resolution_policy_is_refused(tmp_path: Path) -> None:
    """Both fields are hashed into ``run_id`` and were compared to nothing.

    A manifest could name a policy version and a gap-resolution map the query had
    never applied, and each half read correctly on its own.
    """
    store = LocalTableStore(tmp_path)
    executed = phase3a.sealed_result(store)
    manifest = phase3a.research_manifest_for(executed)
    emit_manifest(manifest, executed=executed)  # NEGATIVE CONTROL.

    restated = dataclasses.replace(
        manifest,
        profile_resolution=dataclasses.replace(
            manifest.profile_resolution, resolution_policy_version="policy/invented.9"
        ),
    )
    with pytest.raises(ManifestRefusedError, match="declares resolution policy"):
        emit_manifest(restated, executed=executed)


def test_latest_restated_is_refused_even_for_a_security_with_no_actions(
    tmp_path: Path,
) -> None:
    """The refusal sat inside a per-action loop, so no actions meant no refusal.

    ``select_revision`` was the only runtime enforcement, and a security with no
    corporate-action rows -- the majority of them -- never entered that loop. The
    documented invariant fired only when the data happened to contain an action,
    which is not an invariant.
    """
    from kalpamani.data.contracts.errors import NonPointInTimeViewError
    from kalpamani.data.contracts.vocabulary import RevisionView

    reader = phase3a.reader(LocalTableStore(tmp_path))
    without_actions = phase3a.SEC_TICKER_REUSER
    assert not [
        action for action in phase3a.corporate_actions() if action.security_id == without_actions
    ], "This security has no corporate actions, which is what makes it the case."

    with pytest.raises(NonPointInTimeViewError, match="not a point-in-time view"):
        _series(
            reader,
            security_id=without_actions,
            adjustment_mode=phase3a.split_adjusted_mode(),
            revision_view=RevisionView.LATEST_RESTATED,
        )


def test_an_artifact_claiming_another_scope_or_interval_is_refused() -> None:
    """The key rebuild took both straight off the artifact, comparing a claim to itself.

    ``artifact_key`` exists so that a cache lookup cannot return the wrong series
    and have verification confirm it -- and for the two fields the key is most
    about, it could not.
    """
    from kalpamani.data.curate.adjustment import verify_adjusted_bar_artifact

    artifact = phase3a.adjusted_artifact()
    dataset = phase3a.gold_dataset()
    verify_adjusted_bar_artifact(  # NEGATIVE CONTROL.
        artifact, dataset.bars, dataset.actions, approvals=phase3a.approvals()
    )

    with pytest.raises(ArtifactIntegrityError, match="declares scope"):
        verify_adjusted_bar_artifact(
            dataclasses.replace(artifact, security_id_scope="SEC-SOMEONE-ELSE"),
            dataset.bars,
            dataset.actions,
            approvals=phase3a.approvals(),
        )


def test_a_partition_with_rows_and_no_header_refuses_rather_than_reporting_covered() -> None:
    """The guard checked one direction; this is the other, and it was open.

    A session holding membership rows with no header was never iterated by the
    rebuild, so it went unchecked while ``partitions_covered`` listed it and
    ``6_identity_and_universe`` was recorded as run.
    """
    dataset = phase3a.gold_dataset()
    session = date(2019, 6, 27)
    orphaned = dataclasses.replace(
        dataset,
        universe_headers={
            key: header for key, header in dataset.universe_headers.items() if key != session
        },
    )
    context = dataclasses.replace(phase3a.quality_context(dataset), dataset=orphaned)
    with pytest.raises(QualityGateError, match="hold membership rows with no header"):
        run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})


def test_a_descriptor_inconsistent_with_its_own_hash_is_caught_by_its_own_guard(
    tmp_path: Path,
) -> None:
    """The case no other check reaches.

    ``report_hash`` covers both the descriptor and ``quality_context_hash``, so
    an edit to either normally trips the report-hash guard first -- and a test
    matching on "does not reconcile with its own hash" passes with the descriptor
    guard deleted, because both messages contain that phrase.

    Recomputing ``report_hash`` over the tampered pair removes that cover. What is
    left is a body internally consistent everywhere except in the one relation the
    descriptor guard checks: the standard and the identity it claims.
    """
    from kalpamani.data.quality.report import encode_quality_report

    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    body = dict(encode_quality_report(publication.quality_report))
    context = dict(body["quality_context"])  # type: ignore[call-overload]
    context["universe_definition_parameters"] = [["min_close_price", "0.01"]]
    body["quality_context"] = context

    # Recompute the report hash over the tampered body, so the later guard agrees.
    restated = dataclasses.replace(
        publication.quality_report,
        quality_context=dataclasses.replace(
            publication.quality_report.quality_context,
            universe_definition_parameters=(("min_close_price", "0.01"),),
        ),
    )
    body["report_hash"] = restated.report_hash

    with pytest.raises(QualityGateError, match="persisted quality context does not reconcile"):
        decode_quality_report(body)
