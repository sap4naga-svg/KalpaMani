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
import type {
  AttentionItemPayload,
  ExecutiveOverviewPayload,
  WhatChangedEntryPayload,
} from "@/contracts/read-models";
import type { Ref } from "@/contracts/values";
import type { AttentionListPayload, WhatChangedPayload } from "@/data/client/read-client";
import type { ChangeVariant } from "@/lib/scope";

import { absent, available, qualified, reason, refListOf } from "@/contracts/factories";

const DEMO = "kalpamani.demo";

const ref = (
  id: string,
  kind: string,
  resolution: Ref["resolution"] = "UNRESOLVABLE_V1",
): Ref => ({
  ref_id: id,
  ref_kind: kind,
  resolution,
  classification: "PUBLIC_SAFE",
});

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
    /**
     * `drawdown.current` is `equity / running_peak - 1` (12.3), which is NEVER positive. The
     * dictionary key is `drawdown.current`; `risk.drawdown` was not a dictionary key.
     */
    drawdown: available({ metricId: "drawdown.current", unit: "PERCENT", value: "-2.14", asOf }),
    /**
     * Completed by C4. The market-regime projection does not exist, so this reference resolves
     * to an availability state rather than to a payload -- which is what `UNRESOLVABLE_V1`
     * MEANS (4.3), and why the reference stays VISIBLE instead of being omitted.
     */
    regime_ref: ref("demo-regime-context", "regime_context"),
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
    /**
     * Completed by C4, and both are ABSENCES rather than timestamps.
     *
     * The Strategy Brain runtime that would take a decision, and the scanner that would run a
     * scout pass, are both NOT IMPLEMENTED AND NOT AUTHORIZED -- so there has never been a
     * last decision or a last scout run. A plausible demonstration date here would be the one
     * figure on this page implying the Brain had ever run.
     */
    last_decision: {
      at: absent(
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
        "decision.last_at",
        "DIMENSIONLESS",
      ),
      ref: ref("demo-last-decision", "decision"),
    },
    last_scout_run: {
      at: absent(
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
        "scout.last_run_at",
        "DIMENSIONLESS",
      ),
      ref: ref("demo-last-scout-run", "research_run"),
    },
    /** The reference lists a summary counts from -- `total`, and never `items.length`. */
    what_changed: refListOf(
      [ref("demo-change-1", "source_fact"), ref("demo-change-2", "source_fact")],
      "ZERO_OR_MORE",
      asOf,
    ),
    attention: refListOf(
      [
        ref("demo-attention-1", "source_fact"),
        ref("demo-attention-2", "source_fact"),
        ref("demo-attention-3", "source_fact"),
        ref("demo-attention-4", "source_fact"),
      ],
      "ZERO_OR_MORE",
      asOf,
    ),
    tile_availability: [
      { tile_id: "capital", availability: "AVAILABLE", reason: "NONE" },
      { tile_id: "pnl", availability: "AVAILABLE", reason: "NONE" },
      { tile_id: "exposure", availability: "AVAILABLE", reason: "NONE" },
      { tile_id: "drawdown", availability: "AVAILABLE", reason: "NONE" },
      { tile_id: "performance", availability: "AVAILABLE", reason: "NONE" },
      {
        tile_id: "permitted-risk",
        availability: "NOT_YET_AVAILABLE",
        reason: "POLICY_REFERENCE_MISSING",
      },
      { tile_id: "regime", availability: "NOT_IMPLEMENTED", reason: "PRODUCER_NOT_IMPLEMENTED" },
      {
        tile_id: "last-decision",
        availability: "NOT_IMPLEMENTED",
        reason: "PRODUCER_NOT_IMPLEMENTED",
      },
      {
        tile_id: "execution-quality",
        availability: "NOT_IMPLEMENTED",
        reason: "PRODUCER_NOT_IMPLEMENTED",
      },
    ],
  };
}

/**
 * The attention list.
 *
 * Deliberately NOT pre-sorted, deliberately carrying a DUPLICATE, and deliberately carrying
 * one INCOMPLETE item. Ranking, deduplication and the five-things rule belong to
 * `lib/attention.ts`; a fixture that arrived already ordered and already clean would let a
 * broken ranker pass its tests by doing nothing at all.
 */
export function syntheticAttention(asOf: string, earlier: string): AttentionListPayload {
  const evidence = (id: string, kind: string) => refListOf([ref(id, kind)], "EXACTLY_ONE", asOf);
  const occurrences = (value: number) =>
    available({ metricId: "attention.occurrence_count", unit: "COUNT", value, asOf });

  return {
    items: [
      {
        item_id: "demo-attention-2",
        what_happened: reason("MARK_DATA_OLDER_THAN_CONTRACT", DEMO),
        why_it_matters: reason("EXPOSURE_FIGURES_MAY_BE_STALE", DEMO),
        /**
         * NOT MEASURABLE, and stated as such. It is NOT ranked as zero impact: an item whose
         * impact nobody measured is not an item that has no impact.
         */
        impact: absent(
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
          "attention.impact",
          "DIMENSIONLESS",
        ),
        evidence_refs: evidence("demo-evidence-data-quality", "data_quality"),
        recommended_action: reason("REVIEW_DATA_QUALITY_EVIDENCE", DEMO),
        severity: reason("MEDIUM", DEMO),
        materiality_rank: 2,
        dedup_key: "demo-dedup-mark-staleness",
        first_seen: earlier,
        last_seen: asOf,
        occurrence_count: occurrences(6),
      },
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
        evidence_refs: evidence("demo-evidence-health", "health_transition"),
        /** A PERMITTED GOVERNANCE action, and never an execution instruction. */
        recommended_action: reason("REVIEW_STRATEGY_HEALTH_EVIDENCE", DEMO),
        severity: reason("HIGH", DEMO),
        materiality_rank: 1,
        dedup_key: "demo-dedup-strategy-health",
        first_seen: earlier,
        last_seen: asOf,
        occurrence_count: occurrences(2),
      },
      {
        /**
         * THE DUPLICATE. The same `dedup_key` as `demo-attention-2`, seen earlier and less
         * often, so deduplication folds it away deterministically -- and the panel SAYS it
         * folded one away rather than quietly showing a shorter list.
         */
        item_id: "demo-attention-2-earlier",
        what_happened: reason("MARK_DATA_OLDER_THAN_CONTRACT", DEMO),
        why_it_matters: reason("EXPOSURE_FIGURES_MAY_BE_STALE", DEMO),
        impact: absent(
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
          "attention.impact",
          "DIMENSIONLESS",
        ),
        evidence_refs: evidence("demo-evidence-data-quality-earlier", "data_quality"),
        recommended_action: reason("REVIEW_DATA_QUALITY_EVIDENCE", DEMO),
        severity: reason("MEDIUM", DEMO),
        materiality_rank: 2,
        dedup_key: "demo-dedup-mark-staleness",
        first_seen: earlier,
        last_seen: earlier,
        occurrence_count: occurrences(1),
      },
      {
        item_id: "demo-attention-3",
        what_happened: reason("BORROW_WITHDRAWN_FOR_A_SHORT_CANDIDATE", DEMO),
        why_it_matters: reason("SHORT_CANDIDATE_CANNOT_BE_ACTED_ON", DEMO),
        /** A MEASURED zero impact — a real answer, and not the same thing as no answer. */
        impact: available({
          metricId: "attention.impact_usd",
          unit: "USD",
          value: "0.00",
          asOf,
        }),
        evidence_refs: evidence("demo-evidence-borrow", "source_fact"),
        recommended_action: reason("REVIEW_SHORT_SIDE_BORROW_EVIDENCE", DEMO),
        severity: reason("MEDIUM", DEMO),
        materiality_rank: 3,
        dedup_key: "demo-dedup-borrow",
        first_seen: asOf,
        last_seen: asOf,
        occurrence_count: occurrences(1),
      },
      {
        item_id: "demo-attention-4",
        what_happened: reason("RECONCILIATION_ORPHAN_OBSERVED", DEMO),
        why_it_matters: reason("BROKER_AND_INTERNAL_STATE_MAY_DISAGREE", DEMO),
        impact: absent(
          "INSUFFICIENT_OBSERVATIONS",
          "BELOW_MINIMUM_OBSERVATIONS",
          "attention.impact",
          "DIMENSIONLESS",
        ),
        evidence_refs: evidence("demo-evidence-reconciliation", "reconciliation"),
        recommended_action: reason("REVIEW_RECONCILIATION_EVIDENCE", DEMO),
        severity: reason("LOW", DEMO),
        materiality_rank: 4,
        dedup_key: "demo-dedup-reconciliation",
        first_seen: earlier,
        last_seen: asOf,
        occurrence_count: occurrences(3),
      },
      {
        /**
         * INCOMPLETE ON PURPOSE: no evidence reference at all. §4.5 says an item missing any
         * of the five presented things is NOT RENDERED, and the panel reports that it withheld
         * one instead of silently showing a shorter list.
         */
        item_id: "demo-attention-incomplete",
        what_happened: reason("UNSOURCED_OBSERVATION", DEMO),
        why_it_matters: reason("NO_EVIDENCE_REFERENCE_EXISTS", DEMO),
        impact: absent(
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
          "attention.impact",
          "DIMENSIONLESS",
        ),
        evidence_refs: refListOf([], "ZERO_OR_MORE", asOf),
        recommended_action: reason("REVIEW_SYSTEM_ALERTS", DEMO),
        severity: reason("LOW", DEMO),
        materiality_rank: 5,
        dedup_key: "demo-dedup-unsourced",
        first_seen: asOf,
        last_seen: asOf,
        occurrence_count: occurrences(1),
      },
    ] satisfies AttentionItemPayload[],
  };
}

/* ---------------------------------------------------------------- What Changed */

/**
 * The four comparison behaviours §7 and U17 require, as four deterministic fixtures.
 *
 * Three of them are only reachable when something is WRONG with an endpoint, and a reviewer
 * cannot break a fixture from the interface — so each is selectable, and each is a complete,
 * internally consistent response rather than a mutation of the healthy one.
 */
export function syntheticWhatChanged(
  variant: Exclude<ChangeVariant, "auto">,
  asOf: string,
  baselineAsOf: string,
): WhatChangedPayload {
  const evidence = (id: string) => refListOf([ref(id, "source_fact")], "EXACTLY_ONE", asOf);

  if (variant === "no-baseline") {
    /*
     * NO PRIOR ENDPOINT EXISTS. There are no entries at all, because A DELTA COMPUTED AGAINST
     * A MISSING BASELINE IS A FABRICATED CHANGE (7, U17) -- and the reason it is missing is
     * STATED, rather than the panel rendering an empty list that reads as "nothing changed".
     */
    return {
      baseline_label: "No prior snapshot exists to compare against",
      comparison_as_of: asOf,
      baseline_state: { availability: "NOT_YET_AVAILABLE", reason: "UPSTREAM_INPUT_MISSING" },
      entries: [],
    };
  }

  if (variant === "none") {
    /*
     * BOTH ENDPOINTS ARE SOUND AND NOTHING CHANGED. That is a MEASUREMENT: the comparison ran
     * over a complete population and found no difference. It is a different fact from "no
     * baseline", which is what an unexplained empty list reads as.
     */
    return {
      baseline_label: "Since the previous demonstration snapshot",
      baseline_as_of: baselineAsOf,
      comparison_as_of: asOf,
      entries: [],
    };
  }

  if (variant === "degraded") {
    /*
     * BOTH ENDPOINTS EXIST, AND ONE SIDE OF EACH COMPARISON IS DEGRADED. Each entry reports
     * THAT STATE alongside its values rather than presenting a clean delta: a STALE prior
     * value keeps its qualification, and a PARTIAL after-value is shown as partial.
     *
     * Materiality is INDETERMINATE for both, because materiality computed from a degraded
     * endpoint is a judgement about a number nobody can stand behind.
     */
    return {
      baseline_label: "Since the previous demonstration snapshot (degraded inputs)",
      baseline_as_of: baselineAsOf,
      comparison_as_of: asOf,
      entries: [
        {
          change_id: "demo-change-degraded-1",
          subject: reason("OPEN_PLANNED_RISK", DEMO),
          change_kind: reason("VALUE_CHANGE", DEMO),
          before: qualified("STALE", "UPSTREAM_INPUT_STALE", {
            metricId: "risk.open_planned",
            unit: "USD",
            value: "1610.00",
            asOf: baselineAsOf,
          }),
          after: qualified("STALE", "UPSTREAM_INPUT_STALE", {
            metricId: "risk.open_planned",
            unit: "USD",
            value: "1850.00",
            asOf,
          }),
          materiality: reason("INDETERMINATE", DEMO),
          evidence_refs: evidence("demo-evidence-risk-degraded"),
        },
        {
          change_id: "demo-change-degraded-2",
          subject: reason("PORTFOLIO_RETURN", DEMO),
          change_kind: reason("VALUE_CHANGE", DEMO),
          before: qualified("PARTIAL", "EXTENT_PARTIALLY_COVERED", {
            metricId: "return.time_weighted",
            unit: "PERCENT",
            value: "2.90",
            asOf: baselineAsOf,
          }),
          after: qualified("PARTIAL", "EXTENT_PARTIALLY_COVERED", {
            metricId: "return.time_weighted",
            unit: "PERCENT",
            value: "3.24",
            asOf,
          }),
          materiality: reason("INDETERMINATE", DEMO),
          evidence_refs: evidence("demo-evidence-return-partial"),
        },
      ],
    };
  }

  /** `valid` — two sound endpoints, and real changes between them. */
  const entries: WhatChangedEntryPayload[] = [
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
      evidence_refs: evidence("demo-evidence-2"),
    },
    {
      change_id: "demo-change-2",
      subject: reason("OPEN_INCIDENTS", DEMO),
      change_kind: reason("APPEARANCE", DEMO),
      /**
       * NO PRIOR VALUE, and that is an APPEARANCE rather than a delta.
       *
       * An appearance is only REPORTABLE because both comparison populations are complete:
       * the baseline covered this subject and did not contain it. Inferring an appearance
       * from a subject the baseline never covered would be inventing a change out of missing
       * data (§7).
       */
      after: qualified("EMPTY_VERIFIED", "EMPTY_RESULT_VERIFIED", {
        metricId: "operations.open_incidents",
        unit: "COUNT",
        value: 0,
        asOf,
      }),
      materiality: reason("INFORMATIONAL", DEMO),
      evidence_refs: evidence("demo-evidence-3"),
    },
    {
      change_id: "demo-change-3",
      subject: reason("OPEN_PLANNED_RISK", DEMO),
      change_kind: reason("VALUE_CHANGE", DEMO),
      before: available({
        metricId: "risk.open_planned",
        unit: "USD",
        value: "1610.00",
        asOf: baselineAsOf,
      }),
      after: available({ metricId: "risk.open_planned", unit: "USD", value: "1850.00", asOf }),
      materiality: reason("MATERIAL", DEMO),
      evidence_refs: evidence("demo-evidence-4"),
    },
  ];

  return {
    baseline_label: "Since the previous demonstration snapshot",
    baseline_as_of: baselineAsOf,
    comparison_as_of: asOf,
    entries,
  };
}
