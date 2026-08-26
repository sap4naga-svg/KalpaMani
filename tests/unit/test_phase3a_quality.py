"""Deterministic quality checks, proven against adversarial fixtures.

Each fixture here is constructed to *produce* look-ahead, an ambiguous join or a
silent substitution if the guarantee it targets is broken. The negative controls
are marked, and they matter as much as the positives: a check that over-blocks is
not "safe", it is a check somebody will switch off.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.entities import PriceBar, SecurityAttribute, UniverseMembership
from kalpamani.data.contracts.envelope import FactAnchor, SourceEnvelope
from kalpamani.data.contracts.serde import encode_price_bar, encode_universe_membership
from kalpamani.data.contracts.vocabulary import (
    AnnouncementBoundDerivation,
    BarConstruction,
    BarResolution,
    InformationOrigin,
    InformationSetProfile,
    ProviderBoundDerivation,
    ProviderTimeDerivation,
    PublicBoundDerivation,
    PublicTimeDerivation,
)
from kalpamani.data.quality.checks import (
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

pytestmark = pytest.mark.unit

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER_REALISTIC = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

T0 = datetime(2020, 3, 2, 14, 0, tzinfo=UTC)
SEEN = datetime(2020, 3, 5, 9, 0, tzinfo=UTC)
INGESTED = datetime(2020, 3, 5, 9, 30, tzinfo=UTC)


def _attribute(envelope: SourceEnvelope) -> SecurityAttribute:
    return SecurityAttribute(
        security_id="SEC-TEST",
        attribute="security_type",
        valid_from=date(2020, 1, 1),
        value="COMMON_STOCK",
        envelope=envelope,
    )


def _envelope(**overrides: object) -> SourceEnvelope:
    base: dict[str, object] = {
        "information_origin": InformationOrigin.AUTHORITATIVE_PUBLIC,
        "public_available_time": T0,
        "public_time_derivation": PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP,
        "system_first_seen_time": SEEN,
        "anchor": FactAnchor.sampled_state(T0),
        "source_id": "test",
        "ingestion_time": INGESTED,
        "dataset_version": "gold/test",
    }
    base.update(overrides)
    return SourceEnvelope(**base)  # type: ignore[arg-type]


def _names(findings: tuple[object, ...]) -> set[str]:
    return {getattr(f, "check_name", "") for f in findings}


# ---------------------------------------------------------------------------
# Envelope conformance
# ---------------------------------------------------------------------------


def test_a_well_formed_source_fact_produces_no_findings() -> None:
    """NEGATIVE CONTROL. Passing without lineage is not a defect."""
    assert check_envelope(_attribute(_envelope()), approvals=phase3a.approvals()) == ()


def test_a_well_formed_derived_artifact_produces_no_findings() -> None:
    """NEGATIVE CONTROL N14. Three false BLOCKINGs used to fire here."""
    artifact = phase3a.securities()[0]
    assert check_envelope(artifact, approvals=phase3a.approvals()) == ()


def test_a_public_fact_with_no_resolvable_public_time_is_blocking() -> None:
    record = _attribute(
        _envelope(
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
        )
    )
    findings = check_envelope(record, approvals=phase3a.approvals())
    assert "4.0A.1_public_fact_without_resolvable_public_time" in _names(findings)
    assert all(f.is_blocking for f in findings)


def test_a_proprietary_fact_carrying_public_timing_is_blocking() -> None:
    record = _attribute(
        _envelope(
            information_origin=InformationOrigin.PROVIDER_DERIVED,
            public_available_time=T0,
            provider_available_time=T0,
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
        )
    )
    assert "4.0A.2_proprietary_fact_carrying_public_timing" in _names(
        check_envelope(record, approvals=phase3a.approvals())
    )


def test_a_system_observed_row_carrying_a_provider_bound_is_blocking() -> None:
    """Bounding a provider time that does not exist invents one."""
    record = _attribute(
        _envelope(
            information_origin=InformationOrigin.SYSTEM_OBSERVED,
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
            provider_available_upper_bound=SEEN,
            provider_bound_derivation=ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND,
            provider_time_derivation=ProviderTimeDerivation.NOT_APPLICABLE,
        )
    )
    assert "4.0A.4_system_observed_carrying_vendor_timing" in _names(
        check_envelope(record, approvals=phase3a.approvals())
    )


def test_an_approximation_written_into_an_exact_field_is_blocking() -> None:
    """Approximations live in bound fields, always."""
    record = _attribute(
        _envelope(
            public_available_time=T0,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
        )
    )
    assert "4.0A.7_approximation_written_into_exact_field" in _names(
        check_envelope(record, approvals=phase3a.approvals())
    )


def test_an_exact_time_later_than_its_own_upper_bound_is_blocking() -> None:
    """A bound that precedes the time it bounds is not a bound."""
    record = _attribute(
        _envelope(
            public_available_time=T0,
            public_available_upper_bound=T0 - timedelta(hours=1),
            public_bound_derivation=PublicBoundDerivation.DATE_PLUS_LAG,
        )
    )
    assert "4.0A.8_bound_precedes_the_exact_time_it_bounds" in _names(
        check_envelope(record, approvals=phase3a.approvals())
    )


def test_an_unapproved_bound_relied_upon_is_blocking() -> None:
    record = _attribute(
        _envelope(
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
            public_available_upper_bound=T0,
            public_bound_derivation=PublicBoundDerivation.FIRST_SEEN_UPPER_BOUND,
        )
    )
    names = _names(check_envelope(record, approvals=phase3a.approvals()))
    assert "4.0A.9_unapproved_public_bound" in names


def test_not_applicable_on_a_public_fact_disagrees_with_its_origin() -> None:
    """``NOT_APPLICABLE`` and ``UNKNOWN`` are opposites, and never conflated."""
    record = _attribute(
        _envelope(
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
            public_available_upper_bound=T0,
            public_bound_derivation=PublicBoundDerivation.DATE_PLUS_LAG,
        )
    )
    assert "4.0A.10_derivation_disagrees_with_origin" in _names(
        check_envelope(record, approvals=phase3a.approvals())
    )


def test_a_declared_class_with_no_usable_anchor_is_blocking() -> None:
    """There is nothing for the class invariant to check against."""
    record = _attribute(_envelope(anchor=FactAnchor.announced_forward()))
    assert "4.0A.11_class_without_a_resolved_fact_anchor" in _names(
        check_envelope(record, approvals=phase3a.approvals())
    )


def test_a_date_only_announcement_with_an_approved_bound_passes() -> None:
    """NEGATIVE CONTROL N15. The row an over-blocking check would have rejected."""
    action = next(a for a in phase3a.corporate_actions() if a.action_id == "CA-0002")
    assert action.envelope.anchor.announcement_time is None
    assert action.envelope.anchor.announcement_bound_derivation is (
        AnnouncementBoundDerivation.DATE_PLUS_LAG
    )
    assert check_envelope(action, approvals=phase3a.approvals()) == ()


def test_stored_rows_are_checked_for_a_mixed_envelope() -> None:
    """Reachable where the constructors are not: an older writer, a hand edit."""
    row = dict(encode_price_bar(phase3a.daily_bars()[0])["envelope"])
    row["lineage"] = [{"entity": "x"}]
    findings = check_stored_envelope_shape(row, dataset="price_bar")
    assert "4.0_mixed_source_and_derived_envelope" in _names(findings)


def test_stored_rows_are_checked_for_a_derived_artifact_carrying_source_timing() -> None:
    row = {
        "information_origin": InformationOrigin.DERIVED_ARTIFACT.value,
        "system_first_seen_time": SEEN.isoformat(),
        "lineage": [{"entity": "price_bar"}],
        "artifact_first_built_time": T0.isoformat(),
        "derivation_spec_version": "spec/1",
        "artifact_content_hash": "sha256:x",
    }
    assert "4.0B.1_derived_artifact_carrying_source_timing" in _names(
        check_stored_envelope_shape(row, dataset="universe_membership")
    )


def test_a_stored_origin_outside_the_vocabulary_is_blocking() -> None:
    findings = check_stored_envelope_shape(
        {"information_origin": "PROBABLY_PUBLIC"}, dataset="price_bar"
    )
    assert "4.0.0_origin_outside_the_closed_vocabulary" in _names(findings)


# ---------------------------------------------------------------------------
# Temporal invariants
# ---------------------------------------------------------------------------


def test_a_row_held_before_it_was_public_is_blocking() -> None:
    record = _attribute(_envelope(system_first_seen_time=T0 - timedelta(days=1)))
    assert "4.1.1_held_before_public" in _names(
        check_temporal_invariants(record, resolved_profile=PUBLIC, approvals=phase3a.approvals())
    )


def test_a_row_written_before_it_was_first_seen_is_blocking() -> None:
    record = _attribute(_envelope(ingestion_time=SEEN - timedelta(hours=1)))
    assert "4.1.3_row_written_before_first_seen" in _names(
        check_temporal_invariants(record, resolved_profile=PUBLIC, approvals=phase3a.approvals())
    )


def test_a_provider_ahead_of_public_for_the_same_fact_is_blocking() -> None:
    record = _attribute(
        _envelope(
            provider_available_time=T0 - timedelta(hours=1),
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
        )
    )
    assert "4.1.4_provider_ahead_of_public_for_the_same_fact" in _names(
        check_temporal_invariants(record, resolved_profile=PUBLIC, approvals=phase3a.approvals())
    )


def test_a_sampled_state_available_before_it_was_sampled_is_blocking() -> None:
    """The check an anchor bound to the public time silently disabled."""
    record = _attribute(
        _envelope(
            information_origin=InformationOrigin.PROVIDER_DERIVED,
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
            provider_available_time=T0,
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
            anchor=FactAnchor.sampled_state(T0 + timedelta(hours=2)),
        )
    )
    names = _names(
        check_temporal_invariants(
            record, resolved_profile=PROVIDER_REALISTIC, approvals=phase3a.approvals()
        )
    )
    assert "4.1_sampled_state_available_before_it_happened" in names


def test_an_announced_forward_fact_effective_far_later_is_not_a_violation() -> None:
    """NEGATIVE CONTROL N1-N4. That gap is the entire class."""
    for action in phase3a.corporate_actions():
        findings = check_temporal_invariants(
            action, resolved_profile=PUBLIC, approvals=phase3a.approvals()
        )
        assert findings == (), f"{action.action_id} produced {_names(findings)}"
    for session in phase3a.sessions():
        assert (
            check_temporal_invariants(
                session, resolved_profile=PUBLIC, approvals=phase3a.approvals()
            )
            == ()
        )


def test_the_whole_reference_dataset_is_temporally_clean() -> None:
    """Every fixture row that is meant to pass, passes."""
    approvals = phase3a.approvals()
    for record in (
        *phase3a.daily_bars(),
        *phase3a.minute_bars(),
        *phase3a.listings(),
        *phase3a.attributes(),
        *phase3a.ticker_history(),
    ):
        findings = check_temporal_invariants(record, resolved_profile=FORWARD, approvals=approvals)
        assert findings == (), f"{record.envelope.source_id}: {_names(findings)}"


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


def _session_map() -> dict[datetime, date]:
    out: dict[datetime, date] = {}
    for bar in phase3a.bars():
        out[bar.bar_end_time] = bar.session_date
    return out


def test_the_reference_bars_pass_the_market_data_checks() -> None:
    """NEGATIVE CONTROL. Including the two splits, which the actions explain."""
    findings = check_price_bars(
        phase3a.bars(),
        session_dates_by_instant=_session_map(),
        actions=phase3a.corporate_actions(),
    )
    blocking = [f for f in findings if f.is_blocking]
    assert blocking == [], _names(tuple(blocking))


def test_a_split_with_no_action_explaining_it_is_blocking() -> None:
    """An unadjusted split looks exactly like a -50% return."""
    findings = check_price_bars(
        phase3a.bars(),
        session_dates_by_instant=_session_map(),
        actions=(),
    )
    assert "5.5_split_discontinuity" in _names(findings)


def test_impossible_ohlc_is_blocking() -> None:
    template = phase3a.daily_bars()[0]
    broken = PriceBar(
        security_id=template.security_id,
        resolution=template.resolution,
        bar_end_time=template.bar_end_time,
        bar_start_time=template.bar_start_time,
        session_date=template.session_date,
        open=Decimal("10"),
        high=Decimal("5"),
        low=Decimal("8"),
        close=Decimal("9"),
        volume=1,
        curation_source=template.curation_source,
        bar_construction=template.bar_construction,
        envelope=template.envelope,
    )
    findings = check_price_bars((broken,), session_dates_by_instant=_session_map())
    assert "5.1_impossible_ohlc" in _names(findings)


def test_a_non_positive_price_is_blocking() -> None:
    template = phase3a.daily_bars()[0]
    broken = PriceBar(
        security_id=template.security_id,
        resolution=template.resolution,
        bar_end_time=template.bar_end_time,
        bar_start_time=template.bar_start_time,
        session_date=template.session_date,
        open=Decimal(0),
        high=Decimal(0),
        low=Decimal(0),
        close=Decimal(0),
        volume=-1,
        curation_source=template.curation_source,
        bar_construction=template.bar_construction,
        envelope=template.envelope,
    )
    assert "5.2_non_positive_price_or_negative_volume" in _names(
        check_price_bars((broken,), session_dates_by_instant=_session_map())
    )


def test_a_duplicate_bar_key_is_blocking() -> None:
    bar = phase3a.daily_bars()[0]
    assert "3.1_duplicate_price_bar_key" in _names(
        check_price_bars((bar, bar), session_dates_by_instant=_session_map())
    )


def test_a_session_date_truncated_from_a_utc_timestamp_is_blocking() -> None:
    """A 20:00 ET print belongs to that session and to the NEXT UTC day.

    The adversarial bar ends at midnight UTC on 25 June -- inside the 24 June
    extended session -- and carries the truncated UTC date as its session key.
    """
    template = phase3a.daily_bars()[0]
    end = datetime(2019, 6, 25, 0, 0, tzinfo=UTC)
    truncated = PriceBar(
        security_id=template.security_id,
        resolution=BarResolution.MINUTE,
        bar_end_time=end,
        bar_start_time=end - timedelta(minutes=1),
        session_date=date(2019, 6, 25),
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=100,
        curation_source="adversarial",
        bar_construction=BarConstruction.OFFICIAL_DISSEMINATED,
        envelope=template.envelope,
    )
    findings = check_price_bars((truncated,), session_dates_by_instant={end: date(2019, 6, 24)})
    assert "4.1.12_session_date_derived_by_utc_truncation" in _names(findings)

    corrected = PriceBar(
        security_id=truncated.security_id,
        resolution=truncated.resolution,
        bar_end_time=end,
        bar_start_time=truncated.bar_start_time,
        session_date=date(2019, 6, 24),
        open=truncated.open,
        high=truncated.high,
        low=truncated.low,
        close=truncated.close,
        volume=truncated.volume,
        curation_source=truncated.curation_source,
        bar_construction=truncated.bar_construction,
        envelope=truncated.envelope,
    )
    assert "4.1.12_session_date_derived_by_utc_truncation" not in _names(
        check_price_bars((corrected,), session_dates_by_instant={end: date(2019, 6, 24)})
    )


def test_a_missing_bar_in_a_listed_range_is_a_warning_not_a_block() -> None:
    """NEGATIVE CONTROL N6. A gap is worth looking at; it does not invalidate research."""
    findings = check_price_bars(
        phase3a.daily_bars(),
        session_dates_by_instant=_session_map(),
        actions=phase3a.corporate_actions(),
        expected_sessions=(date(2019, 7, 3),),
    )
    missing = [f for f in findings if f.check_name == "5.4_missing_bar_in_a_listed_range"]
    assert missing
    assert not any(f.is_blocking for f in missing)


# ---------------------------------------------------------------------------
# Identity and universe
# ---------------------------------------------------------------------------


def test_a_recycled_ticker_is_accepted() -> None:
    """NEGATIVE CONTROL. Tickers are reused; only an overlap is a defect."""
    assert check_ticker_history(phase3a.ticker_history()) == ()


def test_a_ticker_overlapping_two_securities_is_blocking() -> None:
    """An overlap makes every join on that ticker ambiguous."""
    findings = check_ticker_history(phase3a.overlapping_ticker_history())
    assert "6.1_ticker_history_overlap" in _names(findings)


def test_the_reference_universe_snapshots_pass() -> None:
    """NEGATIVE CONTROL. Correctly built history is not flagged."""
    findings = check_universe_snapshots(
        phase3a.universe_snapshots(),
        listings=phase3a.listings(),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        evaluation_cutoffs=phase3a.evaluation_cutoffs(),
    )
    assert findings == (), _names(findings)


def test_a_universe_rebuilt_from_current_listings_is_refused() -> None:
    """The survivorship smoke alarm.

    The adversarial snapshot keeps only members that still exist today -- exactly
    what filtering a current listing query produces. If a historical snapshot
    contains no company that has since disappeared, the data is not historical,
    whatever the vendor calls it.
    """
    ever_delisted = {
        listing.security_id for listing in phase3a.listings() if listing.listing_end is not None
    }
    survivors = {
        listing.security_id
        for listing in phase3a.listings()
        if listing.security_id not in ever_delisted
    }
    assert survivors == {phase3a.SEC_CONTINUOUS, phase3a.SEC_TICKER_REUSER}
    reconstructed: dict[date, tuple[UniverseMembership, ...]] = {
        session: tuple(row for row in rows if row.security_id in survivors)
        for session, rows in phase3a.universe_snapshots().items()
    }
    findings = check_universe_snapshots(
        reconstructed,
        listings=phase3a.listings(),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        evaluation_cutoffs=phase3a.evaluation_cutoffs(),
    )
    assert "6.3_survivorship_leakage" in _names(findings)


def test_a_membership_keyed_to_the_wrong_profile_is_blocking() -> None:
    findings = check_universe_snapshots(
        phase3a.universe_snapshots(resolved_profile=PUBLIC),
        listings=phase3a.listings(),
        resolved_profile=FORWARD,
        approvals=phase3a.approvals(),
        evaluation_cutoffs=phase3a.evaluation_cutoffs(),
    )
    assert "6.8_profile_free_or_mismatched_universe" in _names(findings)


def test_eligibility_evaluated_from_inadmissible_data_is_blocking() -> None:
    """The check that exists because this mistake is invisible afterwards."""
    snapshots = phase3a.universe_snapshots()
    impossible_cutoffs = {session: phase3a.utc(2015, 1, 1) for session in snapshots}
    findings = check_universe_snapshots(
        snapshots,
        listings=phase3a.listings(),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        evaluation_cutoffs=impossible_cutoffs,
    )
    assert "6.6_eligibility_from_inadmissible_data" in _names(findings)


def test_a_universe_rebuild_that_drifts_is_blocking() -> None:
    assert check_universe_rebuild("sha256:a", "sha256:a") == ()
    assert "6.5_universe_rebuild_drift" in _names(check_universe_rebuild("sha256:a", "sha256:b"))


# ---------------------------------------------------------------------------
# Profile service
# ---------------------------------------------------------------------------


def test_serving_an_ineligible_row_is_blocking() -> None:
    findings = check_profile_service(
        phase3a.minute_bars(),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        config=phase3a.resolution(),
        as_of=phase3a.utc(2026, 1, 1),
    )
    assert "4.3.5_ineligible_row_served" in _names(findings)


def test_public_timing_substituted_for_absent_provider_timing_is_blocking() -> None:
    """The withdrawn ``DECLARE`` behaviour, caught by name."""
    record = _attribute(_envelope(provider_available_time=None))
    findings = check_profile_service(
        (record,),
        resolved_profile=PROVIDER_REALISTIC,
        approvals=phase3a.approvals(),
        config=phase3a.resolution(requested=PROVIDER_REALISTIC),
        as_of=phase3a.utc(2026, 1, 1),
    )
    names = _names(findings)
    assert "4.3.3_public_timing_substituted_for_absent_provider_timing" in names
    assert "4.3.2_unresolved_provider_availability" in names


def test_a_genuine_max_equal_to_public_is_not_the_withdrawn_behaviour() -> None:
    """NEGATIVE CONTROL N12. 4.3.3 forbids substitution, not a real equality."""
    record = _attribute(
        _envelope(
            provider_available_time=T0,
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
        )
    )
    findings = check_profile_service(
        (record,),
        resolved_profile=PROVIDER_REALISTIC,
        approvals=phase3a.approvals(),
        config=phase3a.resolution(requested=PROVIDER_REALISTIC),
        as_of=phase3a.utc(2026, 1, 1),
    )
    names = _names(findings)
    assert "4.3.3_public_timing_substituted_for_absent_provider_timing" not in names


def test_a_row_admitted_before_its_governing_time_is_blocking() -> None:
    """A backfill may not become available before the cutoff that governs it."""
    action = next(a for a in phase3a.corporate_actions() if a.action_id == "CA-0001")
    findings = check_profile_service(
        (action,),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        config=phase3a.resolution(),
        as_of=phase3a.utc(2019, 6, 24, 20, 0),
    )
    assert "4.3.9_backfill_admitted_too_early" in _names(findings)


def test_a_dataset_absent_from_the_resolution_map_is_blocking() -> None:
    record = _attribute(_envelope())
    findings = check_profile_service(
        (record,),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        config=phase3a.resolution(),
        as_of=phase3a.utc(2026, 1, 1),
    )
    assert "4.3.12_dataset_absent_from_the_resolution_map" not in _names(findings), (
        "security_attribute IS in the fixture's map, so this must not fire."
    )

    orphan = SecurityAttribute(
        dataset="unmapped_feed",
        security_id="SEC-TEST",
        attribute="security_type",
        valid_from=date(2020, 1, 1),
        value="COMMON_STOCK",
        envelope=_envelope(),
    )
    assert "4.3.12_dataset_absent_from_the_resolution_map" in _names(
        check_profile_service(
            (orphan,),
            resolved_profile=PUBLIC,
            approvals=phase3a.approvals(),
            config=phase3a.resolution(),
            as_of=phase3a.utc(2026, 1, 1),
        )
    )


def test_the_resolution_map_must_enter_run_identity() -> None:
    config = phase3a.resolution()
    complete = {
        "dataset_provider_gap_resolutions": list(config.canonical_map()),
        "resolution_policy_version": config.resolution_policy_version,
    }
    assert check_run_identity_inputs(config, complete) == ()

    assert "4.3.13_resolution_map_not_in_run_id" in _names(
        check_run_identity_inputs(config, {"resolution_policy_version": "profres/synthetic.a1"})
    )
    assert "4.3.13_resolution_policy_version_not_in_run_id" in _names(
        check_run_identity_inputs(
            config, {"dataset_provider_gap_resolutions": list(config.canonical_map())}
        )
    )


def test_a_downgraded_run_that_still_names_the_requested_profile_is_blocking() -> None:
    from kalpamani.data.contracts.vocabulary import GlobalProfileResolution

    config = phase3a.resolution(
        requested=PROVIDER_REALISTIC, downgrade=GlobalProfileResolution.DOWNGRADE
    )
    inputs = {
        "dataset_provider_gap_resolutions": list(config.canonical_map()),
        "resolution_policy_version": config.resolution_policy_version,
        "resolved_profile": PROVIDER_REALISTIC.value,
    }
    assert "4.3.11_downgrade_not_carried_through" in _names(
        check_run_identity_inputs(config, inputs)
    )


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def test_an_adjusted_artifact_that_does_not_reproduce_is_blocking() -> None:
    from kalpamani.data.contracts.vocabulary import AdjustmentPolicy
    from kalpamani.data.curate.adjustment import build_adjusted_bar_artifact

    artifact = build_adjusted_bar_artifact(
        [b for b in phase3a.daily_bars() if b.security_id == phase3a.SEC_CONTINUOUS],
        phase3a.corporate_actions(),
        adjustment_policy=AdjustmentPolicy.SPLIT_ONLY,
        resolved_profile=PUBLIC,
        as_of_epoch=phase3a.utc(2019, 6, 28, 21, 0),
        approvals=phase3a.approvals(),
        corporate_action_dataset_version=phase3a.ACTION_DATASET_VERSION,
        raw_bar_dataset_version=phase3a.BAR_DATASET_VERSION,
        security_id_scope=phase3a.SEC_CONTINUOUS,
        artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
        ingestion_time=phase3a.INGESTION_TIME,
        dataset_version=phase3a.DATASET_VERSION,
    )
    assert check_adjusted_artifact_hash(artifact, artifact.envelope.artifact_content_hash) == ()
    assert "4.5.1_adjusted_cache_does_not_reproduce" in _names(
        check_adjusted_artifact_hash(artifact, "sha256:tampered")
    )


def test_a_membership_row_encodes_without_any_source_timing() -> None:
    """A derived artifact never invents public or provider availability."""
    row = encode_universe_membership(phase3a.universe_snapshots()[date(2019, 6, 27)][0])
    envelope = row["envelope"]
    for forbidden in (
        "public_available_time",
        "provider_available_time",
        "system_first_seen_time",
    ):
        assert forbidden not in envelope
