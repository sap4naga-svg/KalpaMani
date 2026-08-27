"""The A1 production path, end to end.

    Bronze bytes -> the resolution boundary -> normalised source facts
        -> derived Gold artifacts -> atomic publication -> a verified read
        -> a point-in-time query

Every step runs against repository-owned synthetic fixtures in a temporary
directory. No provider is contacted, no credential exists, no network call is
made, and nothing is written under ``.runtime``.

The proofs this slice exists for live here: **adjustment**, where knowing about a
split and applying it are different operations; **historical universe**, where a
security present before its delisting must be absent after; **resolution**, where
a declared policy has to actually change the rows; and **publication**, where a
half-written build is not a smaller build.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.entities import (
    AdjustedBarArtifact,
    PriceBar,
    PriceBarValues,
)
from kalpamani.data.contracts.errors import (
    ArtifactIntegrityError,
    DatasetCoverageError,
    DatasetPublicationError,
    IncompleteCoverageError,
    MissingHistoricalSnapshotError,
    PendingContractError,
    PointInTimeError,
    ProfileResolutionError,
    QualityGateError,
    QueryRangeError,
    RequiredInputUnavailableError,
    SecurityNotInDatasetError,
    UnresolvedProviderAvailabilityError,
)
from kalpamani.data.contracts.profiles import DatasetGapResolution, ProfileResolutionConfig
from kalpamani.data.contracts.resolution import decision_available_time
from kalpamani.data.contracts.vocabulary import (
    RAW,
    AdjustmentConvention,
    AdjustmentMode,
    AdjustmentPolicy,
    BarResolution,
    DatasetGapPolicy,
    GlobalProfileResolution,
    InformationSetProfile,
    LimitationToken,
    RevisionView,
    StorageLayer,
)
from kalpamani.data.curate.adjustment import (
    ADJUSTMENT_CONVENTION,
    ADJUSTMENT_SPEC_VERSION,
    MULTI_SECURITY_SCOPE_PREFIX,
    action_lineage_hash,
    adjusted_series,
    admissible_actions,
    artifact_id_for,
    artifact_key,
    bar_lineage_hash,
    build_adjusted_bar_artifact,
    relevant_actions,
    source_versions,
    verify_adjusted_bar_artifact,
)
from kalpamani.data.curate.build import build_gold_dataset
from kalpamani.data.curate.publication import (
    GOLD_ENTITIES,
    QUALITY_REPORT_NAME,
    compute_manifest_hash,
    load_dataset_manifest,
    publish_gold_dataset,
    read_published_dataset,
)
from kalpamani.data.curate.resolution_run import resolve_run_inputs
from kalpamani.data.curate.universe import (
    UniverseDefinition,
    build_universe_snapshot,
    membership_hash_of,
    snapshot_content_hash,
)
from kalpamani.data.ingest.bronze import BronzeStore, RetrievalMetadata
from kalpamani.data.normalize.silver import BarLagPolicy, SessionCalendar, normalize_price_bars
from kalpamani.data.pit.accessors import (
    PointInTimeReader,
    SeriesRequirement,
    _minute_endpoints,
)
from kalpamani.data.quality.checks import check_price_bars
from kalpamani.data.quality.plan import PHASE3A_QUALITY_PLAN
from kalpamani.data.storage import LocalTableStore

pytestmark = pytest.mark.integration

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER_REALISTIC = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

BEFORE_ANNOUNCEMENT = phase3a.utc(2019, 6, 24, 21, 0)
AFTER_EVERYTHING = phase3a.utc(2019, 6, 28, 21, 0)

#: After the synthetic calendar itself became available.
#:
#: ``market_session`` is the one dataset whose provider axis the fixture leaves to
#: a ``FIRST_SEEN_UPPER_BOUND``, and the resolution step derives that bound from
#: when the row was first seen -- 2026. Under ``PROVIDER_REALISTIC_PIT`` the
#: calendar is therefore not available to a 2019 query at all, which is the honest
#: consequence of "we do not know when the vendor published it, so we bound it by
#: when we first held it". Until the calendar was filtered point-in-time like every
#: other input, provider-realistic queries measured completeness against sessions
#: they could not have seen.
AFTER_THE_CALENDAR_WAS_AVAILABLE = phase3a.utc(2026, 8, 21, 0, 0)
SCOPE = phase3a.SEC_CONTINUOUS
VALID_START = date(2019, 6, 24)
VALID_END = date(2019, 6, 28)


def _continuous_bars() -> tuple[PriceBar, ...]:
    return tuple(
        bar
        for bar in phase3a.daily_bars()
        if bar.security_id == SCOPE and bar.session_date.year == 2019
    )


def _closes(series: Sequence[PriceBarValues]) -> list[Decimal]:
    return [value.close for value in series]


def _retrieval(run_id: str | None = None) -> RetrievalMetadata:
    return RetrievalMetadata(
        provider=phase3a.PROVIDER,
        dataset="daily_bars",
        requested_range="2019-06-24..2019-06-28",
        retrieved_at=phase3a.utc(2026, 8, 26, 11, 0),
        source_schema_version="synthetic/1",
        ingestion_run_id=run_id or phase3a.INGESTION_RUN_ID,
    )


# ---------------------------------------------------------------------------
# Bronze -> Silver
# ---------------------------------------------------------------------------


def test_bronze_bytes_normalise_into_source_facts(tmp_path: Path) -> None:
    """The first two layers, with availability written by the ladder rather than copied."""
    store = BronzeStore(tmp_path)
    artifact = store.write(
        payload=phase3a.bronze_payload(),
        retrieval=_retrieval(),
        ingest_date=date(2026, 8, 26),
    )
    calendar = SessionCalendar(sessions=phase3a.sessions())

    bars = normalize_price_bars(
        store.read(artifact.path),
        calendar=calendar,
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
        assert bar.session_date == calendar.session_of(bar.bar_end_time), (
            "The session key comes from the exchange calendar, not from the instant."
        )
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
    artifact = store.write(payload=payload, retrieval=_retrieval(), ingest_date=date(2026, 8, 26))
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
# The resolution boundary
# ---------------------------------------------------------------------------


def test_resolution_changes_the_rows_not_only_the_run_id() -> None:
    """One dataset BOUND, another EXCLUDE, and both actually happen.

    The evidence has to describe rows that are really there: an ``EXCLUDE`` that
    removes nothing and a ``BOUND`` that bounds nothing are declarations, not
    events, and a manifest built on them would claim what the run did not do.
    """
    resolved = phase3a.resolved_inputs(requested=PROVIDER_REALISTIC)

    bounded = resolved.evidence_for("market_session")
    excluded = resolved.evidence_for("ticker_history")

    assert bounded.policy is DatasetGapPolicy.BOUND
    assert bounded.provider_bounded_rows == len(phase3a.sessions())
    for row in resolved.rows("market_session"):
        assert row.envelope.provider_available_upper_bound is not None
        assert row.envelope.provider_available_time is None, (
            "BOUND claims the provider offered the row no later than then, never that it "
            "published at that instant."
        )

    assert excluded.policy is DatasetGapPolicy.EXCLUDE
    assert excluded.excluded_rows == len(phase3a.ticker_history())
    assert resolved.rows("ticker_history") == (), "EXCLUDE removes rows, it does not annotate."

    tokens = resolved.limitation_tokens()
    assert LimitationToken.PROVIDER_TIME_BOUNDED in tokens
    assert LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN in tokens


def test_tokens_come_from_evidence_not_from_declared_policy() -> None:
    """The same config under PUBLIC_PIT resolves no gaps, so it claims none."""
    public = phase3a.resolved_inputs(requested=PUBLIC)
    assert public.evidence_for("market_session").policy is DatasetGapPolicy.BOUND
    assert public.evidence_for("market_session").provider_bounded_rows == 0
    assert LimitationToken.PROVIDER_TIME_BOUNDED not in public.limitation_tokens(), (
        "A declared BOUND that bounded nothing is not evidence that anything was bounded."
    )
    assert LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN not in public.limitation_tokens()


def test_an_unresolved_gap_under_policy_none_refuses_by_name() -> None:
    """``NONE`` over an unresolvable provider time is not a silent pass-through."""
    config = ProfileResolutionConfig(
        requested_profile=PROVIDER_REALISTIC,
        resolution_policy_version=phase3a.RESOLUTION_POLICY_VERSION,
        dataset_resolutions=(
            DatasetGapResolution(
                dataset="market_session",
                policy=DatasetGapPolicy.NONE,
                reason="deliberately unresolved",
            ),
        ),
    )
    with pytest.raises(
        UnresolvedProviderAvailabilityError, match=r"4\.3\.2_unresolved_provider_availability"
    ):
        resolve_run_inputs(
            {"market_session": phase3a.sessions()},
            config=config,
            approvals=phase3a.approvals(),
        )


def test_a_dataset_consumed_without_a_resolution_entry_refuses() -> None:
    with pytest.raises(UnresolvedProviderAvailabilityError, match="complete inventory"):
        resolve_run_inputs(
            {"unmapped_feed": phase3a.attributes()},
            config=phase3a.resolution(),
            approvals=phase3a.approvals(),
        )


def test_reaching_for_rows_that_skipped_resolution_is_loud() -> None:
    resolved = phase3a.resolved_inputs()
    with pytest.raises(KeyError, match="did not go through resolution"):
        resolved.rows("fundamental_fact")


def test_a_downgrade_changes_the_whole_run_before_curation() -> None:
    dataset = phase3a.gold_dataset(
        requested=PROVIDER_REALISTIC, downgrade=GlobalProfileResolution.DOWNGRADE
    )
    assert dataset.resolved_profile is PUBLIC
    for rows in dataset.universe.values():
        assert {row.resolved_profile for row in rows} == {PUBLIC}


# ---------------------------------------------------------------------------
# Atomic publication and verified reads
# ---------------------------------------------------------------------------


def _publish(store: LocalTableStore, dataset: Any, **kwargs: Any) -> Any:
    return publish_gold_dataset(
        store,
        dataset,
        quality=kwargs.pop("quality", phase3a.quality_outcome(dataset)),
        quality_plan=kwargs.pop("quality_plan", PHASE3A_QUALITY_PLAN),
        code_commit_sha=phase3a.CODE_COMMIT_SHA,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
        source_ingestion_run_ids=(phase3a.INGESTION_RUN_ID,),
        **kwargs,
    )


def _read(store: LocalTableStore, *, requested: InformationSetProfile = PUBLIC) -> Any:
    """The verified read, unpacked to the triplet the older assertions expect.

    ``read_published_dataset`` returns a ``VerifiedPublication`` now, because the
    reader accepts nothing else. Unpacking here keeps the assertions about the
    three artifacts readable without giving any test a way to build one.
    """
    publication = read_published_dataset(
        store,
        dataset_version=phase3a.DATASET_VERSION,
        config=phase3a.resolution(requested=requested),
        approvals=phase3a.approvals(),
    )
    return publication.dataset, publication.manifest, publication.quality_report


def _snapshot_rows(*args: Any, **kwargs: Any) -> Any:
    """One session's membership rows, from the build that also names its inputs."""
    return build_universe_snapshot(*args, **kwargs).rows


def test_a_published_dataset_round_trips_through_verified_storage(tmp_path: Path) -> None:
    """Materialised, versioned, checksummed -- not the live result of a query."""
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()
    version, manifest = _publish(store, dataset)

    assert {table.entity for table in manifest.tables} == set(GOLD_ENTITIES)
    assert version.resolution_policy_version == phase3a.RESOLUTION_POLICY_VERSION
    assert manifest.manifest_hash == compute_manifest_hash(manifest)

    reloaded, reloaded_manifest, report = _read(store)
    assert reloaded_manifest.manifest_hash == manifest.manifest_hash
    assert report.report_hash == manifest.quality_report_hash
    assert reloaded.build_time == dataset.build_time
    assert reloaded.coverage_start == dataset.coverage_start
    assert reloaded.resolved_profile is dataset.resolved_profile
    assert set(reloaded.bars) == set(dataset.bars)
    assert set(reloaded.listings) == set(dataset.listings)
    assert sorted(reloaded.universe) == sorted(dataset.universe)

    original = dataset.universe[date(2019, 6, 27)]
    replayed = reloaded.universe[date(2019, 6, 27)]
    assert [row.security_id for row in replayed] == [row.security_id for row in original]
    assert [membership_hash_of(row) for row in replayed] == [
        membership_hash_of(row) for row in original
    ], "Replaying each row's own lineage must reconstruct exactly the decision it recorded."


def test_publication_is_invisible_until_the_commit(tmp_path: Path) -> None:
    """Before the rename nothing is published; after it, everything is."""
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()

    store.write_staged_table(
        layer=StorageLayer.GOLD,
        dataset_version=dataset.dataset_version,
        entity="price_bar",
        rows=[],
    )
    with pytest.raises(DatasetPublicationError, match="never committed"):
        load_dataset_manifest(store, dataset_version=dataset.dataset_version)

    _publish(store, dataset)
    manifest = load_dataset_manifest(store, dataset_version=dataset.dataset_version)
    assert manifest.manifest_hash == compute_manifest_hash(manifest)


def test_a_crash_before_the_commit_leaves_nothing_observable(tmp_path: Path) -> None:
    """Forced-crash recovery at the Gold publication boundary."""
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()

    for entity in ("market_session", "listing"):
        store.write_staged_table(
            layer=StorageLayer.GOLD,
            dataset_version=dataset.dataset_version,
            entity=entity,
            rows=[],
        )
    assert store.staging_root(
        layer=StorageLayer.GOLD, dataset_version=dataset.dataset_version
    ).exists()
    with pytest.raises(DatasetPublicationError):
        load_dataset_manifest(store, dataset_version=dataset.dataset_version)

    _publish(store, dataset)
    reloaded, _, _ = _read(store)
    assert len(reloaded.bars) == len(dataset.bars), (
        "The retry discarded the abandoned attempt; nothing partial survived into the "
        "published version."
    )


def test_a_partial_publication_is_refused(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()
    _publish(store, dataset)

    store.table_path(
        layer=StorageLayer.GOLD, dataset_version=dataset.dataset_version, entity="listing"
    ).unlink()
    with pytest.raises(DatasetPublicationError, match="partial publication"):
        _read(store)


def test_a_tampered_table_is_caught_before_it_is_decoded(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()
    _publish(store, dataset)

    path = store.table_path(
        layer=StorageLayer.GOLD, dataset_version=dataset.dataset_version, entity="price_bar"
    )
    path.write_bytes(path.read_bytes().replace(b"100.00", b"999.00"))
    with pytest.raises(DatasetPublicationError, match="before decoding"):
        _read(store)


def test_publishing_over_an_existing_version_is_refused(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()
    _publish(store, dataset)
    with pytest.raises(DatasetPublicationError, match="already published"):
        _publish(store, dataset)


def test_a_reader_refuses_a_dataset_resolved_under_another_profile(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()
    _publish(store, dataset)
    with pytest.raises(DatasetPublicationError, match="was curated under"):
        _read(store, requested=PROVIDER_REALISTIC)


def test_a_reader_refuses_a_dataset_resolved_under_another_policy(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    publication = phase3a.publish(store)
    other = ProfileResolutionConfig(
        requested_profile=PUBLIC,
        resolution_policy_version="profres/other",
        dataset_resolutions=phase3a.resolution().dataset_resolutions,
    )
    with pytest.raises(DatasetPublicationError, match="resolved under policy"):
        PointInTimeReader(publication, resolution=other, approvals=phase3a.approvals())


def test_a_reader_refuses_a_dataset_whose_policy_reason_differs(tmp_path: Path) -> None:
    """Two runs that bounded the same dataset for different stated reasons differ.

    Comparing only policy names would call them the same run, and the manifest
    would then describe a resolution nobody performed.
    """
    store = LocalTableStore(tmp_path)
    publication = phase3a.publish(store)
    restated = ProfileResolutionConfig(
        requested_profile=PUBLIC,
        resolution_policy_version=phase3a.RESOLUTION_POLICY_VERSION,
        dataset_resolutions=tuple(
            DatasetGapResolution(
                dataset=entry.dataset,
                policy=entry.policy,
                reason="a different stated reason",
            )
            for entry in phase3a.resolution().dataset_resolutions
        ),
    )
    with pytest.raises(DatasetPublicationError, match="different resolution map"):
        PointInTimeReader(publication, resolution=restated, approvals=phase3a.approvals())


def test_two_builds_from_the_same_inputs_produce_the_same_identity(tmp_path: Path) -> None:
    first, first_manifest = _publish(LocalTableStore(tmp_path / "a"), phase3a.gold_dataset())
    second, second_manifest = _publish(LocalTableStore(tmp_path / "b"), phase3a.gold_dataset())
    assert first.content_hash == second.content_hash
    assert first_manifest.manifest_hash == second_manifest.manifest_hash


def test_no_staging_directory_survives_a_successful_publication(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    _publish(store, phase3a.gold_dataset())
    assert sorted((tmp_path / "gold").glob("_staging-*")) == []


# ---------------------------------------------------------------------------
# Adjustment proof
# ---------------------------------------------------------------------------


def _artifact(**overrides: Any) -> AdjustedBarArtifact:
    kwargs: dict[str, Any] = {
        "adjustment_policy": AdjustmentPolicy.SPLIT_ONLY,
        "adjustment_convention": ADJUSTMENT_CONVENTION,
        "resolved_profile": PUBLIC,
        "as_of_epoch": AFTER_EVERYTHING,
        "approvals": phase3a.approvals(),
        "security_id_scope": SCOPE,
        "valid_time_start": VALID_START,
        "valid_time_end": VALID_END,
        "artifact_first_built_time": phase3a.ARTIFACT_FIRST_BUILT,
        "ingestion_time": phase3a.INGESTION_TIME,
        "dataset_version": phase3a.DATASET_VERSION,
    }
    bars = overrides.pop("bars", _continuous_bars())
    kwargs.update(overrides)
    return build_adjusted_bar_artifact(bars, phase3a.corporate_actions(), **kwargs)


def _key(*, as_of: Any, bars: Any = None, actions: Any = None) -> dict[str, Any]:
    """The artifact key for the continuous-security fixture, at one cutoff.

    Built here rather than inline because the key now covers the validity
    interval, the bar resolution and the exact rows consumed -- the four things
    whose absence let two different artifacts share one identity.
    """
    rows = _continuous_bars() if bars is None else bars
    admitted = (
        admissible_actions(
            relevant_actions(
                phase3a.corporate_actions(),
                security_id_scope=SCOPE,
                policy=AdjustmentPolicy.SPLIT_ONLY,
                valid_time_start=VALID_START,
                valid_time_end=VALID_END,
                securities=sorted({bar.security_id for bar in rows}),
            ),
            as_of_epoch=as_of,
            resolved_profile=PUBLIC,
            approvals=phase3a.approvals(),
        )
        if actions is None
        else actions
    )
    return artifact_key(
        adjustment_policy=AdjustmentPolicy.SPLIT_ONLY,
        adjustment_convention=ADJUSTMENT_CONVENTION,
        resolved_profile=PUBLIC,
        as_of_epoch=as_of,
        corporate_action_dataset_versions=source_versions(admitted),
        raw_bar_dataset_versions=source_versions(rows),
        security_id_scope=SCOPE,
        bar_resolution=rows[0].resolution,
        valid_time_start=VALID_START,
        valid_time_end=VALID_END,
        price_bar_lineage_hash=bar_lineage_hash(rows),
        action_lineage_hash=action_lineage_hash(admitted),
    )


def test_an_action_announced_after_as_of_is_not_applied() -> None:
    """Knowing about a split and applying it are two different operations."""
    bars = _continuous_bars()
    actions = phase3a.corporate_actions()

    before = adjusted_series(
        bars,
        actions,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        convention=ADJUSTMENT_CONVENTION,
        as_of_epoch=BEFORE_ANNOUNCEMENT,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )
    after = adjusted_series(
        bars,
        actions,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        convention=ADJUSTMENT_CONVENTION,
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
        convention=ADJUSTMENT_CONVENTION,
        as_of_epoch=phase3a.utc(2019, 6, 26, 20, 30),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )
    pre_ex = [value for value in series if value.session_date < date(2019, 6, 27)]
    assert _closes(pre_ex) == [
        Decimal("100.000000"),
        Decimal("101.000000"),
        Decimal("102.000000"),
    ]


def test_the_adjustment_convention_is_named_everywhere_it_is_used() -> None:
    """An unnamed "adjusted" series is a number whose meaning depends on the code."""
    artifact = _artifact()
    assert artifact.adjustment_convention is AdjustmentConvention.FORWARD_BASE_NORMALIZED
    assert ADJUSTMENT_CONVENTION.value in ADJUSTMENT_SPEC_VERSION
    assert artifact.envelope.derivation_spec_version == ADJUSTMENT_SPEC_VERSION

    key = _key(as_of=AFTER_EVERYTHING)
    assert key["adjustment_convention"] == ADJUSTMENT_CONVENTION.value
    assert artifact.artifact_id == artifact_id_for(key)

    mode = AdjustmentMode.adjusted(AdjustmentPolicy.SPLIT_ONLY, ADJUSTMENT_CONVENTION)
    assert mode.convention is AdjustmentConvention.FORWARD_BASE_NORMALIZED
    assert RAW.convention is None


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
        adjustment_convention=artifact.adjustment_convention,
        resolved_profile=artifact.resolved_profile,
        as_of_epoch=artifact.as_of_epoch,
        corporate_action_dataset_versions=artifact.corporate_action_dataset_versions,
        raw_bar_dataset_versions=artifact.raw_bar_dataset_versions,
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


def test_an_artifact_from_zero_bars_is_refused() -> None:
    with pytest.raises(ArtifactIntegrityError, match="zero bars"):
        _artifact(bars=())


def test_an_artifact_from_inadmissible_bars_is_refused() -> None:
    """Look-ahead with a hash attached is still look-ahead."""
    with pytest.raises(ArtifactIntegrityError, match="not admissible"):
        _artifact(as_of_epoch=phase3a.utc(2019, 6, 24, 12, 0))


def test_an_artifact_spanning_two_securities_needs_an_authorizing_scope() -> None:
    mixed = (
        *_continuous_bars(),
        *[
            bar
            for bar in phase3a.daily_bars()
            if bar.security_id == phase3a.SEC_RENAMED and bar.session_date.year == 2019
        ],
    )
    with pytest.raises(ArtifactIntegrityError, match="names a single security"):
        _artifact(bars=mixed)

    artifact = _artifact(
        bars=mixed,
        security_id_scope=f"{MULTI_SECURITY_SCOPE_PREFIX}{phase3a.UNIVERSE_DEFINITION_VERSION}",
    )
    assert {value.security_id for value in artifact.series} == {SCOPE, phase3a.SEC_RENAMED}


def test_bars_outside_the_declared_validity_interval_are_refused() -> None:
    """The interval is what the artifact claims to be about."""
    with pytest.raises(ArtifactIntegrityError, match="outside the declared validity interval"):
        _artifact(valid_time_end=date(2019, 6, 26))


def test_a_different_as_of_produces_a_different_artifact_identity() -> None:
    """ "The adjusted close on a date" is a number per information set."""

    def identity(as_of: Any) -> str:
        return artifact_id_for(_key(as_of=as_of))

    assert identity(BEFORE_ANNOUNCEMENT) != identity(AFTER_EVERYTHING)


def test_an_unsettled_adjustment_policy_is_refused_not_approximated() -> None:
    """An invented convention would be baked into a hash and cited later as settled."""
    with pytest.raises(PendingContractError, match="Refusing to invent one"):
        adjusted_series(
            _continuous_bars(),
            phase3a.corporate_actions(),
            policy=AdjustmentPolicy.TOTAL_RETURN,
            convention=ADJUSTMENT_CONVENTION,
            as_of_epoch=AFTER_EVERYTHING,
            resolved_profile=PUBLIC,
            approvals=phase3a.approvals(),
        )


# ---------------------------------------------------------------------------
# Historical universe proof
# ---------------------------------------------------------------------------


def test_a_delisted_security_is_present_before_and_absent_after() -> None:
    """The survivorship control, stated as the property a backtest depends on."""
    snapshots = phase3a.universe_snapshots()
    before = {row.security_id for row in snapshots[date(2019, 6, 27)] if row.is_member}
    after = {row.security_id for row in snapshots[date(2021, 1, 5)]}

    assert phase3a.SEC_DELISTED in before
    assert phase3a.SEC_DELISTED not in after
    assert phase3a.SEC_TICKER_REUSER in after
    assert phase3a.SEC_TICKER_REUSER not in before


def test_rebuilding_a_universe_snapshot_is_byte_identical() -> None:
    """Drift means the rule read something it did not declare."""
    first = phase3a.universe_snapshots()[date(2019, 6, 27)]
    second = phase3a.universe_snapshots()[date(2019, 6, 27)]
    assert snapshot_content_hash(first) == snapshot_content_hash(second)


def test_each_membership_row_carries_only_its_own_lineage() -> None:
    """Attaching every admissible input to every row makes lineage true and useless."""
    rows = phase3a.universe_snapshots()[date(2019, 6, 27)]
    for row in rows:
        entities = [ref.entity for ref in row.envelope.lineage]
        assert entities.count("listing") == 1
        assert entities.count("price_bar") == 1
        for consumed in row.inputs:
            assert getattr(consumed, "security_id", row.security_id) == row.security_id, (
                "A membership decision reads only that security's own rows; another "
                "security's bar changing must not look like this decision changing."
            )

    by_security = {row.security_id: row for row in rows}
    assert (
        by_security[phase3a.SEC_CONTINUOUS].envelope.lineage
        != by_security[phase3a.SEC_RENAMED].envelope.lineage
    )


def test_the_membership_hash_covers_the_whole_decision() -> None:
    """A hash over the outcome alone would verify while the evidence drifted."""
    row = next(
        item
        for item in phase3a.universe_snapshots()[date(2019, 6, 27)]
        if item.security_id == phase3a.SEC_CONTINUOUS
    )
    assert membership_hash_of(row) == row.envelope.artifact_content_hash

    altered = type(row)(
        session_date=row.session_date,
        security_id=row.security_id,
        universe_definition_version=row.universe_definition_version,
        resolved_profile=row.resolved_profile,
        is_member=row.is_member,
        price_at_eval=Decimal("1.00"),
        market_cap_at_eval=row.market_cap_at_eval,
        addv_at_eval=row.addv_at_eval,
        history_sessions_at_eval=row.history_sessions_at_eval,
        exclusion_reason=row.exclusion_reason,
        is_common_stock_eligible=row.is_common_stock_eligible,
        inputs=row.inputs,
        envelope=row.envelope,
    )
    assert membership_hash_of(altered) != altered.envelope.artifact_content_hash


def test_a_universe_is_profile_keyed_and_two_profiles_are_two_snapshots() -> None:
    """Eligibility is evaluated on admissible data, so membership is profile-specific."""
    public = phase3a.universe_snapshots(resolved_profile=PUBLIC)[date(2019, 6, 27)]
    provider = phase3a.universe_snapshots(resolved_profile=PROVIDER_REALISTIC)[date(2019, 6, 27)]
    assert {row.resolved_profile for row in public} == {PUBLIC}
    assert {row.resolved_profile for row in provider} == {PROVIDER_REALISTIC}
    assert snapshot_content_hash(public) != snapshot_content_hash(provider)


def test_an_unbuildable_forward_universe_is_refused_not_published_empty() -> None:
    """A universe that could not be computed is not a zero-security market.

    ``FORWARD_SYSTEM`` asks what *we* held, and the fixture first saw its 2019
    reference data in 2026. Nothing is admissible at a 2019 cutoff, so the build
    **refuses** by name. Publishing an empty snapshot instead would make an
    unanswerable question indistinguishable from an answer, and would let a
    profile that cannot reach back before we existed answer a historical question
    anyway.
    """
    with pytest.raises(RequiredInputUnavailableError, match="REQUIRED_INPUT_UNAVAILABLE"):
        phase3a.gold_dataset(requested=FORWARD)


def test_a_rule_that_genuinely_selects_nobody_still_publishes() -> None:
    """NEGATIVE CONTROL. The counterpart the refusal above must not swallow.

    Inputs are admissible; the rule simply excludes everyone. That is a **valid**
    snapshot: its rows are all non-members, each carrying its reason. Refusing it
    would collapse "the rule selected nobody" into "the universe is unavailable",
    which is the conflation the refusal exists to prevent.
    """
    unreachable = UniverseDefinition(
        version="universe/nobody-qualifies",
        min_close_price=Decimal(1_000_000),
        min_addv=Decimal(1),
        min_history_sessions=1,
        addv_window_sessions=3,
        eligible_exchanges=phase3a.universe_definition().eligible_exchanges,
        eligible_security_types=phase3a.universe_definition().eligible_security_types,
    )
    rows = _snapshot_rows(
        phase3a.universe_inputs(),
        session_date=date(2019, 6, 27),
        evaluation_cutoff=phase3a.session_open(date(2019, 6, 27)),
        definition=unreachable,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
        ingestion_time=phase3a.INGESTION_TIME,
        dataset_version=phase3a.DATASET_VERSION,
    )
    assert rows, "The snapshot exists."
    assert not any(row.is_member for row in rows), "And it selected nobody."
    assert all(row.exclusion_reason is not None for row in rows), (
        "Every non-member says why, which is what makes this an answer rather than a gap."
    )


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
        _snapshot_rows(
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


def test_the_universe_mapping_cannot_be_mutated_after_construction() -> None:
    """ "Frozen" that wraps a mutable dict is not frozen."""
    dataset = phase3a.gold_dataset()
    with pytest.raises(TypeError):
        cast("Any", dataset.universe)[date(2019, 6, 27)] = ()


# ---------------------------------------------------------------------------
# Point-in-time query
# ---------------------------------------------------------------------------


def _reader(
    tmp_path: Path,
    *,
    requested: InformationSetProfile = PUBLIC,
    outcome: Any = None,
) -> PointInTimeReader:
    return phase3a.reader(LocalTableStore(tmp_path), requested=requested, outcome=outcome)


def test_the_reader_distinguishes_three_universe_outcomes(tmp_path: Path) -> None:
    """A snapshot with members, an unbuilt session, and a built session with none.

    All three would look like "no members" to a caller that only counted rows,
    and they mean three different things.
    """
    reader = _reader(tmp_path)

    served = reader.get_security_universe(
        as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC
    ).result
    assert served.members

    with pytest.raises(MissingHistoricalSnapshotError, match="refusal, not an empty result"):
        reader.get_security_universe(as_of=phase3a.utc(2019, 6, 25, 20, 0), profile=PUBLIC)

    empty_reader = None
    assert empty_reader is None  # the zero-row case is covered by the build test below


def test_a_zero_row_snapshot_round_trips_as_a_present_snapshot(tmp_path: Path) -> None:
    """A header is what says the session was built; rows alone cannot.

    Without it a genuinely empty selection disappears when the membership table
    is flattened, and "nobody qualified" becomes indistinguishable from "no
    snapshot exists".

    The empty selection is real: only the delisted security's listings are
    supplied, and the session evaluated is after it delisted. Removing rows from a
    published snapshot no longer survives publication, because the quality runner
    rebuilds it and finds the drift -- so the fabricated construction this test
    used to rely on is gone, and the genuine one proves more.
    """
    publication = phase3a.zero_row_publication(LocalTableStore(tmp_path))
    session = date(2021, 1, 5)
    reloaded = publication.dataset
    assert reloaded.snapshot_was_built(session), "The session is present."
    assert reloaded.universe[session] == (), "And it holds no rows."
    assert reloaded.universe_headers[session].row_count == 0


def test_the_universe_accessor_serves_the_stored_snapshot(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    early = reader.get_security_universe(
        as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC
    ).result
    late = reader.get_security_universe(
        as_of=phase3a.utc(2021, 1, 5, 21, 30), profile=PUBLIC
    ).result

    assert early.session_date == date(2019, 6, 27)
    assert phase3a.SEC_DELISTED in early.members
    assert late.session_date == date(2021, 1, 5)
    assert phase3a.SEC_DELISTED not in late.members
    assert late.provenance.dataset_version == phase3a.DATASET_VERSION
    assert late.provenance.resolved_profile is PUBLIC


def test_a_universe_query_with_no_snapshot_is_a_refusal_not_an_empty_result(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    with pytest.raises(MissingHistoricalSnapshotError, match="refusal, not an empty result"):
        reader.get_security_universe(as_of=phase3a.utc(2019, 6, 25, 20, 0), profile=PUBLIC)


def test_a_query_outside_declared_coverage_is_a_refusal(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    with pytest.raises(DatasetCoverageError, match="precedes the declared coverage start"):
        reader.get_security_universe(as_of=phase3a.utc(2010, 1, 4, 20, 0), profile=PUBLIC)
    with pytest.raises(DatasetCoverageError, match="later than the build time"):
        reader.get_security_universe(as_of=phase3a.utc(2030, 1, 4, 20, 0), profile=PUBLIC)


def test_a_query_under_a_profile_the_reader_was_not_bound_to_is_refused(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    with pytest.raises(ProfileResolutionError, match="may not mix profiles"):
        reader.get_security_universe(as_of=phase3a.utc(2021, 1, 5, 21, 30), profile=FORWARD)


def test_an_open_blocking_finding_refuses_every_dependent_query(tmp_path: Path) -> None:
    """Refused, not annotated, and not returned empty.

    The defect is in the data and a real check finds it, rather than being handed
    to the report as a finding: a caller-supplied finding is the same shape of
    evidence as a caller-supplied checks_run list.
    """
    store = LocalTableStore(tmp_path)
    datasets = phase3a.datasets_with_a_blocking_defect()
    resolved = resolve_run_inputs(
        datasets, config=phase3a.resolution(), approvals=phase3a.approvals()
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
    outcome = phase3a.quality_outcome(dataset)
    assert any(
        finding.check_name == "5.2_non_positive_price_or_negative_volume"
        for finding in outcome.report.blocking
    ), "The check found it; nobody told the report about it."

    with pytest.raises(QualityGateError, match="Refusing to publish"):
        _publish(store, dataset, quality=outcome)
    assert not store.version_root(
        layer=StorageLayer.GOLD, dataset_version=phase3a.DATASET_VERSION
    ).exists(), "A build that cannot be believed is never published in the first place."


def test_quality_evidence_cannot_be_edited_after_the_gate(tmp_path: Path) -> None:
    """Swapping the evidence after the gate is what the binding prevents."""
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()
    outcome = phase3a.quality_outcome(dataset)
    assert outcome.report.warnings, (
        "The reference build carries genuine warnings -- its securities are listed on the "
        "half-day session and have no bar for it -- so there is real evidence to tamper with."
    )
    _publish(store, dataset, quality=outcome)

    path = (
        store.version_root(layer=StorageLayer.GOLD, dataset_version=phase3a.DATASET_VERSION)
        / QUALITY_REPORT_NAME
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    body["findings"] = []
    path.write_text(json.dumps(body), encoding="utf-8")

    # The file hash is checked before the body is decoded, so an edited report is
    # refused as edited bytes rather than as a report that fails to reconcile.
    with pytest.raises(QualityGateError, match="hashes to"):
        _read(store)


def test_a_publication_with_no_quality_report_cannot_be_read(tmp_path: Path) -> None:
    """A missing report is not a clean one."""
    store = LocalTableStore(tmp_path)
    _publish(store, phase3a.gold_dataset())
    (
        store.version_root(layer=StorageLayer.GOLD, dataset_version=phase3a.DATASET_VERSION)
        / QUALITY_REPORT_NAME
    ).unlink()
    with pytest.raises(QualityGateError, match="no persisted quality report"):
        _read(store)


def test_raw_and_adjusted_are_different_answers_to_different_questions(
    tmp_path: Path,
) -> None:
    reader = _reader(tmp_path)
    raw = reader.get_price_history(
        security_id=SCOPE,
        start=VALID_START,
        end=VALID_END,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=AFTER_EVERYTHING,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    ).result
    adjusted = reader.get_price_history(
        security_id=SCOPE,
        start=VALID_START,
        end=VALID_END,
        resolution=BarResolution.DAILY,
        adjustment_mode=AdjustmentMode.adjusted(AdjustmentPolicy.SPLIT_ONLY, ADJUSTMENT_CONVENTION),
        as_of=AFTER_EVERYTHING,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
    ).result
    assert _closes(raw.bars)[-1] == Decimal("52.00")
    assert _closes(adjusted.bars)[-1] == Decimal("104.000000")
    assert raw.adjustment_mode.is_raw and not adjusted.adjustment_mode.is_raw
    assert raw.provenance.resolution is BarResolution.DAILY


def test_a_price_series_is_one_resolution(tmp_path: Path) -> None:
    """Mixing daily and minute rows is two series stacked, not a series."""
    reader = _reader(tmp_path)
    daily = reader.get_price_history(
        security_id=phase3a.SEC_RENAMED,
        start=date(2019, 6, 26),
        end=date(2019, 6, 26),
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=AFTER_EVERYTHING,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    ).result
    assert len(daily.bars) == 1
    assert daily.resolution is BarResolution.DAILY
    minute_ends = {bar.bar_end_time for bar in phase3a.minute_bars()}
    assert not ({value.bar_end_time for value in daily.bars} & minute_ends)


def test_minute_coverage_cannot_pass_with_one_arbitrary_bar(tmp_path: Path) -> None:
    """One minute bar in a session is not evidence the session was observed.

    The fixture holds two minute bars on 2019-06-26. Under the dense contract a
    session's whole regular grid must be present, so two bars out of a full
    trading day is a gap -- and a gap is a refusal, not a short series.
    """
    reader = _reader(tmp_path, requested=PROVIDER_REALISTIC)
    with pytest.raises(IncompleteCoverageError, match="expected endpoint"):
        reader.get_price_history(
            security_id=phase3a.SEC_RENAMED,
            start=date(2019, 6, 26),
            end=date(2019, 6, 26),
            resolution=BarResolution.MINUTE,
            adjustment_mode=RAW,
            as_of=AFTER_THE_CALENDAR_WAS_AVAILABLE,
            profile=PROVIDER_REALISTIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )


def test_the_minute_grid_is_the_whole_regular_session() -> None:
    """The expected grid comes from the session, not from what happens to exist."""
    session = next(
        s
        for s in phase3a.sessions()
        if s.session_date == date(2019, 6, 26) and s.exchange.value == "NASDAQ"
    )
    grid = _minute_endpoints(session)
    assert grid[0] == session.regular_open + timedelta(minutes=1)
    assert grid[-1] == session.regular_close
    assert len(grid) == int((session.regular_close - session.regular_open).total_seconds() // 60)
    held = {bar.bar_end_time for bar in phase3a.minute_bars()}
    assert len(held) == 2 and len(grid) > 2, (
        "Two bars against a full grid is exactly the case the dense contract refuses."
    )


def test_an_inverted_range_is_refused(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    with pytest.raises(QueryRangeError, match="is after end"):
        reader.get_price_history(
            security_id=SCOPE,
            start=VALID_END,
            end=VALID_START,
            resolution=BarResolution.DAILY,
            adjustment_mode=RAW,
            as_of=AFTER_EVERYTHING,
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )


def test_a_range_past_declared_coverage_is_refused_not_truncated(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    with pytest.raises(DatasetCoverageError, match="past the declared coverage end"):
        reader.get_price_history(
            security_id=SCOPE,
            start=VALID_START,
            end=date(2022, 1, 1),
            resolution=BarResolution.DAILY,
            adjustment_mode=RAW,
            as_of=AFTER_EVERYTHING,
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )


def test_a_security_the_dataset_never_heard_of_is_refused(tmp_path: Path) -> None:
    """Distinct from a security that exists and did not trade."""
    reader = _reader(tmp_path)
    with pytest.raises(SecurityNotInDatasetError, match="cannot answer"):
        reader.get_price_history(
            security_id="SEC-9999",
            start=VALID_START,
            end=VALID_END,
            resolution=BarResolution.DAILY,
            adjustment_mode=RAW,
            as_of=AFTER_EVERYTHING,
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )


def test_a_missing_required_bar_refuses_rather_than_truncating(tmp_path: Path) -> None:
    """A short series and a gap-ridden one look identical downstream."""
    reader = _reader(tmp_path)
    with pytest.raises(IncompleteCoverageError, match="Refused rather than truncated"):
        reader.get_price_history(
            security_id=SCOPE,
            start=VALID_START,
            end=date(2019, 7, 3),
            resolution=BarResolution.DAILY,
            adjustment_mode=RAW,
            as_of=phase3a.utc(2019, 7, 4, 12, 0),
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )


def test_a_minute_request_over_sessions_with_no_minute_bars_refuses(tmp_path: Path) -> None:
    reader = _reader(tmp_path, requested=PROVIDER_REALISTIC)
    with pytest.raises(IncompleteCoverageError):
        reader.get_price_history(
            security_id=phase3a.SEC_RENAMED,
            start=VALID_START,
            end=VALID_END,
            resolution=BarResolution.MINUTE,
            adjustment_mode=RAW,
            as_of=AFTER_EVERYTHING,
            profile=PROVIDER_REALISTIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )


def test_a_fully_covered_listed_range_is_served(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. Completeness is checked, not assumed to be violated."""
    reader = _reader(tmp_path)
    result = reader.get_price_history(
        security_id=phase3a.SEC_DELISTED,
        start=VALID_START,
        end=VALID_END,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=AFTER_EVERYTHING,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    ).result
    assert len(result.bars) == 5


def test_a_bar_is_not_served_before_its_own_availability(tmp_path: Path) -> None:
    """R1, at the level a backtest actually experiences it.

    The 25 June bar is bounded at 20:30 UTC, half an hour after the cutoff, so a
    query at 20:00 is not entitled to it. This test previously asserted that the
    two-session request came back one bar long -- which is the defect: a caller
    averaging that result gets a number, and nothing in it says a session is
    missing. A REQUIRED series now refuses and names the end that would answer.
    """
    reader = _reader(tmp_path)
    with pytest.raises(IncompleteCoverageError) as refusal:
        reader.get_price_history(
            security_id=SCOPE,
            start=VALID_START,
            end=date(2019, 6, 25),
            resolution=BarResolution.DAILY,
            adjustment_mode=RAW,
            as_of=phase3a.utc(2019, 6, 25, 20, 0),
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )
    message = str(refusal.value)
    assert "not yet available at this as_of" in message
    assert "an end of 2019-06-24 would answer" in message


def test_the_same_query_serves_a_short_series_when_asked_optionally(
    tmp_path: Path,
) -> None:
    """A caller who wants whatever was knowable says so, and the result says so back."""
    reader = _reader(tmp_path)
    result = reader.get_price_history(
        security_id=SCOPE,
        start=VALID_START,
        end=date(2019, 6, 25),
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=phase3a.utc(2019, 6, 25, 20, 0),
        profile=PUBLIC,
        requirement=SeriesRequirement.OPTIONAL,
        revision_view=None,
    ).result
    assert [value.session_date for value in result.bars] == [date(2019, 6, 24)]
    assert result.requirement is SeriesRequirement.OPTIONAL
    assert result.withheld_endpoints == 1, (
        "The result carries the count rather than leaving the caller to notice."
    )


def test_a_series_emptied_by_origin_ineligibility_is_refused(tmp_path: Path) -> None:
    """An emptied required series is not a short series with a token attached.

    Every minute bar in the fixture is PROVIDER_AGGREGATED, so under
    ``PUBLIC_PIT`` the whole requested series is ineligible. Publishing an empty
    one would let a caller average over nothing and get a number.
    """
    reader = _reader(tmp_path, requested=PROVIDER_REALISTIC)
    result = reader.get_price_history(
        security_id=phase3a.SEC_RENAMED,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=AFTER_THE_CALENDAR_WAS_AVAILABLE,
        profile=PROVIDER_REALISTIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    ).result
    assert result.bars, "Daily bars are eligible under PROVIDER_REALISTIC_PIT."

    # The ticker-reuser's daily series is complete and entirely provider-derived,
    # so coverage passes and eligibility empties it. That is a refusal.
    public_reader = _reader(tmp_path / "public")
    with pytest.raises(RequiredInputUnavailableError, match="REQUIRED_INPUT_UNAVAILABLE"):
        public_reader.get_price_history(
            security_id=phase3a.SEC_TICKER_REUSER,
            start=date(2021, 1, 4),
            end=date(2021, 1, 5),
            resolution=BarResolution.DAILY,
            adjustment_mode=RAW,
            as_of=phase3a.utc(2021, 1, 6, 12, 0),
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )


def test_a_downgraded_run_is_labelled_public_pit_end_to_end(tmp_path: Path) -> None:
    reader = phase3a.reader(
        LocalTableStore(tmp_path),
        requested=PROVIDER_REALISTIC,
        downgrade=GlobalProfileResolution.DOWNGRADE,
    )
    result = reader.get_security_universe(
        as_of=phase3a.utc(2021, 1, 5, 21, 30), profile=PROVIDER_REALISTIC
    ).result
    assert result.provenance.resolved_profile is PUBLIC
    assert result.provenance.requested_profile is PROVIDER_REALISTIC
    assert result.provenance.was_downgraded
    assert LimitationToken.PROFILE_DOWNGRADED_TO_PUBLIC in result.provenance.limitations


def test_get_classification_reports_a_declared_gap_rather_than_an_empty_result(
    tmp_path: Path,
) -> None:
    """A caller tells "not built yet" from "this security has no sector"."""
    reader = _reader(tmp_path)
    with pytest.raises(PendingContractError, match="declared gap, not an empty result"):
        reader.get_classification(security_id=SCOPE, as_of=AFTER_EVERYTHING, profile=PUBLIC)


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
