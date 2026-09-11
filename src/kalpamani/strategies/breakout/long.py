"""Breakout Long -- the first equity module, research-stage.

Economic premise, **a hypothesis and nothing more**: momentum continuation --
that a security breaking out of a compact base with relative strength and
volume tends to continue. The specification (section 17.1) names six concepts;
this module realises each as a deterministic, point-in-time test:

    strong trend                -> evaluation close above its N-session average
    compact base or resistance  -> the prior base range is no wider than a bound,
                                    and its high is the resistance to clear
    relative or residual        -> the security's trailing return exceeds the
      strength                      benchmark's over the same window
    price confirmation          -> the evaluation close is strictly above the
                                    base high  (the entry boundary)
    volume confirmation         -> evaluation-bar volume exceeds a multiple of
                                    the base's average volume
    acceptable event / gap      -> the entry bar's own overnight gap is within a
      context                       bound  (the wider event rule is the compiler's)

**Every threshold here is a proposed research parameter, not an accepted
production rule.** They live in :class:`BreakoutLongParameters` with deliberately
plain, conservative placeholder values, and the module's ``StrategySpec`` is a
``REGISTERED_HYPOTHESIS`` authorizing the ``RESEARCH`` environment and no other.
Nothing in this module has been calibrated against market data, and **no alpha
is claimed**: the numbers exist so the offline path has something concrete to
run, and the evaluation protocol (`docs/phase4/equity-evaluation-protocol.md`)
is where they would be tested.

The module answers eligibility and the trigger. It does not size, does not
route, does not construct a protective order from the invalidation level, and
does not decide the market or borrow context -- those are the compiler's later
stages and execution's work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from kalpamani.common.environment import Environment
from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentMode,
    AdjustmentPolicy,
    BarResolution,
    InformationSetProfile,
    RevisionView,
)
from kalpamani.strategies.brain import factors
from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.factors import FactorDefinition, FactorValue
from kalpamani.strategies.brain.identity import require_finite_decimal, require_identifier
from kalpamani.strategies.brain.module import ModuleEvaluation, TemplateTrigger
from kalpamani.strategies.brain.spec import (
    DataRequirements,
    Permissions,
    ResearchGovernance,
    RiskTags,
    StrategySpec,
)
from kalpamani.strategies.brain.vocabulary import (
    AlphaFamily,
    DataDomain,
    Direction,
    EntryCondition,
    FactorFamily,
    InvalidationCondition,
    LifecycleStage,
    ModuleVerdict,
    ReasonCode,
    Requirement,
    StopReferenceKind,
)

#: The one adjustment mode the A1 kernel computes today. Split-only, forward
#: base normalised. Whether dividend or total-return adjustment is the right
#: basis for a momentum breakout is a proposed decision, not one made here.
_ADJUSTMENT_MODE: Final = AdjustmentMode.adjusted(
    AdjustmentPolicy.SPLIT_ONLY, AdjustmentConvention.FORWARD_BASE_NORMALIZED
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BreakoutLongParameters:
    """Proposed research parameters for Breakout Long. **Not accepted production rules.**

    Every value is a placeholder chosen to be plainly conservative and round,
    so that no reader mistakes it for a calibrated result. The session counts
    determine how much history the module reads; the ratios determine where its
    boundaries sit. All of them are the subject of the evaluation protocol's
    experiment ledger, and none has been tested.
    """

    trend_sessions: int = 50
    base_sessions: int = 20
    relative_strength_sessions: int = 60
    volume_baseline_sessions: int = 20
    liquidity_sessions: int = 20
    high_proximity_sessions: int = 252
    #: The base is "compact" when (high - low) / high does not exceed this.
    max_base_compactness: Decimal = field(default_factory=lambda: Decimal("0.15"))
    #: Volume "confirms" when evaluation volume / base-average volume is at least this.
    min_relative_volume: Decimal = field(default_factory=lambda: Decimal("1.5"))
    #: Relative strength "confirms" when the security's trailing return exceeds the
    #: benchmark's by at least this fraction over `relative_strength_sessions`.
    min_relative_strength: Decimal = field(default_factory=lambda: Decimal("0.0"))
    #: The entry bar's own overnight gap must not exceed this absolute fraction.
    max_entry_gap: Decimal = field(default_factory=lambda: Decimal("0.10"))
    #: Minimum average dollar volume over the base, a liquidity floor.
    min_average_dollar_volume: Decimal = field(default_factory=lambda: Decimal("1000000"))

    def __post_init__(self) -> None:
        for name in (
            "trend_sessions",
            "base_sessions",
            "relative_strength_sessions",
            "volume_baseline_sessions",
            "liquidity_sessions",
            "high_proximity_sessions",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise BrainContractError(f"{name} must be a positive integer of sessions.")
        # The ratios are compared against ``Decimal`` factor values, so they are
        # finite ``Decimal`` too: a float here would be the one float the Brain
        # promises never enters, and it would also change the parameters hash.
        for name in (
            "max_base_compactness",
            "min_relative_volume",
            "min_relative_strength",
            "max_entry_gap",
            "min_average_dollar_volume",
        ):
            require_finite_decimal(getattr(self, name), field=name)
        if self.max_base_compactness < 0 or self.max_entry_gap < 0:
            raise BrainContractError("Absolute-fraction bounds cannot be negative.")
        if self.min_relative_volume <= 0 or self.min_average_dollar_volume < 0:
            raise BrainContractError("Volume and liquidity floors must be non-negative ratios.")

    @property
    def required_history_sessions(self) -> int:
        """The deepest window any factor needs, plus the evaluation bar."""
        return max(
            self.trend_sessions,
            self.base_sessions + 1,
            self.relative_strength_sessions + 1,
            self.volume_baseline_sessions + 1,
            self.liquidity_sessions + 1,
            self.high_proximity_sessions,
        )


#: A stable, greppable identity for the research version. The parameters hash is
#: derived from the placeholder values, so a change to any of them is a new
#: version rather than an edit in place.
STRATEGY_ID: Final = "breakout-long"
STRATEGY_MODULE_NAME: Final = "breakout-long"
TRADE_TEMPLATE: Final = "base-breakout-close-confirmation"
FACTOR_DEFINITION_VERSION: Final = "breakout-long.factors/r1"
_VERSION: Final = "breakout-long/r1-research"


def _factor_definitions(params: BreakoutLongParameters) -> tuple[FactorDefinition, ...]:
    """The pinned factor set this version depends on."""
    v = FACTOR_DEFINITION_VERSION
    return (
        FactorDefinition(
            factor_id="trend-ma-close",
            version=v,
            family=FactorFamily.PRICE_MOMENTUM,
            lookback_sessions=params.trend_sessions,
        ),
        FactorDefinition(
            factor_id="relative-strength",
            version=v,
            family=FactorFamily.PRICE_MOMENTUM,
            lookback_sessions=params.relative_strength_sessions + 1,
        ),
        FactorDefinition(
            factor_id="high-proximity",
            version=v,
            family=FactorFamily.PRICE_MOMENTUM,
            lookback_sessions=params.high_proximity_sessions,
        ),
        FactorDefinition(
            factor_id="base-compactness",
            version=v,
            family=FactorFamily.PRICE_VOLUME_QUALITY,
            lookback_sessions=params.base_sessions + 1,
        ),
        FactorDefinition(
            factor_id="relative-volume",
            version=v,
            family=FactorFamily.PRICE_VOLUME_QUALITY,
            lookback_sessions=params.volume_baseline_sessions + 1,
        ),
        FactorDefinition(
            factor_id="entry-gap",
            version=v,
            family=FactorFamily.RISK_CONTEXT,
            lookback_sessions=2,
        ),
        FactorDefinition(
            factor_id="average-dollar-volume",
            version=v,
            family=FactorFamily.PRICE_VOLUME_QUALITY,
            lookback_sessions=params.liquidity_sessions + 1,
        ),
    )


def build_spec(params: BreakoutLongParameters | None = None) -> StrategySpec:
    """The research-stage ``StrategySpec`` for Breakout Long.

    ``REGISTERED_HYPOTHESIS``, authorizing ``RESEARCH`` only. It cannot be
    constructed authorizing ``PAPER`` or ``LIVE`` from this stage -- the spec
    contract refuses it -- so this version can never produce an order-eligible
    candidate no matter how its parameters are tuned.
    """
    params = params or BreakoutLongParameters()
    definitions = _factor_definitions(params)
    return StrategySpec(
        strategy_id=STRATEGY_ID,
        alpha_family=AlphaFamily.MOMENTUM_CONTINUATION,
        strategy_module=STRATEGY_MODULE_NAME,
        trade_template=TRADE_TEMPLATE,
        version=_VERSION,
        lifecycle_stage=LifecycleStage.REGISTERED_HYPOTHESIS,
        authorized_environments=frozenset({Environment.RESEARCH}),
        direction=Direction.LONG,
        expected_holding_sessions=10,
        minimum_holding_sessions=2,
        maximum_holding_sessions=30,
        data=DataRequirements(
            required_profile=InformationSetProfile.PROVIDER_REALISTIC_PIT,
            revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
            adjustment_mode=_ADJUSTMENT_MODE,
            resolution=BarResolution.DAILY,
            required_domains=frozenset(
                {
                    DataDomain.PRICE_BARS,
                    DataDomain.BENCHMARK_BARS,
                    DataDomain.UNIVERSE_MEMBERSHIP,
                    DataDomain.EVENT_CALENDAR,
                    DataDomain.MARKET_PERMISSION,
                }
            ),
            optional_domains=frozenset({DataDomain.AI_RESEARCH}),
            required_history_sessions=params.required_history_sessions,
        ),
        permissions=Permissions(
            market_prerequisite=Requirement.REQUIRED,
            event_prerequisite=Requirement.REQUIRED,
            gap_prerequisite=Requirement.REQUIRED,
            borrow_prerequisite=Requirement.NOT_APPLICABLE,
            ai_requirement=Requirement.OPTIONAL,
            rank_requirement=Requirement.OPTIONAL,
        ),
        factor_definitions=definitions,
        factor_definition_version=FACTOR_DEFINITION_VERSION,
        parameters_hash=_parameters_hash(params),
        manifest_version="breakout-long.manifest/r1",
        configuration_identity="breakout-long.config/r1-research",
        model_version=None,
        prompt_version=None,
        risk_tags=RiskTags(
            family_exposure=AlphaFamily.MOMENTUM_CONTINUATION,
            factor_exposures=(
                FactorFamily.PRICE_MOMENTUM,
                FactorFamily.PRICE_VOLUME_QUALITY,
                FactorFamily.RISK_CONTEXT,
            ),
            capacity_reference="breakout-long.capacity/unmeasured",
            risk_policy_compatibility="momentum-continuation.long/r1",
        ),
        research=ResearchGovernance(
            hypothesis_id="H-breakout-long-continuation",
            baseline_id="ranked-entry-baseline",
            trial_budget=1,
            success_criteria_reference="protocol.breakout-long.success/unset",
            failure_criteria_reference="protocol.breakout-long.failure/unset",
        ),
    )


def _parameters_hash(params: BreakoutLongParameters) -> str:
    """A greppable identity for the exact placeholder values, so a change is a new version."""
    import hashlib

    payload = "|".join(
        f"{name}={getattr(params, name)}"
        for name in (
            "trend_sessions",
            "base_sessions",
            "relative_strength_sessions",
            "volume_baseline_sessions",
            "liquidity_sessions",
            "high_proximity_sessions",
            "max_base_compactness",
            "min_relative_volume",
            "min_relative_strength",
            "max_entry_gap",
            "min_average_dollar_volume",
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"breakout-long.params/{digest}"


class BreakoutLong:
    """The Breakout Long module. Deterministic, offline, research-stage."""

    def __init__(self, params: BreakoutLongParameters | None = None) -> None:
        self._params = params or BreakoutLongParameters()
        self._spec = build_spec(self._params)

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    @property
    def parameters(self) -> BreakoutLongParameters:
        return self._params

    def evaluate(
        self,
        bars: tuple[PriceBarValues, ...],
        benchmark: tuple[PriceBarValues, ...],
    ) -> ModuleEvaluation:
        """Evaluate eligibility and the breakout template over the admitted bars.

        ``bars`` and ``benchmark`` are the gate's admitted, ordered series --
        finite, positive, strictly increasing in session and ending on the
        evaluation session. The module recomputes nothing about their
        admissibility; it computes factors and applies its boundaries.
        """
        p = self._params
        v = FACTOR_DEFINITION_VERSION

        trend_ma = factors.moving_average_close(bars, p.trend_sessions)
        security_return = factors.simple_return(bars, p.relative_strength_sessions)
        benchmark_return = factors.simple_return(benchmark, p.relative_strength_sessions)
        relative_strength = factors.quantized(security_return - benchmark_return)
        base = factors.base_range(bars, p.base_sessions)
        relative_volume = factors.relative_volume(bars, p.volume_baseline_sessions)
        high_proximity = factors.high_proximity(bars, p.high_proximity_sessions)
        entry_gap = factors.entry_gap_fraction(bars)
        dollar_volume = factors.average_dollar_volume(bars, p.liquidity_sessions)

        def value(
            factor_id: str, family: FactorFamily, lookback: int, number: Decimal
        ) -> FactorValue:
            return FactorValue(
                definition=FactorDefinition(
                    factor_id=factor_id, version=v, family=family, lookback_sessions=lookback
                ),
                value=number,
            )

        snapshot = (
            value("trend-ma-close", FactorFamily.PRICE_MOMENTUM, p.trend_sessions, trend_ma),
            value(
                "relative-strength",
                FactorFamily.PRICE_MOMENTUM,
                p.relative_strength_sessions + 1,
                relative_strength,
            ),
            value(
                "high-proximity",
                FactorFamily.PRICE_MOMENTUM,
                p.high_proximity_sessions,
                high_proximity,
            ),
            value(
                "base-compactness",
                FactorFamily.PRICE_VOLUME_QUALITY,
                p.base_sessions + 1,
                base.compactness,
            ),
            value(
                "relative-volume",
                FactorFamily.PRICE_VOLUME_QUALITY,
                p.volume_baseline_sessions + 1,
                relative_volume,
            ),
            value("entry-gap", FactorFamily.RISK_CONTEXT, 2, entry_gap),
            value(
                "average-dollar-volume",
                FactorFamily.PRICE_VOLUME_QUALITY,
                p.liquidity_sessions + 1,
                dollar_volume,
            ),
        )
        quality = (snapshot[3], snapshot[4])  # base compactness and relative volume

        evaluation_close = bars[-1].close

        # -- eligibility: the setup must exist before the trigger can matter --
        eligibility: list[ReasonCode] = []
        if evaluation_close <= trend_ma:
            eligibility.append(ReasonCode.TREND_NOT_ESTABLISHED)
        if relative_strength < p.min_relative_strength:
            eligibility.append(ReasonCode.RELATIVE_STRENGTH_NOT_POSITIVE)
        if base.compactness > p.max_base_compactness:
            eligibility.append(ReasonCode.BASE_NOT_COMPACT)
        if dollar_volume < p.min_average_dollar_volume:
            eligibility.append(ReasonCode.LIQUIDITY_BELOW_MINIMUM)
        if eligibility:
            return ModuleEvaluation(
                verdict=ModuleVerdict.INELIGIBLE,
                factor_snapshot=snapshot,
                setup_quality=quality,
                reason_codes=tuple(eligibility),
                trigger=None,
            )

        # -- module-level entry-gap check; the wider event/gap rule is the compiler's --
        if abs(entry_gap) > p.max_entry_gap:
            return ModuleEvaluation(
                verdict=ModuleVerdict.GAP_CONSTRAINT,
                factor_snapshot=snapshot,
                setup_quality=quality,
                reason_codes=(ReasonCode.ENTRY_GAP_EXCEEDS_LIMIT,),
                trigger=None,
            )

        # -- the trigger: a strict close above the base high, with volume confirmation --
        price_confirms = evaluation_close > base.high
        volume_confirms = relative_volume >= p.min_relative_volume
        if price_confirms and volume_confirms:
            trigger = TemplateTrigger(
                entry_condition=EntryCondition.CLOSE_ABOVE_BASE_HIGH_WITH_VOLUME_CONFIRMATION,
                entry_reference_level=base.high,
                invalidation_condition=InvalidationCondition.CLOSE_BELOW_BASE_LOW,
                stop_reference_kind=StopReferenceKind.BASE_LOW,
                stop_reference_level=base.low,
                stop_from_first_session=base.first_session,
                stop_from_last_session=base.last_session,
            )
            return ModuleEvaluation(
                verdict=ModuleVerdict.TRIGGERED,
                factor_snapshot=snapshot,
                setup_quality=quality,
                reason_codes=(ReasonCode.BREAKOUT_CONFIRMED,),
                trigger=trigger,
            )

        reasons: list[ReasonCode] = []
        if not price_confirms:
            reasons.append(ReasonCode.BREAKOUT_NOT_CONFIRMED)
        if not volume_confirms:
            reasons.append(ReasonCode.VOLUME_NOT_CONFIRMED)
        return ModuleEvaluation(
            verdict=ModuleVerdict.SETUP_NOT_TRIGGERED,
            factor_snapshot=snapshot,
            setup_quality=quality,
            reason_codes=tuple(reasons),
            trigger=None,
        )


require_identifier(STRATEGY_ID, field="STRATEGY_ID")


__all__ = ["STRATEGY_ID", "BreakoutLong", "BreakoutLongParameters", "build_spec"]
