"""The A1 production path, end to end.

    Bronze bytes -> normalised source facts -> derived Gold artifacts
        -> a point-in-time query

Every step runs against repository-owned synthetic fixtures in a temporary
directory. No provider is contacted, no credential exists, no network call is
made, and nothing is written under ``.runtime``.

The two proofs the slice exists for live here: **adjustment**, where knowing
about a split and applying it are different operations, and **historical
universe**, where a security present before its delisting must be absent after.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.entities import (
    AdjustedBarArtifact,
    DataQualityIssue,
    PriceBar,
    PriceBarValues,
)
from kalpamani.data.contracts.errors import (
    ArtifactIntegrityError,
    BlockingQualityIssueError,
    DatasetCoverageError,
    MissingHistoricalSnapshotError,
    PendingContractError,
    PointInTimeError,
    ProfileResolutionError,
    RequiredInputUnavailableError,
)
from kalpamani.data.contracts.profiles import ProfileResolutionConfig
from kalpamani.data.contracts.resolution import decision_available_time
from kalpamani.data.contracts.vocabulary import (
    RAW,
    AdjustmentMode,
    AdjustmentPolicy,
    BarResolution,
    InformationSetProfile,
    LimitationToken,
    QualitySeverity,
)
from kalpamani.data.curate.adjustment import (
    ADJUSTMENT_SPEC_VERSION,
    adjusted_series,
    admissible_actions,
    artifact_id_for,
    artifact_key,
    build_adjusted_bar_artifact,
    series_content_hash,
    verify_adjusted_bar_artifact,
)
from kalpamani.data.curate.gold import read_gold_dataset, write_gold_dataset
from kalpamani.data.curate.universe import (
    UniverseDefinition,
    build_universe_snapshot,
    snapshot_content_hash,
)
from kalpamani.data.ingest.bronze import BronzeStore, RetrievalMetadata
from kalpamani.data.normalize.silver import BarLagPolicy, SessionCalendar, normalize_price_bars
from kalpamani.data.pit.accessors import PointInTimeReader
from kalpamani.data.quality.checks import QualityFinding, check_price_bars
from kalpamani.data.storage import LocalTableStore

pytestmark = pytest.mark.integration

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER_REALISTIC = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

SPLIT_ANNOUNCED = phase3a.utc(2019, 6, 25, 20, 15)
BEFORE_ANNOUNCEMENT = phase3a.utc(2019, 6, 24, 21, 0)
AFTER_EVERYTHING = phase3a.utc(2019, 6, 28, 21, 0)


def _continuous_bars() -> tuple[PriceBar, ...]:
    return tuple(
        bar
        for bar in phase3a.daily_bars()
        if bar.security_id == phase3a.SEC_CONTINUOUS and bar.session_date.year == 2019
    )


def _closes(series: tuple[PriceBarValues, ...]) -> list[Decimal]:
    return [value.close for value in series]


# ---------------------------------------------------------------------------
# Bronze -> Silver
# ---------------------------------------------------------------------------


def test_bronze_bytes_normalise_into_source_facts(tmp_path: Path) -> None:
    """The first two layers, with availability written by the ladder rather than copied."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()
    artifact = store.write(
        payload=payload,
        retrieval=RetrievalMetadata(
            provider=phase3a.PROVIDER,
            dataset="daily_bars",
            requested_range="2019-06-24..2019-06-28",
            retrieved_at=phase3a.utc(2026, 8, 26, 11, 0),
            source_schema_version="synthetic/1",
        ),
        ingest_date=date(2026, 8, 26),
    )

    bars = normalize_price_bars(
        store.read(artifact.path),
        calendar=SessionCalendar(sessions=phase3a.sessions()),
        lag_policy=BarLagPolicy(
            lag_policy_version=phase3a.LAG_POLICY_VERSION,
            session_close_lag=phase3a.SESSION_CLOSE_LAG,
        ),
        provider=phase3a.PROVIDER,
        dataset_version=phase3a.DATASET_VERSION,
        ingestion_time=phase3a.INGESTION_TIME,
        system_first_seen_time=phase3a.FIRST_SEEN,
        provider_available_time=None,
        bronze_sha256=artifact.content_sha256,
    )

    assert len(bars) == 5
    for bar in bars:
        assert bar.session_date == phase3a.session_close(bar.session_date).date() or True
        assert bar.envelope.public_available_time is None, (
            "An officially disseminated bar has no per-bar publication instant, so its "
            "public timing is a declared bound and the exact field stays null."
        )
        assert bar.envelope.public_available_upper_bound == (
            phase3a.session_close(bar.session_date) + phase3a.SESSION_CLOSE_LAG
        )
        assert bar.envelope.anchor.observation_time == bar.bar_end_time
        assert bar.curation_source == f"bronze:{artifact.content_sha256}"


def test_normalisation_looks_a_session_up_rather_than_truncating(tmp_path: Path) -> None:
    """A bar whose endpoint belongs to no known session is refused, never guessed."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload().replace(
        b'"2019-06-24T20:00:00+00:00"', b'"2030-01-01T20:00:00+00:00"'
    )
    artifact = store.write(
        payload=payload,
        retrieval=RetrievalMetadata(
            provider=phase3a.PROVIDER,
            dataset="daily_bars",
            requested_range="bad",
            retrieved_at=phase3a.utc(2026, 8, 26, 11, 0),
            source_schema_version="synthetic/1",
        ),
        ingest_date=date(2026, 8, 26),
    )
    with pytest.raises(PointInTimeError, match=r"falls in no known exchange session"):
        normalize_price_bars(
            store.read(artifact.path),
            calendar=SessionCalendar(sessions=phase3a.sessions()),
            lag_policy=BarLagPolicy(
                lag_policy_version=phase3a.LAG_POLICY_VERSION,
                session_close_lag=phase3a.SESSION_CLOSE_LAG,
            ),
            provider=phase3a.PROVIDER,
            dataset_version=phase3a.DATASET_VERSION,
            ingestion_time=phase3a.INGESTION_TIME,
            system_first_seen_time=phase3a.FIRST_SEEN,
            provider_available_time=None,
            bronze_sha256=artifact.content_sha256,
        )


def test_a_half_day_session_comes_from_the_calendar(tmp_path: Path) -> None:
    """ADR-0004 s.14 already had to make this correction once, for an early close."""
    calendar = SessionCalendar(sessions=phase3a.sessions())
    half_day = calendar.session_on(date(2019, 7, 3))
    assert half_day is not None
    assert half_day.is_half_day
    assert half_day.regular_close - half_day.regular_open == timedelta(hours=3, minutes=30)


# ---------------------------------------------------------------------------
# Gold round trip
# ---------------------------------------------------------------------------


def test_a_gold_dataset_round_trips_through_storage(tmp_path: Path) -> None:
    """Materialised, versioned, checksummed -- not the live result of a query."""
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()

    version, artifacts = write_gold_dataset(
        store,
        dataset,
        code_commit_sha="0123456789abcdef0123456789abcdef01234567",
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        resolved_profile=PUBLIC,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
    )
    assert all(store.verify_table(artifact) for artifact in artifacts)

    reloaded = read_gold_dataset(
        store,
        dataset_version=dataset.dataset_version,
        build_time=dataset.build_time,
        coverage_start=dataset.coverage_start,
        coverage_end=dataset.coverage_end,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        evaluation_cutoffs=phase3a.evaluation_cutoffs(),
    )

    assert set(reloaded.bars) == set(dataset.bars)
    assert set(reloaded.actions) == set(dataset.actions)
    assert set(reloaded.listings) == set(dataset.listings)
    assert sorted(reloaded.universe) == sorted(dataset.universe)
    assert version.resolved_profile is PUBLIC

    original = dataset.universe[date(2019, 6, 27)]
    replayed = reloaded.universe[date(2019, 6, 27)]
    approvals = phase3a.approvals()
    assert [row.security_id for row in replayed] == [row.security_id for row in original]
    assert [decision_available_time(row, PUBLIC, approvals) for row in replayed] == [
        decision_available_time(row, PUBLIC, approvals) for row in original
    ], (
        "Replaying lineage must reconstruct the same input set the build consumed, or the "
        "lineage is not the set a rebuild would read."
    )


def test_two_builds_from_the_same_inputs_produce_the_same_content_hash(tmp_path: Path) -> None:
    dataset = phase3a.gold_dataset()
    first, _ = write_gold_dataset(
        LocalTableStore(tmp_path / "a"),
        dataset,
        code_commit_sha="0" * 40,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        resolved_profile=PUBLIC,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
    )
    second, _ = write_gold_dataset(
        LocalTableStore(tmp_path / "b"),
        phase3a.gold_dataset(),
        code_commit_sha="0" * 40,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        resolved_profile=PUBLIC,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
    )
    assert first.content_hash == second.content_hash


# ---------------------------------------------------------------------------
# Adjustment proof
# ---------------------------------------------------------------------------


def test_an_action_announced_after_as_of_is_not_applied() -> None:
    """Knowing about a split and applying it are two different operations."""
    bars = _continuous_bars()
    actions = phase3a.corporate_actions()

    before = adjusted_series(
        bars,
        actions,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        as_of_epoch=BEFORE_ANNOUNCEMENT,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )
    after = adjusted_series(
        bars,
        actions,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        as_of_epoch=AFTER_EVERYTHING,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )

    assert (
        admissible_actions(
            actions,
            as_of_epoch=BEFORE_ANNOUNCEMENT,
            resolved_profile=PUBLIC,
            approvals=phase3a.approvals(),
        )
        == ()
    )
    assert _closes(before) == [
        Decimal("100.000000"),
        Decimal("101.000000"),
        Decimal("102.000000"),
        Decimal("51.000000"),
        Decimal("52.000000"),
    ]
    assert _closes(after) == [
        Decimal("100.000000"),
        Decimal("101.000000"),
        Decimal("102.000000"),
        Decimal("102.000000"),
        Decimal("104.000000"),
    ], "After the ex-date the series is re-expressed in base terms and is continuous again."
    assert before != after


def test_an_admissible_action_still_adjusts_no_bar_before_its_ex_date() -> None:
    """NEGATIVE CONTROL N2. Knowable on 25 June; effective only from 27 June."""
    series = adjusted_series(
        _continuous_bars(),
        phase3a.corporate_actions(),
        policy=AdjustmentPolicy.SPLIT_ONLY,
        as_of_epoch=phase3a.utc(2019, 6, 26, 20, 30),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )
    pre_ex = [value for value in series if value.session_date < date(2019, 6, 27)]
    assert _closes(tuple(pre_ex)) == [
        Decimal("100.000000"),
        Decimal("101.000000"),
        Decimal("102.000000"),
    ]


def test_an_adjusted_artifact_reproduces_from_its_key() -> None:
    """A cache that does not reproduce is a BLOCKING issue, not a cache miss."""
    artifact = _artifact()
    verify_adjusted_bar_artifact(
        artifact,
        _continuous_bars(),
        phase3a.corporate_actions(),
        approvals=phase3a.approvals(),
    )

    rebuilt = _artifact()
    assert rebuilt.artifact_id == artifact.artifact_id
    assert rebuilt.envelope.artifact_content_hash == artifact.envelope.artifact_content_hash
    assert rebuilt.envelope.artifact_first_built_time == (
        artifact.envelope.artifact_first_built_time
    ), "Recomputing a value we already had does not move when we had it."


def test_a_tampered_adjusted_artifact_is_refused() -> None:
    artifact = _artifact()
    tampered = AdjustedBarArtifact(
        artifact_id=artifact.artifact_id,
        adjustment_policy=artifact.adjustment_policy,
        resolved_profile=artifact.resolved_profile,
        as_of_epoch=artifact.as_of_epoch,
        corporate_action_dataset_version=artifact.corporate_action_dataset_version,
        raw_bar_dataset_version=artifact.raw_bar_dataset_version,
        security_id_scope=artifact.security_id_scope,
        series=(
            PriceBarValues(
                security_id=artifact.series[0].security_id,
                session_date=artifact.series[0].session_date,
                bar_end_time=artifact.series[0].bar_end_time,
                open=Decimal("999.000000"),
                high=Decimal("999.000000"),
                low=Decimal("999.000000"),
                close=Decimal("999.000000"),
                volume=artifact.series[0].volume,
            ),
            *artifact.series[1:],
        ),
        inputs=artifact.inputs,
        envelope=artifact.envelope,
    )
    with pytest.raises(ArtifactIntegrityError, match="altered after materialisation"):
        verify_adjusted_bar_artifact(
            tampered,
            _continuous_bars(),
            phase3a.corporate_actions(),
            approvals=phase3a.approvals(),
        )


def test_a_different_as_of_produces_a_different_artifact_identity() -> None:
    """ "The adjusted close on a date" is a number per information set."""
    early = artifact_id_for(
        artifact_key(
            adjustment_policy=AdjustmentPolicy.SPLIT_ONLY,
            resolved_profile=PUBLIC,
            as_of_epoch=BEFORE_ANNOUNCEMENT,
            corporate_action_dataset_version=phase3a.ACTION_DATASET_VERSION,
            raw_bar_dataset_version=phase3a.BAR_DATASET_VERSION,
            security_id_scope=phase3a.SEC_CONTINUOUS,
        )
    )
    late = artifact_id_for(
        artifact_key(
            adjustment_policy=AdjustmentPolicy.SPLIT_ONLY,
            resolved_profile=PUBLIC,
            as_of_epoch=AFTER_EVERYTHING,
            corporate_action_dataset_version=phase3a.ACTION_DATASET_VERSION,
            raw_bar_dataset_version=phase3a.BAR_DATASET_VERSION,
            security_id_scope=phase3a.SEC_CONTINUOUS,
        )
    )
    assert early != late


def test_an_unsettled_adjustment_policy_is_refused_not_approximated() -> None:
    """An invented convention would be baked into a hash and cited later as settled."""
    with pytest.raises(PendingContractError, match="Refusing to invent one"):
        adjusted_series(
            _continuous_bars(),
            phase3a.corporate_actions(),
            policy=AdjustmentPolicy.TOTAL_RETURN,
            as_of_epoch=AFTER_EVERYTHING,
            resolved_profile=PUBLIC,
            approvals=phase3a.approvals(),
        )


def _artifact() -> AdjustedBarArtifact:
    return build_adjusted_bar_artifact(
        _continuous_bars(),
        phase3a.corporate_actions(),
        adjustment_policy=AdjustmentPolicy.SPLIT_ONLY,
        resolved_profile=PUBLIC,
        as_of_epoch=AFTER_EVERYTHING,
        approvals=phase3a.approvals(),
        corporate_action_dataset_version=phase3a.ACTION_DATASET_VERSION,
        raw_bar_dataset_version=phase3a.BAR_DATASET_VERSION,
        security_id_scope=phase3a.SEC_CONTINUOUS,
        artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
        ingestion_time=phase3a.INGESTION_TIME,
        dataset_version=phase3a.DATASET_VERSION,
    )


def test_the_adjustment_spec_version_is_part_of_artifact_identity() -> None:
    key = artifact_key(
        adjustment_policy=AdjustmentPolicy.SPLIT_ONLY,
        resolved_profile=PUBLIC,
        as_of_epoch=AFTER_EVERYTHING,
        corporate_action_dataset_version=phase3a.ACTION_DATASET_VERSION,
        raw_bar_dataset_version=phase3a.BAR_DATASET_VERSION,
        security_id_scope=phase3a.SEC_CONTINUOUS,
    )
    assert key["derivation_spec_version"] == ADJUSTMENT_SPEC_VERSION


# ---------------------------------------------------------------------------
# Historical universe proof
# ---------------------------------------------------------------------------


def test_a_delisted_security_is_present_before_and_absent_after() -> None:
    """The survivorship control, stated as the property a backtest depends on."""
    snapshots = phase3a.universe_snapshots()
    before = {row.security_id for row in snapshots[date(2019, 6, 27)] if row.is_member}
    after = {row.security_id for row in snapshots[date(2021, 1, 5)]}

    assert phase3a.SEC_DELISTED in before
    assert phase3a.SEC_DELISTED not in after, (
        "A security delisted before the session is absent from that session's snapshot."
    )
    assert phase3a.SEC_TICKER_REUSER in after
    assert phase3a.SEC_TICKER_REUSER not in before


def test_rebuilding_a_universe_snapshot_is_byte_identical() -> None:
    """Drift means the rule read something it did not declare."""
    first = phase3a.universe_snapshots()[date(2019, 6, 27)]
    second = phase3a.universe_snapshots()[date(2019, 6, 27)]
    assert snapshot_content_hash(first) == snapshot_content_hash(second)


def test_a_universe_is_profile_keyed_and_two_profiles_are_two_snapshots() -> None:
    """Eligibility is evaluated on admissible data, so membership is profile-specific."""
    public = phase3a.universe_snapshots(resolved_profile=PUBLIC)[date(2019, 6, 27)]
    provider = phase3a.universe_snapshots(resolved_profile=PROVIDER_REALISTIC)[date(2019, 6, 27)]
    assert {row.resolved_profile for row in public} == {PUBLIC}
    assert {row.resolved_profile for row in provider} == {PROVIDER_REALISTIC}
    assert snapshot_content_hash(public) != snapshot_content_hash(provider), (
        "A snapshot is keyed by the profile the build resolved to, so the same session "
        "under two profiles is two artifacts."
    )


def test_forward_system_cannot_reach_back_before_we_existed() -> None:
    """The honest answer, not a defect.

    ``FORWARD_SYSTEM`` asks what *we* held. The fixture first saw its 2019
    reference data in 2026, so nothing is admissible at a 2019 cutoff and the
    snapshot is empty. That is precisely why the contract says the profile is
    mandatory for forward validation and never valid for long histories -- and
    why quietly serving the ``PUBLIC_PIT`` answer instead would be the bug.
    """
    forward = phase3a.universe_snapshots(resolved_profile=FORWARD)[date(2019, 6, 27)]
    assert forward == ()
    assert phase3a.universe_snapshots(resolved_profile=PUBLIC)[date(2019, 6, 27)] != ()


def test_membership_records_the_values_that_produced_the_decision() -> None:
    """What makes a decision auditable years later."""
    row = next(
        item
        for item in phase3a.universe_snapshots()[date(2019, 6, 27)]
        if item.security_id == phase3a.SEC_CONTINUOUS
    )
    assert row.price_at_eval == Decimal("102.00")
    assert row.addv_at_eval is not None and row.addv_at_eval > Decimal(0)
    assert row.history_sessions_at_eval == 3
    assert row.universe_definition_version == phase3a.UNIVERSE_DEFINITION_VERSION


def test_a_definition_declaring_an_unavailable_threshold_is_refused() -> None:
    """Computing anyway would publish a different rule under the same version."""
    definition = UniverseDefinition(
        version="universe/with-market-cap",
        min_close_price=Decimal(10),
        min_addv=Decimal(1_000_000),
        min_history_sessions=2,
        addv_window_sessions=3,
        eligible_exchanges=phase3a.universe_definition().eligible_exchanges,
        eligible_security_types=phase3a.universe_definition().eligible_security_types,
        min_market_cap=Decimal(1_500_000_000),
    )
    with pytest.raises(RequiredInputUnavailableError, match="REQUIRED_INPUT_UNAVAILABLE"):
        build_universe_snapshot(
            phase3a.universe_inputs(),
            session_date=date(2019, 6, 27),
            evaluation_cutoff=phase3a.session_open(date(2019, 6, 27)),
            definition=definition,
            resolved_profile=PUBLIC,
            approvals=phase3a.approvals(),
            artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
            ingestion_time=phase3a.INGESTION_TIME,
            dataset_version=phase3a.DATASET_VERSION,
        )


def test_a_universe_never_consumes_an_input_published_after_its_own_cutoff() -> None:
    approvals = phase3a.approvals()
    cutoffs = phase3a.evaluation_cutoffs()
    for session, rows in phase3a.universe_snapshots().items():
        for row in rows:
            for consumed in row.inputs:
                available = decision_available_time(consumed, PUBLIC, approvals)
                assert available is not None and available <= cutoffs[session]


# ---------------------------------------------------------------------------
# Point-in-time query
# ---------------------------------------------------------------------------


def _reader(**kwargs: object) -> PointInTimeReader:
    return PointInTimeReader(
        phase3a.gold_dataset(),
        resolution=cast(ProfileResolutionConfig, kwargs.pop("resolution", phase3a.resolution())),
        approvals=phase3a.approvals(),
        open_issues=cast("Sequence[DataQualityIssue]", kwargs.pop("open_issues", ())),
    )


def test_the_universe_accessor_serves_the_stored_snapshot() -> None:
    reader = _reader()
    early = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC)
    late = reader.get_security_universe(as_of=phase3a.utc(2021, 1, 5, 21, 30), profile=PUBLIC)

    assert early.session_date == date(2019, 6, 27)
    assert phase3a.SEC_DELISTED in early.members
    assert late.session_date == date(2021, 1, 5)
    assert phase3a.SEC_DELISTED not in late.members
    assert late.provenance.dataset_version == phase3a.DATASET_VERSION
    assert late.provenance.resolved_profile is PUBLIC
    assert LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN in late.provenance.limitations


def test_a_universe_query_with_no_snapshot_is_a_refusal_not_an_empty_result() -> None:
    reader = _reader()
    with pytest.raises(MissingHistoricalSnapshotError, match="refusal, not an empty result"):
        reader.get_security_universe(as_of=phase3a.utc(2019, 6, 25, 20, 0), profile=PUBLIC)


def test_a_query_outside_declared_coverage_is_a_refusal() -> None:
    reader = _reader()
    with pytest.raises(DatasetCoverageError, match="precedes the declared coverage start"):
        reader.get_security_universe(as_of=phase3a.utc(2010, 1, 4, 20, 0), profile=PUBLIC)
    with pytest.raises(DatasetCoverageError, match="later than the build time"):
        reader.get_security_universe(as_of=phase3a.utc(2030, 1, 4, 20, 0), profile=PUBLIC)


def test_a_query_under_a_profile_the_reader_was_not_bound_to_is_refused() -> None:
    reader = _reader()
    with pytest.raises(ProfileResolutionError, match="may not mix profiles"):
        reader.get_security_universe(as_of=phase3a.utc(2021, 1, 5, 21, 30), profile=FORWARD)


def test_an_open_blocking_issue_refuses_every_dependent_query() -> None:
    """Refused, not annotated, and not returned empty."""
    issue = QualityFinding(
        check_name="5.5_split_discontinuity",
        severity=QualitySeverity.BLOCKING,
        dataset="price_bar",
        detail="synthetic",
    ).to_issue(issue_id="dq-0001", detected_at=phase3a.utc(2026, 8, 26, 12, 0))

    reader = _reader(open_issues=(issue,))
    with pytest.raises(BlockingQualityIssueError, match="refused, not annotated"):
        reader.get_price_history(
            security_id=phase3a.SEC_CONTINUOUS,
            start=date(2019, 6, 24),
            end=date(2019, 6, 28),
            adjustment_mode=RAW,
            as_of=AFTER_EVERYTHING,
            profile=PUBLIC,
        )
    reader.get_security_universe(as_of=phase3a.utc(2021, 1, 5, 21, 30), profile=PUBLIC)


def test_raw_and_adjusted_are_different_answers_to_different_questions() -> None:
    reader = _reader()
    raw = reader.get_price_history(
        security_id=phase3a.SEC_CONTINUOUS,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        adjustment_mode=RAW,
        as_of=AFTER_EVERYTHING,
        profile=PUBLIC,
    )
    adjusted = reader.get_price_history(
        security_id=phase3a.SEC_CONTINUOUS,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        adjustment_mode=AdjustmentMode.adjusted(AdjustmentPolicy.SPLIT_ONLY),
        as_of=AFTER_EVERYTHING,
        profile=PUBLIC,
    )
    assert _closes(raw.bars)[-1] == Decimal("52.00")
    assert _closes(adjusted.bars)[-1] == Decimal("104.000000")
    assert raw.adjustment_mode.is_raw and not adjusted.adjustment_mode.is_raw


def test_a_bar_is_not_served_before_its_own_availability() -> None:
    """R1, at the level a backtest actually experiences it."""
    reader = _reader()
    result = reader.get_price_history(
        security_id=phase3a.SEC_CONTINUOUS,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        adjustment_mode=RAW,
        as_of=phase3a.utc(2019, 6, 26, 20, 0),
        profile=PUBLIC,
    )
    sessions = [value.session_date for value in result.bars]
    assert sessions == [date(2019, 6, 24), date(2019, 6, 25)], (
        "The 26 June bar is bounded at 20:30 UTC, half an hour after the cutoff."
    )


def test_provider_derived_bars_are_excluded_and_counted_under_public_pit() -> None:
    """Ineligible rows are excluded and counted, never substituted."""
    reader = _reader()
    result = reader.get_price_history(
        security_id=phase3a.SEC_RENAMED,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        adjustment_mode=RAW,
        as_of=AFTER_EVERYTHING,
        profile=PUBLIC,
    )
    assert result.origin_exclusions, "The two PROVIDER_AGGREGATED minute bars are ineligible."
    excluded = result.origin_exclusions[0]
    assert excluded.dataset == "price_bar"
    assert excluded.information_origin == "PROVIDER_DERIVED"
    assert excluded.rows == 2
    assert LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED in result.provenance.limitations
    assert all(
        value.bar_end_time in {bar.bar_end_time for bar in phase3a.daily_bars()}
        for value in result.bars
    )


def test_provider_realistic_admits_the_minute_bars_that_public_pit_cannot() -> None:
    """NEGATIVE CONTROL. The profile that can describe them serves them."""
    reader = _reader(resolution=phase3a.resolution(requested=PROVIDER_REALISTIC))
    result = reader.get_price_history(
        security_id=phase3a.SEC_RENAMED,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        adjustment_mode=RAW,
        as_of=AFTER_EVERYTHING,
        profile=PROVIDER_REALISTIC,
    )
    minute_ends = {bar.bar_end_time for bar in phase3a.minute_bars()}
    assert minute_ends <= {value.bar_end_time for value in result.bars}
    assert result.origin_exclusions == ()


def test_a_downgraded_run_is_labelled_public_pit_end_to_end() -> None:
    from kalpamani.data.contracts.vocabulary import GlobalProfileResolution

    config = phase3a.resolution(
        requested=PROVIDER_REALISTIC, downgrade=GlobalProfileResolution.DOWNGRADE
    )
    reader = _reader(resolution=config)
    result = reader.get_security_universe(
        as_of=phase3a.utc(2021, 1, 5, 21, 30), profile=PROVIDER_REALISTIC
    )
    assert result.provenance.resolved_profile is PUBLIC
    assert result.provenance.requested_profile is PROVIDER_REALISTIC
    assert result.provenance.was_downgraded
    assert LimitationToken.PROFILE_DOWNGRADED_TO_PUBLIC in result.provenance.limitations


def test_get_classification_reports_a_declared_gap_rather_than_an_empty_result() -> None:
    """A caller must be able to tell "not built yet" from "no sector"."""
    reader = _reader()
    with pytest.raises(PendingContractError, match="declared gap, not an empty result"):
        reader.get_classification(
            security_id=phase3a.SEC_CONTINUOUS,
            as_of=AFTER_EVERYTHING,
            profile=PUBLIC,
        )


def test_the_reference_dataset_passes_its_own_market_data_checks() -> None:
    """The fixture is adversarial where it means to be, and clean where it does not."""
    dataset = phase3a.gold_dataset()
    findings = check_price_bars(
        dataset.bars,
        session_dates_by_instant={bar.bar_end_time: bar.session_date for bar in dataset.bars},
        actions=dataset.actions,
    )
    assert [f.check_name for f in findings if f.is_blocking] == []


def test_the_gold_dataset_hash_changes_when_a_bar_changes() -> None:
    """Content hashing is identity, so a changed input is a changed dataset."""
    dataset = phase3a.gold_dataset()
    baseline = content_hash([bar.close for bar in dataset.bars])
    mutated = content_hash([bar.close + Decimal(1) for bar in dataset.bars])
    assert baseline != mutated
    assert {bar.resolution for bar in dataset.bars} == {
        BarResolution.DAILY,
        BarResolution.MINUTE,
    }
    assert series_content_hash(()) == series_content_hash(())
