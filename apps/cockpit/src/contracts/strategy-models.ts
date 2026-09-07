/**
 * `StrategyPerformance` — `read-model-contracts.md` §4.5, keyed by strategy module **and**
 * strategy version.
 *
 * **Every result is attributed to an exact strategy version.** Modules keep separate
 * attribution and share family context, and **no diversification or alpha claim is carried
 * in this payload, nor is one derivable from it** — whether Breakout Long and Pullback Long
 * are economically distinct is **open gate G7**, and nothing here decides it.
 *
 * WHAT THIS IS NOT. No strategy module exists, no strategy has ever run, and no figure this
 * contract can carry is a result. It is the shape a recorded outcome would arrive in.
 */
import { z } from "zod";

import { collectionPayload } from "./pagination";
import { refOf } from "./references";
import { envelope } from "./envelope";
import {
  analysisWindow,
  performanceSummaryPayload,
} from "./portfolio-models";
import { metricOf, reasonCoded, safeId } from "./values";
import { availabilityState, fieldReasonCode } from "./vocabularies";

/**
 * The recorded health state, and nothing that would make this a health screen.
 *
 * Area 5 — the transitions, the drift measures, the failure clusters, the recovery authority
 * and the research-queue entry a degradation creates — is **C7's**, and this cycle
 * implements none of it. What a strategy-performance reader legitimately needs is the
 * CURRENT RECORDED STATE, so results are not read as if the module were healthy when the
 * record says otherwise, plus a link to the area that owns the rest.
 *
 * **The state is displayed, never derived.** Nothing here computes a health state from a
 * performance figure, and **the view causes no transition**.
 */
export const strategyHealthContext = z.object({
  /** One of the seven ADR-0026 states, carried as a closed-vocabulary token. */
  state: metricOf("strategy.health_state"),
  /** Why the record says what it says. A closed code, never free text. */
  reason: reasonCoded,
  /** Where the transitions, drift and queue entry live — Area 5, and not implemented. */
  detail_ref: refOf("StrategyPerformance.detail_ref"),
  /** What this context deliberately does not carry, named rather than left blank. */
  omitted: z.array(
    z.object({
      subject: reasonCoded,
      availability: availabilityState,
      reason: fieldReasonCode,
    }),
  ),
});
export type StrategyHealthContext = z.infer<typeof strategyHealthContext>;

/**
 * The per-module figures Area 4 names that a `PerformanceSummary` does not carry.
 *
 * ADDITIVE, and each one is a §12.3 metric or a presentation definition this cycle proposes
 * and labels. They sit beside the summary rather than inside it, because a
 * `PerformanceSummary` is the same shape wherever it appears and widening it here would
 * change it everywhere.
 */
export const strategyModuleMetrics = z.object({
  realized_pnl: metricOf("pnl.realized"),
  unrealized_pnl: metricOf("pnl.unrealized"),
  average_holding_period: metricOf("holding_period"),
  opportunity_count: metricOf("strategy.opportunity_count"),
  turnover: metricOf("strategy.turnover"),
  /** Displayed from a record. Nothing here computes a capacity or authorizes one. */
  capacity: metricOf("strategy.capacity"),
  mfe: metricOf("mfe"),
  mae: metricOf("mae"),
  capture_ratio: metricOf("capture_ratio"),
  /** Signed basis points against a named reference, quantity-weighted by default. */
  slippage: metricOf("slippage.aggregate"),
});
export type StrategyModuleMetrics = z.infer<typeof strategyModuleMetrics>;

export const strategyPerformance = z.object({
  strategy_module: reasonCoded,
  alpha_family: reasonCoded,
  /** The EXACT version the results below were produced by. */
  strategy_version: safeId,
  /** EMBEDDED, over this module and version only. */
  summary: performanceSummaryPayload,
  /** Sector, regime, volatility regime, trade template and factor bucket. */
  slices: z.array(
    z.object({
      axis: reasonCoded,
      bucket: reasonCoded,
      summary: performanceSummaryPayload,
    }),
  ),
  trade_population: reasonCoded,
  module_metrics: strategyModuleMetrics,
  health_context: strategyHealthContext,
});
export type StrategyPerformance = z.infer<typeof strategyPerformance>;

/**
 * The family roll-up, carried beside the modules rather than derived from them by a screen.
 *
 * **Two modules in one family are one exposure with two names until measured otherwise**
 * (Area 4). The roll-up therefore states its member versions and carries **no
 * diversification figure at all**: there is no benefit to report, and reporting one would be
 * the claim G7 exists to withhold.
 */
export const alphaFamilyRollup = z.object({
  alpha_family: reasonCoded,
  member_versions: z.array(safeId),
  summary: performanceSummaryPayload,
  /** Stated on the roll-up, so a reader is not left to infer what it does not say. */
  diversification_claim: z.object({
    availability: availabilityState,
    reason: fieldReasonCode,
    gate: reasonCoded,
  }),
});
export type AlphaFamilyRollup = z.infer<typeof alphaFamilyRollup>;

export const strategyPerformancePayload = collectionPayload(strategyPerformance, {
  window: analysisWindow,
  families: z.array(alphaFamilyRollup),
});
export type StrategyPerformancePayload = z.infer<typeof strategyPerformancePayload>;

export const STRATEGY_PERFORMANCE_SCHEMA = "cockpit.strategy_performance.v2";
export const strategyPerformanceEnvelope = envelope(
  strategyPerformancePayload,
  STRATEGY_PERFORMANCE_SCHEMA,
);
