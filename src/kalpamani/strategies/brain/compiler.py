"""The deterministic decision compiler: the Brain's final stage (specification section 15).

Thirteen validations, in the accepted order, stopping at the first refusal. A
later stage never runs after an earlier one refuses, so an unresolved
point-in-time gate never reaches a borrow check and an unauthorized strategy
version never reaches AI evidence. The output is a
:class:`~kalpamani.strategies.brain.intent.CandidateIntent` status and nothing
else -- no share count, no dollars, no order type, no route, no stop *order*.

The compiler is deterministic and offline. It reads no clock (the decision
instant is ``inputs.as_of_time``), no network, no provider, no broker and no
model. Given the same immutable inputs it produces the same intent, including
the same derived ``candidate_id``.

One asymmetry is load-bearing (section 14.3): **a deterministic failure cannot
be rescued by AI.** The AI stage runs at position eight, *after* the
deterministic eligibility and template stages have already passed, so AI can
only move a surviving candidate to a refusal -- never move a refused one back.
That ordering is the mechanism, not a comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.strategies.brain import factors
from kalpamani.strategies.brain.consolidation import (
    ConsolidationResult,
    PeerConclusion,
    consolidate,
)
from kalpamani.strategies.brain.evidence import AiEvidenceRecord, EvaluationInputs
from kalpamani.strategies.brain.gate import (
    forward_horizon_session,
    market_permission_for,
    run_reality_gate,
)
from kalpamani.strategies.brain.identity import candidate_id
from kalpamani.strategies.brain.intent import (
    AiEvidenceReference,
    CandidateIntent,
    CoverageEvidence,
    EvidenceSummary,
    LevelReference,
    LineageReferences,
    RankEvidence,
    RiskContext,
    StrategyAttribution,
    TradeThesis,
)
from kalpamani.strategies.brain.module import ModuleEvaluation, StrategyModule
from kalpamani.strategies.brain.vocabulary import (
    COMPILER_STAGE_ORDER,
    ChallengerVerdict,
    CompilerStage,
    DecisionState,
    Direction,
    EarningsCarryPermission,
    EventTimestampQuality,
    ModuleVerdict,
    RankState,
    ReasonCode,
    Requirement,
    SectorClusterState,
)

#: The window, in sessions before the evaluation bar, over which the risk context's
#: liquidity is measured. A context figure for the risk engine, not a signal input.
_LIQUIDITY_CONTEXT_SESSIONS = 20


@dataclass(frozen=True, slots=True, kw_only=True)
class _StageRefusal:
    """A stage's refusal: the state, its reasons and the stage that concluded."""

    state: DecisionState
    reasons: tuple[ReasonCode, ...]
    stage: CompilerStage
    contradictions: tuple[ReasonCode, ...] = ()


def _stages_before(stage: CompilerStage) -> tuple[CompilerStage, ...]:
    return COMPILER_STAGE_ORDER[: COMPILER_STAGE_ORDER.index(stage)]


def compile_candidate(
    inputs: EvaluationInputs,
    module: StrategyModule,
    *,
    peers: tuple[PeerConclusion, ...] = (),
    max_ai_staleness: timedelta | None = None,
) -> CandidateIntent:
    """Compile one candidate for ``module`` over ``inputs``. Returns a ``CandidateIntent``.

    ``peers`` are other modules' conclusions about the same security in the same
    decision window, used by the consolidation stage. ``max_ai_staleness``, when
    given, bounds how old AI evidence may be relative to the decision instant --
    a research parameter, defaulting to no bound (only future-dated evidence is
    refused outright).
    """
    spec = module.spec
    evidence_reference = _evidence_reference(inputs)
    cid = candidate_id(
        security_id=inputs.security_id,
        direction=spec.direction.value,
        strategy_id=spec.strategy_id,
        strategy_version=spec.version,
        as_of_time=inputs.as_of_time,
        environment=inputs.environment.value,
        evidence_reference=evidence_reference,
    )

    builder = _IntentBuilder(inputs=inputs, spec=spec, module=module, candidate_id=cid)

    # 1 -- point-in-time reality gate
    gate = run_reality_gate(inputs, spec)
    if not gate.admitted:
        assert gate.reason is not None and gate.state is not None
        return builder.refuse(
            _StageRefusal(
                state=gate.state,
                reasons=(gate.reason,),
                stage=CompilerStage.POINT_IN_TIME_REALITY_GATE,
            )
        )

    # 2 -- authorized strategy version
    version_refusal = spec.refusal_for(inputs.environment)
    if version_refusal is not None:
        return builder.refuse(
            _StageRefusal(
                state=DecisionState.REJECTED,
                reasons=(version_refusal,),
                stage=CompilerStage.AUTHORIZED_STRATEGY_VERSION,
            )
        )

    # 3 -- factor-definition version: every pinned definition must carry the version
    # the spec declares. A pin that disagrees with itself is not a pin.
    if any(
        definition.version != spec.factor_definition_version
        for definition in spec.factor_definitions
    ):
        return builder.refuse(
            _StageRefusal(
                state=DecisionState.REJECTED,
                reasons=(ReasonCode.FACTOR_DEFINITION_VERSION_MISMATCH,),
                stage=CompilerStage.FACTOR_DEFINITION_VERSION,
            )
        )

    # 4 -- required data coverage
    available = len(gate.bars)
    if available < spec.data.required_history_sessions:
        return builder.refuse(
            _StageRefusal(
                state=DecisionState.BLOCKED_DATA,
                reasons=(ReasonCode.INSUFFICIENT_HISTORY,),
                stage=CompilerStage.REQUIRED_DATA_COVERAGE,
            )
        )

    # -- the module evaluates once; stages 5 and 6 read its verdict. The computed
    # snapshot must also carry the pinned version, or the evaluation and the spec
    # disagree about what was computed.
    evaluation = module.evaluate(gate.bars, gate.benchmark_bars)
    builder.attach_evaluation(evaluation, gate.bars, gate.benchmark_bars, gate)
    if any(
        value.definition.version != spec.factor_definition_version
        for value in evaluation.factor_snapshot
    ):
        return builder.refuse(
            _StageRefusal(
                state=DecisionState.REJECTED,
                reasons=(ReasonCode.FACTOR_DEFINITION_VERSION_MISMATCH,),
                stage=CompilerStage.FACTOR_DEFINITION_VERSION,
            )
        )

    # 5 -- strategy and module eligibility
    if evaluation.verdict is ModuleVerdict.INELIGIBLE:
        return builder.refuse(
            _StageRefusal(
                state=DecisionState.REJECTED,
                reasons=evaluation.reason_codes,
                stage=CompilerStage.STRATEGY_AND_MODULE_ELIGIBILITY,
            )
        )
    if evaluation.verdict is ModuleVerdict.GAP_CONSTRAINT:
        # A module-level entry-gap refusal is an eligibility refusal: the setup is
        # real but not enterable now on gap grounds.
        return builder.refuse(
            _StageRefusal(
                state=DecisionState.REJECTED,
                reasons=evaluation.reason_codes,
                stage=CompilerStage.STRATEGY_AND_MODULE_ELIGIBILITY,
            )
        )

    # 6 -- trade-template match
    if evaluation.verdict is not ModuleVerdict.TRIGGERED:
        # Eligible but the entry condition is not met now: the thesis stands, the
        # trigger does not. WATCHLIST, with evidence and risk context but no thesis.
        return builder.watchlist_without_thesis(evaluation.reason_codes)

    # 7 -- duplicate-economic-exposure consolidation
    consolidation = consolidate(
        spec=spec,
        primary_direction=spec.direction,
        primary_verdict=evaluation.verdict,
        peers=peers,
    )
    builder.attach_consolidation(consolidation)

    # 8 -- AI schema and provenance, where required
    ai_refusal = builder.resolve_ai(max_ai_staleness=max_ai_staleness)
    if ai_refusal is not None:
        return builder.refuse(ai_refusal)

    # 9 -- unresolved contradictions
    if consolidation.has_direction_contradiction:
        return builder.refuse(
            _StageRefusal(
                state=DecisionState.BLOCKED_CONTRADICTION,
                reasons=(ReasonCode.DIRECTION_CONTRADICTION,),
                stage=CompilerStage.UNRESOLVED_CONTRADICTIONS,
                contradictions=(ReasonCode.DIRECTION_CONTRADICTION,),
            )
        )

    # 10 -- market permission context
    permission = market_permission_for(builder.market_permission)
    if permission is not None:
        reason, state = permission
        if state is DecisionState.WATCHLIST:
            return builder.watchlist_with_thesis(reason, CompilerStage.MARKET_PERMISSION_CONTEXT)
        return builder.refuse(
            _StageRefusal(
                state=state, reasons=(reason,), stage=CompilerStage.MARKET_PERMISSION_CONTEXT
            )
        )

    # 11 -- event and gap context: a scheduled event inside the holding horizon leaves the
    # thesis standing but defers the entry, so this is a WATCHLIST that keeps its thesis.
    event_reason = builder.resolve_event_and_gap()
    if event_reason is not None:
        return builder.watchlist_with_thesis(event_reason, CompilerStage.EVENT_AND_GAP_CONTEXT)

    # 12 -- short borrow prerequisite, if applicable
    borrow_refusal = builder.resolve_borrow()
    if borrow_refusal is not None:
        return builder.refuse(borrow_refusal)

    # 13 -- immutable reason-code construction: every requirement satisfied
    return builder.ready()


class _IntentBuilder:
    """Assembles the evidence, thesis and risk context as the stages pass.

    A builder rather than a pile of locals because the final intent needs
    sections computed at several different stages, and a refusal at any stage
    must be able to emit whatever has been established so far and nothing it has
    not. Every method returns data; none performs I/O.
    """

    def __init__(
        self,
        *,
        inputs: EvaluationInputs,
        spec: object,
        module: StrategyModule,
        candidate_id: str,
    ) -> None:
        self._inputs = inputs
        self._spec = module.spec
        self._module = module
        self._candidate_id = candidate_id
        self._evaluation: ModuleEvaluation | None = None
        self._bars: tuple[PriceBarValues, ...] = ()
        self._evidence: EvidenceSummary | None = None
        self._consolidation: ConsolidationResult | None = None
        self._ai_reference: AiEvidenceReference | None = None
        self._thesis: TradeThesis | None = None
        self._risk_context: RiskContext | None = None
        self.market_permission = (
            inputs.market_context.permission_long
            if inputs.market_context is not None and spec_direction(module) is Direction.LONG
            else (
                inputs.market_context.permission_short
                if inputs.market_context is not None
                else None
            )
        )

    # -- assembly --------------------------------------------------------------

    def attach_evaluation(
        self,
        evaluation: ModuleEvaluation,
        bars: tuple[PriceBarValues, ...],
        benchmark: tuple[PriceBarValues, ...],
        gate: object,
    ) -> None:
        self._evaluation = evaluation
        self._bars = bars
        self._evidence = self._build_evidence(evaluation, gate)
        self._risk_context = self._build_risk_context(evaluation, bars)

    def attach_consolidation(self, consolidation: ConsolidationResult) -> None:
        self._consolidation = consolidation

    def _attribution(self) -> StrategyAttribution:
        if self._consolidation is not None:
            return self._consolidation.attribution
        return consolidate(
            spec=self._spec,
            primary_direction=self._spec.direction,
            primary_verdict=(
                self._evaluation.verdict
                if self._evaluation is not None
                else ModuleVerdict.INELIGIBLE
            ),
            peers=(),
        ).attribution

    def _build_evidence(self, evaluation: ModuleEvaluation, gate: object) -> EvidenceSummary:
        series = self._inputs.price_history
        provenance = series.provenance
        benchmark = self._inputs.benchmark_history
        first_session = self._bars[0].session_date
        last_session = self._bars[-1].session_date
        lineage = LineageReferences(
            price_dataset_version=provenance.dataset_version,
            price_manifest_hash=provenance.manifest_hash,
            price_quality_report_hash=provenance.quality_report_hash,
            benchmark_security_id=(benchmark.security_id if benchmark is not None else None),
            benchmark_dataset_version=(
                benchmark.provenance.dataset_version if benchmark is not None else None
            ),
            benchmark_manifest_hash=(
                benchmark.provenance.manifest_hash if benchmark is not None else None
            ),
            universe_snapshot_artifact_id=(
                self._inputs.universe.snapshot_artifact_id
                if self._inputs.universe is not None and self._inputs.universe.snapshot_artifact_id
                else None
            ),
            universe_snapshot_content_hash=(
                self._inputs.universe.snapshot_content_hash
                if self._inputs.universe is not None and self._inputs.universe.snapshot_content_hash
                else None
            ),
            universe_definition_version=(
                self._inputs.universe.universe_definition_version
                if self._inputs.universe is not None
                else None
            ),
            event_source_reference=(
                self._inputs.event_context.source_reference
                if self._inputs.event_context is not None
                else None
            ),
            market_context_version=(
                self._inputs.market_context.version
                if self._inputs.market_context is not None
                else None
            ),
            market_regime_reference=(
                self._inputs.market_context.regime_reference
                if self._inputs.market_context is not None
                else None
            ),
        )
        coverage = CoverageEvidence(
            sessions_available=len(self._bars),
            sessions_required=self._spec.data.required_history_sessions,
            first_session=first_session,
            last_session=last_session,
            resolved_profile=provenance.resolved_profile,
            dataset_version=provenance.dataset_version,
            manifest_hash=provenance.manifest_hash,
            quality_report_hash=provenance.quality_report_hash,
            limitations=provenance.limitations,
        )
        rank = self._build_rank()
        return EvidenceSummary(
            factor_snapshot=evaluation.factor_snapshot,
            factor_vector_reference=self._factor_vector_reference(evaluation),
            setup_quality=evaluation.setup_quality,
            rank=rank,
            coverage=coverage,
            lineage=lineage,
        )

    def _build_rank(self) -> RankEvidence:
        # Cross-sectional rank needs a universe-wide scanner run; this slice
        # evaluates one security, so rank is explicitly NOT_COMPUTED rather than
        # a fabricated 1-of-1.
        return RankEvidence(state=RankState.NOT_COMPUTED, rank=None, population=None)

    def _factor_vector_reference(self, evaluation: ModuleEvaluation) -> str:
        payload = "|".join(
            f"{value.definition.reference}={value.value}" for value in evaluation.factor_snapshot
        )
        import hashlib

        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"factors/{self._spec.factor_definition_version}/{digest}"

    def _build_risk_context(
        self, evaluation: ModuleEvaluation, bars: tuple[PriceBarValues, ...]
    ) -> RiskContext:
        event = self._inputs.event_context
        upcoming = event is not None and event.next_event_session is not None
        gap_estimate = factors.max_abs_overnight_gap(
            bars, min(len(bars) - 1, self._spec.data.required_history_sessions - 1)
        )
        entry_gap = factors.entry_gap_fraction(bars)
        # Liquidity is a property of the bars, computed here rather than read from a
        # module-specific factor id, so the risk context is the same shape whichever
        # module produced the candidate. The window excludes the evaluation bar.
        liquidity_window = min(len(bars) - 1, _LIQUIDITY_CONTEXT_SESSIONS)
        liquidity = factors.average_dollar_volume(bars, liquidity_window)
        market = self._inputs.market_context
        permission = self.market_permission if market is not None else None
        return RiskContext(
            upcoming_event_flag=upcoming,
            next_event_session=event.next_event_session if event is not None else None,
            event_timestamp_quality=(
                event.timestamp_quality if event is not None else EventTimestampQuality.UNKNOWN
            ),
            gap_risk_estimate=gap_estimate,
            entry_gap_fraction=entry_gap,
            earnings_carry_permission=EarningsCarryPermission.NOT_PERMITTED,
            liquidity_average_dollar_volume=liquidity,
            family_exposure=self._spec.alpha_family,
            factor_exposures=self._spec.risk_tags.factor_exposures,
            sector_cluster=SectorClusterState.UNAVAILABLE,
            sector_cluster_reference=None,
            market_permission_version=market.version if market is not None else None,
            market_permission=permission,
        )

    # -- the AI stage ----------------------------------------------------------

    def resolve_ai(self, *, max_ai_staleness: timedelta | None) -> _StageRefusal | None:
        requirement = self._spec.permissions.ai_requirement
        record = self._inputs.ai_evidence
        if record is None:
            if requirement is Requirement.REQUIRED:
                return _StageRefusal(
                    state=DecisionState.BLOCKED_AI,
                    reasons=(ReasonCode.AI_EVIDENCE_MISSING,),
                    stage=CompilerStage.AI_SCHEMA_AND_PROVENANCE,
                )
            self._ai_reference = _no_ai_reference(requirement)
            return None
        malformed = _ai_schema_defect(record)
        if malformed is not None:
            return _StageRefusal(
                state=DecisionState.BLOCKED_AI,
                reasons=(malformed,),
                stage=CompilerStage.AI_SCHEMA_AND_PROVENANCE,
            )
        stale = _ai_staleness_defect(
            record, as_of=self._inputs.as_of_time, max_ai_staleness=max_ai_staleness
        )
        if stale is not None:
            return _StageRefusal(
                state=DecisionState.BLOCKED_AI,
                reasons=(stale,),
                stage=CompilerStage.AI_SCHEMA_AND_PROVENANCE,
            )
        if record.challenger_verdict is ChallengerVerdict.FALSIFIED:
            # AI removing a candidate. Never a rescue -- it can only refuse.
            self._ai_reference = _ai_reference_from(record)
            return _StageRefusal(
                state=DecisionState.REJECTED,
                reasons=(ReasonCode.AI_CHALLENGER_FALSIFIED,),
                stage=CompilerStage.AI_SCHEMA_AND_PROVENANCE,
            )
        self._ai_reference = _ai_reference_from(record)
        return None

    # -- the thesis and the remaining stages -----------------------------------

    def _build_thesis(self) -> TradeThesis:
        assert self._evaluation is not None and self._evaluation.trigger is not None
        trigger = self._evaluation.trigger
        stop = LevelReference(
            kind=trigger.stop_reference_kind,
            level=trigger.stop_reference_level,
            derived_from_first_session=trigger.stop_from_first_session,
            derived_from_last_session=trigger.stop_from_last_session,
        )
        return TradeThesis(
            entry_condition=trigger.entry_condition,
            entry_reference_level=trigger.entry_reference_level,
            invalidation_condition=trigger.invalidation_condition,
            technical_stop_reference=stop,
            expected_holding_sessions=self._spec.expected_holding_sessions,
            minimum_holding_sessions=self._spec.minimum_holding_sessions,
            maximum_holding_sessions=self._spec.maximum_holding_sessions,
        )

    def resolve_event_and_gap(self) -> ReasonCode | None:
        # The entry-bar gap was already checked by the module; the compiler's
        # event/gap stage enforces the no-carry-through-earnings rule, which is a
        # WATCHLIST rather than a data block: the thesis stands, the timing does not.
        event = self._inputs.event_context
        if event is not None and event.next_event_session is not None:
            horizon_last = self._horizon_last_session()
            if event.next_event_session <= horizon_last:
                return ReasonCode.EVENT_WITHIN_HOLDING_HORIZON
        return None

    def _horizon_last_session(self) -> date:
        return forward_horizon_session(
            self._inputs.evaluation_session, self._spec.maximum_holding_sessions
        )

    def resolve_borrow(self) -> _StageRefusal | None:
        if self._spec.direction is Direction.LONG:
            return None
        short = self._inputs.short_context
        if short is None:
            return _StageRefusal(
                state=DecisionState.BLOCKED_BORROW,
                reasons=(ReasonCode.BORROW_CONTEXT_MISSING,),
                stage=CompilerStage.SHORT_BORROW_PREREQUISITE,
            )
        if not short.is_fully_qualified:
            return _StageRefusal(
                state=DecisionState.BLOCKED_BORROW,
                reasons=(ReasonCode.BORROW_STATE_UNKNOWN,),
                stage=CompilerStage.SHORT_BORROW_PREREQUISITE,
            )
        return None

    # -- terminal intents ------------------------------------------------------

    def refuse(self, refusal: _StageRefusal) -> CandidateIntent:
        include_setup = refusal.state is DecisionState.WATCHLIST
        return CandidateIntent(
            candidate_id=self._candidate_id,
            security_id=self._inputs.security_id,
            as_of_time=self._inputs.as_of_time,
            evaluation_session=self._inputs.evaluation_session,
            direction=self._spec.direction,
            environment=self._inputs.environment,
            strategy=self._attribution(),
            status=refusal.state,
            reason_codes=refusal.reasons,
            concluded_at_stage=refusal.stage,
            stages_passed=_stages_before(refusal.stage),
            contradictions=refusal.contradictions,
            evidence=self._evidence if include_setup else self._evidence_if_available(),
            ai=self._ai_reference or _no_ai_reference(self._spec.permissions.ai_requirement),
            thesis=None,
            risk_context=self._risk_context if include_setup else None,
            short_context=self._inputs.short_context
            if self._spec.direction is Direction.SHORT
            else None,
        )

    def _evidence_if_available(self) -> EvidenceSummary | None:
        # A refusal after the evidence was built may still carry it (a rejection at
        # eligibility has factors worth journaling); a refusal before it carries none.
        return self._evidence

    def watchlist_without_thesis(self, reasons: tuple[ReasonCode, ...]) -> CandidateIntent:
        return CandidateIntent(
            candidate_id=self._candidate_id,
            security_id=self._inputs.security_id,
            as_of_time=self._inputs.as_of_time,
            evaluation_session=self._inputs.evaluation_session,
            direction=self._spec.direction,
            environment=self._inputs.environment,
            strategy=self._attribution(),
            status=DecisionState.WATCHLIST,
            reason_codes=reasons or (ReasonCode.BREAKOUT_NOT_CONFIRMED,),
            concluded_at_stage=CompilerStage.TRADE_TEMPLATE_MATCH,
            stages_passed=_stages_before(CompilerStage.TRADE_TEMPLATE_MATCH),
            contradictions=(),
            evidence=self._evidence,
            ai=_no_ai_reference(self._spec.permissions.ai_requirement),
            thesis=None,
            risk_context=self._risk_context,
            short_context=None,
        )

    def watchlist_with_thesis(self, reason: ReasonCode, stage: CompilerStage) -> CandidateIntent:
        return CandidateIntent(
            candidate_id=self._candidate_id,
            security_id=self._inputs.security_id,
            as_of_time=self._inputs.as_of_time,
            evaluation_session=self._inputs.evaluation_session,
            direction=self._spec.direction,
            environment=self._inputs.environment,
            strategy=self._attribution(),
            status=DecisionState.WATCHLIST,
            reason_codes=(reason,),
            concluded_at_stage=stage,
            stages_passed=_stages_before(stage),
            contradictions=(),
            evidence=self._evidence,
            ai=self._ai_reference or _no_ai_reference(self._spec.permissions.ai_requirement),
            thesis=self._build_thesis(),
            risk_context=self._risk_context,
            short_context=None,
        )

    def ready(self) -> CandidateIntent:
        return CandidateIntent(
            candidate_id=self._candidate_id,
            security_id=self._inputs.security_id,
            as_of_time=self._inputs.as_of_time,
            evaluation_session=self._inputs.evaluation_session,
            direction=self._spec.direction,
            environment=self._inputs.environment,
            strategy=self._attribution(),
            status=DecisionState.READY_FOR_RISK_REVIEW,
            reason_codes=(ReasonCode.ALL_DETERMINISTIC_REQUIREMENTS_SATISFIED,),
            concluded_at_stage=CompilerStage.IMMUTABLE_REASON_CODE_CONSTRUCTION,
            stages_passed=_stages_before(CompilerStage.IMMUTABLE_REASON_CODE_CONSTRUCTION),
            contradictions=(),
            evidence=self._evidence,
            ai=self._ai_reference or _no_ai_reference(self._spec.permissions.ai_requirement),
            thesis=self._build_thesis(),
            risk_context=self._risk_context,
            short_context=(
                self._inputs.short_context if self._spec.direction is Direction.SHORT else None
            ),
        )


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------


def _evidence_reference(inputs: EvaluationInputs) -> str:
    """A deterministic identity for the exact price evidence a decision read.

    Derived from the result's provenance and its bar endpoints, so two runs over
    the same point-in-time result produce the same reference and therefore the
    same ``candidate_id``, and a different result produces a different one. The
    bars' closes and volumes are hashed, never a vendor row copied out.
    """
    series = inputs.price_history
    provenance = series.provenance
    payload = {
        "dataset_version": provenance.dataset_version,
        "manifest_hash": provenance.manifest_hash,
        "quality_report_hash": provenance.quality_report_hash,
        "as_of": provenance.as_of,
        "resolved_profile": provenance.resolved_profile.value,
        "resolution": series.resolution.value,
        "endpoints": [[bar.session_date, bar.close, bar.volume] for bar in series.bars],
    }
    return content_hash(payload).replace("sha256:", "sha256_")


def _no_ai_reference(requirement: Requirement) -> AiEvidenceReference:
    return AiEvidenceReference(
        requirement=requirement,
        research_output_reference=None,
        challenger_output_reference=None,
        source_publish_time=None,
        model_version=None,
        prompt_version=None,
        schema_version=None,
        confidence=None,
        evidence_quality=None,
    )


def _ai_schema_defect(record: AiEvidenceRecord) -> ReasonCode | None:
    """Whether the AI output is missing a required provenance field."""
    required = (
        record.research_output_reference,
        record.challenger_output_reference,
        record.source_publish_time,
        record.produced_at,
        record.model_version,
        record.prompt_version,
        record.schema_version,
        record.confidence,
        record.evidence_quality,
        record.challenger_verdict,
    )
    if any(value is None for value in required):
        return ReasonCode.AI_EVIDENCE_MALFORMED
    try:
        _ai_reference_from(record)
    except Exception:
        return ReasonCode.AI_EVIDENCE_MALFORMED
    return None


def _ai_staleness_defect(
    record: AiEvidenceRecord, *, as_of: datetime, max_ai_staleness: timedelta | None
) -> ReasonCode | None:
    publish = record.source_publish_time
    produced = record.produced_at
    assert publish is not None and produced is not None  # schema stage ran first
    if publish > as_of or produced > as_of:
        # Evidence dated after the decision instant is not knowable at it.
        return ReasonCode.AI_EVIDENCE_STALE
    if max_ai_staleness is not None and (as_of - publish) > max_ai_staleness:
        return ReasonCode.AI_EVIDENCE_STALE
    return None


def _ai_reference_from(record: AiEvidenceRecord) -> AiEvidenceReference:
    return AiEvidenceReference(
        requirement=Requirement.REQUIRED,
        research_output_reference=record.research_output_reference,
        challenger_output_reference=record.challenger_output_reference,
        source_publish_time=record.source_publish_time,
        model_version=record.model_version,
        prompt_version=record.prompt_version,
        schema_version=record.schema_version,
        confidence=record.confidence,
        evidence_quality=record.evidence_quality,
    )


def spec_direction(module: StrategyModule) -> Direction:
    return module.spec.direction


__all__ = ["compile_candidate"]
