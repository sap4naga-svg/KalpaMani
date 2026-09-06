/**
 * The SYNTHETIC demonstration scenario.
 *
 * Deterministic and repository-owned. NO provider row, NO broker record, NO private
 * identifier, NO personal account data and NO copied real trade history appears here, and
 * every identity is obviously fictional.
 *
 * NOTHING IN THIS FILE IS A RESULT. It exists so the visual states have something to render
 * and is labelled SYNTHETIC at page level and at component level wherever it is shown.
 */
import type { ExecutiveOverviewPayload } from "@/contracts/read-models";
import type { AttentionListPayload, WhatChangedPayload } from "@/data/client/read-client";

import { absent, available, qualified, reason } from "@/contracts/factories";

const DEMO = "kalpamani.demo";

export function syntheticExecutiveOverview(asOf: string): ExecutiveOverviewPayload {
  return {
    /** The authoritative strategy capital of CLAUDE.md section 6. Never broker equity. */
    strategy_capital: { amount: "80000.00", currency: "USD" },
    /** OBSERVED and informational. It never participates in sizing. */
    broker_reported_equity: available({
      metricId: "portfolio.broker_reported_equity",
      unit: "USD",
      value: "1000000.00",
      asOf,
    }),
    cash: available({ metricId: "portfolio.cash", unit: "USD", value: "62450.00", asOf }),
    pnl: [
      {
        window: "DAY",
        /** ADR-0029 section 2.1: a measured zero is a RESULT, and stays AVAILABLE. */
        realized: available({ metricId: "pnl.realized", unit: "USD", value: "0.00", asOf }),
        unrealized: available({
          metricId: "pnl.unrealized",
          unit: "USD",
          value: "-318.40",
          asOf,
        }),
      },
      {
        window: "WEEK",
        realized: available({ metricId: "pnl.realized", unit: "USD", value: "1240.75", asOf }),
        unrealized: available({
          metricId: "pnl.unrealized",
          unit: "USD",
          value: "-318.40",
          asOf,
        }),
      },
      {
        window: "MONTH",
        realized: available({ metricId: "pnl.realized", unit: "USD", value: "2915.10", asOf }),
        /** A value-bearing state that keeps its qualification. */
        unrealized: qualified("STALE", "UPSTREAM_INPUT_STALE", {
          metricId: "pnl.unrealized",
          unit: "USD",
          value: "-318.40",
          asOf,
        }),
      },
      {
        window: "CUMULATIVE",
        realized: available({ metricId: "pnl.realized", unit: "USD", value: "2915.10", asOf }),
        unrealized: available({
          metricId: "pnl.unrealized",
          unit: "USD",
          value: "-318.40",
          asOf,
        }),
      },
    ],
    return_pct: available({
      metricId: "return.time_weighted",
      unit: "PERCENT",
      value: "3.24",
      asOf,
    }),
    exposure: {
      long: { amount: "31200.00", currency: "USD", direction: "LONG" },
      short: { amount: "8400.00", currency: "USD", direction: "SHORT" },
      gross: { amount: "39600.00", currency: "USD", direction: "LONG" },
      net: { amount: "22800.00", currency: "USD", direction: "LONG" },
    },
    open_planned_risk: {
      record: {
        amount: { amount: "1850.00", currency: "USD" },
        as_of: asOf,
        policy: { policy_id: "risk-policy-demo", policy_version: "0.0.0-demo", as_of: asOf },
        staleness: "FRESH",
      },
      availability: "AVAILABLE",
      reason: "NONE",
      as_of: asOf,
    },
    /**
     * A separately governed policy value with no versioned reference is
     * POLICY_REFERENCE_MISSING -- NEVER a number (ADR-0028 section 2.4).
     */
    permitted_open_risk: {
      availability: "NOT_YET_AVAILABLE",
      reason: "POLICY_REFERENCE_MISSING",
    },
    /** A measured zero drawdown is a value, not an absence. `drawdown.current` is the
     * dictionary key for it (section 12.3); `risk.drawdown` was not a dictionary key. */
    drawdown: available({ metricId: "drawdown.current", unit: "PERCENT", value: "0.00", asOf }),
    system_health: reason("DEMONSTRATION_ONLY", DEMO),
    data_freshness: available({
      metricId: "freshness.source_age",
      unit: "SECONDS",
      value: 45,
      asOf,
    }),
    active_strategies: available({
      metricId: "strategy.active_count",
      unit: "COUNT",
      value: 3,
      asOf,
    }),
    /** A completed query over an empty population -- NOT a measured zero. */
    open_incidents: qualified("EMPTY_VERIFIED", "EMPTY_RESULT_VERIFIED", {
      metricId: "operations.open_incidents",
      unit: "COUNT",
      value: 0,
      asOf,
    }),
    tile_availability: [
      { tile_id: "capital", availability: "AVAILABLE", reason: "NONE" },
      { tile_id: "pnl", availability: "AVAILABLE", reason: "NONE" },
      { tile_id: "exposure", availability: "AVAILABLE", reason: "NONE" },
      { tile_id: "drawdown", availability: "AVAILABLE", reason: "NONE" },
      {
        tile_id: "permitted-risk",
        availability: "NOT_YET_AVAILABLE",
        reason: "POLICY_REFERENCE_MISSING",
      },
      {
        tile_id: "execution-quality",
        availability: "NOT_IMPLEMENTED",
        reason: "PRODUCER_NOT_IMPLEMENTED",
      },
    ],
  };
}

export function syntheticAttention(asOf: string): AttentionListPayload {
  const evidence = {
    items: [
      {
        ref_id: "demo-evidence-1",
        ref_kind: "source_fact",
        resolution: "UNRESOLVABLE_V1" as const,
        classification: "PUBLIC_SAFE" as const,
      },
    ],
    cardinality: "EXACTLY_ONE" as const,
    truncated: false,
  };
  return {
    items: [
      {
        item_id: "demo-attention-1",
        what_happened: reason("STRATEGY_ENTERED_DEGRADED", DEMO),
        why_it_matters: reason("NEW_ENTRY_QUALITY_MAY_DECLINE", DEMO),
        impact: available({
          metricId: "strategy.health_impact",
          unit: "R_MULTIPLE",
          value: "-0.42",
          asOf,
        }),
        evidence_refs: evidence,
        /** A PERMITTED GOVERNANCE action, and never an execution instruction. */
        recommended_action: reason("REVIEW_STRATEGY_HEALTH_EVIDENCE", DEMO),
        severity: reason("MEDIUM", DEMO),
        materiality_rank: 1,
        dedup_key: "demo-dedup-1",
        first_seen: asOf,
        last_seen: asOf,
        occurrence_count: available({
          metricId: "attention.occurrence_count",
          unit: "COUNT",
          value: 2,
          asOf,
        }),
      },
      {
        item_id: "demo-attention-2",
        what_happened: reason("MARK_DATA_OLDER_THAN_CONTRACT", DEMO),
        why_it_matters: reason("EXPOSURE_FIGURES_MAY_BE_STALE", DEMO),
        impact: absent(
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
          "attention.impact",
          "DIMENSIONLESS",
        ),
        evidence_refs: evidence,
        recommended_action: reason("REVIEW_DATA_QUALITY_EVIDENCE", DEMO),
        severity: reason("LOW", DEMO),
        materiality_rank: 2,
        dedup_key: "demo-dedup-2",
        first_seen: asOf,
        last_seen: asOf,
        occurrence_count: available({
          metricId: "attention.occurrence_count",
          unit: "COUNT",
          value: 1,
          asOf,
        }),
      },
    ],
  };
}

export function syntheticWhatChanged(asOf: string, baselineAsOf: string): WhatChangedPayload {
  const evidenceRef = (id: string) => ({
    items: [
      {
        ref_id: id,
        ref_kind: "source_fact",
        resolution: "UNRESOLVABLE_V1" as const,
        classification: "PUBLIC_SAFE" as const,
      },
    ],
    cardinality: "EXACTLY_ONE" as const,
    truncated: false,
  });
  return {
    baseline_label: "since the previous demonstration snapshot",
    baseline_as_of: baselineAsOf,
    comparison_as_of: asOf,
    entries: [
      {
        change_id: "demo-change-1",
        subject: reason("STRATEGY_HEALTH", DEMO),
        change_kind: reason("STATE_TRANSITION", DEMO),
        before: available({
          metricId: "strategy.health_state",
          unit: "DIMENSIONLESS",
          value: "WATCH",
          asOf: baselineAsOf,
        }),
        after: available({
          metricId: "strategy.health_state",
          unit: "DIMENSIONLESS",
          value: "DEGRADED",
          asOf,
        }),
        materiality: reason("MATERIAL", DEMO),
        evidence_refs: evidenceRef("demo-evidence-2"),
      },
      {
        change_id: "demo-change-2",
        subject: reason("OPEN_INCIDENTS", DEMO),
        change_kind: reason("APPEARANCE", DEMO),
        /** No prior value exists, so before is ABSENT rather than a fabricated baseline. */
        after: qualified("EMPTY_VERIFIED", "EMPTY_RESULT_VERIFIED", {
          metricId: "operations.open_incidents",
          unit: "COUNT",
          value: 0,
          asOf,
        }),
        materiality: reason("INFORMATIONAL", DEMO),
        evidence_refs: evidenceRef("demo-evidence-3"),
      },
    ],
  };
}
