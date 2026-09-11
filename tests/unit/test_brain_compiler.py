"""The deterministic decision compiler: the thirteen stages, in order, stopping first.

These tests drive the whole compiler over the synthetic scenario and its negative
controls. They check three kinds of property: that each outcome is the right closed
status with the right reason code; that the concluding stage and the stages recorded
as passed are exactly the accepted prefix (a later stage never runs after an earlier
refusal); and that the two invariants the boundary rests on hold -- the output is a
status and never a size or an order, and a deterministic failure is never rescued by
AI.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from decimal import Decimal

import pytest

from fixtures import brain_equity as fx
from kalpamani.common.environment import Environment
from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.data.contracts.vocabulary import InformationSetProfile, LimitationToken
from kalpamani.strategies.brain.compiler import compile_candidate
from kalpamani.strategies.brain.consolidation import PeerConclusion
from kalpamani.strategies.brain.evidence import AiEvidenceRecord
from kalpamani.strategies.brain.intent import CandidateIntent
from kalpamani.strategies.brain.module import ModuleEvaluation, TemplateTrigger
from kalpamani.strategies.brain.spec import StrategySpec
from kalpamani.strategies.brain.vocabulary import (
    COMPILER_STAGE_ORDER,
    AlphaFamily,
    ChallengerVerdict,
    CompilerStage,
    DecisionState,
    Direction,
    ModuleVerdict,
    ReasonCode,
)
from kalpamani.strategies.breakout.long import BreakoutLong

pytestmark = pytest.mark.unit

MODULE = BreakoutLong(fx.TEST_PARAMS)


def _compile(scenario: fx.Scenario, **kwargs: object) -> CandidateIntent:
    return compile_candidate(scenario.inputs, MODULE, **kwargs)  # type: ignore[arg-type]


# -- the happy path ---------------------------------------------------------------------


def test_an_eligible_triggered_candidate_is_ready_for_risk_review() -> None:
    intent = compile_candidate(fx.build_scenario().inputs, MODULE)
    assert intent.status is DecisionState.READY_FOR_RISK_REVIEW
    assert intent.reason_codes == (ReasonCode.ALL_DETERMINISTIC_REQUIREMENTS_SATISFIED,)
    assert intent.concluded_at_stage is CompilerStage.IMMUTABLE_REASON_CODE_CONSTRUCTION
    assert len(intent.stages_passed) == 12
    assert intent.thesis is not None
    assert intent.evidence is not None
    assert intent.risk_context is not None


def test_ready_is_not_an_order_or_a_size() -> None:
    """The whole output is a status; the intent carries no size, quantity or order field."""
    intent = compile_candidate(fx.build_scenario().inputs, MODULE)
    # The thesis carries reference *levels*, never a share count or an order.
    thesis = intent.thesis
    assert thesis is not None
    assert isinstance(thesis.entry_reference_level, Decimal)
    assert thesis.technical_stop_reference.kind.value == "BASE_LOW"


def test_the_decision_is_reproducible() -> None:
    scenario = fx.build_scenario()
    first = compile_candidate(scenario.inputs, MODULE)
    second = compile_candidate(scenario.inputs, MODULE)
    assert first.candidate_id == second.candidate_id
    assert first.status is second.status
    assert first.reason_codes == second.reason_codes


# -- every terminal outcome, with its concluding stage ----------------------------------


def test_the_boundary_close_watches_at_the_template_stage() -> None:
    intent = _compile(fx.build_scenario(breakout_close=Decimal("100.5")))
    assert intent.status is DecisionState.WATCHLIST
    assert intent.concluded_at_stage is CompilerStage.TRADE_TEMPLATE_MATCH
    assert intent.thesis is None  # no confirmed entry level yet
    assert intent.evidence is not None and intent.risk_context is not None


def test_a_non_member_is_rejected_at_the_reality_gate() -> None:
    intent = _compile(fx.build_scenario(universe_member=False))
    assert intent.status is DecisionState.REJECTED
    assert intent.reason_codes == (ReasonCode.UNIVERSE_NON_MEMBER,)
    assert intent.concluded_at_stage is CompilerStage.POINT_IN_TIME_REALITY_GATE
    assert intent.stages_passed == ()


def test_missing_required_event_evidence_blocks_data() -> None:
    intent = _compile(fx.build_scenario(with_event=False))
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (ReasonCode.EVENT_EVIDENCE_UNRESOLVED,)
    assert intent.concluded_at_stage is CompilerStage.POINT_IN_TIME_REALITY_GATE


def test_an_event_within_the_holding_horizon_watches() -> None:
    scenario = fx.build_scenario()
    within = scenario.evaluation_session + timedelta(days=3)
    intent = _compile(fx.build_scenario(next_event_session=within))
    assert intent.status is DecisionState.WATCHLIST
    assert intent.reason_codes == (ReasonCode.EVENT_WITHIN_HOLDING_HORIZON,)
    assert intent.concluded_at_stage is CompilerStage.EVENT_AND_GAP_CONTEXT
    assert intent.thesis is not None  # the thesis stands; the timing does not


def test_a_deferred_market_watches_with_a_thesis() -> None:
    from kalpamani.strategies.brain.vocabulary import MarketPermission

    intent = _compile(fx.build_scenario(market_long=MarketPermission.DEFERRED))
    assert intent.status is DecisionState.WATCHLIST
    assert intent.reason_codes == (ReasonCode.MARKET_ENTRY_DEFERRED,)
    assert intent.concluded_at_stage is CompilerStage.MARKET_PERMISSION_CONTEXT
    assert intent.thesis is not None


def test_a_denied_market_rejects() -> None:
    from kalpamani.strategies.brain.vocabulary import MarketPermission

    intent = _compile(fx.build_scenario(market_long=MarketPermission.DENIED))
    assert intent.status is DecisionState.REJECTED
    assert intent.reason_codes == (ReasonCode.MARKET_PERMISSION_DENIED,)
    assert intent.concluded_at_stage is CompilerStage.MARKET_PERMISSION_CONTEXT


def test_an_unauthorized_environment_is_rejected() -> None:
    # The research-stage spec authorizes RESEARCH only; PAPER is not authorized.
    intent = _compile(fx.build_scenario(environment=Environment.PAPER))
    assert intent.status is DecisionState.REJECTED
    assert intent.reason_codes == (ReasonCode.ENVIRONMENT_NOT_AUTHORIZED,)
    assert intent.concluded_at_stage is CompilerStage.AUTHORIZED_STRATEGY_VERSION


# -- stages never run out of order ------------------------------------------------------


def test_stages_passed_is_always_the_accepted_prefix() -> None:
    """Stages recorded as passed are exactly those before the concluding one, every outcome."""
    from kalpamani.strategies.brain.vocabulary import MarketPermission

    scenarios = [
        fx.build_scenario(),
        fx.build_scenario(breakout_close=Decimal("100.5")),
        fx.build_scenario(universe_member=False),
        fx.build_scenario(with_event=False),
        fx.build_scenario(market_long=MarketPermission.DENIED),
        fx.build_scenario(environment=Environment.PAPER),
    ]
    for scenario in scenarios:
        intent = compile_candidate(scenario.inputs, MODULE)
        index = COMPILER_STAGE_ORDER.index(intent.concluded_at_stage)
        assert intent.stages_passed == COMPILER_STAGE_ORDER[:index]


# -- the point-in-time gate's own refusals ----------------------------------------------


def test_a_future_dated_bar_blocks_data() -> None:
    scenario = fx.build_scenario()
    bars = list(scenario.security_bars)
    future = dataclasses.replace(bars[-1], bar_end_time=scenario.as_of + timedelta(days=1))
    bars[-1] = future
    price = dataclasses.replace(scenario.inputs.price_history, bars=tuple(bars))
    intent = compile_candidate(fx.with_price(scenario, price).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (ReasonCode.OBSERVATION_AFTER_AS_OF,)


def test_a_stale_series_that_stops_before_the_evaluation_session_blocks() -> None:
    scenario = fx.build_scenario()
    price = dataclasses.replace(scenario.inputs.price_history, bars=scenario.security_bars[:-1])
    intent = compile_candidate(fx.with_price(scenario, price).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (ReasonCode.STALE_PRICE_HISTORY,)


def test_a_downgraded_profile_blocks() -> None:
    scenario = fx.build_scenario()
    provenance = dataclasses.replace(
        scenario.inputs.price_history.provenance,
        resolved_profile=InformationSetProfile.PUBLIC_PIT,
    )
    price = dataclasses.replace(scenario.inputs.price_history, provenance=provenance)
    intent = compile_candidate(fx.with_price(scenario, price).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (ReasonCode.PROFILE_DOWNGRADED,)


def test_a_non_point_in_time_limitation_blocks() -> None:
    scenario = fx.build_scenario()
    provenance = dataclasses.replace(
        scenario.inputs.price_history.provenance,
        limitations=(LimitationToken.NON_PIT_RESTATED_VIEW,),
    )
    price = dataclasses.replace(scenario.inputs.price_history, provenance=provenance)
    intent = compile_candidate(fx.with_price(scenario, price).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (ReasonCode.NON_POINT_IN_TIME_LIMITATION,)


def test_an_as_of_mismatch_between_evidence_and_decision_blocks() -> None:
    scenario = fx.build_scenario()
    provenance = dataclasses.replace(
        scenario.inputs.price_history.provenance, as_of=scenario.as_of + timedelta(hours=1)
    )
    price = dataclasses.replace(scenario.inputs.price_history, provenance=provenance)
    intent = compile_candidate(fx.with_price(scenario, price).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (ReasonCode.EVIDENCE_AS_OF_MISMATCH,)


# -- the AI stage: schema, staleness, and the rescue asymmetry --------------------------


def test_optional_ai_absent_is_not_a_block() -> None:
    intent = compile_candidate(fx.build_scenario(with_ai=False).inputs, MODULE)
    assert intent.status is DecisionState.READY_FOR_RISK_REVIEW
    assert not intent.ai.carries_output


def test_well_formed_ai_evidence_is_carried_on_a_ready_intent() -> None:
    intent = compile_candidate(fx.build_scenario(with_ai=True).inputs, MODULE)
    assert intent.status is DecisionState.READY_FOR_RISK_REVIEW
    assert intent.ai.carries_output
    assert intent.ai.model_version == "model/synthetic.1"


def test_malformed_ai_evidence_blocks_ai() -> None:
    record = AiEvidenceRecord(research_output_reference="only-this-field")
    intent = compile_candidate(fx.build_scenario(ai=record).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_AI
    assert intent.reason_codes == (ReasonCode.AI_EVIDENCE_MALFORMED,)
    assert intent.concluded_at_stage is CompilerStage.AI_SCHEMA_AND_PROVENANCE


def test_future_dated_ai_evidence_is_stale_and_blocks() -> None:
    scenario = fx.build_scenario()
    record = fx.fresh_ai(scenario.as_of)
    future = dataclasses.replace(record, source_publish_time=scenario.as_of + timedelta(hours=1))
    intent = compile_candidate(fx.build_scenario(ai=future).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_AI
    assert intent.reason_codes == (ReasonCode.AI_EVIDENCE_STALE,)


def test_a_challenger_that_falsifies_the_thesis_removes_the_candidate() -> None:
    """AI may remove a candidate. The removal is a rejection, never a rescue."""
    scenario = fx.build_scenario()
    record = dataclasses.replace(
        fx.fresh_ai(scenario.as_of), challenger_verdict=ChallengerVerdict.FALSIFIED
    )
    intent = compile_candidate(fx.build_scenario(ai=record).inputs, MODULE)
    assert intent.status is DecisionState.REJECTED
    assert intent.reason_codes == (ReasonCode.AI_CHALLENGER_FALSIFIED,)
    assert intent.concluded_at_stage is CompilerStage.AI_SCHEMA_AND_PROVENANCE


def test_ai_cannot_rescue_a_deterministic_block() -> None:
    """No AI evidence turns a non-member (rejected at the gate) into a candidate.

    The gate concludes at stage one; the AI stage is stage eight and never runs. The
    asymmetry is structural: AI evidence cannot even be reached once a deterministic
    stage has refused.
    """
    strong_ai = fx.fresh_ai(fx.build_scenario().as_of)
    intent = compile_candidate(
        fx.build_scenario(universe_member=False, ai=strong_ai).inputs, MODULE
    )
    assert intent.status is DecisionState.REJECTED
    assert intent.concluded_at_stage is CompilerStage.POINT_IN_TIME_REALITY_GATE
    assert intent.is_deterministic_refusal


# -- consolidation and contradiction ----------------------------------------------------


def test_a_single_module_candidate_has_one_attribution() -> None:
    intent = compile_candidate(fx.build_scenario().inputs, MODULE)
    assert len(intent.strategy.contributing) == 1
    assert intent.strategy.contributing[0].strategy_id == "breakout-long"


def test_an_agreeing_peer_is_preserved_as_a_ranked_attribution() -> None:
    peer = PeerConclusion(
        strategy_id="pullback-long",
        strategy_version="pullback-long/r1",
        strategy_module="pullback-long",
        trade_template="pullback-support",
        alpha_family=AlphaFamily.MOMENTUM_CONTINUATION,
        direction=Direction.LONG,
        verdict=ModuleVerdict.TRIGGERED,
    )
    intent = compile_candidate(fx.build_scenario().inputs, MODULE, peers=(peer,))
    assert intent.status is DecisionState.READY_FOR_RISK_REVIEW
    ids = [c.strategy_id for c in intent.strategy.contributing]
    assert ids == ["breakout-long", "pullback-long"]


def test_a_direction_contradiction_blocks_rather_than_preferring_one() -> None:
    short_peer = PeerConclusion(
        strategy_id="deterioration-short",
        strategy_version="deterioration-short/r1",
        strategy_module="deterioration-short",
        trade_template="deterioration",
        alpha_family=AlphaFamily.FUNDAMENTAL_DETERIORATION,
        direction=Direction.SHORT,
        verdict=ModuleVerdict.TRIGGERED,
    )
    intent = compile_candidate(fx.build_scenario().inputs, MODULE, peers=(short_peer,))
    assert intent.status is DecisionState.BLOCKED_CONTRADICTION
    assert intent.reason_codes == (ReasonCode.DIRECTION_CONTRADICTION,)
    assert intent.contradictions == (ReasonCode.DIRECTION_CONTRADICTION,)
    assert intent.concluded_at_stage is CompilerStage.UNRESOLVED_CONTRADICTIONS


# -- the short-borrow stage, driven by a synthetic short module -------------------------


class _AlwaysTriggeredShort:
    """A minimal short module, for exercising the borrow stage the long module skips.

    Not a strategy: it triggers unconditionally on a synthetic SHORT spec, so the
    compiler reaches stage twelve and the borrow prerequisite decides the outcome.
    """

    def __init__(self, spec: StrategySpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    def evaluate(
        self,
        bars: tuple[PriceBarValues, ...],
        benchmark: tuple[PriceBarValues, ...],
    ) -> ModuleEvaluation:
        from kalpamani.strategies.brain.factors import FactorValue
        from kalpamani.strategies.brain.vocabulary import (
            EntryCondition,
            FactorFamily,
            InvalidationCondition,
            StopReferenceKind,
        )

        snapshot = (
            FactorValue(
                definition=dataclasses.replace(self._spec.factor_definitions[0]),
                value=Decimal("1"),
            ),
        )
        trigger = TemplateTrigger(
            entry_condition=EntryCondition.CLOSE_ABOVE_BASE_HIGH_WITH_VOLUME_CONFIRMATION,
            entry_reference_level=Decimal("100"),
            invalidation_condition=InvalidationCondition.CLOSE_BELOW_BASE_LOW,
            stop_reference_kind=StopReferenceKind.BASE_LOW,
            stop_reference_level=Decimal("90"),
            stop_from_first_session=bars[0].session_date,
            stop_from_last_session=bars[-2].session_date,
        )
        _ = FactorFamily  # referenced for clarity; snapshot uses the spec's own definition
        return ModuleEvaluation(
            verdict=ModuleVerdict.TRIGGERED,
            factor_snapshot=snapshot,
            setup_quality=snapshot,
            reason_codes=(ReasonCode.BREAKOUT_CONFIRMED,),
            trigger=trigger,
        )


def _short_spec() -> StrategySpec:
    from kalpamani.data.contracts.vocabulary import (
        AdjustmentConvention,
        AdjustmentMode,
        AdjustmentPolicy,
        BarResolution,
        InformationSetProfile,
        RevisionView,
    )
    from kalpamani.strategies.brain.factors import FactorDefinition
    from kalpamani.strategies.brain.spec import (
        DataRequirements,
        Permissions,
        ResearchGovernance,
        RiskTags,
    )
    from kalpamani.strategies.brain.vocabulary import (
        DataDomain,
        FactorFamily,
        LifecycleStage,
        Requirement,
    )

    definition = FactorDefinition(
        factor_id="short-signal",
        version="short/r1",
        family=FactorFamily.FUNDAMENTAL_QUALITY,
        lookback_sessions=fx.TEST_PARAMS.required_history_sessions,
    )
    return StrategySpec(
        strategy_id="synthetic-short",
        alpha_family=AlphaFamily.FUNDAMENTAL_DETERIORATION,
        strategy_module="synthetic-short",
        trade_template="synthetic-short",
        version="synthetic-short/r1",
        lifecycle_stage=LifecycleStage.REGISTERED_HYPOTHESIS,
        authorized_environments=frozenset({Environment.RESEARCH}),
        direction=Direction.SHORT,
        expected_holding_sessions=10,
        minimum_holding_sessions=2,
        maximum_holding_sessions=30,
        data=DataRequirements(
            required_profile=InformationSetProfile.PROVIDER_REALISTIC_PIT,
            revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
            adjustment_mode=AdjustmentMode.adjusted(
                AdjustmentPolicy.SPLIT_ONLY, AdjustmentConvention.FORWARD_BASE_NORMALIZED
            ),
            resolution=BarResolution.DAILY,
            required_domains=frozenset({DataDomain.PRICE_BARS, DataDomain.BORROW}),
            optional_domains=frozenset(),
            required_history_sessions=fx.TEST_PARAMS.required_history_sessions,
        ),
        permissions=Permissions(
            market_prerequisite=Requirement.NOT_APPLICABLE,
            event_prerequisite=Requirement.NOT_APPLICABLE,
            gap_prerequisite=Requirement.OPTIONAL,
            borrow_prerequisite=Requirement.REQUIRED,
            ai_requirement=Requirement.NOT_APPLICABLE,
            rank_requirement=Requirement.OPTIONAL,
        ),
        factor_definitions=(definition,),
        factor_definition_version="short/r1",
        parameters_hash="short.params/r1",
        manifest_version="short.manifest/r1",
        configuration_identity="short.config/r1",
        model_version=None,
        prompt_version=None,
        risk_tags=RiskTags(
            family_exposure=AlphaFamily.FUNDAMENTAL_DETERIORATION,
            factor_exposures=(FactorFamily.FUNDAMENTAL_QUALITY,),
            capacity_reference="short.capacity/unmeasured",
            risk_policy_compatibility="deterioration.short/r1",
        ),
        research=ResearchGovernance(
            hypothesis_id="H-short",
            baseline_id="short-baseline",
            trial_budget=1,
            success_criteria_reference="protocol.short.success/unset",
            failure_criteria_reference="protocol.short.failure/unset",
        ),
    )


def test_a_short_with_unknown_borrow_is_blocked_borrow() -> None:
    module = _AlwaysTriggeredShort(_short_spec())
    scenario = fx.build_scenario(with_event=False, with_market=False)
    inputs = dataclasses.replace(
        scenario.inputs, short_context=fx.unknown_short_context(scenario.as_of)
    )
    intent = compile_candidate(inputs, module)
    assert intent.status is DecisionState.BLOCKED_BORROW
    assert intent.reason_codes == (ReasonCode.BORROW_STATE_UNKNOWN,)
    assert intent.concluded_at_stage is CompilerStage.SHORT_BORROW_PREREQUISITE


def test_a_short_with_no_borrow_context_is_blocked_borrow() -> None:
    module = _AlwaysTriggeredShort(_short_spec())
    scenario = fx.build_scenario(with_event=False, with_market=False)
    inputs = dataclasses.replace(scenario.inputs, short_context=None)
    intent = compile_candidate(inputs, module)
    assert intent.status is DecisionState.BLOCKED_BORROW
    assert intent.reason_codes == (ReasonCode.BORROW_CONTEXT_MISSING,)


def test_a_short_with_qualified_borrow_is_ready() -> None:
    module = _AlwaysTriggeredShort(_short_spec())
    scenario = fx.build_scenario(with_event=False, with_market=False)
    inputs = dataclasses.replace(
        scenario.inputs, short_context=fx.qualified_short_context(scenario.as_of)
    )
    intent = compile_candidate(inputs, module)
    assert intent.status is DecisionState.READY_FOR_RISK_REVIEW
    assert intent.short_context is not None
    assert intent.direction is Direction.SHORT
