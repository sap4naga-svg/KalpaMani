"""The per-candidate audit journal (specification section 27).

Every Brain decision leaves one immutable journal record: what was asked, which
version answered, what evidence it read *by reference*, what the AI contributed,
what contradicted, the reason codes and the final status. The record is derived
from a :class:`~kalpamani.strategies.brain.intent.CandidateIntent`, so a
decision and its audit trail cannot describe different things.

**Provider payload bytes are never written to the journal.** Licensed vendor
rows stay inside the private deployment boundary (`CLAUDE.md` section 4.22); the
journal carries lineage *identifiers* -- dataset versions, manifest hashes,
snapshot ids, source references -- and a reference is not a row. The record is
built entirely from identifiers the intent already carries, so there is no field
a bar value or a vendor row could enter through.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.strategies.brain.intent import CandidateIntent, RiskContext
from kalpamani.strategies.brain.vocabulary import (
    CompilerStage,
    DecisionState,
    Direction,
    ReasonCode,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class JournalRecord:
    """One decision's complete, reference-only audit record."""

    candidate_id: str
    security_id: str
    as_of_time: datetime
    evaluation_session: date
    direction: Direction
    environment: str
    alpha_family: str
    strategy_module: str
    trade_template: str
    strategy_version: str
    factor_definition_version: str
    resolved_profile: str | None
    factor_vector_reference: str | None
    lineage_references: tuple[str, ...]
    #: The Research and Challenger output references (section 27), beside the
    #: model, prompt and publish time. An AI contribution journaled without its
    #: output references cannot be traced back to what it said.
    ai_research_output_reference: str | None
    ai_challenger_output_reference: str | None
    ai_model_version: str | None
    ai_prompt_version: str | None
    ai_source_publish_time: datetime | None
    #: The risk-context tags (section 27) as ``name=value`` identifiers built from
    #: closed vocabulary members and identifiers only -- never a number, never
    #: prose. Empty when the decision refused before a risk context existed.
    risk_context_tags: tuple[str, ...]
    contradictions: tuple[ReasonCode, ...]
    reason_codes: tuple[ReasonCode, ...]
    status: DecisionState
    concluded_at_stage: CompilerStage
    stages_passed: tuple[CompilerStage, ...]

    @property
    def record_hash(self) -> str:
        """A content hash over the record's canonical form, for tamper-evidence."""
        return content_hash(
            {
                "candidate_id": self.candidate_id,
                "security_id": self.security_id,
                "as_of_time": self.as_of_time,
                "evaluation_session": self.evaluation_session,
                "direction": self.direction.value,
                "environment": self.environment,
                "alpha_family": self.alpha_family,
                "strategy_module": self.strategy_module,
                "trade_template": self.trade_template,
                "strategy_version": self.strategy_version,
                "factor_definition_version": self.factor_definition_version,
                "resolved_profile": self.resolved_profile,
                "factor_vector_reference": self.factor_vector_reference,
                "lineage_references": list(self.lineage_references),
                "ai_research_output_reference": self.ai_research_output_reference,
                "ai_challenger_output_reference": self.ai_challenger_output_reference,
                "ai_model_version": self.ai_model_version,
                "ai_prompt_version": self.ai_prompt_version,
                "ai_source_publish_time": self.ai_source_publish_time,
                "risk_context_tags": list(self.risk_context_tags),
                "contradictions": [code.value for code in self.contradictions],
                "reason_codes": [code.value for code in self.reason_codes],
                "status": self.status.value,
                "concluded_at_stage": self.concluded_at_stage.value,
                "stages_passed": [stage.value for stage in self.stages_passed],
            }
        )


def _risk_context_tags(context: RiskContext | None) -> tuple[str, ...]:
    """The risk context as closed-value tags. No number and no free text is carried."""
    if context is None:
        return ()
    upcoming = "true" if context.upcoming_event_flag else "false"
    tags = [
        f"family_exposure={context.family_exposure.value}",
        *(f"factor_exposure={family.value}" for family in context.factor_exposures),
        f"upcoming_event={upcoming}",
        f"event_timestamp_quality={context.event_timestamp_quality.value}",
        f"earnings_carry={context.earnings_carry_permission.value}",
        f"sector_cluster={context.sector_cluster.value}",
    ]
    if context.market_permission is not None and context.market_permission_version is not None:
        tags.append(f"market_permission={context.market_permission.value}")
        tags.append(f"market_permission_version={context.market_permission_version}")
    return tuple(tags)


def journal_record(intent: CandidateIntent) -> JournalRecord:
    """Derive the audit record for ``intent``. References only; never a vendor row."""
    lineage: tuple[str, ...] = ()
    factor_vector_reference: str | None = None
    resolved_profile: str | None = None
    if intent.evidence is not None:
        factor_vector_reference = intent.evidence.factor_vector_reference
        resolved_profile = intent.evidence.coverage.resolved_profile.value
        references = intent.evidence.lineage
        candidates = (
            references.price_dataset_version,
            references.price_manifest_hash,
            references.price_quality_report_hash,
            references.benchmark_dataset_version,
            references.benchmark_manifest_hash,
            references.universe_snapshot_artifact_id,
            references.universe_snapshot_content_hash,
            references.universe_definition_version,
            references.event_source_reference,
            references.market_context_version,
            references.market_regime_reference,
        )
        lineage = tuple(reference for reference in candidates if reference is not None)
    return JournalRecord(
        candidate_id=intent.candidate_id,
        security_id=intent.security_id,
        as_of_time=intent.as_of_time,
        evaluation_session=intent.evaluation_session,
        direction=intent.direction,
        environment=intent.environment.value,
        alpha_family=intent.strategy.alpha_family.value,
        strategy_module=intent.strategy.strategy_module,
        trade_template=intent.strategy.trade_template,
        strategy_version=intent.strategy.strategy_version,
        factor_definition_version=intent.strategy.factor_definition_version,
        resolved_profile=resolved_profile,
        factor_vector_reference=factor_vector_reference,
        lineage_references=lineage,
        ai_research_output_reference=intent.ai.research_output_reference,
        ai_challenger_output_reference=intent.ai.challenger_output_reference,
        ai_model_version=intent.ai.model_version,
        ai_prompt_version=intent.ai.prompt_version,
        ai_source_publish_time=intent.ai.source_publish_time,
        risk_context_tags=_risk_context_tags(intent.risk_context),
        contradictions=intent.contradictions,
        reason_codes=intent.reason_codes,
        status=intent.status,
        concluded_at_stage=intent.concluded_at_stage,
        stages_passed=intent.stages_passed,
    )


__all__ = ["JournalRecord", "journal_record"]
