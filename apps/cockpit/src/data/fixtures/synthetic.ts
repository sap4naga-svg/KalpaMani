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
import type { OwningArea } from "@/contracts/vocabularies";
import type { AttentionListPayload, WhatChangedPayload } from "@/data/client/read-client";
import type { ChangeVariant } from "@/lib/scope";

import { absent, available, qualified, reason, refListOf } from "@/contracts/factories";

import {
  BOOK,
  STRATEGY_CAPITAL_CENTS,
  centsToDecimal,
  pctOfCapitalHundredths,
} from "./book";
import { equityWindow } from "./equity";

const DEMO = "kalpamani.demo";

/**
 * A reference, optionally DECLARING the area that owns the record it names (§4.3.2).
 *
 * With no fourth argument the reference carries no `owning_area` key at all rather than an
 * `undefined` one: an absence states nothing, and no area is ever invented to satisfy a link.
 */
const ref = (
  id: string,
  kind: Ref["ref_kind"],
  resolution: Ref["resolution"] = "UNRESOLVABLE_V1",
  owningArea?: OwningArea,
): Ref => {
  const reference: Ref = {
    ref_id: id,
    ref_kind: kind,
    resolution,
    classification: "PUBLIC_SAFE",
  };
  return owningArea === undefined ? reference : { ...reference, owning_area: owningArea };
};

/**
 * Realized profit and loss over the last `sessions` sessions of the retained extent.
 *
 * The windows are counted in SESSIONS on the named market calendar, not in wall-clock days,
 * because the ledger's exits are dated by session. A window containing no exit reports a
 * measured zero, and ADR-0029 §2.1 keeps a measured zero `AVAILABLE`.
 */
function realizedOverSessions(sessions: number): number {
  const from = BOOK.equityCents.length - sessions;
  return BOOK.trades.reduce(
    (total, trade) =>
      total +
      trade.exits
        .filter((exit) => exit.session >= from)
        .reduce((subtotal, exit) => subtotal + exit.realizedCents, 0),
    0,
  );
}

/**
 * The executive overview, projected from the SAME demonstration book every C5 screen reads.
 *
 * IT USED TO CARRY ITS OWN HAND-WRITTEN TOTALS, and they were internally consistent with
 * nothing: the overview said gross exposure was USD 39,600 while the positions that produced
 * it did not exist yet. Now every figure below is read from the book, so the overview, the
 * position table, the exposure aggregates, the trade ledger and the equity curve are five
 * projections of one set of numbers.
 */
export function syntheticExecutiveOverview(
  asOf: string,
  originMs: number,
): ExecutiveOverviewPayload {
  const totals = BOOK.totals;
  const window = equityWindow(originMs, "ALL");
  /** Cash is what the equity is not carrying as a net position. */
  const netSignedCents =
    totals.netDirection === "LONG" ? totals.netValueCents : -totals.netValueCents;
  const equityCents = BOOK.equityCents[BOOK.equityCents.length - 1];
  const cashCents = equityCents - netSignedCents;
  const money = (cents: number) => centsToDecimal(cents);
  const realized = (cents: number) =>
    available({ metricId: "pnl.realized", unit: "USD", value: money(cents), asOf });
  const unrealized = () =>
    available({
      metricId: "pnl.unrealized",
      unit: "USD",
      value: money(totals.unrealizedCents),
      asOf,
    });
  return {
    /** The authoritative strategy capital of CLAUDE.md section 6. Never broker equity. */
    strategy_capital: { amount: centsToDecimal(STRATEGY_CAPITAL_CENTS), currency: "USD" },
    /** OBSERVED and informational. It never participates in sizing. */
    broker_reported_equity: available({
      metricId: "portfolio.broker_reported_equity",
      unit: "USD",
      value: "1000000.00",
      asOf,
    }),
    cash: available({ metricId: "portfolio.cash", unit: "USD", value: money(cashCents), asOf }),
    /**
     * Realized and unrealized are NEVER summed into one unlabelled figure, and each window's
     * realized figure counts only the exits inside it.
     *
     * Unrealized is a POINT-IN-TIME quantity: the open book's mark-to-market right now. It is
     * the same in every window because it is not a flow, and reporting a different unrealized
     * per window would state a change nobody measured.
     */
    pnl: [
      { window: "DAY", realized: realized(realizedOverSessions(1)), unrealized: unrealized() },
      { window: "WEEK", realized: realized(realizedOverSessions(5)), unrealized: unrealized() },
      {
        window: "MONTH",
        realized: realized(realizedOverSessions(21)),
        /** A value-bearing state that keeps its qualification. A stale figure is still stale. */
        unrealized: qualified("STALE", "UPSTREAM_INPUT_STALE", {
          metricId: "pnl.unrealized",
          unit: "USD",
          value: money(totals.unrealizedCents),
          asOf,
        }),
      },
      {
        window: "CUMULATIVE",
        realized: realized(totals.realizedCents),
        unrealized: unrealized(),
      },
    ],
    /** The chain-linked time-weighted return over the whole retained extent. */
    return_pct: available({
      metricId: "return.time_weighted",
      unit: "PERCENT",
      value: centsToDecimal(window.totalReturnHundredths),
      asOf,
    }),
    /** Magnitude and direction, never a profit sign, and read from the open positions. */
    exposure: {
      long: { amount: money(totals.longValueCents), currency: "USD", direction: "LONG" },
      short: { amount: money(totals.shortValueCents), currency: "USD", direction: "SHORT" },
      gross: { amount: money(totals.grossValueCents), currency: "USD", direction: "LONG" },
      net: {
        amount: money(totals.netValueCents),
        currency: "USD",
        direction: totals.netDirection,
      },
    },
    /**
     * The §4.4 assessment, in full.
     *
     * C3 carried a two-field subset of this record; C5 completed it, so the assessment now
     * states the instant it was made at, the policy version that produced it, the
     * protective state it read and the fact that it is an ASSESSMENT rather than an entry
     * record. USD 1,850.00 is 2.31% of the authoritative USD 80,000 strategy capital.
     */
    open_planned_risk: {
      record: {
        risk_money: available({
          metricId: "risk.open_planned",
          unit: "USD",
          value: money(totals.openPlannedRiskCents),
          asOf,
        }),
        risk_pct_of_capital: available({
          metricId: "risk.open_planned_pct",
          unit: "PERCENT",
          value: centsToDecimal(pctOfCapitalHundredths(totals.openPlannedRiskCents)),
          asOf,
        }),
        as_of: asOf,
        assessment_ref: ref("demo-risk-assessment", "risk_decision", "AUTHORIZED_READ"),
        risk_policy_ref: {
          policy_id: "risk-policy-demo",
          policy_version: "0.0.0-demo",
          as_of: asOf,
        },
        protection_state: reason("PROTECTIVE_ORDER_WORKING", DEMO),
        source: "RISK_ENGINE_ASSESSMENT",
        staleness: "FRESH",
      },
      /*
       * PARTIAL, because one of the five component assessments is STALE.
       *
       * §4.4: "an aggregate containing any STALE or missing component is PARTIAL with the
       * components named". The risk dashboard names them; the overview reports the state.
       */
      availability: "PARTIAL",
      reason: "UPSTREAM_INPUT_STALE",
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
    drawdown: available({
      metricId: "drawdown.current",
      unit: "PERCENT",
      value: centsToDecimal(
        window.drawdownHundredths[window.drawdownHundredths.length - 1] ?? 0,
      ),
      asOf,
    }),
    /**
     * Completed by C4. The market-regime projection does not exist, so this reference resolves
     * to an availability state rather than to a payload -- which is what `UNRESOLVABLE_V1`
     * MEANS (4.3), and why the reference stays VISIBLE instead of being omitted.
     */
    regime_ref: ref("demo-regime-context", "regime_context", "ENDPOINT"),
    system_health: reason("DEMONSTRATION_ONLY", DEMO),
    data_freshness: available({
      metricId: "freshness.source_age",
      unit: "SECONDS",
      value: 45,
      asOf,
    }),
    /** How many EXACT versions the open book is attributed to, read from the positions. */
    active_strategies: available({
      metricId: "strategy.active_count",
      unit: "COUNT",
      value: new Set(BOOK.openTrades.map((trade) => trade.versionId)).size,
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
      ref: ref("demo-last-decision", "decision", "ENDPOINT"),
    },
    last_scout_run: {
      at: absent(
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
        "scout.last_run_at",
        "DIMENSIONLESS",
      ),
      ref: ref("demo-last-scout-run", "research_run", "ENDPOINT"),
    },
    /** The reference lists a summary counts from -- `total`, and never `items.length`. */
    what_changed: refListOf(
      [
        ref("demo-change-1", "source_fact", "AUTHORIZED_READ"),
        ref("demo-change-2", "source_fact", "AUTHORIZED_READ"),
      ],
      "ZERO_OR_MORE",
      asOf,
    ),
    attention: refListOf(
      [
        ref("demo-attention-1", "source_fact", "AUTHORIZED_READ"),
        ref("demo-attention-2", "source_fact", "AUTHORIZED_READ"),
        ref("demo-attention-3", "source_fact", "AUTHORIZED_READ"),
        ref("demo-attention-4", "source_fact", "AUTHORIZED_READ"),
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
  /*
   * THE TWO KINDS §4.5 PERMITS HERE, AND IT USED TO TAKE ANY KIND AT ALL.
   *
   * `AttentionItem.evidence_refs` is declared "kind `evidence` or `source_fact`" — a
   * stated SET — and this helper was handing it `data_quality`, `health_transition` and
   * `reconciliation`, three kinds the field may not carry. **The producer is corrected
   * rather than the field widened to fit it** (ADR-0030 R2).
   *
   * The kind is `source_fact` on EVERY item, and the reason is what an `AttentionItem`
   * IS. Area 28 names it a "projection, derived from alerts, health, risk, data quality
   * and governance", and section 4.3 defines `source_fact` as "the recorded fact a
   * projection was built from". Each of these references names exactly that: the recorded
   * data-quality finding, health transition, borrow record or reconciliation break the
   * item was projected from.
   *
   * **The borrow item is `source_fact` too, and it was briefly `evidence`.** The
   * catalogue types `evidence` on `ShortSideSnapshot.borrow[].record_ref`, which is a
   * DIFFERENT host field -- and R2 is explicit that "a kind is a property of the FIELD,
   * not of the field NAME". Read as an attention item's evidence, the borrow record is
   * the fact the projection was built from, and typing it `evidence` here left it the
   * one reference with NO owning-area destination, because section 5 catalogues no route
   * and no owning area for a classified evidence artefact and R10 refuses a guess.
   *
   * **THE PER-AREA DRILL-DOWN IS RESTORED, AND NOT BY TOUCHING A SINGLE KIND.** Every
   * reference below is still `source_fact`, because that is what it IS. What each one now
   * ALSO carries is `owning_area` -- the second closed attribute section 4.3.2 adds under
   * ADR-0031, answering the different question *which area is responsible for this record*.
   * The data-quality finding is owned by area 22, the health transition by area 5, the
   * reconciliation break by area 10, and the borrow record by area 13, whose acceptance
   * criterion is the one about borrow. **None of them is defaulted to the Audit Trail**,
   * which owns `AuditEvent` and does not own these.
   *
   * The area is DECLARED from the record's own ownership and never guessed from the
   * identifier, which is a fixture naming habit rather than a contract.
   */
  const evidence = (
    id: string,
    owningArea: OwningArea,
    kind: "evidence" | "source_fact" = "source_fact",
  ) => refListOf([ref(id, kind, "AUTHORIZED_READ", owningArea)], "EXACTLY_ONE", asOf);
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
        evidence_refs: evidence("demo-evidence-data-quality", "DATA_QUALITY"),
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
        evidence_refs: evidence("demo-evidence-health", "STRATEGY_HEALTH"),
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
        evidence_refs: evidence("demo-evidence-data-quality-earlier", "DATA_QUALITY"),
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
        evidence_refs: evidence("demo-evidence-borrow", "SHORT_SIDE"),
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
        evidence_refs: evidence("demo-evidence-reconciliation", "RECONCILIATION"),
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
  /*
   * THE AREA IS DECLARED WHERE A CATALOGUED AREA OWNS THE RECORD, AND ABSENT WHERE NONE DOES.
   *
   * A health transition is owned by area 5 and an incident by area 23, so those two say so.
   * The two risk-figure changes name a recorded risk fact, and the section 4.3.2 vocabulary
   * has NO risk member: the reference therefore DECLARES NONE rather than being pushed to the
   * nearest catalogued page. An absence here is a stated absence -- it is not a claim that no
   * area owns the record, and it is never resolved to `AUDIT_TRAIL` (A4, A2).
   */
  const evidence = (id: string, owningArea?: OwningArea) =>
    refListOf([ref(id, "source_fact", "AUTHORIZED_READ", owningArea)], "EXACTLY_ONE", asOf);

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
      evidence_refs: evidence("demo-evidence-2", "STRATEGY_HEALTH"),
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
      evidence_refs: evidence("demo-evidence-3", "SYSTEM_OPERATIONS"),
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
