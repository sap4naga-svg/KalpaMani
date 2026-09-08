/**
 * Read-model identity — what a response IS, independently of what a viewer selected.
 *
 * A cache key must describe the ACTUAL read-model source (`read-model-contracts.md` §7):
 * `api_version`, `schema_version`, environment, source provenance, access scope,
 * classification and every query parameter. **An environment or provenance omitted from a
 * cache key is a cross-environment leak waiting to happen** — and a provenance DERIVED FROM
 * THE SELECTOR rather than from the source is the same defect wearing the right shape.
 *
 * The scenario selector is not the provenance. `QualificationStatus` reads REAL tracked
 * governance facts in BOTH scenarios, so labelling its cache entry `SYNTHETIC` because the
 * demo scenario is selected states the opposite of the truth; the three operational read
 * models are fixture-adapter output in BOTH scenarios, so labelling them
 * `REPOSITORY_TRACKED` in project scope does the same in the other direction.
 *
 * Provenance is therefore a property of the read model here, exactly as it is in the
 * envelope the adapter produces, and the two are asserted to agree.
 */
import {
  ATTENTION_LIST_SCHEMA,
  EXECUTIVE_OVERVIEW_SCHEMA,
  PERFORMANCE_SERIES_SCHEMA,
  QUALIFICATION_STATUS_SCHEMA,
  WHAT_CHANGED_SCHEMA,
} from "@/contracts/read-models";
import {
  EXPOSURE_AGGREGATE_SCHEMA,
  PERFORMANCE_SUMMARY_SCHEMA,
  POSITION_SNAPSHOT_SCHEMA,
  TRADE_DETAIL_SCHEMA,
  TRADE_LIFECYCLE_SCHEMA,
  TRADE_SUMMARY_SCHEMA,
} from "@/contracts/portfolio-models";
import {
  CANDIDATE_DETAIL_SCHEMA,
  CANDIDATE_FUNNEL_SCHEMA,
  CANDIDATE_SUMMARY_SCHEMA,
  MISSED_OPPORTUNITY_SCHEMA,
} from "@/contracts/signal-models";
import {
  STRATEGY_HEALTH_SCHEMA,
  STRATEGY_PERFORMANCE_SCHEMA,
  STRATEGY_VERSION_SCHEMA,
} from "@/contracts/strategy-models";
import {
  AI_CONTRIBUTION_SCHEMA,
  CHAMPION_CHALLENGER_SCHEMA,
  FEEDBACK_PIPELINE_SCHEMA,
  HYPOTHESIS_REGISTRATION_SCHEMA,
  RESEARCH_QUEUE_SCHEMA,
  RESEARCH_RUN_SCHEMA,
} from "@/contracts/research-models";
import {
  DECISION_RECORD_SCHEMA,
  GOVERNANCE_PACKET_SCHEMA,
} from "@/contracts/governance-models";
import {
  EXECUTION_QUALITY_SCHEMA,
  RECONCILIATION_SCHEMA,
} from "@/contracts/execution-quality-page";
import {
  ALERT_SCHEMA,
  DATA_QUALITY_SCHEMA,
  SYSTEM_INCIDENT_SCHEMA,
  SYSTEM_JOB_SCHEMA,
} from "@/contracts/operations-models";
import { AUDIT_EVENT_SCHEMA } from "@/contracts/audit-models";
import {
  ASK_ANSWER_SCHEMA,
  SEARCH_RESULT_PAGE_SCHEMA,
} from "@/contracts/ask-models";
import {
  MARKET_REGIME_SCHEMA,
  RISK_SNAPSHOT_SCHEMA,
  SHORT_SIDE_SNAPSHOT_SCHEMA,
} from "@/contracts/risk-market-models";
import type { DataClassification, DataProvenance } from "@/contracts/vocabularies";

export interface ReadModelIdentity {
  /** The §7.1 admission name. */
  readonly readModel: string;
  /** The stable cache-key name. */
  readonly queryName: string;
  readonly schemaVersion: string;
  /** Where the numbers COME FROM, never which scenario was selected. */
  readonly provenance: DataProvenance;
  readonly classification: DataClassification;
  /** Which authorization a caller needed — part of the key, so two scopes never share one. */
  readonly accessScope: string;
}

/**
 * Fixture-adapter output in BOTH scenarios: populated in demo, and an absence in project
 * scope. §7.1 admits `REPOSITORY_TRACKED` only from the enumerated governance read models,
 * and this is not one of them.
 */
export const EXECUTIVE_OVERVIEW_IDENTITY: ReadModelIdentity = {
  readModel: "ExecutiveOverview",
  queryName: "executive-overview",
  schemaVersion: EXECUTIVE_OVERVIEW_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "executive:read",
};

export const ATTENTION_IDENTITY: ReadModelIdentity = {
  readModel: "AttentionItem",
  queryName: "attention",
  schemaVersion: ATTENTION_LIST_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "executive:read",
};

export const WHAT_CHANGED_IDENTITY: ReadModelIdentity = {
  readModel: "WhatChangedEntry",
  queryName: "what-changed",
  schemaVersion: WHAT_CHANGED_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "executive:read",
};

/**
 * The one read model whose facts are REAL in both scenarios. They are `REPOSITORY_TRACKED`
 * and are never relabelled `SYNTHETIC` to fit a scenario selector (§2.2).
 */
export const QUALIFICATION_IDENTITY: ReadModelIdentity = {
  readModel: "QualificationStatus",
  queryName: "qualification-status",
  schemaVersion: QUALIFICATION_STATUS_SCHEMA,
  provenance: "REPOSITORY_TRACKED",
  classification: "PUBLIC_SAFE",
  accessScope: "governance:read",
};

/**
 * The performance overview's series (§4.5 `PerformanceSeries`).
 *
 * §4.5 classifies a real one `PRIVATE_OPERATIONAL`, which the `PUBLIC_EDGE` boundary REFUSES
 * — correctly, and that is the point. What this application can show is a repository-owned
 * synthetic demonstration, and it is labelled `PUBLIC_SAFE` / `SYNTHETIC` because that is
 * what it IS. A real recorded portfolio series would carry `PRIVATE_OPERATIONAL` with
 * `SYSTEM_RECORDED` provenance and would be refused here rather than relabelled to fit the
 * host — the admission rule doing its job, not a gap in it.
 */
export const PERFORMANCE_SERIES_IDENTITY: ReadModelIdentity = {
  readModel: "PerformanceSeries",
  queryName: "performance-series",
  schemaVersion: PERFORMANCE_SERIES_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "portfolio:read",
};

/* ------------------------------------------------------------------ added by C5 */

/*
 * THE SAME REASONING AS `PerformanceSeries`, APPLIED TO NINE MORE READ MODELS.
 *
 * §4.5 classifies every one of these `PRIVATE_OPERATIONAL` — a real recorded position, trade
 * or risk assessment is private operational state, and the `PUBLIC_EDGE` boundary REFUSES
 * one. What this application can show is a repository-owned synthetic demonstration, and it
 * is labelled `PUBLIC_SAFE` / `SYNTHETIC` because that is what it IS. A real payload would
 * carry `PRIVATE_OPERATIONAL` with `SYSTEM_RECORDED` provenance and would be refused here
 * rather than relabelled to fit the host.
 *
 * **The access scope is the contract's**, not a convenience: §5.1 gives portfolio reads
 * `portfolio:read`, the lifecycle `execution:read`, strategy `strategy:read`, risk and the
 * short side `risk:read`, and the regime `market:read`. Two access scopes never share a
 * cache entry (§7), so a screen holding several of them holds several entries.
 */

export const PERFORMANCE_SUMMARY_IDENTITY: ReadModelIdentity = {
  readModel: "PerformanceSummary",
  queryName: "performance-summary",
  schemaVersion: PERFORMANCE_SUMMARY_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "portfolio:read",
};

export const POSITION_SNAPSHOT_IDENTITY: ReadModelIdentity = {
  readModel: "PositionSnapshot",
  queryName: "position-snapshot",
  schemaVersion: POSITION_SNAPSHOT_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "portfolio:read",
};

export const EXPOSURE_AGGREGATE_IDENTITY: ReadModelIdentity = {
  readModel: "ExposureAggregate",
  queryName: "exposure-aggregate",
  schemaVersion: EXPOSURE_AGGREGATE_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "portfolio:read",
};

export const TRADE_SUMMARY_IDENTITY: ReadModelIdentity = {
  readModel: "TradeSummary",
  queryName: "trade-summary",
  schemaVersion: TRADE_SUMMARY_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "portfolio:read",
};

export const TRADE_DETAIL_IDENTITY: ReadModelIdentity = {
  readModel: "TradeDetail",
  queryName: "trade-detail",
  schemaVersion: TRADE_DETAIL_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "portfolio:read",
};

/**
 * The lifecycle is `execution:read`, and that separation is the point.
 *
 * Execution mechanics are a different screen with a different owner (Area 36.3). Keying the
 * basic lifecycle under the portfolio scope would put order and fill facts in the same cache
 * entry as the ledger, which is the collapse the four-concepts rule exists to prevent.
 */
export const TRADE_LIFECYCLE_IDENTITY: ReadModelIdentity = {
  readModel: "TradeLifecycle",
  queryName: "trade-lifecycle",
  schemaVersion: TRADE_LIFECYCLE_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "execution:read",
};

export const STRATEGY_PERFORMANCE_IDENTITY: ReadModelIdentity = {
  readModel: "StrategyPerformance",
  queryName: "strategy-performance",
  schemaVersion: STRATEGY_PERFORMANCE_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "strategy:read",
};

export const RISK_SNAPSHOT_IDENTITY: ReadModelIdentity = {
  readModel: "RiskSnapshot",
  queryName: "risk-snapshot",
  schemaVersion: RISK_SNAPSHOT_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "risk:read",
};

export const SHORT_SIDE_IDENTITY: ReadModelIdentity = {
  readModel: "ShortSideSnapshot",
  queryName: "short-side-snapshot",
  schemaVersion: SHORT_SIDE_SNAPSHOT_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "risk:read",
};

export const MARKET_REGIME_IDENTITY: ReadModelIdentity = {
  readModel: "MarketRegime",
  queryName: "market-regime",
  schemaVersion: MARKET_REGIME_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "market:read",
};

/* ------------------------------------------------------------------ added by C6 */

/*
 * THE FOUR SIGNALS READ MODELS, ALL UNDER `signals:read`.
 *
 * §5.1 gives `/signals/funnel`, `/signals/candidates`, `/signals/candidates/{id}` and
 * `/signals/missed` the same access scope, and each is a different read model with its own
 * schema version — so four cache entries, never one. The reasoning about classification is the
 * one `PerformanceSeries` established: §4.5 classifies a real one `PRIVATE_OPERATIONAL`, the
 * `PUBLIC_EDGE` boundary refuses that, and what this application can show is a repository-owned
 * synthetic demonstration labelled `PUBLIC_SAFE` / `SYNTHETIC` because that is what it IS.
 */

export const CANDIDATE_FUNNEL_IDENTITY: ReadModelIdentity = {
  readModel: "CandidateFunnel",
  queryName: "candidate-funnel",
  schemaVersion: CANDIDATE_FUNNEL_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "signals:read",
};

export const CANDIDATE_SUMMARY_IDENTITY: ReadModelIdentity = {
  readModel: "CandidateSummary",
  queryName: "candidate-summary",
  schemaVersion: CANDIDATE_SUMMARY_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "signals:read",
};

export const CANDIDATE_DETAIL_IDENTITY: ReadModelIdentity = {
  readModel: "CandidateDetail",
  queryName: "candidate-detail",
  schemaVersion: CANDIDATE_DETAIL_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "signals:read",
};

export const MISSED_OPPORTUNITY_IDENTITY: ReadModelIdentity = {
  readModel: "MissedOpportunity",
  queryName: "missed-opportunity",
  schemaVersion: MISSED_OPPORTUNITY_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "signals:read",
};

/* ------------------------------------------------------------------ added by C7 */

/*
 * TEN MORE READ MODELS, AND THE SAME REASONING THE C5 BLOCK ESTABLISHED.
 *
 * §4.5 classifies every one of these `PRIVATE_OPERATIONAL` — a real health transition, a real
 * research run, a real exposure ledger and a real governance packet are private operational
 * state, and the `PUBLIC_EDGE` boundary REFUSES one. What this application can show is a
 * repository-owned synthetic demonstration, labelled `PUBLIC_SAFE` / `SYNTHETIC` because that
 * is what it IS.
 *
 * **THE ACCESS SCOPE IS THE CONTRACT'S**, and the split is load-bearing: §4.3.4 gives the
 * strategy models `strategy:read`, the research models `research:read` and the two governance
 * models `governance:read`. Two access scopes never share a cache entry (§7), so the research
 * screens hold their own entries and the governance packets hold theirs.
 *
 * **THE SCHEMA VERSIONS ARE `v1`, AND THAT IS NOT AN OVERSIGHT.** §5.2 versions a schema PER
 * READ MODEL: "one view can evolve without a global bump". These ten read models have never
 * been served before, so each carries its own first version. The nineteen existing models keep
 * `v2` — the identity of the coordinated replacement that produced them — and copying `v2` on
 * to a model that has no `v1` would state a history it does not have.
 */

export const STRATEGY_HEALTH_IDENTITY: ReadModelIdentity = {
  readModel: "StrategyHealth",
  queryName: "strategy-health",
  schemaVersion: STRATEGY_HEALTH_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "strategy:read",
};

export const STRATEGY_VERSION_IDENTITY: ReadModelIdentity = {
  readModel: "StrategyVersion",
  queryName: "strategy-version",
  schemaVersion: STRATEGY_VERSION_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "strategy:read",
};

export const RESEARCH_RUN_IDENTITY: ReadModelIdentity = {
  readModel: "ResearchRun",
  queryName: "research-run",
  schemaVersion: RESEARCH_RUN_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "research:read",
};

export const RESEARCH_QUEUE_IDENTITY: ReadModelIdentity = {
  readModel: "ResearchQueueItem",
  queryName: "research-queue",
  schemaVersion: RESEARCH_QUEUE_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "research:read",
};

export const HYPOTHESIS_REGISTRATION_IDENTITY: ReadModelIdentity = {
  readModel: "HypothesisRegistration",
  queryName: "hypothesis-registration",
  schemaVersion: HYPOTHESIS_REGISTRATION_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "research:read",
};

export const CHAMPION_CHALLENGER_IDENTITY: ReadModelIdentity = {
  readModel: "ChampionChallengerComparison",
  queryName: "champion-challenger",
  schemaVersion: CHAMPION_CHALLENGER_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "research:read",
};

export const AI_CONTRIBUTION_IDENTITY: ReadModelIdentity = {
  readModel: "AiContribution",
  queryName: "ai-contribution",
  schemaVersion: AI_CONTRIBUTION_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "research:read",
};

export const FEEDBACK_PIPELINE_IDENTITY: ReadModelIdentity = {
  readModel: "FeedbackPipeline",
  queryName: "feedback-pipeline",
  schemaVersion: FEEDBACK_PIPELINE_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "research:read",
};

export const GOVERNANCE_PACKET_IDENTITY: ReadModelIdentity = {
  readModel: "GovernancePacket",
  queryName: "governance-packet",
  schemaVersion: GOVERNANCE_PACKET_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "governance:read",
};

export const DECISION_RECORD_IDENTITY: ReadModelIdentity = {
  readModel: "DecisionRecord",
  queryName: "decision-record",
  schemaVersion: DECISION_RECORD_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "governance:read",
};

/* ------------------------------------------------------------------ added by C8 */

/*
 * SEVEN MORE READ MODELS, AND THE SAME REASONING THE C5 BLOCK ESTABLISHED.
 *
 * §4.5 classifies every one of these `PRIVATE_OPERATIONAL` — a real fill, a real broker
 * comparison, a real provider-quality record, a real job run and a real audit event are
 * private operational state, and the `PUBLIC_EDGE` boundary REFUSES one. What this application
 * can show is a repository-owned synthetic demonstration, labelled `PUBLIC_SAFE` / `SYNTHETIC`
 * because that is what it IS.
 *
 * **THE ACCESS SCOPES ARE THE CONTRACT'S**, and the split is load-bearing: §5.1 gives
 * `/execution/quality` and `/execution/reconciliation` `execution:read`, the three system reads
 * `system:read`, and `/audit/events` its own `audit:read` — the one scope §4.3 marks
 * `AUTHORIZED_READ` for the `audit_event` kind. Two access scopes never share a cache entry
 * (§7), so the audit page holds its own.
 *
 * **THE SCHEMA VERSIONS ARE `v1`, AND THAT IS NOT AN OVERSIGHT.** §5.2 versions a schema PER
 * READ MODEL. These seven have never been served before, so each carries its own first
 * version; the nineteen coordinated models keep `v2` and the ten C7 models keep `v1`, because
 * copying a version on to a model that has no history would state one it does not have.
 */

export const EXECUTION_QUALITY_IDENTITY: ReadModelIdentity = {
  readModel: "ExecutionQuality",
  queryName: "execution-quality",
  schemaVersion: EXECUTION_QUALITY_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "execution:read",
};

export const RECONCILIATION_IDENTITY: ReadModelIdentity = {
  readModel: "ReconciliationStatus",
  queryName: "reconciliation-status",
  schemaVersion: RECONCILIATION_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "execution:read",
};

export const DATA_QUALITY_IDENTITY: ReadModelIdentity = {
  readModel: "DataQuality",
  queryName: "data-quality",
  schemaVersion: DATA_QUALITY_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "system:read",
};

export const SYSTEM_JOB_IDENTITY: ReadModelIdentity = {
  readModel: "SystemJob",
  queryName: "system-job",
  schemaVersion: SYSTEM_JOB_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "system:read",
};

export const SYSTEM_INCIDENT_IDENTITY: ReadModelIdentity = {
  readModel: "SystemIncident",
  queryName: "system-incident",
  schemaVersion: SYSTEM_INCIDENT_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "system:read",
};

export const ALERT_IDENTITY: ReadModelIdentity = {
  readModel: "Alert",
  queryName: "alert",
  schemaVersion: ALERT_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "system:read",
};

/**
 * The audit projection, under its own scope.
 *
 * §4.3 resolves an `audit_event` under `AUTHORIZED_READ` on `audit:read`, and this is the only
 * read model in the application that carries it. A separate scope is a separate cache entry,
 * which is exactly what §7 requires.
 */
export const AUDIT_EVENT_IDENTITY: ReadModelIdentity = {
  readModel: "AuditEvent",
  queryName: "audit-event",
  schemaVersion: AUDIT_EVENT_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "audit:read",
};

/**
 * The C9 search and assistant identities — Areas 30 and 31.
 *
 * **THE PROVENANCE IS THE INDEX'S OWN, AND NEVER THE SELECTOR'S.** `SearchResultPage` is a
 * composite index built by this fixture adapter in BOTH scenarios, so its envelope is
 * `SYNTHETIC` in both. That is a statement about the INDEX; each indexed ROW carries its own
 * `environment`, `provenance` and `classification`, which is exactly the cross-provenance
 * arrangement §4.3.1 authorizes for this read model and for almost nothing else. A tracked
 * governance fact indexed here stays `REPOSITORY_TRACKED` on its own row and **is never
 * relabelled `SYNTHETIC` to sit in one list** (§7.1).
 *
 * `AskAnswer` is `SYNTHETIC` because §2.6 catalogues it as `SYNTHETIC` with no governance
 * blend, and because §7.1 does not admit `REPOSITORY_TRACKED` to `PUBLIC_EDGE` from it. That
 * is what bounds the question catalogue: an answer over tracked governance facts would have
 * to either mislabel them or be refused at admission, so the assistant produces none and the
 * governance area keeps its own facts.
 *
 * **THE ACCESS SCOPES ARE THE CONTRACT'S.** §4.5 gives search "the union of the scopes the
 * caller holds, and nothing outside them is listed", and an answer "the union of the caller's
 * read scopes". A union is one value here, and it is its own — two access scopes never share
 * a cache entry (§7), so neither of these borrows another read model's.
 *
 * **THE SCHEMA VERSIONS ARE `v1`, AND THAT IS NOT AN OVERSIGHT.** §5.2 versions a schema PER
 * READ MODEL. These two have never been served before, so each carries its own first
 * version; the nineteen coordinated models keep `v2`, and the ten C7 and seven C8 models keep
 * `v1`, because copying a version on to a model with no history would state one it does not
 * have.
 */
export const SEARCH_RESULT_PAGE_IDENTITY: ReadModelIdentity = {
  readModel: "SearchResultPage",
  queryName: "search-result-page",
  schemaVersion: SEARCH_RESULT_PAGE_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "search:read",
};

export const ASK_ANSWER_IDENTITY: ReadModelIdentity = {
  readModel: "AskAnswer",
  queryName: "ask-answer",
  schemaVersion: ASK_ANSWER_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "ask:read",
};

export const READ_MODEL_IDENTITIES: readonly ReadModelIdentity[] = [
  EXECUTIVE_OVERVIEW_IDENTITY,
  ATTENTION_IDENTITY,
  WHAT_CHANGED_IDENTITY,
  QUALIFICATION_IDENTITY,
  PERFORMANCE_SERIES_IDENTITY,
  PERFORMANCE_SUMMARY_IDENTITY,
  POSITION_SNAPSHOT_IDENTITY,
  EXPOSURE_AGGREGATE_IDENTITY,
  TRADE_SUMMARY_IDENTITY,
  TRADE_DETAIL_IDENTITY,
  TRADE_LIFECYCLE_IDENTITY,
  STRATEGY_PERFORMANCE_IDENTITY,
  RISK_SNAPSHOT_IDENTITY,
  SHORT_SIDE_IDENTITY,
  MARKET_REGIME_IDENTITY,
  CANDIDATE_FUNNEL_IDENTITY,
  CANDIDATE_SUMMARY_IDENTITY,
  CANDIDATE_DETAIL_IDENTITY,
  MISSED_OPPORTUNITY_IDENTITY,
  STRATEGY_HEALTH_IDENTITY,
  STRATEGY_VERSION_IDENTITY,
  RESEARCH_RUN_IDENTITY,
  RESEARCH_QUEUE_IDENTITY,
  HYPOTHESIS_REGISTRATION_IDENTITY,
  CHAMPION_CHALLENGER_IDENTITY,
  AI_CONTRIBUTION_IDENTITY,
  FEEDBACK_PIPELINE_IDENTITY,
  GOVERNANCE_PACKET_IDENTITY,
  DECISION_RECORD_IDENTITY,
  EXECUTION_QUALITY_IDENTITY,
  RECONCILIATION_IDENTITY,
  DATA_QUALITY_IDENTITY,
  SYSTEM_JOB_IDENTITY,
  SYSTEM_INCIDENT_IDENTITY,
  ALERT_IDENTITY,
  AUDIT_EVENT_IDENTITY,
  SEARCH_RESULT_PAGE_IDENTITY,
  ASK_ANSWER_IDENTITY,
];
