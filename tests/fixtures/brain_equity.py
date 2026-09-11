"""Synthetic fixtures for the offline equity Brain path.

Small, deliberately constructed and clearly labelled. **None of this is market
history.** The closes and volumes are round placeholder numbers chosen to place
a scenario on one side or the other of a boundary; they are not real prices,
they carry no economic claim, and nothing here is calibrated against anything.

The builders return the kernel's own :class:`BarSeriesResult` and
:class:`UniverseSnapshotResult` -- the same types a
:class:`~kalpamani.data.pit.accessors.PointInTimeReader` returns -- plus the
Brain's own context records. Everything is constructed with an explicit,
injected ``as_of`` and evaluation session, so a test never depends on a clock.

The reduced ``TEST_PARAMS`` window (a handful of sessions rather than the
module's default 252) is a fixture convenience, stated openly: the Breakout Long
parameters are research parameters, and a smaller lookback keeps a fixture to a
readable number of bars. The module's real default window is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from kalpamani.common.environment import Environment
from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentMode,
    AdjustmentPolicy,
    BarResolution,
    InformationSetProfile,
    LimitationToken,
    RevisionView,
)
from kalpamani.data.pit.accessors import BarSeriesResult, ResultProvenance, UniverseSnapshotResult
from kalpamani.strategies.brain.evidence import (
    AiEvidenceRecord,
    EvaluationInputs,
    EventContext,
    MarketPermissionContext,
    ShortContext,
)
from kalpamani.strategies.brain.vocabulary import (
    BorrowAvailability,
    BorrowFeeState,
    ChallengerVerdict,
    EventTimestampQuality,
    EvidenceState,
    MarketPermission,
    RecallRiskState,
    ShortSaleRestrictionState,
    SqueezeState,
)
from kalpamani.strategies.breakout.long import BreakoutLongParameters

SECURITY_ID = "SEC-TGT"
BENCHMARK_ID = "SEC-BENCH"
PROFILE = InformationSetProfile.PROVIDER_REALISTIC_PIT
ADJUSTMENT = AdjustmentMode.adjusted(
    AdjustmentPolicy.SPLIT_ONLY, AdjustmentConvention.FORWARD_BASE_NORMALIZED
)
DATASET_VERSION = "gold/synthetic.brain.1"
MANIFEST_HASH = "sha256:" + "a1" * 32
QUALITY_REPORT_HASH = "sha256:" + "b2" * 32
UNIVERSE_DEFINITION_VERSION = "universe/synthetic.brain.1"
SNAPSHOT_ARTIFACT_ID = "art-synthetic-brain-1"
SNAPSHOT_CONTENT_HASH = "sha256:" + "c3" * 32

#: A small research window, so a fixture is a readable number of bars. The
#: module's production default (252-session high proximity) is unchanged.
TEST_PARAMS = BreakoutLongParameters(
    trend_sessions=10,
    base_sessions=5,
    relative_strength_sessions=10,
    volume_baseline_sessions=5,
    liquidity_sessions=5,
    high_proximity_sessions=10,
)

_FIRST_SESSION = date(2021, 1, 4)
_BASE_VOLUME = 100_000
_BREAKOUT_VOLUME = 300_000
_BASE_CLOSE = Decimal("100")
_BREAKOUT_CLOSE = Decimal("101")


def _session(index: int) -> date:
    """The index-th synthetic session. Weekends are skipped so dates read plausibly."""
    day = _FIRST_SESSION
    seen = 0
    while True:
        if day.weekday() < 5:
            if seen == index:
                return day
            seen += 1
        day += timedelta(days=1)


def _bar(security_id: str, index: int, close: Decimal, volume: int) -> PriceBarValues:
    session = _session(index)
    return PriceBarValues(
        security_id=security_id,
        session_date=session,
        bar_end_time=datetime(session.year, session.month, session.day, 21, tzinfo=UTC),
        open=close,
        high=close + Decimal("0.5"),
        low=close - Decimal("0.5"),
        close=close,
        volume=volume,
    )


def _as_of_for(last_index: int) -> datetime:
    """A decision instant after the evaluation session closes."""
    session = _session(last_index)
    return datetime(session.year, session.month, session.day, 23, tzinfo=UTC)


def _provenance(
    as_of: datetime,
    *,
    resolved: InformationSetProfile | None = None,
    limitations: tuple[LimitationToken, ...] = (),
) -> ResultProvenance:
    return ResultProvenance(
        dataset_version=DATASET_VERSION,
        manifest_hash=MANIFEST_HASH,
        quality_report_hash=QUALITY_REPORT_HASH,
        as_of=as_of,
        requested_profile=PROFILE,
        resolved_profile=resolved or PROFILE,
        revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
        limitations=limitations,
        resolution=BarResolution.DAILY,
        adjustment_convention=AdjustmentConvention.FORWARD_BASE_NORMALIZED,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Scenario:
    """A whole synthetic evaluation, and the pieces to vary it for negative controls."""

    inputs: EvaluationInputs
    params: BreakoutLongParameters
    security_bars: tuple[PriceBarValues, ...]
    benchmark_bars: tuple[PriceBarValues, ...]
    evaluation_session: date
    as_of: datetime


def _security_closes(params: BreakoutLongParameters, breakout_close: Decimal) -> list[Decimal]:
    """A rising trend, then a compact flat base, then one breakout bar.

    The rising leg guarantees the evaluation close sits above its moving average
    and above the benchmark; the flat base is compact and its high is the level
    the breakout clears.
    """
    rise = max(params.trend_sessions, params.relative_strength_sessions) + 1
    closes = [Decimal("80") + Decimal("2") * Decimal(i) for i in range(rise)]
    closes += [_BASE_CLOSE] * params.base_sessions
    closes.append(breakout_close)
    return closes


def build_scenario(
    *,
    params: BreakoutLongParameters = TEST_PARAMS,
    breakout_close: Decimal = _BREAKOUT_CLOSE,
    breakout_volume: int = _BREAKOUT_VOLUME,
    environment: Environment = Environment.RESEARCH,
    with_event: bool = True,
    next_event_session: date | None = None,
    with_market: bool = True,
    market_long: MarketPermission = MarketPermission.PERMITTED,
    with_universe: bool = True,
    universe_member: bool = True,
    with_ai: bool = False,
    ai: AiEvidenceRecord | None = None,
) -> Scenario:
    """The canonical eligible-and-triggered scenario, with switches for the negative cases."""
    closes = _security_closes(params, breakout_close)
    volumes = [_BASE_VOLUME] * (len(closes) - 1) + [breakout_volume]
    security_bars = tuple(
        _bar(SECURITY_ID, i, close, volume)
        for i, (close, volume) in enumerate(zip(closes, volumes, strict=True))
    )
    benchmark_bars = tuple(
        _bar(BENCHMARK_ID, i, Decimal("100"), _BASE_VOLUME) for i in range(len(closes))
    )
    last_index = len(closes) - 1
    evaluation_session = _session(last_index)
    as_of = _as_of_for(last_index)

    price = BarSeriesResult(
        security_id=SECURITY_ID,
        resolution=BarResolution.DAILY,
        adjustment_mode=ADJUSTMENT,
        bars=security_bars,
        provenance=_provenance(as_of),
    )
    benchmark = BarSeriesResult(
        security_id=BENCHMARK_ID,
        resolution=BarResolution.DAILY,
        adjustment_mode=ADJUSTMENT,
        bars=benchmark_bars,
        provenance=_provenance(as_of),
    )
    universe = (
        UniverseSnapshotResult(
            session_date=evaluation_session,
            universe_definition_version=UNIVERSE_DEFINITION_VERSION,
            members=(SECURITY_ID,) if universe_member else (),
            non_members=() if universe_member else (SECURITY_ID,),
            provenance=_provenance(as_of),
            snapshot_content_hash=SNAPSHOT_CONTENT_HASH,
            snapshot_artifact_id=SNAPSHOT_ARTIFACT_ID,
        )
        if with_universe
        else None
    )
    event = (
        EventContext(
            state=EvidenceState.RESOLVED,
            as_of=as_of,
            source_reference="events/synthetic.brain.1",
            coverage_through_session=evaluation_session + timedelta(days=400),
            next_event_session=next_event_session,
            timestamp_quality=EventTimestampQuality.DATE_ONLY,
        )
        if with_event
        else None
    )
    market = (
        MarketPermissionContext(
            version="regime/synthetic.brain.1",
            as_of=as_of,
            regime_reference="regime/bull",
            permission_long=market_long,
            permission_short=MarketPermission.DENIED,
        )
        if with_market
        else None
    )
    ai_record = ai if ai is not None else (fresh_ai(as_of) if with_ai else None)
    inputs = EvaluationInputs(
        as_of_time=as_of,
        environment=environment,
        security_id=SECURITY_ID,
        evaluation_session=evaluation_session,
        price_history=price,
        benchmark_history=benchmark,
        universe=universe,
        event_context=event,
        market_context=market,
        ai_evidence=ai_record,
    )
    return Scenario(
        inputs=inputs,
        params=params,
        security_bars=security_bars,
        benchmark_bars=benchmark_bars,
        evaluation_session=evaluation_session,
        as_of=as_of,
    )


def with_price(scenario: Scenario, price: BarSeriesResult) -> Scenario:
    """A copy of ``scenario`` whose price result is replaced."""
    return replace(scenario, inputs=replace(scenario.inputs, price_history=price))


def fresh_ai(as_of: datetime) -> AiEvidenceRecord:
    """A complete, well-formed AI record whose evidence predates the decision instant."""
    return AiEvidenceRecord(
        research_output_reference="ai/research/synthetic.1",
        challenger_output_reference="ai/challenger/synthetic.1",
        source_publish_time=as_of - timedelta(hours=6),
        produced_at=as_of - timedelta(hours=1),
        model_version="model/synthetic.1",
        prompt_version="prompt/synthetic.1",
        schema_version="schema/synthetic.1",
        confidence=Decimal("0.6"),
        evidence_quality=Decimal("0.7"),
        challenger_verdict=ChallengerVerdict.NOT_FALSIFIED,
    )


def qualified_short_context(as_of: datetime) -> ShortContext:
    """A fully qualified short context, for the short-path tests."""
    return ShortContext(
        as_of=as_of,
        evidence_reference="borrow/synthetic.1",
        borrow_availability=BorrowAvailability.AVAILABLE,
        borrow_fee=BorrowFeeState.NORMAL,
        squeeze=SqueezeState.NORMAL,
        short_sale_restriction=ShortSaleRestrictionState.NOT_IN_EFFECT,
        recall_risk=RecallRiskState.LOW,
    )


def unknown_short_context(as_of: datetime) -> ShortContext:
    """A short context whose borrow availability is unknown -- the gate blocks on it."""
    return ShortContext(
        as_of=as_of,
        evidence_reference="borrow/synthetic.unknown",
        borrow_availability=BorrowAvailability.UNKNOWN,
        borrow_fee=BorrowFeeState.UNKNOWN,
        squeeze=SqueezeState.UNKNOWN,
        short_sale_restriction=ShortSaleRestrictionState.UNKNOWN,
        recall_risk=RecallRiskState.UNKNOWN,
    )


__all__ = [
    "ADJUSTMENT",
    "BENCHMARK_ID",
    "PROFILE",
    "SECURITY_ID",
    "TEST_PARAMS",
    "Scenario",
    "build_scenario",
    "fresh_ai",
    "qualified_short_context",
    "unknown_short_context",
    "with_price",
]
