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
import { STRATEGY_PERFORMANCE_SCHEMA } from "@/contracts/strategy-models";
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
];
