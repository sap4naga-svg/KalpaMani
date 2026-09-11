"""The point-in-time reality gate: stage one of the Brain, before any strategy logic.

Specification section 4. It establishes that the world was knowable as of the
decision instant and refuses otherwise. It never substitutes a value for
missing evidence: a zero standing in for an unknown reads downstream as a
measurement, and every later check treats it as one. So every refusal here is
a reason code, and none is a default.

What it checks over the kernel results a caller supplies:

* the price result answered *this* security, at the required resolution and
  adjustment mode, under a point-in-time profile, at *this* ``as_of`` -- a
  result carrying a different question is not admissible evidence for this one;
* the result did not silently downgrade its information profile, and carries no
  non-point-in-time limitation;
* the bars are strictly ordered, unique, finite and positive, and none is dated
  after the decision instant;
* the series ends on the evaluation session -- a series that stops earlier is
  stale, not "the most recent available";
* where a benchmark is required, its session grid matches the security's over
  their overlap -- a relative comparison over two different windows is not one;
* every declared-required context (universe, event, market permission, AI,
  short) resolved, with the universe snapshot taken for the evaluation session
  and the event coverage reaching the holding horizon;
* lineage and a quality-report identity are present.

It returns a :class:`GateOutcome`: either the admitted, ordered bars and the
resolved coverage, or the first blocking reason with the state it maps to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.data.contracts.vocabulary import (
    AdjustmentMode,
    BarResolution,
    InformationSetProfile,
    LimitationToken,
)
from kalpamani.data.pit.accessors import BarSeriesResult, UniverseSnapshotResult
from kalpamani.strategies.brain.evidence import EvaluationInputs
from kalpamani.strategies.brain.spec import StrategySpec
from kalpamani.strategies.brain.vocabulary import (
    DataDomain,
    DecisionState,
    EvidenceState,
    MarketPermission,
    ReasonCode,
    Requirement,
)

#: Profiles that answer a point-in-time question. ``FORWARD_SYSTEM`` is what
#: KalpaMani actually held, not what was knowable, so it is not admissible here.
_POINT_IN_TIME_PROFILES = frozenset(
    {InformationSetProfile.PUBLIC_PIT, InformationSetProfile.PROVIDER_REALISTIC_PIT}
)

#: Limitation tokens that mark a result as not point-in-time. Their presence is
#: a refusal, not a footnote.
_NON_POINT_IN_TIME_LIMITATIONS = frozenset(
    {LimitationToken.NON_PIT_RESTATED_VIEW, LimitationToken.PROFILE_DOWNGRADED_TO_PUBLIC}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GateOutcome:
    """The gate's verdict. Exactly one of ``bars``/``coverage`` or ``reason`` is set."""

    admitted: bool
    reason: ReasonCode | None = None
    state: DecisionState | None = None
    bars: tuple[PriceBarValues, ...] = ()
    benchmark_bars: tuple[PriceBarValues, ...] = ()
    resolved_profile: InformationSetProfile | None = None

    @classmethod
    def blocked(cls, reason: ReasonCode, state: DecisionState) -> GateOutcome:
        return cls(admitted=False, reason=reason, state=state)


def _blocked_bars(
    bars: tuple[PriceBarValues, ...],
    *,
    security_id: str,
    as_of: datetime,
    evaluation_session: date,
) -> ReasonCode | None:
    """The first structural defect in a bar series, or ``None`` if it is intact."""
    if not bars:
        return ReasonCode.EVIDENCE_MISSING
    previous: PriceBarValues | None = None
    for bar in bars:
        if bar.security_id != security_id:
            return ReasonCode.SECURITY_MISMATCH
        if bar.bar_end_time > as_of:
            return ReasonCode.OBSERVATION_AFTER_AS_OF
        for price in (bar.open, bar.high, bar.low, bar.close):
            if not price.is_finite() or price <= 0:
                return ReasonCode.INVALID_BAR_VALUES
        if bar.volume < 0:
            return ReasonCode.INVALID_BAR_VALUES
        if not (bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high):
            return ReasonCode.INVALID_BAR_VALUES
        if previous is not None:
            if bar.session_date == previous.session_date:
                return ReasonCode.DUPLICATE_OBSERVATION
            if bar.session_date < previous.session_date:
                return ReasonCode.OBSERVATIONS_MISORDERED
        previous = bar
    if bars[-1].session_date != evaluation_session:
        return ReasonCode.STALE_PRICE_HISTORY
    return None


def _blocked_price_result(
    result: BarSeriesResult,
    *,
    security_id: str,
    resolution: BarResolution,
    adjustment_mode: AdjustmentMode,
    required_profile: InformationSetProfile,
    as_of: datetime,
) -> ReasonCode | None:
    """The first reason the price result is not admissible evidence, or ``None``."""
    provenance = result.provenance
    if result.security_id != security_id:
        return ReasonCode.SECURITY_MISMATCH
    if result.resolution is not resolution:
        return ReasonCode.RESOLUTION_MISMATCH
    if result.adjustment_mode != adjustment_mode:
        return ReasonCode.ADJUSTMENT_MODE_MISMATCH
    if provenance.requested_profile is not required_profile:
        return ReasonCode.PROFILE_MISMATCH
    if provenance.resolved_profile not in _POINT_IN_TIME_PROFILES:
        return ReasonCode.PROFILE_MISMATCH
    if provenance.was_downgraded:
        return ReasonCode.PROFILE_DOWNGRADED
    if provenance.as_of != as_of:
        return ReasonCode.EVIDENCE_AS_OF_MISMATCH
    if any(token in _NON_POINT_IN_TIME_LIMITATIONS for token in provenance.limitations):
        return ReasonCode.NON_POINT_IN_TIME_LIMITATION
    if not provenance.dataset_version or not provenance.manifest_hash:
        return ReasonCode.LINEAGE_INCOMPLETE
    if not provenance.quality_report_hash:
        return ReasonCode.QUALITY_EVIDENCE_MISSING
    return None


def _blocked_universe(
    universe: UniverseSnapshotResult | None,
    *,
    requirement: Requirement,
    security_id: str,
    evaluation_session: date,
    as_of: datetime,
    required_profile: InformationSetProfile,
) -> tuple[ReasonCode, DecisionState] | None:
    if requirement is not Requirement.REQUIRED:
        return None
    if universe is None:
        return (ReasonCode.EVIDENCE_MISSING, DecisionState.BLOCKED_DATA)
    provenance = universe.provenance
    if provenance.as_of != as_of:
        return (ReasonCode.EVIDENCE_AS_OF_MISMATCH, DecisionState.BLOCKED_DATA)
    if provenance.requested_profile is not required_profile or provenance.was_downgraded:
        return (ReasonCode.PROFILE_MISMATCH, DecisionState.BLOCKED_DATA)
    if universe.session_date != evaluation_session:
        return (ReasonCode.UNIVERSE_SNAPSHOT_SESSION_MISMATCH, DecisionState.BLOCKED_DATA)
    if security_id not in universe.members:
        return (ReasonCode.UNIVERSE_NON_MEMBER, DecisionState.REJECTED)
    return None


def _blocked_event(
    inputs: EvaluationInputs,
    *,
    requirement: Requirement,
    horizon_last_session: date,
) -> tuple[ReasonCode, DecisionState] | None:
    if requirement is Requirement.NOT_APPLICABLE:
        return None
    event = inputs.event_context
    if event is None:
        if requirement is Requirement.REQUIRED:
            return (ReasonCode.EVENT_EVIDENCE_UNRESOLVED, DecisionState.BLOCKED_DATA)
        return None
    if event.state is EvidenceState.UNAVAILABLE:
        return (ReasonCode.EVENT_EVIDENCE_UNRESOLVED, DecisionState.BLOCKED_DATA)
    if event.as_of != inputs.as_of_time:
        return (ReasonCode.EVIDENCE_AS_OF_MISMATCH, DecisionState.BLOCKED_DATA)
    # An absence of a known event is evidence only as far ahead as the source saw.
    if (
        event.coverage_through_session is None
        or event.coverage_through_session < horizon_last_session
    ):
        return (ReasonCode.EVENT_EVIDENCE_UNRESOLVED, DecisionState.BLOCKED_DATA)
    return None


def _blocked_market(
    inputs: EvaluationInputs, *, requirement: Requirement
) -> tuple[ReasonCode, DecisionState] | None:
    if requirement is Requirement.NOT_APPLICABLE:
        return None
    context = inputs.market_context
    if context is None:
        if requirement is Requirement.REQUIRED:
            return (ReasonCode.MARKET_CONTEXT_UNRESOLVED, DecisionState.BLOCKED_DATA)
        return None
    if context.as_of != inputs.as_of_time:
        return (ReasonCode.EVIDENCE_AS_OF_MISMATCH, DecisionState.BLOCKED_DATA)
    return None


def run_reality_gate(inputs: EvaluationInputs, spec: StrategySpec) -> GateOutcome:
    """Run the point-in-time reality gate for one evaluation. Returns a :class:`GateOutcome`.

    The order of checks is deliberate: the price result's admissibility comes
    first, because a result that answered a different question is not evidence
    for this one, and there is nothing to inspect inside it until that holds.
    """
    data = spec.data
    price_series = inputs.price_history
    price_reason = _blocked_price_result(
        price_series,
        security_id=inputs.security_id,
        resolution=data.resolution,
        adjustment_mode=data.adjustment_mode,
        required_profile=data.required_profile,
        as_of=inputs.as_of_time,
    )
    if price_reason is not None:
        return GateOutcome.blocked(price_reason, DecisionState.BLOCKED_DATA)

    bars = tuple(price_series.bars)
    bar_reason = _blocked_bars(
        bars,
        security_id=inputs.security_id,
        as_of=inputs.as_of_time,
        evaluation_session=inputs.evaluation_session,
    )
    if bar_reason is not None:
        return GateOutcome.blocked(bar_reason, DecisionState.BLOCKED_DATA)

    benchmark_bars: tuple[PriceBarValues, ...] = ()
    if DataDomain.BENCHMARK_BARS in data.required_domains:
        if inputs.benchmark_history is None:
            return GateOutcome.blocked(ReasonCode.EVIDENCE_MISSING, DecisionState.BLOCKED_DATA)
        benchmark_series = inputs.benchmark_history
        benchmark_reason = _blocked_price_result(
            benchmark_series,
            security_id=benchmark_series.security_id,
            resolution=data.resolution,
            adjustment_mode=data.adjustment_mode,
            required_profile=data.required_profile,
            as_of=inputs.as_of_time,
        )
        if benchmark_reason is not None:
            return GateOutcome.blocked(benchmark_reason, DecisionState.BLOCKED_DATA)
        benchmark_bars = tuple(benchmark_series.bars)
        benchmark_bar_reason = _blocked_bars(
            benchmark_bars,
            security_id=benchmark_series.security_id,
            as_of=inputs.as_of_time,
            evaluation_session=inputs.evaluation_session,
        )
        if benchmark_bar_reason is not None:
            return GateOutcome.blocked(benchmark_bar_reason, DecisionState.BLOCKED_DATA)
        if _session_grids_differ(bars, benchmark_bars):
            return GateOutcome.blocked(ReasonCode.SESSION_GRID_MISMATCH, DecisionState.BLOCKED_DATA)

    universe_block = _blocked_universe(
        inputs.universe,
        requirement=(
            Requirement.REQUIRED
            if DataDomain.UNIVERSE_MEMBERSHIP in data.required_domains
            else Requirement.NOT_APPLICABLE
        ),
        security_id=inputs.security_id,
        evaluation_session=inputs.evaluation_session,
        as_of=inputs.as_of_time,
        required_profile=data.required_profile,
    )
    if universe_block is not None:
        return GateOutcome.blocked(*universe_block)

    horizon_last = forward_horizon_session(inputs.evaluation_session, spec.maximum_holding_sessions)
    event_block = _blocked_event(
        inputs, requirement=spec.permissions.event_prerequisite, horizon_last_session=horizon_last
    )
    if event_block is not None:
        return GateOutcome.blocked(*event_block)

    market_block = _blocked_market(inputs, requirement=spec.permissions.market_prerequisite)
    if market_block is not None:
        return GateOutcome.blocked(*market_block)

    return GateOutcome(
        admitted=True,
        bars=bars,
        benchmark_bars=benchmark_bars,
        resolved_profile=price_series.provenance.resolved_profile,
    )


def _session_grids_differ(
    bars: tuple[PriceBarValues, ...], benchmark_bars: tuple[PriceBarValues, ...]
) -> bool:
    """Whether the two series disagree about which sessions they cover, where they overlap.

    A relative-strength comparison is a comparison of the same sessions. The
    trailing overlap of the two grids -- both already end on the evaluation
    session -- must be session-for-session identical; a benchmark that skips a
    session the security traded, or vice versa, would make a trailing-return
    comparison a comparison of two different windows.
    """
    overlap = min(len(bars), len(benchmark_bars))
    security_grid = tuple(bar.session_date for bar in bars[-overlap:])
    benchmark_grid = tuple(bar.session_date for bar in benchmark_bars[-overlap:])
    return security_grid != benchmark_grid


def forward_horizon_session(evaluation_session: date, maximum_holding_sessions: int) -> date:
    """A conservative calendar bound on the last date the holding horizon can reach.

    **An approximation, and stated as one.** The Brain holds historical bars, not
    a forward exchange calendar, so it cannot know the exact date
    ``maximum_holding_sessions`` trading days ahead. Trading days span roughly
    seven calendar days for every five, and holidays lengthen that further, so
    the bound converts sessions to calendar days at 7/5 and adds a fixed cushion.
    It errs long on purpose: an event just beyond a too-short bound would be
    carried through, which is the failure section 19 forbids, whereas erring long
    only defers a candidate to the watchlist.
    """
    calendar_days = (maximum_holding_sessions * 7 + 4) // 5 + 5
    return evaluation_session + timedelta(days=calendar_days)


def market_permission_for(
    context_permission: MarketPermission | None,
) -> tuple[ReasonCode, DecisionState] | None:
    """Translate a resolved market permission into a stage-10 outcome, or ``None`` to pass.

    Kept here beside the gate because it reads the same context, but applied by
    the compiler at stage ten rather than by the gate: a denied or deferred
    market is not a data problem, it is a permission decision.
    """
    if context_permission is None or context_permission is MarketPermission.PERMITTED:
        return None
    if context_permission is MarketPermission.DEFERRED:
        return (ReasonCode.MARKET_ENTRY_DEFERRED, DecisionState.WATCHLIST)
    return (ReasonCode.MARKET_PERMISSION_DENIED, DecisionState.REJECTED)


__all__ = [
    "GateOutcome",
    "forward_horizon_session",
    "market_permission_for",
    "run_reality_gate",
]
