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
from datetime import datetime

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.strategies.brain.intent import CandidateIntent
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
    direction: Direction
    environment: str
    alpha_family: str
    strategy_module: str
    trade_template: str
    strategy_version: str
    factor_definition_version: str
    factor_vector_reference: str | None
    lineage_references: tuple[str, ...]
    ai_model_version: str | None
    ai_prompt_version: str | None
    ai_source_publish_time: datetime | None
    contradictions: tuple[ReasonCode, ...]
    reason_codes: tuple[ReasonCode, ...]
    status: DecisionState
    concluded_at_stage: CompilerStage

    @property
    def record_hash(self) -> str:
        """A content hash over the record's canonical form, for tamper-evidence."""
        return content_hash(
            {
                "candidate_id": self.candidate_id,
                "security_id": self.security_id,
                "as_of_time": self.as_of_time,
                "direction": self.direction.value,
                "environment": self.environment,
                "alpha_family": self.alpha_family,
                "strategy_module": self.strategy_module,
                "trade_template": self.trade_template,
                "strategy_version": self.strategy_version,
                "factor_definition_version": self.factor_definition_version,
                "factor_vector_reference": self.factor_vector_reference,
                "lineage_references": list(self.lineage_references),
                "ai_model_version": self.ai_model_version,
                "ai_prompt_version": self.ai_prompt_version,
                "ai_source_publish_time": self.ai_source_publish_time,
                "contradictions": [code.value for code in self.contradictions],
                "reason_codes": [code.value for code in self.reason_codes],
                "status": self.status.value,
                "concluded_at_stage": self.concluded_at_stage.value,
            }
        )


def journal_record(intent: CandidateIntent) -> JournalRecord:
    """Derive the audit record for ``intent``. References only; never a vendor row."""
    lineage: tuple[str, ...] = ()
    factor_vector_reference: str | None = None
    if intent.evidence is not None:
        factor_vector_reference = intent.evidence.factor_vector_reference
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
        direction=intent.direction,
        environment=intent.environment.value,
        alpha_family=intent.strategy.alpha_family.value,
        strategy_module=intent.strategy.strategy_module,
        trade_template=intent.strategy.trade_template,
        strategy_version=intent.strategy.strategy_version,
        factor_definition_version=intent.strategy.factor_definition_version,
        factor_vector_reference=factor_vector_reference,
        lineage_references=lineage,
        ai_model_version=intent.ai.model_version,
        ai_prompt_version=intent.ai.prompt_version,
        ai_source_publish_time=intent.ai.source_publish_time,
        contradictions=intent.contradictions,
        reason_codes=intent.reason_codes,
        status=intent.status,
        concluded_at_stage=intent.concluded_at_stage,
    )


__all__ = ["JournalRecord", "journal_record"]
