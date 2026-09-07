/**
 * The C3 payload contracts, transcribed from `read-model-contracts.md` §4.5.
 *
 * SCOPE: `ExecutiveOverview`, `AttentionItem`, `WhatChangedEntry` and `QualificationStatus`
 * — the read models the C3 foundation actually renders. The catalog is larger, and no
 * claim is made here that every catalogued read model exists.
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { refListFieldOf, refOf } from "./references";
import type { HostFieldKey } from "./references";
import {
  countValue,
  dateOnly,
  instant,
  magnitude,
  metricValue,
  money,
  reasonCoded,
  recordValue,
  safeId,
  series,
  seriesGranularity,
} from "./values";
import { availabilityState, fieldReasonCode } from "./vocabularies";

/**
 * §4.5 `{ at: MetricValue, ref: Ref }` — a last-run record.
 *
 * The instant is a `MetricValue`, not a bare timestamp, so "no run has ever happened" is
 * expressible as a STATE rather than as a missing key or an epoch zero. `ref` stays present
 * either way: §4.3 keeps a reference visible even when it resolves to an availability state,
 * so a reader knows the join exists and what it waits on.
 */
/*
 * IT TAKES ITS HOST FIELD, BECAUSE ONE SHAPE CARRIES TWO KINDS.
 *
 * `last_decision.ref` is a `decision` and `last_scout_run.ref` is a `research_run` (4.3.1),
 * so a single shared schema could only have validated whichever kind it was compiled with.
 * The kind is a property of the FIELD, and the field is what is passed in.
 */
const lastRunRecord = (key: HostFieldKey) => z.object({ at: metricValue, ref: refOf(key) });
export type LastRunRecord = z.infer<ReturnType<typeof lastRunRecord>>;

/**
 * §4.4 — the four risk quantities, kept apart.
 *
 * C3 carried a two-field subset of two of them; C5 needs all four in full, and **a second
 * type with the same name is exactly what §4.2 forbids**. They are now defined once, in
 * `contracts/risk-records.ts`, and re-exported here so the read models that carried them
 * keep their import path.
 */
import { currentOpenPlannedRisk, permittedRisk } from "./risk-records";

export {
  currentOpenPlannedRisk,
  gapEventRisk,
  initialPlannedRisk,
  permittedRisk,
  PERMITTED_RISK_SCOPES,
} from "./risk-records";

const pnlWindow = z.object({
  window: z.enum(["DAY", "WEEK", "MONTH", "CUMULATIVE"]),
  /** realized and unrealized are NEVER summed into one unlabelled figure. */
  realized: metricValue,
  unrealized: metricValue,
});

export const executiveOverviewPayload = z.object({
  /** USD 80,000, authoritative. NEVER substituted by broker-reported equity. */
  strategy_capital: money,
  /** OBSERVED, informational, and never substituted for strategy capital. */
  broker_reported_equity: metricValue,
  cash: metricValue,
  pnl: z.array(pnlWindow),
  return_pct: metricValue,
  exposure: z.object({
    long: magnitude,
    short: magnitude,
    gross: magnitude,
    net: magnitude,
  }),
  open_planned_risk: recordValue(currentOpenPlannedRisk),
  permitted_open_risk: recordValue(permittedRisk),
  drawdown: metricValue,
  /** §4.3 kind `regime_context`. Carried even when it resolves to a state (§4.3). */
  regime_ref: refOf("ExecutiveOverview.regime_ref"),
  system_health: reasonCoded,
  /** The age of the OLDEST required input, never the newest and never the build age. */
  data_freshness: metricValue,
  active_strategies: countValue,
  open_incidents: countValue,
  /** Completed by C4: the Brain runtime that would produce one does not exist. */
  last_decision: lastRunRecord("ExecutiveOverview.last_decision.ref"),
  last_scout_run: lastRunRecord("ExecutiveOverview.last_scout_run.ref"),
  /** §4.5, kind `source_fact`. The counts a summary renders come from `total`, not `length`. */
  what_changed: refListFieldOf("ExecutiveOverview.what_changed"),
  attention: refListFieldOf("ExecutiveOverview.attention"),
  /** One entry per tile, so a PARTIAL page names its failing parts. */
  tile_availability: z.array(
    z.object({ tile_id: safeId, availability: availabilityState, reason: fieldReasonCode }),
  ),
});
export type ExecutiveOverviewPayload = z.infer<typeof executiveOverviewPayload>;

export const EXECUTIVE_OVERVIEW_SCHEMA = "cockpit.executive_overview.v2";
export const executiveOverviewEnvelope = envelope(
  executiveOverviewPayload,
  EXECUTIVE_OVERVIEW_SCHEMA,
);

/**
 * §4.5 `AttentionItem`. An item missing any of the five presented things is NOT RENDERED,
 * and `recommended_action` is drawn from a closed governance vocabulary containing no
 * order, stop, capital, risk, promotion or provider verb.
 */
export const attentionItemPayload = z.object({
  item_id: safeId,
  what_happened: reasonCoded,
  why_it_matters: reasonCoded,
  impact: metricValue,
  evidence_refs: refListFieldOf("AttentionItem.evidence_refs"),
  recommended_action: reasonCoded,
  severity: reasonCoded,
  materiality_rank: z.number().int(),
  dedup_key: safeId,
  first_seen: instant,
  last_seen: instant,
  occurrence_count: countValue,
});
export type AttentionItemPayload = z.infer<typeof attentionItemPayload>;

export const ATTENTION_LIST_SCHEMA = "cockpit.attention_list.v2";
export const attentionListEnvelope = envelope(
  z.object({ items: z.array(attentionItemPayload) }),
  ATTENTION_LIST_SCHEMA,
);

/**
 * §4.5 `WhatChangedEntry`. A change with no resolvable evidence reference is not rendered,
 * and a change is NEVER synthesised from the absence of a value.
 */
export const whatChangedEntryPayload = z.object({
  change_id: safeId,
  subject: reasonCoded,
  change_kind: reasonCoded,
  /** Present when a prior value exists. A delta against a missing baseline is fabricated. */
  before: metricValue.optional(),
  after: metricValue,
  materiality: reasonCoded,
  evidence_refs: refListFieldOf("WhatChangedEntry.evidence_refs"),
});
export type WhatChangedEntryPayload = z.infer<typeof whatChangedEntryPayload>;

export const WHAT_CHANGED_SCHEMA = "cockpit.what_changed.v2";
export const whatChangedEnvelope = envelope(
  z
    .object({
      /** The comparison window is explicit and displayed; both endpoints carry their as-of. */
      baseline_label: z.string().min(1),
      baseline_as_of: instant.optional(),
      comparison_as_of: instant.optional(),
      /**
       * WHY no comparison was possible, when none was.
       *
       * A missing baseline is an availability state with a reason code — never a zero
       * baseline, and never an entry list computed against one endpoint. It is present
       * exactly when `baseline_as_of` is absent, so the two cannot disagree about whether a
       * baseline exists.
       */
      baseline_state: z
        .object({ availability: availabilityState, reason: fieldReasonCode })
        .optional(),
      /** Present only when BOTH endpoints are available; otherwise the state says so. */
      entries: z.array(whatChangedEntryPayload),
    })
    .superRefine((candidate, ctx) => {
      const hasBaseline = candidate.baseline_as_of !== undefined;
      if (hasBaseline === (candidate.baseline_state !== undefined)) {
        ctx.addIssue({
          code: "custom",
          message:
            "a comparison states EITHER a baseline as-of OR the state explaining its absence",
        });
      }
      /*
       * "A DELTA COMPUTED AGAINST A MISSING BASELINE IS A FABRICATED CHANGE" (7, U17). With
       * no baseline endpoint there is nothing to compare against, so there are no entries --
       * enforced here rather than left to whichever component renders the list.
       */
      if (!hasBaseline && candidate.entries.length > 0) {
        ctx.addIssue({
          code: "custom",
          message: "no baseline endpoint exists, so no entry can state a change against one",
        });
      }
      if (hasBaseline && candidate.comparison_as_of === undefined) {
        ctx.addIssue({
          code: "custom",
          message: "a comparison against a baseline states the instant it was compared at",
        });
      }
      if (
        candidate.baseline_as_of !== undefined &&
        candidate.comparison_as_of !== undefined &&
        candidate.baseline_as_of >= candidate.comparison_as_of
      ) {
        ctx.addIssue({
          code: "custom",
          message: "the baseline endpoint precedes the comparison endpoint",
        });
      }
      /*
       * An entry whose BEFORE is present must be a delta, and an entry whose before is absent
       * is an APPEARANCE. Both are legitimate; what is not is an entry carrying a `before`
       * that is not value-bearing, which renders as a delta from a value nobody has.
       */
      for (const entry of candidate.entries) {
        if (entry.before === undefined) {
          continue;
        }
        const bearing = ["AVAILABLE", "STALE", "PARTIAL", "EMPTY_VERIFIED"].includes(
          entry.before.availability,
        );
        if (!bearing) {
          ctx.addIssue({
            code: "custom",
            message:
              `change ${entry.change_id} carries a prior value that is not a value: an ` +
              "unavailable endpoint is reported as that state, never as a delta",
          });
        }
      }
    }),
  WHAT_CHANGED_SCHEMA,
);

/**
 * §4.5 `QualificationStatus` — REAL facts, provenance `REPOSITORY_TRACKED`, classification
 * `PUBLIC_SAFE`. Each fact carries the tracked source it was read from, each gate is read
 * INDEPENDENTLY, P1-P9 render `UNEVALUATED`, and Run B authorization and its date gate
 * render as TWO SEPARATE FACTS.
 */
const trackedSource = z.object({
  /** The exact tracked path the fact was read from. */
  path: z.string().min(1),
  /** The exact repository commit the fact was read at. */
  commit: z.string().regex(/^[0-9a-f]{40}$/, "commit must be a full 40-character SHA"),
});

export const qualificationStatusPayload = z.object({
  facts: z.array(
    z.object({
      fact_id: safeId,
      subject: reasonCoded,
      state: reasonCoded,
      as_of: dateOnly,
      source: trackedSource,
    }),
  ),
  gates: z.array(
    z.object({
      gate: z.enum(["G1", "G2", "G3", "G4", "G5", "G6", "G7"]),
      state: z.enum(["OPEN", "CLOSED"]),
      scope: reasonCoded,
      source: trackedSource,
    }),
  ),
  adr_states: z.array(
    z.object({ adr: safeId, state: reasonCoded, source: trackedSource }),
  ),
  /** P1 to P9, and UNEVALUATED is the only state this payload can carry today. */
  provider_tests: z.array(
    z.object({ test: reasonCoded, state: z.literal("UNEVALUATED") }),
  ),
  /**
   * Authorization and date eligibility are TWO SEPARATE FACTS.
   *
   * `date_gate` is the earliest APPROVED TARGET date and `authorization` is a written
   * decision. A date arriving changes the first and NEVER the second, which is why they are
   * separate fields rather than one "ready" flag — and why `date_basis` states the calendar
   * the comparison is made on, so "has the date passed" has one answer rather than a
   * timezone's worth of them.
   */
  run_authorizations: z.array(
    z.object({
      run: reasonCoded,
      authorization: reasonCoded,
      date_gate: metricValue,
      /** The calendar the date gate is evaluated on. A date without a basis is not a gate. */
      date_basis: reasonCoded,
      /** The separation this run must keep from the one before it, where one is required. */
      minimum_separation: metricValue,
      /** The run this separation is measured from, where there is one. */
      preceded_by: reasonCoded.optional(),
      source: trackedSource,
    }),
  ),
  /**
   * What stands between the project and the next gate, each read from tracked authority.
   * A blocker is a recorded state, never an estimate and never a percentage of anything.
   */
  blockers: z.array(
    z.object({
      blocker_id: safeId,
      subject: reasonCoded,
      state: reasonCoded,
      /** The gate or run this blocker stands in front of. */
      blocks: reasonCoded,
      source: trackedSource,
    }),
  ),
  /** The one governance event that must happen next. Not a prediction, and not a schedule. */
  next_required_event: z.object({
    event: reasonCoded,
    /** Who takes it. Every one of these is a human decision. */
    actor: reasonCoded,
    /** What must be true first, stated rather than implied. */
    prerequisite: reasonCoded,
    source: trackedSource,
  }),
  /**
   * The governed research values of `CLAUDE.md` §6, reproduced for display context.
   *
   * THEY LIVE HERE, IN THE TRACKED READ MODEL, ON PURPOSE. They are REAL facts read from
   * tracked repository authority, and §2.2 forbids relabelling a real fact `SYNTHETIC` —
   * which is what carrying them inside the synthetic risk snapshot would do. The risk screen
   * reads both models and badges each panel individually, exactly as §5 requires of a page
   * carrying both kinds.
   *
   * **They are research parameters, not permitted limits**, and not performance expectations.
   * Displaying one grants nothing, authorizes nothing and changes nothing.
   */
  research_parameters: z.array(
    z.object({
      parameter: reasonCoded,
      value: metricValue,
      /** What the number is measured against, so a percentage names its denominator. */
      basis: reasonCoded,
      source: trackedSource,
    }),
  ),
  /** The delivery cycle this application is in, read from tracked authority. */
  implementation_phase: reasonCoded,
  phase_state: reasonCoded,
  live_trading: reasonCoded,
  /** The repository revision the facts were read from -- the payload identity. */
  read_at_commit: z.string().regex(/^[0-9a-f]{40}$/),
  /**
   * WHEN THE SNAPSHOT WAS TAKEN, which is not when any fact became true.
   *
   * Each fact carries its own `as_of` — the date the SOURCE records — and this carries the
   * date the transcription happened. Collapsing them would date every fact to the day someone
   * copied it, and a governance record's age is measured from when it became true.
   */
  snapshot_extracted_on: dateOnly,
});
export type QualificationStatusPayload = z.infer<typeof qualificationStatusPayload>;

export const QUALIFICATION_STATUS_SCHEMA = "cockpit.qualification_status.v1";
export const qualificationStatusEnvelope = envelope(
  qualificationStatusPayload,
  QUALIFICATION_STATUS_SCHEMA,
);

/* ================================================================ PerformanceSeries */

/**
 * §4.2 `SignedMoney` — "Money plus an explicit sign convention: profit positive, loss
 * negative". A cash flow states the same convention: money arriving is positive, money
 * leaving is negative, and the `kind` and the sign must agree rather than being two
 * independent claims about one movement.
 */
export const signedMoney = z.object({
  amount: money.shape.amount,
  currency: money.shape.currency,
  sign_convention: z.literal("INFLOW_POSITIVE_OUTFLOW_NEGATIVE"),
});

export const cashFlow = z
  .object({
    at: instant,
    amount: signedMoney,
    kind: z.enum(["DEPOSIT", "WITHDRAWAL"]),
  })
  .superRefine((candidate, ctx) => {
    const negative = candidate.amount.amount.startsWith("-");
    if (candidate.kind === "WITHDRAWAL" && !negative) {
      ctx.addIssue({ code: "custom", message: "a WITHDRAWAL is a negative signed amount" });
    }
    if (candidate.kind === "DEPOSIT" && negative) {
      ctx.addIssue({ code: "custom", message: "a DEPOSIT is a positive signed amount" });
    }
  });

export const COST_TREATMENTS = ["GROSS", "NET_COMMISSIONS", "NET_ALL_COSTS"] as const;
export const DRAWDOWN_BASES = ["CLOSE_ONLY", "INTRADAY"] as const;

/**
 * §4.5 `PerformanceSeries` — the read model the executive performance overview draws.
 *
 * IT IS A READ MODEL, NOT A CHART SHAPE. A chart-only structure would bypass admission and
 * carry no provenance, no as-of, no coverage and no availability — and "a series with mixed
 * provenance is never drawn as one line" (`ui-ux-specification.md` §13) is not enforceable on
 * a bare array of numbers.
 *
 * Four invariants are checked here rather than trusted to the renderer:
 *
 *   THE THREE SERIES ARE ALIGNED    same granularity, calendar, timezone and instants, so a
 *                                   reader comparing equity against drawdown at a point is
 *                                   comparing the same period
 *   A DRAWDOWN IS NOT POSITIVE      §12.3 defines `drawdown.current` as `equity/peak − 1`,
 *                                   which is <= 0. A positive "drawdown" is a different
 *                                   quantity wearing the name
 *   A GAP IS PARTIAL                missing points make the series `PARTIAL`, never zero;
 *                                   `Series` itself enforces coverage against the extent
 *   COST TREATMENT IS STATED        two summaries with different treatments are never
 *                                   compared, so a series that does not say which it is
 *                                   cannot be compared with anything
 */
export const performanceSeriesPayload = z
  .object({
    series_id: safeId,
    granularity: seriesGranularity,
    /** The named market calendar. A date range without one is not a date range. */
    calendar: reasonCoded,
    /** The half-open window the extent was requested over, stated with its basis. */
    window: z.object({
      from: instant,
      to: instant,
      calendar: reasonCoded,
      timezone: z.literal("UTC"),
    }),
    equity: series,
    return_series: series,
    drawdown_series: series,
    /**
     * ADDITIVE: the return of EACH period, aligned to the same instants.
     *
     * `return_series` is cumulative since the window opened; this is per period, and the two
     * carry different `metric_id`s because they are different quantities. It exists so a
     * heat map of monthly returns reads a produced value instead of a screen deriving one —
     * **a screen that computes its own variant of a metric is reporting a different metric
     * under the same name** (§12.2).
     */
    period_return_series: series.optional(),
    /** CLOSE_ONLY or INTRADAY, stated ON the series (§4.5). */
    drawdown_basis: z.enum(DRAWDOWN_BASES),
    /**
     * A deposit or withdrawal NEVER appears in a return or profit series (§4.5), and the
     * equity series used for drawdown is cash-flow adjusted so an external flow produces no
     * drawdown and no new peak (§12.3).
     */
    cash_flows: z.array(cashFlow),
    cost_treatment: z.enum(COST_TREATMENTS),
    /** §4.3 kind `benchmark_series`. Present as references; never spliced into one line. */
    benchmark_refs: refListFieldOf("PerformanceSeries.benchmark_refs"),
    /** The benchmark actually drawn, when one is resolvable. ABSENT is the ordinary case. */
    benchmark_series: series.optional(),
    benchmark_label: reasonCoded.optional(),
  })
  .superRefine((candidate, ctx) => {
    const aligned = [candidate.equity, candidate.return_series, candidate.drawdown_series];
    for (const other of aligned.slice(1)) {
      if (
        other.granularity !== candidate.equity.granularity ||
        other.calendar.code !== candidate.equity.calendar.code ||
        other.points.length !== candidate.equity.points.length
      ) {
        ctx.addIssue({
          code: "custom",
          message: "the equity, return and drawdown series share one granularity, calendar and extent",
        });
        return;
      }
    }
    for (let index = 0; index < candidate.equity.points.length; index += 1) {
      if (
        candidate.return_series.points[index].t !== candidate.equity.points[index].t ||
        candidate.drawdown_series.points[index].t !== candidate.equity.points[index].t
      ) {
        ctx.addIssue({
          code: "custom",
          message: "the three series carry the same instants, so one point is one period",
        });
        return;
      }
    }
    for (const point of candidate.drawdown_series.points) {
      if (typeof point.v.value !== "string") {
        continue;
      }
      if (!point.v.value.startsWith("-") && /[1-9]/.test(point.v.value)) {
        ctx.addIssue({
          code: "custom",
          message: "a drawdown is equity/peak - 1, which is never positive (§12.3)",
        });
        return;
      }
    }
    if (
      candidate.period_return_series !== undefined &&
      candidate.period_return_series.points.length !== candidate.equity.points.length
    ) {
      ctx.addIssue({
        code: "custom",
        message: "the per-period return series covers the same periods as the equity series",
      });
    }
    if (candidate.granularity !== candidate.equity.granularity) {
      ctx.addIssue({
        code: "custom",
        message: "the payload granularity is the granularity its series actually carry",
      });
    }
    if (
      candidate.benchmark_series !== undefined &&
      candidate.benchmark_label === undefined
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a drawn benchmark is named, so a reader knows what it is being compared with",
      });
    }
  });
export type PerformanceSeriesPayload = z.infer<typeof performanceSeriesPayload>;

export const PERFORMANCE_SERIES_SCHEMA = "cockpit.performance_series.v1";
export const performanceSeriesEnvelope = envelope(
  performanceSeriesPayload,
  PERFORMANCE_SERIES_SCHEMA,
);
