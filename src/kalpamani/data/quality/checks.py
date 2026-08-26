"""Deterministic data-quality checks. Same inputs, same findings.

No sampling, no thresholds tuned by eye, no model deciding what looks wrong.
Findings are typed data, not log lines, because the code that refuses to serve a
result has to be able to query them.

**A check that over-blocks is not "safe".** It is a check that will be loosened
under deadline pressure by someone who no longer remembers why it was there. The
negative-control fixtures exist for exactly that reason: a scheduled earnings
date announced six weeks ahead, a holiday calendar published a year early, a
proprietary snapshot with a legitimately null public time, an approved bound
standing in for an unestablished exact instant -- all of these must **pass**, and
an earlier revision of the plan would have blocked every one of them.

**Every temporal check reads one origin-aware anchor.** Anchoring the class
invariants to the public time silently disabled all three of them for proprietary
and system-observed rows, where the public time is legitimately null: a consensus
snapshot stamped *before* the moment it was sampled would have passed. Every
inequality below is evaluated only over times a record actually has; a comparison
against a time a record legitimately lacks is skipped, not failed.

**Everything reads the resolved profile**, never the requested one. A downgrade
changes the run before any filtering or checking happens.

Some checks in the envelope section are unreachable from this package's own
constructors -- the two envelopes are disjoint types, so a source row cannot grow
lineage. They are implemented anyway, and applied to **rows read back from
storage**, which is where a malformed envelope can genuinely arrive: from an
older writer, a hand-edited file, or a partial restore.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from kalpamani.data.contracts.anchors import resolved_fact_anchor
from kalpamani.data.contracts.entities import (
    AdjustedBarArtifact,
    CorporateAction,
    DataQualityIssue,
    Listing,
    PriceBar,
    TickerHistory,
    UniverseMembership,
)
from kalpamani.data.contracts.envelope import DerivedEnvelope, SourceEnvelope
from kalpamani.data.contracts.profiles import ProfileResolutionConfig
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    decision_available_time,
    is_eligible,
    resolved_provider_time,
    resolved_public_time,
    source_anchor,
)
from kalpamani.data.contracts.vocabulary import (
    EXACT_PROVIDER_DERIVATIONS,
    EXACT_PUBLIC_DERIVATIONS,
    CorporateActionType,
    DatasetGapPolicy,
    InformationOrigin,
    InformationSetProfile,
    IssueStatus,
    PublicTimeDerivation,
    QualitySeverity,
)

#: Fields that belong to the source envelope alone.
_SOURCE_ONLY_FIELDS: Final = (
    "public_available_time",
    "public_available_upper_bound",
    "provider_available_time",
    "provider_available_upper_bound",
    "system_first_seen_time",
)

#: Fields that belong to the derived envelope alone.
_DERIVED_ONLY_FIELDS: Final = (
    "lineage",
    "artifact_first_built_time",
    "derivation_spec_version",
    "artifact_content_hash",
)

#: The validity field each output validity requires.
_VALIDITY_FIELD: Final[dict[str, tuple[str, ...]]] = {
    "SESSION_SCOPED": ("effective_session",),
    "INTERVAL": ("valid_time_start", "valid_time_end"),
    "PERIOD_END": ("period_end",),
    "EVENT_REFERENCED": ("observation_reference",),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityFinding:
    """One deterministic finding. Typed so a refusal can be decided mechanically."""

    check_name: str
    severity: QualitySeverity
    dataset: str
    detail: str
    security_id: str | None = None
    session_date: date | None = None

    @property
    def is_blocking(self) -> bool:
        """Whether this finding refuses every dependent result."""
        return self.severity is QualitySeverity.BLOCKING

    def to_issue(
        self,
        *,
        issue_id: str,
        detected_at: datetime,
        ingestion_run_id: str | None = None,
    ) -> DataQualityIssue:
        """Render this finding as a storable, queryable issue row."""
        return DataQualityIssue(
            issue_id=issue_id,
            check_name=self.check_name,
            severity=self.severity,
            dataset=self.dataset,
            detected_at=detected_at,
            detail=self.detail,
            status=IssueStatus.OPEN,
            security_id=self.security_id,
            session_date=self.session_date,
            ingestion_run_id=ingestion_run_id,
        )


def _blocking(check: str, dataset: str, detail: str, **scope: Any) -> QualityFinding:
    return QualityFinding(
        check_name=check,
        severity=QualitySeverity.BLOCKING,
        dataset=dataset,
        detail=detail,
        **scope,
    )


def _warning(check: str, dataset: str, detail: str, **scope: Any) -> QualityFinding:
    return QualityFinding(
        check_name=check,
        severity=QualitySeverity.WARNING,
        dataset=dataset,
        detail=detail,
        **scope,
    )


# ---------------------------------------------------------------------------
# 4.0 -- envelope conformance, branched before anything else
# ---------------------------------------------------------------------------


def check_envelope(record: PitRecord, *, approvals: BoundApprovals) -> tuple[QualityFinding, ...]:
    """Branch on envelope, then apply that envelope's rules and no others.

    Running source-shaped checks over every row is what produced three false
    BLOCKINGs on a correctly-formed derived artifact in an earlier revision: it
    failed the origin vocabulary check, failed "missing first-seen", and was
    graded against a derivation enum it does not have.
    """
    envelope = record.envelope
    if isinstance(envelope, DerivedEnvelope):
        return _check_derived_envelope(record, envelope)
    return _check_source_envelope(record, envelope, approvals)


def _check_source_envelope(
    record: PitRecord,
    envelope: SourceEnvelope,
    approvals: BoundApprovals,
) -> tuple[QualityFinding, ...]:
    dataset = record.dataset
    found: list[QualityFinding] = []
    origin = envelope.information_origin

    if origin is InformationOrigin.AUTHORITATIVE_PUBLIC and (
        resolved_public_time(record, approvals) is None
    ):
        found.append(
            _blocking(
                "4.0A.1_public_fact_without_resolvable_public_time",
                dataset,
                "An AUTHORITATIVE_PUBLIC row has neither an exact public time nor an "
                "approved upper bound, so resolved_public_time is null. UNKNOWN alone is "
                "not this finding: a row with an approved bound resolves and is admissible.",
            )
        )

    if origin is InformationOrigin.PROVIDER_DERIVED and (
        envelope.public_available_time is not None
        or envelope.public_available_upper_bound is not None
    ):
        found.append(
            _blocking(
                "4.0A.2_proprietary_fact_carrying_public_timing",
                dataset,
                "A PROVIDER_DERIVED row carries public timing. If an authoritative public "
                "instant exists for this exact fact, the origin is wrong.",
            )
        )

    if origin is InformationOrigin.SYSTEM_OBSERVED and any(
        value is not None
        for value in (
            envelope.public_available_time,
            envelope.public_available_upper_bound,
            envelope.provider_available_time,
            envelope.provider_available_upper_bound,
        )
    ):
        found.append(
            _blocking(
                "4.0A.4_system_observed_carrying_vendor_timing",
                dataset,
                "A SYSTEM_OBSERVED row carries public or provider timing, exact or bounded. "
                "We polled an endpoint; there is no external publication instant to carry.",
            )
        )

    if (
        envelope.public_time_derivation in EXACT_PUBLIC_DERIVATIONS
        and envelope.public_available_time is None
    ) or (
        envelope.provider_time_derivation in EXACT_PROVIDER_DERIVATIONS
        and envelope.provider_available_time is None
    ):
        found.append(
            _blocking(
                "4.0A.6_exact_derivation_without_exact_value",
                dataset,
                "A derivation from the exact vocabulary is declared while the exact field "
                "it names is null.",
            )
        )

    if (
        envelope.public_available_time is not None
        and envelope.public_time_derivation not in EXACT_PUBLIC_DERIVATIONS
    ) or (
        envelope.provider_available_time is not None
        and envelope.provider_time_derivation not in EXACT_PROVIDER_DERIVATIONS
    ):
        found.append(
            _blocking(
                "4.0A.7_approximation_written_into_exact_field",
                dataset,
                "An exact availability field holds a value whose derivation is not an exact "
                "derivation. Approximations live in bound fields, always.",
            )
        )

    for label, exact, bound in (
        ("public", envelope.public_available_time, envelope.public_available_upper_bound),
        ("provider", envelope.provider_available_time, envelope.provider_available_upper_bound),
    ):
        if exact is not None and bound is not None and exact > bound:
            found.append(
                _blocking(
                    "4.0A.8_bound_precedes_the_exact_time_it_bounds",
                    dataset,
                    f"The {label} exact time {exact.isoformat()} is later than its own upper "
                    f"bound {bound.isoformat()}. A bound that precedes the time it bounds is "
                    "not a bound.",
                )
            )

    approved = approvals.for_dataset(dataset)
    if (
        envelope.public_available_time is None
        and envelope.public_available_upper_bound is not None
        and envelope.public_bound_derivation not in approved.public
    ):
        found.append(
            _blocking(
                "4.0A.9_unapproved_public_bound",
                dataset,
                f"public_bound_derivation={envelope.public_bound_derivation.value} is not "
                "approved for this dataset, so the bound cannot resolve the axis. Approval "
                "is what makes a bound usable.",
            )
        )
    if (
        envelope.provider_available_time is None
        and envelope.provider_available_upper_bound is not None
        and envelope.provider_bound_derivation not in approved.provider
    ):
        found.append(
            _blocking(
                "4.0A.9_unapproved_provider_bound",
                dataset,
                f"provider_bound_derivation={envelope.provider_bound_derivation.value} is "
                "not approved for this dataset.",
            )
        )

    if (
        envelope.public_time_derivation is PublicTimeDerivation.NOT_APPLICABLE
        and origin is InformationOrigin.AUTHORITATIVE_PUBLIC
    ) or (
        envelope.public_time_derivation is PublicTimeDerivation.UNKNOWN
        and origin is not InformationOrigin.AUTHORITATIVE_PUBLIC
    ):
        found.append(
            _blocking(
                "4.0A.10_derivation_disagrees_with_origin",
                dataset,
                "NOT_APPLICABLE means no public time exists; UNKNOWN means one exists and we "
                "failed to establish it. The declared derivation contradicts the origin.",
            )
        )

    if resolved_fact_anchor(envelope.anchor, approved.announcement) is None:
        found.append(
            _blocking(
                "4.0A.11_class_without_a_resolved_fact_anchor",
                dataset,
                f"The row declares {envelope.temporal_fact_class.value} but has no usable "
                "anchor: neither an exact instant nor an approved upper bound. There is "
                "nothing for the class invariant to check against.",
            )
        )

    return tuple(found)


def _check_derived_envelope(
    record: PitRecord,
    envelope: DerivedEnvelope,
) -> tuple[QualityFinding, ...]:
    dataset = record.dataset
    found: list[QualityFinding] = []

    if not envelope.lineage or any(not ref.is_resolvable() for ref in envelope.lineage):
        found.append(
            _blocking(
                "4.0B.2_incomplete_lineage",
                dataset,
                "Lineage is empty, or an input does not resolve to a published dataset "
                "version and a row selector. A summary is not lineage: it cannot be "
                "replayed, and lineage that cannot be replayed cannot prove reproduction.",
            )
        )

    if not envelope.derivation_spec_version or not envelope.artifact_content_hash:
        found.append(
            _blocking(
                "4.0B.3_missing_derived_envelope_fields",
                dataset,
                "A derived artifact must carry artifact_first_built_time, "
                "derivation_spec_version and artifact_content_hash.",
            )
        )

    required = _VALIDITY_FIELD[envelope.output_validity.value]
    validity = envelope.validity
    missing = [name for name in required if not getattr(validity, name)]
    if missing:
        found.append(
            _blocking(
                "4.0B.5_output_validity_without_its_field",
                dataset,
                f"output_validity={envelope.output_validity.value} requires {required}; "
                f"missing {missing}.",
            )
        )

    return tuple(found)


def check_stored_envelope_shape(
    row: Mapping[str, Any], *, dataset: str
) -> tuple[QualityFinding, ...]:
    """Envelope conformance for a row read back from storage.

    Reachable where the object-level checks are not: a row written by an older
    writer, hand-edited, or partially restored can carry a shape the constructors
    would never produce.
    """
    found: list[QualityFinding] = []
    origin_raw = row.get("information_origin")
    valid = {member.value for member in InformationOrigin}
    if origin_raw not in valid:
        return (
            _blocking(
                "4.0.0_origin_outside_the_closed_vocabulary",
                dataset,
                f"information_origin={origin_raw!r} is outside the closed vocabulary "
                f"{sorted(valid)}.",
            ),
        )

    is_derived = origin_raw == InformationOrigin.DERIVED_ARTIFACT.value
    source_present = [f for f in _SOURCE_ONLY_FIELDS if row.get(f) is not None]
    derived_present = [f for f in _DERIVED_ONLY_FIELDS if row.get(f) is not None]

    if is_derived and source_present:
        found.append(
            _blocking(
                "4.0B.1_derived_artifact_carrying_source_timing",
                dataset,
                f"A DERIVED_ARTIFACT row carries source-envelope fields {source_present}. A "
                "derived value never invents public or provider availability.",
            )
        )
    if not is_derived and derived_present:
        found.append(
            _blocking(
                "4.0_mixed_source_and_derived_envelope",
                dataset,
                f"A source row carries derived-envelope fields {derived_present}. A row "
                "carries one envelope or the other, never both.",
            )
        )
    if not is_derived and row.get("system_first_seen_time") is None:
        found.append(
            _blocking(
                "4.0A.5_missing_system_first_seen_time",
                dataset,
                "A source row has no system_first_seen_time. It is always known, because we "
                "were there.",
            )
        )
    if is_derived and row.get("temporal_fact_class") is not None:
        found.append(
            _blocking(
                "4.0B.4_derived_artifact_declares_a_source_temporal_class",
                dataset,
                "A derived artifact declares output_validity, never a source "
                "temporal_fact_class. There is no derived RETROSPECTIVE.",
            )
        )
    return tuple(found)


# ---------------------------------------------------------------------------
# 4.1 -- impossibility and leakage, class-aware and origin-aware
# ---------------------------------------------------------------------------


def check_temporal_invariants(
    record: PitRecord,
    *,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    dataset_build_time: datetime | None = None,
) -> tuple[QualityFinding, ...]:
    """The class invariants, plus the orderings a record's own times must satisfy.

    There is deliberately **no** check of the form ``effective_date < available``.
    For an announced-forward fact an effective date later than availability is the
    normal, correct case -- that is the entire class.
    """
    envelope = record.envelope
    if isinstance(envelope, DerivedEnvelope):
        return ()

    dataset = record.dataset
    found: list[QualityFinding] = []
    approved = approvals.for_dataset(dataset)
    anchor = source_anchor(record, resolved_profile, approvals)
    fact_anchor = resolved_fact_anchor(envelope.anchor, approved.announcement)
    seen = envelope.system_first_seen_time
    public = envelope.public_available_time
    provider = envelope.provider_available_time

    if (
        envelope.information_origin is InformationOrigin.AUTHORITATIVE_PUBLIC
        and public is not None
        and seen < public
    ):
        found.append(
            _blocking(
                "4.1.1_held_before_public",
                dataset,
                f"We recorded first seeing this row at {seen.isoformat()}, before it became "
                f"public at {public.isoformat()}.",
            )
        )

    if provider is not None and seen < provider:
        found.append(
            _blocking(
                "4.1.2_held_before_provider_supplied",
                dataset,
                f"We recorded first seeing this row at {seen.isoformat()}, before the "
                f"provider offered it at {provider.isoformat()}.",
            )
        )

    if envelope.ingestion_time < seen:
        found.append(
            _blocking(
                "4.1.3_row_written_before_first_seen",
                dataset,
                f"ingestion_time {envelope.ingestion_time.isoformat()} precedes "
                f"system_first_seen_time {seen.isoformat()}.",
            )
        )

    if (
        envelope.information_origin is InformationOrigin.AUTHORITATIVE_PUBLIC
        and public is not None
        and provider is not None
        and provider < public
    ):
        found.append(
            _blocking(
                "4.1.4_provider_ahead_of_public_for_the_same_fact",
                dataset,
                "A provider cannot have offered a public fact before it was public; one of "
                "the two exact timestamps is wrong. Bounds are excluded from this check -- a "
                "bound is not a claim about ordering.",
            )
        )

    if anchor is not None and fact_anchor is not None and anchor < fact_anchor:
        found.append(
            _blocking(
                f"4.1_{envelope.temporal_fact_class.value.lower()}_available_before_it_happened",
                dataset,
                f"The governing availability anchor {anchor.isoformat()} precedes the "
                f"{envelope.temporal_fact_class.value} fact anchor {fact_anchor.isoformat()}.",
            )
        )

    if dataset_build_time is not None:
        available = decision_available_time(record, resolved_profile, approvals)
        if available is not None and available > dataset_build_time:
            found.append(
                _blocking(
                    "4.1.9_future_dated_availability",
                    dataset,
                    f"decision_available_time {available.isoformat()} is later than the "
                    f"dataset build time {dataset_build_time.isoformat()}.",
                )
            )

    return tuple(found)


# ---------------------------------------------------------------------------
# 4.3 -- information-set profile
# ---------------------------------------------------------------------------


def check_profile_service(
    records: Sequence[PitRecord],
    *,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    config: ProfileResolutionConfig,
    as_of: datetime,
) -> tuple[QualityFinding, ...]:
    """Checks over the set of rows a run is about to serve."""
    found: list[QualityFinding] = []

    if config.resolved_profile is not resolved_profile:
        found.append(
            _blocking(
                "4.3.1_mixed_profiles_in_one_result",
                "run",
                f"Rows are being served under {resolved_profile.value} while the run "
                f"resolved to {config.resolved_profile.value}.",
            )
        )

    for record in records:
        dataset = record.dataset
        envelope = record.envelope

        if not is_eligible(record, resolved_profile):
            found.append(
                _blocking(
                    "4.3.5_ineligible_row_served",
                    dataset,
                    f"A row whose origin cannot be described by {resolved_profile.value} is "
                    "present in the result. Ineligible rows are excluded and counted, never "
                    "served.",
                )
            )
            continue

        if isinstance(envelope, SourceEnvelope):
            found.extend(
                _check_source_profile(record, envelope, resolved_profile, approvals, config)
            )

        available = decision_available_time(record, resolved_profile, approvals)
        if available is not None and available > as_of:
            found.append(
                _blocking(
                    "4.3.9_backfill_admitted_too_early",
                    dataset,
                    f"A row governed by {available.isoformat()} is present in a result cut "
                    f"off at {as_of.isoformat()}.",
                )
            )

        if not config.has_entry_for(dataset) and not isinstance(envelope, DerivedEnvelope):
            found.append(
                _blocking(
                    "4.3.12_dataset_absent_from_the_resolution_map",
                    dataset,
                    "A directly read source dataset is absent from "
                    "dataset_provider_gap_resolutions. The map is a complete inventory of "
                    "direct source reads, not a list of the problematic ones.",
                )
            )

    return tuple(found)


def _check_source_profile(
    record: PitRecord,
    envelope: SourceEnvelope,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    config: ProfileResolutionConfig,
) -> list[QualityFinding]:
    dataset = record.dataset
    found: list[QualityFinding] = []
    policy = config.policy_for(dataset)

    if (
        policy is DatasetGapPolicy.BOUND
        and envelope.information_origin is InformationOrigin.SYSTEM_OBSERVED
        and envelope.provider_available_upper_bound is not None
    ):
        found.append(
            _blocking(
                "4.3.10_bound_applied_to_a_system_observed_row",
                dataset,
                "BOUND bounds a provider time that exists but is unstated. Applying it to a "
                "SYSTEM_OBSERVED row invents a provider that does not exist.",
            )
        )

    if resolved_profile is not InformationSetProfile.PROVIDER_REALISTIC_PIT:
        return found

    provider = resolved_provider_time(record, approvals)
    if provider is None and envelope.information_origin is not InformationOrigin.SYSTEM_OBSERVED:
        if policy not in {DatasetGapPolicy.EXCLUDE, DatasetGapPolicy.BOUND}:
            found.append(
                _blocking(
                    "4.3.2_unresolved_provider_availability",
                    dataset,
                    "resolved_provider_time is null under PROVIDER_REALISTIC_PIT and the "
                    f"dataset policy is {policy.value}. Policies are per dataset, and each "
                    "is checked against its own.",
                )
            )
        if resolved_public_time(record, approvals) is not None:
            found.append(
                _blocking(
                    "4.3.3_public_timing_substituted_for_absent_provider_timing",
                    dataset,
                    "The row would be served on public timing because provider timing is "
                    "absent -- the withdrawn DECLARE behaviour. A legitimate "
                    "max(public, provider) == public, with BOTH present, is correct and is "
                    "not this finding.",
                )
            )
    return found


def check_run_identity_inputs(
    config: ProfileResolutionConfig,
    run_id_inputs: Mapping[str, Any],
) -> tuple[QualityFinding, ...]:
    """The canonical resolution map and its policy version must enter ``run_id``."""
    found: list[QualityFinding] = []
    if run_id_inputs.get("dataset_provider_gap_resolutions") != list(config.canonical_map()):
        found.append(
            _blocking(
                "4.3.13_resolution_map_not_in_run_id",
                "run",
                "The canonical ordered per-dataset map is absent from, or differs from, the "
                "run_id inputs. Two runs that resolved the same query differently admit "
                "different rows and must not share an identity.",
            )
        )
    if run_id_inputs.get("resolution_policy_version") != config.resolution_policy_version:
        found.append(
            _blocking(
                "4.3.13_resolution_policy_version_not_in_run_id",
                "run",
                "resolution_policy_version is absent from the run_id inputs.",
            )
        )
    if config.resolved_profile is not config.requested_profile:
        named = {
            value
            for value in run_id_inputs.values()
            if isinstance(value, str) and value == config.requested_profile.value
        }
        if named:
            found.append(
                _blocking(
                    "4.3.11_downgrade_not_carried_through",
                    "run",
                    "The run resolved to a different profile than it requested, but the "
                    "run_id inputs still name the requested one. A downgraded run is never "
                    "labelled with the profile it asked for.",
                )
            )
    return tuple(found)


# ---------------------------------------------------------------------------
# 5 -- market data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataThresholds:
    """Versioned, deterministic thresholds. No value here is tuned by eye."""

    version: str
    #: Absolute close-to-close move above which an unexplained gap is a split.
    split_discontinuity_fraction: Decimal


DEFAULT_MARKET_THRESHOLDS: Final = MarketDataThresholds(
    version="market-checks/a1.1",
    split_discontinuity_fraction=Decimal("0.35"),
)


def check_price_bars(
    bars: Sequence[PriceBar],
    *,
    session_dates_by_instant: Mapping[datetime, date],
    actions: Sequence[CorporateAction] = (),
    expected_sessions: Sequence[date] = (),
    thresholds: MarketDataThresholds = DEFAULT_MARKET_THRESHOLDS,
) -> tuple[QualityFinding, ...]:
    """Structural and market-data checks over a set of raw bars."""
    dataset = "price_bar"
    found: list[QualityFinding] = []

    seen_keys: dict[tuple[str, str, datetime], int] = {}
    for bar in bars:
        key = bar.primary_key
        seen_keys[key] = seen_keys.get(key, 0) + 1

        if (
            bar.high < bar.low
            or not (bar.low <= bar.open <= bar.high)
            or not (bar.low <= bar.close <= bar.high)
        ):
            found.append(
                _blocking(
                    "5.1_impossible_ohlc",
                    dataset,
                    f"OHLC is impossible: open={bar.open} high={bar.high} low={bar.low} "
                    f"close={bar.close}.",
                    security_id=bar.security_id,
                    session_date=bar.session_date,
                )
            )
        if min(bar.open, bar.high, bar.low, bar.close) <= 0 or bar.volume < 0:
            found.append(
                _blocking(
                    "5.2_non_positive_price_or_negative_volume",
                    dataset,
                    f"A price is non-positive or volume is negative (volume={bar.volume}).",
                    security_id=bar.security_id,
                    session_date=bar.session_date,
                )
            )

        expected_session = session_dates_by_instant.get(bar.bar_end_time)
        if expected_session is None:
            found.append(
                _blocking(
                    "4.1.12_bar_outside_any_known_session",
                    dataset,
                    f"Bar ending {bar.bar_end_time.isoformat()} belongs to no calendar "
                    "session, so its session_date cannot be verified.",
                    security_id=bar.security_id,
                    session_date=bar.session_date,
                )
            )
        elif expected_session != bar.session_date:
            found.append(
                _blocking(
                    "4.1.12_session_date_derived_by_utc_truncation",
                    dataset,
                    f"session_date={bar.session_date.isoformat()} disagrees with the calendar "
                    f"session {expected_session.isoformat()} for {bar.bar_end_time.isoformat()}. "
                    "A 20:00 ET print belongs to that session and to the next UTC day.",
                    security_id=bar.security_id,
                    session_date=bar.session_date,
                )
            )

    for key, count in sorted(seen_keys.items()):
        if count > 1:
            found.append(
                _blocking(
                    "3.1_duplicate_price_bar_key",
                    dataset,
                    f"{count} rows share the primary key {key}. Identity is "
                    "(security_id, resolution, bar_end_time); two minute bars in one session "
                    "must never collide.",
                    security_id=key[0],
                )
            )

    found.extend(_check_split_discontinuity(bars, actions, thresholds))
    found.extend(_check_missing_sessions(bars, expected_sessions))
    return tuple(found)


def _check_split_discontinuity(
    bars: Sequence[PriceBar],
    actions: Sequence[CorporateAction],
    thresholds: MarketDataThresholds,
) -> list[QualityFinding]:
    """An unadjusted split looks exactly like a -50% return, and destroys momentum."""
    found: list[QualityFinding] = []
    explained = {
        (action.security_id, action.ex_date)
        for action in actions
        if action.ex_date is not None
        and action.action_type in {CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT}
    }
    by_security: dict[str, list[PriceBar]] = {}
    for bar in bars:
        by_security.setdefault(bar.security_id, []).append(bar)

    for security_id, series in sorted(by_security.items()):
        ordered = sorted(series, key=lambda b: b.bar_end_time)
        for previous, current in itertools.pairwise(ordered):
            if previous.close <= 0:
                continue
            move = abs(current.close - previous.close) / previous.close
            if move <= thresholds.split_discontinuity_fraction:
                continue
            if (security_id, current.session_date) in explained:
                continue
            found.append(
                _blocking(
                    "5.5_split_discontinuity",
                    "price_bar",
                    f"Close moved {move:.4f} from {previous.close} to {current.close} with no "
                    "corporate action explaining it.",
                    security_id=security_id,
                    session_date=current.session_date,
                )
            )
    return found


def _check_missing_sessions(
    bars: Sequence[PriceBar],
    expected_sessions: Sequence[date],
) -> list[QualityFinding]:
    if not expected_sessions:
        return []
    found: list[QualityFinding] = []
    by_security: dict[str, set[date]] = {}
    for bar in bars:
        by_security.setdefault(bar.security_id, set()).add(bar.session_date)
    for security_id, covered in sorted(by_security.items()):
        missing = sorted(set(expected_sessions) - covered)
        for session in missing:
            found.append(
                _warning(
                    "5.4_missing_bar_in_a_listed_range",
                    "price_bar",
                    f"No bar for {security_id} on session {session.isoformat()}. A "
                    "non-trading day is not a zero.",
                    security_id=security_id,
                    session_date=session,
                )
            )
    return found


def check_adjusted_artifact_hash(
    artifact: AdjustedBarArtifact,
    recomputed_hash: str,
) -> tuple[QualityFinding, ...]:
    """A cache that does not reproduce is a BLOCKING issue, not a cache miss."""
    if artifact.envelope.artifact_content_hash == recomputed_hash:
        return ()
    return (
        _blocking(
            "4.5.1_adjusted_cache_does_not_reproduce",
            "adjusted_bar_artifact",
            f"Artifact {artifact.artifact_id} recomputes to {recomputed_hash}, not to the "
            f"{artifact.envelope.artifact_content_hash} it records.",
        ),
    )


# ---------------------------------------------------------------------------
# 6 -- identity and universe
# ---------------------------------------------------------------------------


def check_ticker_history(rows: Sequence[TickerHistory]) -> tuple[QualityFinding, ...]:
    """One ticker maps to at most one security on any date.

    An overlap makes every join on that ticker ambiguous, which is why it is
    BLOCKING rather than a warning. Tickers are recycled, so a ticker reused by a
    different security **later** is correct and must pass.
    """
    found: list[QualityFinding] = []
    for left in rows:
        for right in rows:
            if left is right or left.ticker != right.ticker:
                continue
            if left.security_id == right.security_id:
                continue
            if _ranges_overlap(left, right):
                pair = tuple(sorted((left.security_id, right.security_id)))
                found.append(
                    _blocking(
                        "6.1_ticker_history_overlap",
                        "ticker_history",
                        f"Ticker {left.ticker!r} maps to both {pair[0]} and {pair[1]} on "
                        "overlapping dates.",
                    )
                )
    return tuple(_dedupe(found))


def _ranges_overlap(left: TickerHistory, right: TickerHistory) -> bool:
    left_end = left.valid_to or date.max
    right_end = right.valid_to or date.max
    return left.valid_from <= right_end and right.valid_from <= left_end


def check_universe_snapshots(
    snapshots: Mapping[date, Sequence[UniverseMembership]],
    *,
    listings: Sequence[Listing],
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    evaluation_cutoffs: Mapping[date, datetime],
) -> tuple[QualityFinding, ...]:
    """Survivorship, profile keying and eligibility-input admissibility.

    Checks 6.3 and 6.4 are deliberately crude, and that is the point: they are the
    smoke alarm for the defect that is otherwise invisible. If an old snapshot
    contains no company that has since disappeared, the data is not historical,
    whatever the vendor calls it.
    """
    dataset = "universe_membership"
    found: list[QualityFinding] = []
    ever_delisted = {listing.security_id for listing in listings if listing.listing_end is not None}

    any_delisted_anywhere = False
    for session, rows in sorted(snapshots.items()):
        members = [row.security_id for row in rows if row.is_member]
        delisted_members = [sid for sid in members if sid in ever_delisted]
        if delisted_members:
            any_delisted_anywhere = True
        elif members:
            found.append(
                _blocking(
                    "6.3_survivorship_leakage",
                    dataset,
                    f"The snapshot for {session.isoformat()} has {len(members)} members and "
                    "none of them has since delisted. A historical universe with no "
                    "subsequent disappearances is not historical.",
                    session_date=session,
                )
            )

        for row in rows:
            if row.resolved_profile is not resolved_profile:
                found.append(
                    _blocking(
                        "6.8_profile_free_or_mismatched_universe",
                        dataset,
                        f"Membership is keyed to {row.resolved_profile.value} while the run "
                        f"resolved to {resolved_profile.value}. Eligibility is evaluated on "
                        "admissible data, so membership is profile-specific.",
                        security_id=row.security_id,
                        session_date=session,
                    )
                )
            cutoff = evaluation_cutoffs.get(session)
            if cutoff is None:
                continue
            for consumed in row.inputs:
                available = decision_available_time(consumed, resolved_profile, approvals)
                if available is None or available > cutoff:
                    found.append(
                        _blocking(
                            "6.6_eligibility_from_inadmissible_data",
                            dataset,
                            "A membership decision consumed an input that was not admissible "
                            f"at the session cutoff {cutoff.isoformat()}. This is how a "
                            "universe quietly gets built from current data.",
                            security_id=row.security_id,
                            session_date=session,
                        )
                    )
                    break

    if snapshots and not any_delisted_anywhere:
        found.append(
            _blocking(
                "6.4_delisted_absence",
                dataset,
                "No delisted security appears in any historical snapshot.",
            )
        )
    return tuple(_dedupe(found))


def check_universe_rebuild(
    original_hash: str,
    rebuilt_hash: str,
) -> tuple[QualityFinding, ...]:
    """A rebuild from the same inputs, rule version and profile must not drift."""
    if original_hash == rebuilt_hash:
        return ()
    return (
        _blocking(
            "6.5_universe_rebuild_drift",
            "universe_membership",
            f"Rebuilding produced {rebuilt_hash} where the stored snapshot records "
            f"{original_hash}. Drift means the rule read something it did not declare.",
        ),
    )


def _dedupe(findings: Sequence[QualityFinding]) -> list[QualityFinding]:
    seen: set[tuple[str, str, str]] = set()
    out: list[QualityFinding] = []
    for finding in findings:
        key = (finding.check_name, finding.dataset, finding.detail)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def blocking_findings(findings: Sequence[QualityFinding]) -> tuple[QualityFinding, ...]:
    """Only the findings that refuse a result."""
    return tuple(f for f in findings if f.is_blocking)


__all__ = [
    "DEFAULT_MARKET_THRESHOLDS",
    "MarketDataThresholds",
    "QualityFinding",
    "blocking_findings",
    "check_adjusted_artifact_hash",
    "check_envelope",
    "check_price_bars",
    "check_profile_service",
    "check_run_identity_inputs",
    "check_stored_envelope_shape",
    "check_temporal_invariants",
    "check_ticker_history",
    "check_universe_rebuild",
    "check_universe_snapshots",
]
