"""Snapshot-header lineage and adjusted-artifact source identity.

Two artifacts whose evidence pointed at the right things without being held to
them. The snapshot header named the listing states it considered only when no
membership row had lineage of its own -- so the evidence for "this security was
looked at and did not qualify" appeared exactly when nothing qualified, and
vanished the moment one other security did. The adjusted artifact took its source
dataset versions from the caller as two scalars, so an exact lineage spanning two
immutable builds was keyed to one of them and nothing checked which.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.entities import CorporateAction, Listing, PriceBar
from kalpamani.data.contracts.errors import (
    ArtifactIntegrityError,
    DatasetPublicationError,
    RequiredInputUnavailableError,
)
from kalpamani.data.contracts.vocabulary import (
    AdjustmentPolicy,
    BarResolution,
    InformationSetProfile,
    ListingFactKind,
)
from kalpamani.data.curate.adjustment import (
    ADJUSTMENT_CONVENTION,
    adjusted_series,
    build_adjusted_bar_artifact,
    relevant_actions,
    source_versions,
    verify_adjusted_bar_artifact,
)
from kalpamani.data.curate.publication import publish_gold_dataset
from kalpamani.data.curate.universe import build_snapshot_header, current_listings
from kalpamani.data.quality.plan import PHASE3A_QUALITY_PLAN
from kalpamani.data.storage import LocalTableStore

PUBLIC = InformationSetProfile.PUBLIC_PIT
SPLIT_EX_DATE = date(2019, 6, 27)
SECURITY = phase3a.SEC_CONTINUOUS


# ---------------------------------------------------------------------------
# 8 -- the header's lineage is the whole build
# ---------------------------------------------------------------------------


def _header(tmp_path: Path, session: date = date(2019, 6, 27)) -> Any:
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    return publication.dataset.universe_headers[session]


def test_a_snapshot_header_names_every_listing_state_it_considered(
    tmp_path: Path,
) -> None:
    """Including the ones that produced no membership row.

    The 2021 snapshot is the case: the delisted security is considered, found
    unlisted, and produces nothing. Its listing is evidence for that finding, and
    a header that named it only when *nothing* qualified would drop it here.
    """
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    dataset = publication.dataset
    session = date(2021, 1, 5)
    header = dataset.universe_headers[session]

    considered = {
        listing.listing_id
        for listing in current_listings(dataset.listings)
        if listing.listing_fact_kind is ListingFactKind.STATE
    }
    named = {
        dict(ref.selector)["listing_id"]
        for ref in header.envelope.lineage
        if ref.entity == "listing"
    }
    assert considered <= named, (
        f"Considered {sorted(considered)}; the header names {sorted(named)}. A security the "
        "rule examined and excluded is part of what the snapshot decided."
    )
    assert dataset.universe[session], "And this snapshot does have rows, which is the point."


def test_a_post_delisting_snapshot_still_names_the_ended_listing(tmp_path: Path) -> None:
    """The delisted security is the evidence that it was looked at and had gone."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    header = publication.dataset.universe_headers[date(2021, 1, 5)]
    named = {
        dict(ref.selector)["listing_id"]
        for ref in header.envelope.lineage
        if ref.entity == "listing"
    }
    delisted = {
        listing.listing_id
        for listing in phase3a.listings()
        if listing.security_id == phase3a.SEC_DELISTED
    }
    assert delisted & named, "Its listing state is named among the considered evidence."


def test_removing_one_considered_listing_changes_the_header_identity(
    tmp_path: Path,
) -> None:
    """Otherwise the considered set would be a list nobody could check."""
    header = _header(tmp_path)
    trimmed = dataclasses.replace(
        header,
        envelope=dataclasses.replace(
            header.envelope,
            lineage=tuple(ref for ref in header.envelope.lineage if ref.entity != "listing")[:1]
            or header.envelope.lineage[:1],
        ),
    )
    assert trimmed.header_identity_hash != header.header_identity_hash


def test_the_header_records_what_each_required_domain_supplied(tmp_path: Path) -> None:
    """A zero-row snapshot is only interpretable beside what the rule had to work with."""
    header = _header(tmp_path)
    coverage = dict(
        (name, (supplied, admissible))
        for name, supplied, admissible in header.required_domain_coverage
    )
    assert set(coverage) == {"listing", "price_bar", "security_attribute"}
    for name, (supplied, admissible) in coverage.items():
        assert supplied >= admissible >= 0, name
        assert admissible > 0, f"{name} had admissible rows, or the build would have refused."


#: Every route through the normal path to a membership row that disagrees with
#: its header is caught earlier -- the quality runner's rebuild check refuses the
#: publication, and a stored row edited afterwards fails its own content hash. The
#: row-agreement checks are therefore defence against a snapshot assembled or
#: restored by something other than this builder, and they are exercised directly
#: because nothing else can reach them.


def _verify_pair(row: Any, header: Any) -> None:
    from kalpamani.data.curate.publication import _verify_one_header

    _verify_one_header(
        header.session_date,
        dataclasses.replace(
            header,
            row_count=1,
            snapshot_content_hash=_membership_hash([row]),
            envelope=dataclasses.replace(
                header.envelope, artifact_content_hash=_membership_hash([row])
            ),
        ),
        [row],
        _manifest_for(),
        listings=phase3a.listings(),
        attributes=phase3a.attributes(),
        bars=phase3a.bars(),
        approvals=phase3a.approvals(),
    )


def _manifest_for() -> Any:
    from kalpamani.data.contracts.vocabulary import GlobalProfileResolution, StorageLayer
    from kalpamani.data.curate.publication import DatasetManifest

    return DatasetManifest(
        publication_format_version=3,
        dataset_version=phase3a.DATASET_VERSION,
        layer=StorageLayer.GOLD,
        build_time=phase3a.BUILD_TIME,
        coverage_start=phase3a.COVERAGE_START,
        coverage_end=phase3a.COVERAGE_END,
        resolved_profile=PUBLIC,
        requested_profile=PUBLIC,
        global_profile_resolution=GlobalProfileResolution.NONE,
        resolution_policy_version=phase3a.RESOLUTION_POLICY_VERSION,
        resolution_map=(),
        resolution_evidence=(),
        resolution_receipt_hash="",
        quality_report_hash="",
        quality_report_file_hash="",
        quality_plan_version=PHASE3A_QUALITY_PLAN.plan_version,
        quality_context_hash="",
        tables=(),
        source_ingestion_run_ids=(),
        code_commit_sha=phase3a.CODE_COMMIT_SHA,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
        manifest_hash="",
    )


def _reference_pair(tmp_path: Path) -> tuple[Any, Any]:
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    session = date(2019, 6, 27)
    return (
        publication.dataset.universe[session][0],
        publication.dataset.universe_headers[session],
    )


def test_a_matching_row_and_header_verify(tmp_path: Path) -> None:
    """NEGATIVE CONTROL for the three refusals below."""
    row, header = _reference_pair(tmp_path)
    _verify_pair(row, header)


def test_a_row_dated_to_another_session_refuses(tmp_path: Path) -> None:
    """A snapshot is one session's decisions."""
    row, header = _reference_pair(tmp_path)
    with pytest.raises(DatasetPublicationError, match="is dated"):
        _verify_pair(dataclasses.replace(row, session_date=date(2019, 6, 28)), header)


def test_a_row_keyed_to_another_definition_version_refuses(tmp_path: Path) -> None:
    """Changing the rule creates a new version; it does not change history."""
    row, header = _reference_pair(tmp_path)
    with pytest.raises(DatasetPublicationError, match="universe definition"):
        _verify_pair(
            dataclasses.replace(row, universe_definition_version="universe/other.9"), header
        )


def test_a_row_keyed_to_another_profile_refuses(tmp_path: Path) -> None:
    """Eligibility is evaluated on admissible data, so membership is profile-specific."""
    row, header = _reference_pair(tmp_path)
    with pytest.raises(DatasetPublicationError, match="is keyed"):
        _verify_pair(
            dataclasses.replace(row, resolved_profile=InformationSetProfile.FORWARD_SYSTEM),
            header,
        )


def test_the_quality_runner_catches_a_tampered_row_before_publication(
    tmp_path: Path,
) -> None:
    """Which is why the checks above cannot be reached through the normal path.

    The rebuild check recomputes the snapshot from the same inputs, so a row
    altered after the build no longer matches what the rule produces -- and that
    refuses the publication rather than the read.
    """
    from kalpamani.data.contracts.errors import QualityGateError

    dataset = phase3a.gold_dataset()
    session = date(2019, 6, 27)
    rows = list(dataset.universe[session])
    rows[0] = dataclasses.replace(rows[0], is_member=not rows[0].is_member)
    header = dataset.universe_headers[session]
    tampered = _rebuild(
        dataset,
        universe={**dataset.universe, session: tuple(rows)},
        universe_headers={
            **dataset.universe_headers,
            session: dataclasses.replace(
                header,
                snapshot_content_hash=_membership_hash(rows),
                envelope=dataclasses.replace(
                    header.envelope, artifact_content_hash=_membership_hash(rows)
                ),
            ),
        },
    )
    with pytest.raises(QualityGateError, match=r"6\.5_universe_rebuild_drift"):
        publish_gold_dataset(
            LocalTableStore(tmp_path),
            tampered,
            quality=phase3a.quality_outcome(tampered),
            quality_plan=PHASE3A_QUALITY_PLAN,
            code_commit_sha=phase3a.CODE_COMMIT_SHA,
            lag_policy_version=phase3a.LAG_POLICY_VERSION,
            universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
        )


def _membership_hash(rows: Any) -> str:
    from kalpamani.data.contracts.canonical import content_hash
    from kalpamani.data.curate.universe import membership_hash_of

    return content_hash(sorted(membership_hash_of(row) for row in rows))


def _rebuild(dataset: Any, **overrides: Any) -> Any:
    base = {
        "dataset_version": dataset.dataset_version,
        "build_time": dataset.build_time,
        "coverage_start": dataset.coverage_start,
        "coverage_end": dataset.coverage_end,
        "resolved_profile": dataset.resolved_profile,
        "resolution_policy_version": dataset.resolution_policy_version,
        "resolution_receipt": dataset.resolution_receipt,
        "resolution_evidence": dataset.resolution_evidence,
        "sessions": dataset.sessions,
        "listings": dataset.listings,
        "attributes": dataset.attributes,
        "tickers": dataset.tickers,
        "bars": dataset.bars,
        "actions": dataset.actions,
        "universe": dataset.universe,
        "universe_headers": dataset.universe_headers,
    }
    base.update(overrides)
    return type(dataset)(**base)


def test_a_header_lineage_naming_a_wrong_source_version_is_refused(
    tmp_path: Path,
) -> None:
    """Now caught at publication, by rebuilding the header rather than the rows.

    The read still replays the header's lineage, but it no longer gets the chance:
    comparing only membership content left everything else in the header
    unchecked, and rebuilding the whole identity means a misdirected lineage is a
    drift the quality gate refuses.
    """
    from kalpamani.data.contracts.errors import QualityGateError

    dataset = phase3a.gold_dataset()
    session = date(2019, 6, 27)
    header = dataset.universe_headers[session]
    misdirected = dataclasses.replace(
        header,
        envelope=dataclasses.replace(
            header.envelope,
            lineage=tuple(
                dataclasses.replace(ref, dataset_version="gold/never-published.1")
                if ref.entity == "listing"
                else ref
                for ref in header.envelope.lineage
            ),
        ),
    )
    tampered = _rebuild(
        dataset, universe_headers={**dataset.universe_headers, session: misdirected}
    )
    with pytest.raises(QualityGateError, match=r"6\.5_universe_rebuild_drift"):
        publish_gold_dataset(
            LocalTableStore(tmp_path),
            tampered,
            quality=phase3a.quality_outcome(tampered),
            quality_plan=PHASE3A_QUALITY_PLAN,
            code_commit_sha=phase3a.CODE_COMMIT_SHA,
            lag_policy_version=phase3a.LAG_POLICY_VERSION,
            universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
        )


def test_the_same_thresholds_under_one_version_must_rebuild(tmp_path: Path) -> None:
    """A version string is a promise that two builds used one rule.

    Nothing checked it, so the same ``universe/synthetic.a1`` with a different
    minimum price produced a different membership set under an identical label --
    and the header, which recorded only the version, said they agreed.
    """
    from kalpamani.data.curate.universe import definition_hash

    original = phase3a.universe_definition()
    restated = dataclasses.replace(original, min_close_price=original.min_close_price + 1)
    assert restated.version == original.version
    assert definition_hash(restated) != definition_hash(original)


def test_a_header_with_no_listing_evidence_at_all_is_refused() -> None:
    """ "We saw no listing states" is not the same finding as "nobody was listed"."""
    with pytest.raises(RequiredInputUnavailableError, match="REQUIRED_INPUT_UNAVAILABLE"):
        build_snapshot_header(
            (),
            session_date=date(2019, 6, 27),
            definition=phase3a.universe_definition(),
            resolved_profile=PUBLIC,
            evaluation_cutoff=phase3a.session_open(date(2019, 6, 27)),
            considered_listings=(),
            artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
            ingestion_time=phase3a.INGESTION_TIME,
            dataset_version=phase3a.DATASET_VERSION,
        )


# ---------------------------------------------------------------------------
# 9 -- the adjusted artifact's source identity comes from its rows
# ---------------------------------------------------------------------------


def _bars(start: date, end: date) -> tuple[PriceBar, ...]:
    return tuple(
        bar
        for bar in phase3a.daily_bars()
        if bar.security_id == SECURITY and start <= bar.session_date <= end
    )


def _artifact(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "adjustment_policy": AdjustmentPolicy.SPLIT_ONLY,
        "adjustment_convention": ADJUSTMENT_CONVENTION,
        "resolved_profile": PUBLIC,
        "as_of_epoch": phase3a.utc(2019, 7, 1, 12, 0),
        "approvals": phase3a.approvals(),
        "security_id_scope": SECURITY,
        "valid_time_start": date(2019, 6, 24),
        "valid_time_end": date(2019, 6, 28),
        "artifact_first_built_time": phase3a.ARTIFACT_FIRST_BUILT,
        "ingestion_time": phase3a.INGESTION_TIME,
        "dataset_version": phase3a.DATASET_VERSION,
    }
    bars = overrides.pop("bars", None)
    kwargs.update(overrides)
    rows = bars if bars is not None else _bars(kwargs["valid_time_start"], kwargs["valid_time_end"])
    return build_adjusted_bar_artifact(rows, phase3a.corporate_actions(), **kwargs)


def test_the_source_versions_are_derived_from_the_rows() -> None:
    """A caller-supplied version entered the key unverified."""
    artifact = _artifact()
    assert artifact.raw_bar_dataset_versions == (phase3a.BAR_DATASET_VERSION,)
    assert artifact.corporate_action_dataset_versions == (phase3a.ACTION_DATASET_VERSION,)


def test_multi_version_bar_lineage_produces_a_canonical_version_tuple() -> None:
    """An exact lineage spanning two immutable builds is true of both."""
    rows = _bars(date(2019, 6, 24), date(2019, 6, 28))
    split = tuple(
        dataclasses.replace(
            bar, envelope=dataclasses.replace(bar.envelope, dataset_version="gold/second.2")
        )
        if bar.session_date >= date(2019, 6, 27)
        else bar
        for bar in rows
    )
    artifact = _artifact(bars=split)
    assert artifact.raw_bar_dataset_versions == (
        "gold/second.2",
        phase3a.BAR_DATASET_VERSION,
    ), "Sorted, deduplicated, and true of every build the bars came from."
    assert source_versions(split) == artifact.raw_bar_dataset_versions


def test_a_false_source_version_cannot_enter_the_artifact_identity() -> None:
    """Claiming a build the artifact did not read is refused.

    The recomputed key is built from the rows the lineage resolves to, so a false
    claim on the artifact would otherwise be *ignored* rather than refused -- and
    the claim is what a later result cites.
    """
    artifact = _artifact()
    forged = dataclasses.replace(artifact, raw_bar_dataset_versions=("gold/never-read.9",))
    with pytest.raises(ArtifactIntegrityError, match="claims source versions"):
        verify_adjusted_bar_artifact(
            forged,
            _bars(date(2019, 6, 24), date(2019, 6, 28)),
            phase3a.corporate_actions(),
            approvals=phase3a.approvals(),
        )


def test_the_same_action_id_in_two_versions_resolves_the_named_one() -> None:
    """A corrected ratio in a later build shares the action_id."""
    actions = phase3a.corporate_actions()
    corrected = tuple(
        dataclasses.replace(
            action,
            ratio=None if action.ratio is None else action.ratio + Decimal(1),
            envelope=dataclasses.replace(action.envelope, dataset_version="gold/corrected.2"),
        )
        for action in actions
    )
    artifact = _artifact()
    # Both revisions are offered; the lineage names the original's version.
    verify_adjusted_bar_artifact(
        artifact,
        _bars(date(2019, 6, 24), date(2019, 6, 28)),
        (*actions, *corrected),
        approvals=phase3a.approvals(),
    )


def test_an_action_present_only_in_another_version_is_refused() -> None:
    """Matching on action_id alone found whichever copy was last in the mapping."""
    corrected = tuple(
        dataclasses.replace(
            action,
            envelope=dataclasses.replace(action.envelope, dataset_version="gold/corrected.2"),
        )
        for action in phase3a.corporate_actions()
    )
    artifact = _artifact()
    if not any(ref.entity == "corporate_action" for ref in artifact.envelope.lineage):
        pytest.skip("This interval consumes no corporate action.")
    with pytest.raises(ArtifactIntegrityError, match="in dataset version"):
        verify_adjusted_bar_artifact(
            artifact,
            _bars(date(2019, 6, 24), date(2019, 6, 28)),
            corrected,
            approvals=phase3a.approvals(),
        )


# -- the interval boundary --------------------------------------------------


def test_a_split_on_the_first_day_of_the_interval_affects_the_first_bar() -> None:
    """The convention applies a factor on or after the ex-date, so the first bar scales.

    Excluding it left the artifact's numbers and its lineage agreeing with each
    other while both contradicted the convention the artifact is labelled with.
    """
    kept = relevant_actions(
        phase3a.corporate_actions(),
        security_id_scope=SECURITY,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=SPLIT_EX_DATE,
        valid_time_end=date(2019, 6, 28),
        securities=[SECURITY],
    )
    assert [action.ex_date for action in kept] == [SPLIT_EX_DATE], (
        "The action whose ex-date is the interval's first day is inside the interval."
    )

    bars = _bars(SPLIT_EX_DATE, date(2019, 6, 28))
    series = adjusted_series(
        bars,
        kept,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        convention=ADJUSTMENT_CONVENTION,
        as_of_epoch=phase3a.utc(2019, 7, 1, 12, 0),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )
    raw = {bar.session_date: bar.close for bar in bars}
    adjusted = {value.session_date: value.close for value in series}
    assert adjusted[SPLIT_EX_DATE] != raw[SPLIT_EX_DATE], (
        "The first bar is scaled, because the split takes effect on that very session."
    )


def test_an_action_before_the_interval_is_still_relevant() -> None:
    """Under a fixed-base convention it scales every bar the interval holds.

    This asserted the opposite, and the opposite was a real inconsistency: the
    reader applied an earlier split and a materialised artifact over the same bars
    did not, so one bar was 104.00 through one path and 52.00 through the other.
    ``FORWARD_BASE_NORMALIZED`` expresses every bar in the original base, so a
    bar's adjusted value is a property of the bar and the actions -- not of the
    interval a caller happened to ask for.
    """
    kept = relevant_actions(
        phase3a.corporate_actions(),
        security_id_scope=SECURITY,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=date(2019, 6, 28),
        valid_time_end=date(2019, 7, 3),
        securities=[SECURITY],
    )
    assert [action.ex_date for action in kept] == [SPLIT_EX_DATE], (
        "The 27 June split is before the interval and still scales every bar in it."
    )


def test_both_adjustment_paths_agree_over_the_same_bars() -> None:
    """On-demand and materialised are one convention or they are two answers."""
    bars = _bars(date(2019, 6, 28), date(2019, 7, 3))
    as_of = phase3a.utc(2019, 7, 10, 12, 0)
    on_demand = adjusted_series(
        bars,
        phase3a.corporate_actions(),
        policy=AdjustmentPolicy.SPLIT_ONLY,
        convention=ADJUSTMENT_CONVENTION,
        as_of_epoch=as_of,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )
    materialised = adjusted_series(
        bars,
        relevant_actions(
            phase3a.corporate_actions(),
            security_id_scope=SECURITY,
            policy=AdjustmentPolicy.SPLIT_ONLY,
            valid_time_start=date(2019, 6, 28),
            valid_time_end=date(2019, 7, 3),
            securities=[SECURITY],
        ),
        policy=AdjustmentPolicy.SPLIT_ONLY,
        convention=ADJUSTMENT_CONVENTION,
        as_of_epoch=as_of,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )
    assert [value.close for value in on_demand] == [value.close for value in materialised]


def test_one_bar_has_one_adjusted_value_through_two_intervals() -> None:
    """Which is what makes the convention worth its name."""
    as_of = phase3a.utc(2019, 7, 10, 12, 0)

    def closes(start: date, end: date) -> dict[date, object]:
        bars = _bars(start, end)
        kept = relevant_actions(
            phase3a.corporate_actions(),
            security_id_scope=SECURITY,
            policy=AdjustmentPolicy.SPLIT_ONLY,
            valid_time_start=start,
            valid_time_end=end,
            securities=[SECURITY],
        )
        series = adjusted_series(
            bars,
            kept,
            policy=AdjustmentPolicy.SPLIT_ONLY,
            convention=ADJUSTMENT_CONVENTION,
            as_of_epoch=as_of,
            resolved_profile=PUBLIC,
            approvals=phase3a.approvals(),
        )
        return {value.session_date: value.close for value in series}

    wide = closes(date(2019, 6, 24), date(2019, 6, 28))
    narrow = closes(date(2019, 6, 28), date(2019, 6, 28))
    assert wide[date(2019, 6, 28)] == narrow[date(2019, 6, 28)]


def test_equivalent_instants_produce_one_artifact_id() -> None:
    """A cutoff written in another offset is the same cutoff."""
    from datetime import timedelta, timezone

    utc_epoch = phase3a.utc(2019, 7, 1, 12, 0)
    same = utc_epoch.astimezone(timezone(timedelta(hours=-5)))
    assert utc_epoch == same and utc_epoch.isoformat() != same.isoformat()
    assert _artifact(as_of_epoch=utc_epoch).artifact_id == (_artifact(as_of_epoch=same).artifact_id)


def test_an_action_after_the_interval_is_excluded() -> None:
    """It adjusts none of the interval's bars."""
    kept = relevant_actions(
        phase3a.corporate_actions(),
        security_id_scope=SECURITY,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=date(2019, 6, 24),
        valid_time_end=date(2019, 6, 26),
        securities=[SECURITY],
    )
    assert kept == (), "The 27 June ex-date is after this interval closes."


def test_an_artifact_over_the_boundary_interval_verifies() -> None:
    """NEGATIVE CONTROL. The corrected boundary still round-trips."""
    artifact = _artifact(valid_time_start=SPLIT_EX_DATE, valid_time_end=date(2019, 6, 28))
    verify_adjusted_bar_artifact(
        artifact,
        _bars(SPLIT_EX_DATE, date(2019, 6, 28)),
        phase3a.corporate_actions(),
        approvals=phase3a.approvals(),
    )
    assert any(ref.entity == "corporate_action" for ref in artifact.envelope.lineage), (
        "And the action it applied is named in its lineage."
    )


def test_the_boundary_interval_is_a_different_artifact_from_the_wider_one() -> None:
    """Different interval, different rows, different action set -- different key."""
    wide = _artifact()
    narrow = _artifact(valid_time_start=SPLIT_EX_DATE, valid_time_end=date(2019, 6, 28))
    assert wide.artifact_id != narrow.artifact_id


# -- keeping the unused imports honest ---------------------------------------


def test_the_fixture_action_is_a_split_with_the_expected_ex_date() -> None:
    """The boundary tests above rest on this, so it is asserted rather than assumed."""
    splits = [
        action
        for action in phase3a.corporate_actions()
        if isinstance(action, CorporateAction)
        and action.security_id == SECURITY
        and action.ex_date == SPLIT_EX_DATE
    ]
    assert splits, "The continuously listed security splits on 27 June 2019."


def test_every_fixture_listing_is_a_listing() -> None:
    """Guards the isinstance narrowing the header tests rely on."""
    assert all(isinstance(row, Listing) for row in phase3a.listings())
    assert all(isinstance(bar, PriceBar) for bar in phase3a.daily_bars())
    assert BarResolution.DAILY is phase3a.daily_bars()[0].resolution


# ---------------------------------------------------------------------------
# Adversarial review of this round's own closures
# ---------------------------------------------------------------------------


def test_an_unsettled_policy_refuses_in_the_documented_way() -> None:
    """A bare KeyError reads like a bug in this module rather than a decision."""
    from kalpamani.data.contracts.errors import PendingContractError

    with pytest.raises(PendingContractError, match="not settled by the merged Phase-3 plan"):
        relevant_actions(
            phase3a.corporate_actions(),
            security_id_scope=SECURITY,
            policy=AdjustmentPolicy.TOTAL_RETURN,
            valid_time_start=date(2019, 6, 24),
            valid_time_end=date(2019, 6, 28),
            securities=[SECURITY],
        )


def test_a_split_with_no_ratio_is_not_an_input() -> None:
    """It adjusts nothing, and would push the artifact's availability later anyway."""
    split = next(
        action
        for action in phase3a.corporate_actions()
        if action.security_id == SECURITY and action.ex_date == SPLIT_EX_DATE
    )
    phantom = dataclasses.replace(
        split,
        action_id="CA-PHANTOM",
        ratio=None,
        envelope=dataclasses.replace(split.envelope, source_id="action:CA-PHANTOM"),
    )
    kept = relevant_actions(
        (*phase3a.corporate_actions(), phantom),
        security_id_scope=SECURITY,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=date(2019, 6, 24),
        valid_time_end=date(2019, 6, 28),
        securities=[SECURITY],
    )
    assert "CA-PHANTOM" not in {action.action_id for action in kept}


def test_two_actions_with_different_ratios_are_two_artifacts() -> None:
    """Hashing the id and version alone let a cache return other prices."""
    from kalpamani.data.curate.adjustment import action_lineage_hash

    split = next(
        action
        for action in phase3a.corporate_actions()
        if action.security_id == SECURITY and action.ex_date == SPLIT_EX_DATE
    )
    restated = dataclasses.replace(split, ratio=Decimal(3))
    assert action_lineage_hash([split]) != action_lineage_hash([restated])


def test_two_different_actions_sharing_a_key_refuse_verification() -> None:
    """Otherwise list order decides which one an artifact verified against."""
    artifact = _artifact(valid_time_start=SPLIT_EX_DATE, valid_time_end=date(2019, 6, 28))
    actions = phase3a.corporate_actions()
    conflicting = tuple(
        dataclasses.replace(action, ratio=Decimal(9)) if action.ex_date == SPLIT_EX_DATE else action
        for action in actions
    )
    with pytest.raises(ArtifactIntegrityError, match="share"):
        verify_adjusted_bar_artifact(
            artifact,
            _bars(SPLIT_EX_DATE, date(2019, 6, 28)),
            (*actions, *conflicting),
            approvals=phase3a.approvals(),
        )


def _exact_lineage(header: Any, rows: Any) -> Any:
    from kalpamani.data.curate.publication import _require_header_lineage_is_exact

    return _require_header_lineage_is_exact(
        header.session_date,
        header,
        rows,
        listings=phase3a.listings(),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )


def test_a_header_omitting_an_input_its_rows_consumed_is_refused(tmp_path: Path) -> None:
    """Replaying proves the named rows exist, not that they are the right rows."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    session = date(2019, 6, 27)
    header = publication.dataset.universe_headers[session]
    rows = publication.dataset.universe[session]
    _exact_lineage(header, rows)

    stripped = dataclasses.replace(
        header,
        envelope=dataclasses.replace(header.envelope, lineage=header.envelope.lineage[:1]),
    )
    with pytest.raises(DatasetPublicationError, match="does not name"):
        _exact_lineage(stripped, rows)


def test_a_header_naming_an_announcement_is_refused(tmp_path: Path) -> None:
    """The rule considers listing states; an announcement is not one.

    Recomputed rather than pattern-matched: the read derives the governed set the
    builder would have produced and requires equality, so an announcement is
    refused for the reason it is wrong -- the rule never weighed it -- rather than
    because its selector happened to carry a recognisable kind.
    """
    from kalpamani.data.contracts.envelope import LineageRef
    from kalpamani.data.curate.lineage import listing_selector

    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    session = date(2019, 6, 27)
    header = publication.dataset.universe_headers[session]
    announcement = next(
        row for row in phase3a.listings() if row.listing_fact_kind is not ListingFactKind.STATE
    )
    widened = dataclasses.replace(
        header,
        envelope=dataclasses.replace(
            header.envelope,
            lineage=(
                *header.envelope.lineage,
                LineageRef.of(
                    entity="listing",
                    dataset_version=announcement.envelope.dataset_version,
                    selector=listing_selector(announcement),
                ),
            ),
        ),
    )
    with pytest.raises(DatasetPublicationError, match="could not have considered"):
        _exact_lineage(widened, publication.dataset.universe[session])


def test_a_header_omitting_a_considered_listing_is_refused(tmp_path: Path) -> None:
    """A security examined and excluded is part of what the snapshot decided.

    Recomputing the header hash afterwards does not help: the governed set is
    re-derived from the published listings and the snapshot's own cutoff, so the
    omission is visible whatever the header says about itself.
    """
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    session = date(2021, 1, 5)
    header = publication.dataset.universe_headers[session]
    rows = publication.dataset.universe[session]

    # A listing the rule considered that produced no membership row -- the exact
    # evidence a superset check could never miss, because nothing else names it.
    from_rows = {ref for row in rows for ref in row.envelope.lineage}
    non_member_refs = [
        ref for ref in header.envelope.lineage if ref.entity == "listing" and ref not in from_rows
    ]
    assert non_member_refs, "The 2021 snapshot considers a security that qualified for nothing."
    dropped = dataclasses.replace(
        header,
        envelope=dataclasses.replace(
            header.envelope,
            lineage=tuple(ref for ref in header.envelope.lineage if ref != non_member_refs[0]),
        ),
    )
    with pytest.raises(DatasetPublicationError, match="omits listing rows the rule did"):
        _exact_lineage(dropped, rows)
