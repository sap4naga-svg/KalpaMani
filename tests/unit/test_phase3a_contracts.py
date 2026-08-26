"""Phase-3A contract kernel: envelopes, resolved times, anchors, profiles.

Adversarial by default. Where a negative control appears it is labelled, because
the reason those exist is that an over-blocking check gets disabled by whoever is
next under deadline pressure -- and a disabled check protects nothing.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime, timedelta

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.anchors import (
    DOMAIN_ANCHOR_ALIASES,
    announced_forward_fact_anchor,
    resolved_fact_anchor,
    retrospective_fact_anchor,
    sampled_state_fact_anchor,
)
from kalpamani.data.contracts.entities import (
    SOURCE_ENTITY_TEMPORAL_CLASS,
    PriceBar,
    SecurityAttribute,
)
from kalpamani.data.contracts.envelope import (
    DerivedEnvelope,
    FactAnchor,
    LineageRef,
    OutputValidityDeclaration,
    SourceEnvelope,
)
from kalpamani.data.contracts.errors import EnvelopeError, ProfileResolutionError
from kalpamani.data.contracts.profiles import (
    DatasetGapResolution,
    ProfileResolutionConfig,
    TimingBasis,
    bound_provider_time,
    resolve_dataset_gap,
)
from kalpamani.data.contracts.resolution import (
    ApprovedBoundPolicy,
    BoundApprovals,
    decision_available_time,
    is_eligible,
    origin_eligible,
    resolved_provider_time,
    resolved_public_time,
    source_anchor,
)
from kalpamani.data.contracts.vocabulary import (
    AnnouncementBoundDerivation,
    DatasetGapPolicy,
    GlobalProfileResolution,
    InformationOrigin,
    InformationSetProfile,
    ProviderBoundDerivation,
    ProviderTimeDerivation,
    PublicBoundDerivation,
    PublicTimeDerivation,
    TemporalFactClass,
)

pytestmark = pytest.mark.unit

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER_REALISTIC = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

T0 = datetime(2020, 3, 2, 14, 0, tzinfo=UTC)
SEEN = datetime(2020, 3, 5, 9, 0, tzinfo=UTC)
INGESTED = datetime(2020, 3, 5, 9, 30, tzinfo=UTC)


def _attribute(
    envelope: SourceEnvelope,
    *,
    dataset: str = "security_attribute",
) -> SecurityAttribute:
    """A minimal source record carrying ``envelope``, for kernel-level tests."""
    return SecurityAttribute(
        dataset=dataset,
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


# ---------------------------------------------------------------------------
# 1 -- the two envelopes are mutually exclusive
# ---------------------------------------------------------------------------


def test_source_and_derived_envelopes_share_no_availability_fields() -> None:
    """They are disjoint types, not a superset and a subset."""
    source_fields = {f.name for f in fields(SourceEnvelope)}
    derived_fields = {f.name for f in fields(DerivedEnvelope)}
    overlap = source_fields & derived_fields

    assert overlap == {"ingestion_time", "dataset_version", "quality_status", "provider"}, (
        "The only fields the two envelopes may share are physical row properties -- when the "
        "row was written and which build it belongs to -- never a claim about when anyone "
        f"could have known anything. Found overlap: {sorted(overlap)}."
    )
    for name in (
        "public_available_time",
        "provider_available_time",
        "system_first_seen_time",
        "anchor",
    ):
        assert name in source_fields and name not in derived_fields
    for name in ("lineage", "artifact_first_built_time", "artifact_content_hash"):
        assert name in derived_fields and name not in source_fields


def test_a_source_envelope_refuses_the_derived_origin() -> None:
    """Constructing an impossible mixed envelope fails immediately."""
    with pytest.raises(EnvelopeError, match="selects the derived envelope"):
        _envelope(information_origin=InformationOrigin.DERIVED_ARTIFACT)


def test_a_derived_artifact_cannot_accept_source_availability_fields() -> None:
    """The field does not exist, so this is a TypeError at the call site."""
    with pytest.raises(TypeError):
        DerivedEnvelope(  # type: ignore[call-arg]
            lineage=(LineageRef.of(entity="price_bar", dataset_version="v", selector={"a": "b"}),),
            artifact_first_built_time=T0,
            derivation_spec_version="spec/1",
            artifact_content_hash="sha256:x",
            validity=OutputValidityDeclaration.session_scoped(date(2020, 1, 2)),
            ingestion_time=INGESTED,
            dataset_version="gold/test",
            system_first_seen_time=SEEN,
        )


def test_a_source_fact_cannot_accept_derived_artifact_fields() -> None:
    with pytest.raises(TypeError):
        _envelope(lineage=())


def test_a_derived_artifact_with_no_lineage_is_refused() -> None:
    with pytest.raises(EnvelopeError, match="no lineage is not a derived artifact"):
        DerivedEnvelope(
            lineage=(),
            artifact_first_built_time=T0,
            derivation_spec_version="spec/1",
            artifact_content_hash="sha256:x",
            validity=OutputValidityDeclaration.session_scoped(date(2020, 1, 2)),
            ingestion_time=INGESTED,
            dataset_version="gold/test",
        )


# ---------------------------------------------------------------------------
# 2-5 -- exact times and approved bounds
# ---------------------------------------------------------------------------


def test_unknown_exact_time_with_an_approved_bound_is_admissible() -> None:
    """NEGATIVE CONTROL. ``UNKNOWN`` alone is not disqualifying.

    Unusability is ``resolved_public_time IS NULL``, not
    ``derivation == UNKNOWN``. Blocking on the derivation made ``BOUND`` unusable
    for exactly the rows it was designed for.
    """
    bound = T0 + timedelta(hours=6)
    record = _attribute(
        _envelope(
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
            public_available_upper_bound=bound,
            public_bound_derivation=PublicBoundDerivation.DATE_PLUS_LAG,
        )
    )
    approvals = BoundApprovals(
        by_dataset={
            "security_attribute": ApprovedBoundPolicy(
                public=frozenset({PublicBoundDerivation.DATE_PLUS_LAG})
            )
        }
    )
    assert resolved_public_time(record, approvals) == bound
    assert decision_available_time(record, PUBLIC, approvals) == bound
    assert record.envelope.public_available_time is None, (
        "The bound must satisfy the requirement without ever being written into, or "
        "mistaken for, the exact value."
    )


def test_unknown_exact_time_with_no_approved_bound_refuses() -> None:
    record = _attribute(
        _envelope(
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
        )
    )
    assert resolved_public_time(record, BoundApprovals()) is None
    assert decision_available_time(record, PUBLIC, BoundApprovals()) is None


def test_a_bound_whose_derivation_is_not_approved_does_not_resolve() -> None:
    """Approval is what makes a bound usable. An unconfigured dataset approves nothing."""
    record = _attribute(
        _envelope(
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
            public_available_upper_bound=T0 + timedelta(hours=6),
            public_bound_derivation=PublicBoundDerivation.DATE_PLUS_LAG,
        )
    )
    approvals = BoundApprovals(
        by_dataset={
            "security_attribute": ApprovedBoundPolicy(
                public=frozenset({PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG})
            )
        }
    )
    assert resolved_public_time(record, approvals) is None


def test_provider_exact_null_with_an_approved_bound_is_admissible() -> None:
    """The ``BOUND`` resolution, end to end, on the provider axis."""
    record = _attribute(
        _envelope(
            provider_available_time=None,
            provider_time_derivation=ProviderTimeDerivation.UNKNOWN,
        )
    )
    bounded = record.with_envelope(bound_provider_time(record.envelope))
    approvals = BoundApprovals(
        by_dataset={
            "security_attribute": ApprovedBoundPolicy(
                provider=frozenset({ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND})
            )
        }
    )
    assert bounded.envelope.provider_available_time is None, (
        "BOUND never claims the provider published at system_first_seen_time; it claims only "
        "that the provider offered the row no later than then."
    )
    assert bounded.envelope.provider_available_upper_bound == SEEN
    assert resolved_provider_time(bounded, approvals) == SEEN


def test_bound_refuses_to_invent_a_provider_for_a_system_observed_row() -> None:
    envelope = _envelope(
        information_origin=InformationOrigin.SYSTEM_OBSERVED,
        public_available_time=None,
        public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
        provider_time_derivation=ProviderTimeDerivation.NOT_APPLICABLE,
    )
    with pytest.raises(ProfileResolutionError, match="does not manufacture one"):
        bound_provider_time(envelope)


# ---------------------------------------------------------------------------
# 7-8 -- resolved fact-time anchors
# ---------------------------------------------------------------------------


def test_a_date_only_announcement_with_an_approved_bound_is_checked_not_skipped() -> None:
    """The half of the fix that stops an invariant silently not running."""
    bound = datetime(2021, 1, 5, 1, 0, tzinfo=UTC)
    anchor = FactAnchor.announced_forward(
        announcement_time_upper_bound=bound,
        announcement_bound_derivation=AnnouncementBoundDerivation.DATE_PLUS_LAG,
    )
    approved = frozenset({AnnouncementBoundDerivation.DATE_PLUS_LAG})
    assert announced_forward_fact_anchor(anchor, approved) == bound
    assert resolved_fact_anchor(anchor, approved) == bound


def test_an_unapproved_announcement_bound_leaves_no_anchor() -> None:
    anchor = FactAnchor.announced_forward(
        announcement_time_upper_bound=datetime(2021, 1, 5, 1, 0, tzinfo=UTC),
        announcement_bound_derivation=AnnouncementBoundDerivation.DATE_PLUS_LAG,
    )
    assert announced_forward_fact_anchor(anchor, frozenset()) is None


def test_a_declared_class_with_neither_exact_nor_bounded_anchor_has_none() -> None:
    anchor = FactAnchor.announced_forward()
    assert resolved_fact_anchor(anchor, frozenset()) is None


def test_each_anchor_function_answers_only_for_its_own_class() -> None:
    """A class's anchor function never speaks for another class's row."""
    retrospective = FactAnchor.retrospective(T0)
    sampled = FactAnchor.sampled_state(T0)
    assert retrospective_fact_anchor(retrospective) == T0
    assert retrospective_fact_anchor(sampled) is None
    assert sampled_state_fact_anchor(sampled) == T0
    assert sampled_state_fact_anchor(retrospective) is None


def test_every_declared_domain_alias_names_a_real_class() -> None:
    """The contract's alias table is data, so an unmapped alias is findable."""
    for alias in DOMAIN_ANCHOR_ALIASES:
        assert isinstance(alias.serves_as, TemporalFactClass)
    entities = {alias.entity for alias in DOMAIN_ANCHOR_ALIASES}
    for required in ("source_document", "analyst_revision", "price_bar"):
        assert required in entities


def test_no_phase3a_source_entity_declares_a_class_without_an_anchor_route() -> None:
    """No temporal invariant may silently skip because an alias was never mapped."""
    aliased = {alias.entity for alias in DOMAIN_ANCHOR_ALIASES}
    for entity, declared in SOURCE_ENTITY_TEMPORAL_CLASS.items():
        if declared is None:
            continue  # per-row class; the row's own anchor decides
        anchor_field = {
            TemporalFactClass.RETROSPECTIVE: "observation_time",
            TemporalFactClass.ANNOUNCED_FORWARD: "announcement_time",
            TemporalFactClass.SAMPLED_STATE: "sample_time",
        }[declared]
        assert entity in aliased or anchor_field in {f.name for f in fields(FactAnchor)}, (
            f"{entity} declares {declared.value} but neither names the class anchor directly "
            "nor appears in the declared domain-alias table."
        )


def test_the_price_bar_alias_is_the_bar_endpoint() -> None:
    """``observation_time = bar_end_time``: a bar cannot be available before it closed."""
    bar = phase3a.daily_bars()[0]
    assert bar.observation_time == bar.bar_end_time
    assert bar.envelope.anchor.observation_time == bar.bar_end_time


# ---------------------------------------------------------------------------
# 9-10 -- origin eligibility
# ---------------------------------------------------------------------------


def test_provider_derived_is_ineligible_under_public_pit() -> None:
    """The market never saw a proprietary observation. Excluding it is correct."""
    assert not origin_eligible(InformationOrigin.PROVIDER_DERIVED, PUBLIC)
    assert origin_eligible(InformationOrigin.PROVIDER_DERIVED, PROVIDER_REALISTIC)
    assert origin_eligible(InformationOrigin.PROVIDER_DERIVED, FORWARD)


def test_system_observed_is_eligible_only_under_forward_system() -> None:
    assert not origin_eligible(InformationOrigin.SYSTEM_OBSERVED, PUBLIC)
    assert not origin_eligible(InformationOrigin.SYSTEM_OBSERVED, PROVIDER_REALISTIC)
    assert origin_eligible(InformationOrigin.SYSTEM_OBSERVED, FORWARD)


def test_a_proprietary_row_with_a_null_public_time_is_admissible_where_it_should_be() -> None:
    """NEGATIVE CONTROL N7/N8. Rejecting this row everywhere is the bug, not the fix."""
    record = _attribute(
        _envelope(
            information_origin=InformationOrigin.PROVIDER_DERIVED,
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
            provider_available_time=T0,
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
        )
    )
    approvals = BoundApprovals()
    assert decision_available_time(record, PUBLIC, approvals) is None
    assert decision_available_time(record, PROVIDER_REALISTIC, approvals) == T0
    assert decision_available_time(record, FORWARD, approvals) == SEEN


def test_a_system_observed_row_is_governed_by_first_seen_under_forward_system() -> None:
    """NEGATIVE CONTROL N10. The only profile that can describe it, which is what it is for."""
    record = _attribute(
        _envelope(
            information_origin=InformationOrigin.SYSTEM_OBSERVED,
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
            provider_time_derivation=ProviderTimeDerivation.NOT_APPLICABLE,
        )
    )
    assert decision_available_time(record, FORWARD, BoundApprovals()) == SEEN
    assert source_anchor(record, FORWARD, BoundApprovals()) == SEEN


def test_provider_realistic_needs_both_axes_for_a_public_fact() -> None:
    """Simulating a subscriber means knowing when the SUBSCRIBER got the row."""
    record = _attribute(_envelope(provider_available_time=None))
    assert decision_available_time(record, PROVIDER_REALISTIC, BoundApprovals()) is None

    with_provider = _attribute(
        _envelope(
            provider_available_time=T0 + timedelta(hours=8),
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
        )
    )
    assert decision_available_time(with_provider, PROVIDER_REALISTIC, BoundApprovals()) == (
        T0 + timedelta(hours=8)
    )


def test_the_profile_ordering_holds_where_a_record_is_eligible_under_all_three() -> None:
    record = _attribute(
        _envelope(
            provider_available_time=T0 + timedelta(hours=8),
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
        )
    )
    approvals = BoundApprovals()
    public = decision_available_time(record, PUBLIC, approvals)
    provider = decision_available_time(record, PROVIDER_REALISTIC, approvals)
    forward = decision_available_time(record, FORWARD, approvals)
    assert public is not None and provider is not None and forward is not None
    assert public <= provider <= forward


def test_the_ordering_is_not_asserted_across_a_profile_a_record_is_ineligible_for() -> None:
    """NEGATIVE CONTROL N9. A malformed comparison is not a violated invariant."""
    record = _attribute(
        _envelope(
            information_origin=InformationOrigin.PROVIDER_DERIVED,
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
            provider_available_time=T0,
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
        )
    )
    assert not is_eligible(record, PUBLIC)
    assert decision_available_time(record, PUBLIC, BoundApprovals()) is None


# ---------------------------------------------------------------------------
# Derived-artifact availability
# ---------------------------------------------------------------------------


def test_a_derived_artifact_is_as_available_as_its_slowest_input() -> None:
    dataset = phase3a.gold_dataset()
    snapshot = dataset.universe[date(2019, 6, 27)][0]
    approvals = phase3a.approvals()

    input_times = [
        available
        for item in snapshot.inputs
        if (available := decision_available_time(item, PUBLIC, approvals)) is not None
    ]
    expected = max(input_times)
    assert decision_available_time(snapshot, PUBLIC, approvals) == expected


def test_forward_system_availability_never_precedes_the_first_build() -> None:
    """We did not hold a computed value before we computed it."""
    dataset = phase3a.gold_dataset()
    snapshot = dataset.universe[date(2019, 6, 27)][0]
    available = decision_available_time(snapshot, FORWARD, phase3a.approvals())
    assert available is not None
    assert available >= snapshot.envelope.artifact_first_built_time


def test_derived_eligibility_is_the_intersection_of_its_inputs() -> None:
    """No amount of arithmetic makes a proprietary input public."""
    dataset = phase3a.gold_dataset()
    snapshot = dataset.universe[date(2019, 6, 27)][0]
    assert is_eligible(snapshot, PUBLIC), (
        "NEGATIVE CONTROL N11: every input here is AUTHORITATIVE_PUBLIC, and deriving a value "
        "does not make it private."
    )

    proprietary = _attribute(
        _envelope(
            information_origin=InformationOrigin.PROVIDER_DERIVED,
            public_available_time=None,
            public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
            provider_available_time=T0,
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
        )
    )
    tainted = phase3a.securities()[0]
    tainted = type(tainted)(
        security_id=tainted.security_id,
        inputs=(*tainted.inputs, proprietary),
        envelope=tainted.envelope,
    )
    assert not is_eligible(tainted, PUBLIC)
    assert is_eligible(tainted, PROVIDER_REALISTIC)


# ---------------------------------------------------------------------------
# 11-12 -- per-dataset resolution
# ---------------------------------------------------------------------------


def test_declare_does_not_exist_anywhere_in_the_gap_vocabulary() -> None:
    """The withdrawn resolution. A rule cannot both permit and prohibit the same act."""
    assert {member.value for member in DatasetGapPolicy} == {"NONE", "EXCLUDE", "BOUND"}
    assert "DECLARE" not in {member.value for member in DatasetGapPolicy}
    assert "DECLARE" not in {member.value for member in GlobalProfileResolution}


def test_downgrade_is_global_and_absent_from_the_per_dataset_vocabulary() -> None:
    assert "DOWNGRADE" not in {member.value for member in DatasetGapPolicy}
    assert "DOWNGRADE" in {member.value for member in GlobalProfileResolution}


def test_one_run_may_bound_one_dataset_and_exclude_another() -> None:
    """NEGATIVE CONTROL N16. The ordinary case a single scalar could not express."""
    config = phase3a.resolution(requested=PROVIDER_REALISTIC)
    assert config.policy_for("market_session") is DatasetGapPolicy.BOUND
    assert config.policy_for("ticker_history") is DatasetGapPolicy.EXCLUDE

    approvals = phase3a.approvals()
    bounded = resolve_dataset_gap(
        phase3a.sessions(), dataset="market_session", config=config, approvals=approvals
    )
    excluded = resolve_dataset_gap(
        phase3a.ticker_history(),
        dataset="ticker_history",
        config=config,
        approvals=approvals,
    )

    assert len(bounded.records) == len(phase3a.sessions())
    assert bounded.evidence.provider_basis is TimingBasis.BOUND
    assert bounded.evidence.provider_bounded_rows == len(phase3a.sessions())

    assert excluded.records == ()
    assert excluded.evidence.policy is DatasetGapPolicy.EXCLUDE
    assert excluded.evidence.excluded_rows == len(phase3a.ticker_history())


def test_resolution_evidence_reconciles_on_each_axis_independently() -> None:
    """A dataset may be bounded on one axis and exact on the other."""
    config = phase3a.resolution(requested=PROVIDER_REALISTIC)
    outcome = resolve_dataset_gap(
        phase3a.sessions(),
        dataset="market_session",
        config=config,
        approvals=phase3a.approvals(),
    )
    assert outcome.evidence.public_axis_reconciles()
    assert outcome.evidence.provider_axis_reconciles()
    assert outcome.evidence.public_basis is TimingBasis.EXACT
    assert outcome.evidence.provider_basis is TimingBasis.BOUND


def test_a_downgrade_relabels_the_whole_run_before_anything_is_filtered() -> None:
    config = phase3a.resolution(
        requested=PROVIDER_REALISTIC, downgrade=GlobalProfileResolution.DOWNGRADE
    )
    assert config.requested_profile is PROVIDER_REALISTIC
    assert config.resolved_profile is PUBLIC


def test_a_dataset_resolved_twice_is_refused() -> None:
    with pytest.raises(ProfileResolutionError, match="resolved more than once"):
        ProfileResolutionConfig(
            requested_profile=PUBLIC,
            resolution_policy_version="v1",
            dataset_resolutions=(
                DatasetGapResolution(dataset="price_bar", policy=DatasetGapPolicy.NONE, reason="a"),
                DatasetGapResolution(
                    dataset="price_bar", policy=DatasetGapPolicy.BOUND, reason="b"
                ),
            ),
        )


def test_an_unnamed_resolution_policy_is_refused() -> None:
    with pytest.raises(ProfileResolutionError, match="resolution_policy_version is required"):
        ProfileResolutionConfig(requested_profile=PUBLIC, resolution_policy_version="")


def test_the_canonical_map_is_dataset_ordered_and_complete() -> None:
    """Not a summary of the map -- the map, in full, in a stable order."""
    config = phase3a.resolution()
    canonical = config.canonical_map()
    assert [entry[0] for entry in canonical] == sorted(entry[0] for entry in canonical)
    assert len(canonical) == len(config.dataset_resolutions)


# ---------------------------------------------------------------------------
# 14 -- bar identity
# ---------------------------------------------------------------------------


def test_two_minute_bars_in_one_session_have_distinct_identities() -> None:
    """The old ``(security_id, session_date, resolution)`` key collided them into one row."""
    minutes = phase3a.minute_bars()
    assert len(minutes) == 2
    assert len({bar.session_date for bar in minutes}) == 1
    assert len({bar.primary_key for bar in minutes}) == 2, (
        "Identity is the bar's own endpoint. Keying on session_date cannot represent minute "
        "bars at all."
    )


def test_session_date_is_a_calendar_key_not_part_of_bar_identity() -> None:
    bar: PriceBar = phase3a.minute_bars()[0]
    assert bar.primary_key == (bar.security_id, bar.resolution.value, bar.bar_end_time)
    assert bar.session_date not in bar.primary_key
