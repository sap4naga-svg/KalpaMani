/**
 * The portfolio payload contracts of `read-model-contracts.md` §4.5.
 *
 * `PerformanceSummary`, `PositionSnapshot`, `ExposureAggregate`, `TradeSummary`,
 * `TradeDetail` and `TradeLifecycle` — the read models the C5 portfolio screens render.
 *
 * SCOPE, STATED HONESTLY. `TradeLifecycle` carries the **complete** lifecycle C6 owns —
 * orders, fills, protective-order events, adds, partial exits, the exit, reconciliation and
 * appended corrections — **for the trades whose execution evidence a fixture actually
 * records**, and every trade without such a record keeps the trade-level stages C5 carried
 * with every absent kind named. **A missing event renders as a gap and never as an
 * inference.** `ExecutionQuality` is carried for ONE TRADE, embedded on its detail; the
 * aggregate `/execution/quality` surface of Area 9 is a later cycle and nothing here
 * implements it. `ReconciliationStatus` is reached only as a reference that resolves to an
 * availability state.
 *
 * THE FOUR CONCEPTS STAY APART (Area 36.3): the trade ledger, one trade's story, execution
 * mechanics and the audit trail "share identifiers and never share a screen".
 */
import { z } from "zod";

import { collectionPayload } from "./pagination";
import { envelope } from "./envelope";
import { COST_TREATMENTS, signedMoney } from "./read-models";
import {
  currentOpenPlannedRisk,
  gapEventRisk,
  initialPlannedRisk,
  permittedRisk,
  PERMITTED_RISK_SCOPES,
} from "./risk-records";
import {
  instant,
  magnitude,
  metricOf,
  metricValue,
  money,
  quantity,
  reasonCoded,
  recordValue,
  ref,
  refList,
  safeId,
  series,
  hundredths,
  versionPins,
} from "./values";
import {
  availabilityState,
  DOWNSTREAM_STAGES,
  environment as environmentEnum,
  fieldReasonCode,
} from "./vocabularies";
import { isValueBearing } from "./validity";
import { executionQuality } from "./execution-models";
import { riskDecision } from "./risk-decision";

/** §2.7's downstream axis, as a schema. A SEPARATE axis, never merged with the Brain's. */
export const downstreamStage = z.enum(DOWNSTREAM_STAGES);

/** The §4.4 permitted-risk scopes, as a schema, so an ABSENT limit can still name itself. */
export const permittedScope = z.enum(PERMITTED_RISK_SCOPES);

/** The half-open analysis window, with the calendar basis a date range is meaningless without. */
export const analysisWindow = z.object({
  from: instant,
  to: instant,
  calendar: reasonCoded,
  timezone: z.literal("UTC"),
});

/**
 * The resolved identity of a security reference.
 *
 * §4.5 carries only `security_ref`, and a table of reference identifiers is unreadable. The
 * reference is therefore resolved `EMBEDDED` (§4.3) and its resolution carried here, as an
 * ADDITIVE presentation field: it is the display identity of the subject and nothing more.
 *
 * **It is not a vendor row.** No provider is selected, no licensed row exists in this
 * application, and every security this application can name is an obviously fictional,
 * repository-owned demonstration subject.
 */
export const securityIdentity = z.object({
  symbol: safeId,
  display_name: z.string().min(1),
});
export type SecurityIdentity = z.infer<typeof securityIdentity>;

/* ============================================================ PerformanceSummary */

export const TRADE_STATUSES = ["OPEN", "CLOSED", "PARTIALLY_EXITED"] as const;
export const DATA_COMPLETENESS = ["COMPLETE", "PARTIAL", "UNKNOWN"] as const;

/**
 * The declared minimum-observation rule of one metric, and whether it was met.
 *
 * §12.1 requires every metric to declare a minimum and to return
 * `INSUFFICIENT_OBSERVATIONS` with `BELOW_MINIMUM_OBSERVATIONS` below it. The minimums
 * differ per metric and they are not all counts of the same thing — `win_rate` and
 * `profit_factor` need 20 **trades**, `expectancy` needs 30 **trades**, and `sharpe` needs
 * 60 **return periods**. One number cannot carry four rules, so each rule travels with the
 * metric it governs.
 *
 * A screen showing a ratio without its rule has shown half the rule.
 */
export const observationRule = z
  .object({
    /** The dictionary key this rule governs. */
    metric_id: z.string().min(1),
    /** What the rule counts — trades, or return periods. They are not interchangeable. */
    population: reasonCoded,
    observed: metricOf("performance.observation_count"),
    minimum: metricOf("performance.minimum_observations"),
    met: z.boolean(),
  })
  .superRefine((candidate, ctx) => {
    const observed = candidate.observed.value;
    const minimum = candidate.minimum.value;
    if (typeof observed !== "number" || typeof minimum !== "number") {
      return;
    }
    if (candidate.met !== observed >= minimum) {
      ctx.addIssue({
        code: "custom",
        message: "a rule is met exactly when the observed count reaches its declared minimum",
      });
    }
  });
export type ObservationRule = z.infer<typeof observationRule>;

/** Which field each observation rule governs. A rule naming no field governs nothing. */
const RULE_FIELDS: Readonly<Record<string, "expectancy" | "profit_factor" | "win_rate" | "sharpe">> =
  {
    "expectancy.currency": "expectancy",
    "expectancy.r": "expectancy",
    profit_factor: "profit_factor",
    win_rate: "win_rate",
    sharpe: "sharpe",
  };

/**
 * §4.5 `PerformanceSummary` — the ratios, over one **defined** population and one window.
 *
 * Four invariants are enforced here rather than trusted to a screen:
 *
 *   A RATIO BELOW ITS MINIMUM IS NOT A RATIO   a metric whose own rule is unmet may not be
 *                                              value-bearing, whatever the others did
 *   THE RULES ARE STATED, NOT IMPLIED          every governed metric carries its observed
 *                                              count and its declared minimum
 *   THE WINDOW IS EXPLICIT                     half-open, with its calendar and timezone
 *   THE COST TREATMENT IS STATED               two summaries with different treatments are
 *                                              never compared (§4.5)
 */
export const performanceSummaryPayload = z
  .object({
    window: analysisWindow,
    total_return: metricOf("return.time_weighted"),
    /** Present only when explicitly requested, and always labelled as such (§12.4). */
    money_weighted_return: metricOf("return.money_weighted").optional(),
    max_drawdown: metricOf("drawdown.max"),
    /** Unit stated by the metric it carries: `expectancy.currency` or `expectancy.r`. */
    expectancy: z.union([metricOf("expectancy.currency"), metricOf("expectancy.r")]),
    profit_factor: metricOf("profit_factor"),
    win_rate: metricOf("win_rate"),
    sharpe: metricOf("sharpe"),
    average_winner: metricOf("pnl.average_winner"),
    average_loser: metricOf("pnl.average_loser"),
    r_multiple_distribution: z.array(
      z.object({ bucket: reasonCoded, count: metricOf("r_multiple.bucket_count") }),
    ),
    /** The defined population every ratio above is computed over. */
    trade_population: reasonCoded,
    /** True exactly when every rule below is met. */
    minimum_observations_met: z.boolean(),
    cost_treatment: z.enum(COST_TREATMENTS),
    /** ADDITIVE: the per-metric rules of §12.1, so a reader can check them. */
    observation_rules: z.array(observationRule),
    /** The size of the defined population itself. */
    observation_count: metricOf("performance.observation_count"),
    /**
     * ADDITIVE: rows the population deliberately excludes, and why.
     *
     * §12.3 refuses `expectancy.r` "for any trade lacking `risk.initial_planned`", so a
     * population that silently dropped one would report an average over a different set
     * than it names. Each exclusion is counted and reason-coded, exactly as
     * `slippage.aggregate` requires of the fills it cannot reference.
     */
    exclusions: z.array(
      z.object({ reason: reasonCoded, count: metricOf("trade.count") }),
    ),
  })
  .superRefine((candidate, ctx) => {
    const fields = {
      expectancy: candidate.expectancy,
      profit_factor: candidate.profit_factor,
      win_rate: candidate.win_rate,
      sharpe: candidate.sharpe,
    } as const;
    const everyRuleMet = candidate.observation_rules.every((rule) => rule.met);
    if (candidate.minimum_observations_met !== everyRuleMet) {
      ctx.addIssue({
        code: "custom",
        message: "minimum_observations_met states whether EVERY declared rule was met",
      });
    }
    for (const rule of candidate.observation_rules) {
      const field = RULE_FIELDS[rule.metric_id];
      if (field === undefined) {
        ctx.addIssue({
          code: "custom",
          message: `observation rule ${rule.metric_id} governs no field of this summary`,
        });
        continue;
      }
      if (!rule.met && isValueBearing(fields[field].availability)) {
        ctx.addIssue({
          code: "custom",
          message: `${field} carries a value below its own declared minimum observation count`,
        });
      }
    }
  });
export type PerformanceSummaryPayload = z.infer<typeof performanceSummaryPayload>;

export const PERFORMANCE_SUMMARY_SCHEMA = "cockpit.performance_summary.v1";
export const performanceSummaryEnvelope = envelope(
  performanceSummaryPayload,
  PERFORMANCE_SUMMARY_SCHEMA,
);

/* =============================================================== PositionSnapshot */

const positionGroupings = z.object({
  sector: reasonCoded,
  industry: reasonCoded,
  strategy_module: reasonCoded,
  alpha_family: reasonCoded,
  factor_bucket: reasonCoded,
  correlation_cluster: reasonCoded,
});

/**
 * §4.5 `PositionSnapshot`.
 *
 * **Borrow state comes from a record and is never inferred from price behaviour**, and an
 * unknown borrow state renders unknown, **never available**. The two risk quantities are
 * separate fields and **neither is derived from the other**.
 */
export const positionSnapshot = z
  .object({
    position_id: safeId,
    security_ref: ref,
    /** The `EMBEDDED` resolution of that reference. A fictional demonstration subject. */
    security: securityIdentity,
    direction: z.enum(["LONG", "SHORT"]),
    quantity,
    entry_price: metricOf("position.entry_price"),
    /** The mark, carrying its OWN as-of — never the response's. */
    current_price: metricOf("position.current_price"),
    unrealized: signedMoney,
    initial_planned_risk: recordValue(initialPlannedRisk),
    open_planned_risk: recordValue(currentOpenPlannedRisk),
    /** Present where the model applies. A modelled scenario, never folded into planned risk. */
    gap_event_risk: recordValue(gapEventRisk).optional(),
    /** A REFERENCE to a level, never an order. */
    invalidation_ref: ref,
    holding_duration: metricOf("holding_period"),
    /** Required when direction is SHORT. From a borrow RECORD, never inferred from price. */
    borrow_state: reasonCoded.optional(),
    groupings: positionGroupings,
    trade_ref: ref,
    pins: versionPins,
  })
  .superRefine((candidate, ctx) => {
    if (candidate.direction === "SHORT" && candidate.borrow_state === undefined) {
      ctx.addIssue({
        code: "custom",
        message: "a short position states its borrow state, read from a borrow record",
      });
    }
    if (candidate.quantity <= 0) {
      ctx.addIssue({
        code: "custom",
        message: "an open position holds a positive share count; direction carries the side",
      });
    }
  });
export type PositionSnapshot = z.infer<typeof positionSnapshot>;

export const positionSnapshotPayload = collectionPayload(positionSnapshot, {
  /** The snapshot instant every position in this page was valued against. */
  as_of: instant,
  /** The authoritative strategy capital every percentage is measured against. */
  strategy_capital: money,
});
export type PositionSnapshotPayload = z.infer<typeof positionSnapshotPayload>;

export const POSITION_SNAPSHOT_SCHEMA = "cockpit.position_snapshot.v1";
export const positionSnapshotEnvelope = envelope(
  positionSnapshotPayload,
  POSITION_SNAPSHOT_SCHEMA,
);

/* =============================================================== ExposureAggregate */

/**
 * One bucket of one grouping axis.
 *
 * **Every magnitude carries a direction and no exposure carries a profit sign** (§4.5). The
 * arithmetic between the four is checked in integer hundredths rather than in doubles:
 * `gross` is long plus short, and `net` is their difference, carried as a positive magnitude
 * whose `direction` states which side it leans.
 */
export const exposureBucket = z
  .object({
    bucket: reasonCoded,
    long: magnitude,
    short: magnitude,
    gross: magnitude,
    net: magnitude,
    open_planned_risk: recordValue(currentOpenPlannedRisk),
    position_count: metricOf("position.count"),
  })
  .superRefine((candidate, ctx) => {
    if (candidate.long.direction !== "LONG" || candidate.short.direction !== "SHORT") {
      ctx.addIssue({
        code: "custom",
        message: "the long and short magnitudes carry their own sides",
      });
    }
    const long = hundredths(candidate.long.amount);
    const short = hundredths(candidate.short.amount);
    const gross = hundredths(candidate.gross.amount);
    const net = hundredths(candidate.net.amount);
    if (long === null || short === null || gross === null || net === null) {
      return;
    }
    if (long < 0 || short < 0 || gross < 0 || net < 0) {
      ctx.addIssue({
        code: "custom",
        message: "a magnitude is never negative; the direction carries the side",
      });
      return;
    }
    if (gross !== long + short) {
      ctx.addIssue({ code: "custom", message: "gross exposure is long plus short" });
    }
    if (net !== Math.abs(long - short)) {
      ctx.addIssue({
        code: "custom",
        message: "net exposure is the magnitude of long minus short",
      });
    }
    const leansLong = long >= short;
    if (net !== 0 && candidate.net.direction !== (leansLong ? "LONG" : "SHORT")) {
      ctx.addIssue({
        code: "custom",
        message: "net exposure leans to the larger side, and its direction says which",
      });
    }
  });
export type ExposureBucket = z.infer<typeof exposureBucket>;

/**
 * §4.5 `ExposureAggregate`.
 *
 * **A grouping is displayed, never computed as a permitted exposure**, and `permitted`
 * carries separately governed policy values that this application displays and does not
 * derive. **A position contributes to each axis exactly once.**
 */
export const exposureAggregate = z.object({
  grouping: reasonCoded,
  buckets: z.array(exposureBucket),
  /** The named base every magnitude is measured against. */
  base: reasonCoded,
  /**
   * The permitted limits that apply to this axis.
   *
   * **The scope is carried OUTSIDE the record**, and that is additive on purpose: §4.4 keeps
   * `scope` inside `PermittedRisk`, so an ABSENT limit — the ordinary case, because a
   * permitted value with no versioned policy reference is `POLICY_REFERENCE_MISSING` and is
   * never served — could not say WHICH limit is missing. Naming the scope beside the wrapper
   * lets a missing limit be reported as the specific missing limit it is.
   *
   * **Displayed, never computed.** No view derives a permitted exposure, and showing a limit
   * is not granting it.
   */
  permitted: z.array(
    z.object({ scope: permittedScope, value: recordValue(permittedRisk) }),
  ),
  concentration: metricOf("risk.concentration"),
  correlation_ref: ref.optional(),
});
export type ExposureAggregate = z.infer<typeof exposureAggregate>;

export const exposureAggregatePayload = collectionPayload(exposureAggregate, {
  as_of: instant,
  /** The portfolio totals every axis must reconcile to, stated once. */
  totals: z.object({
    long: magnitude,
    short: magnitude,
    gross: magnitude,
    net: magnitude,
    position_count: metricOf("position.count"),
  }),
});
export type ExposureAggregatePayload = z.infer<typeof exposureAggregatePayload>;

export const EXPOSURE_AGGREGATE_SCHEMA = "cockpit.exposure_aggregate.v1";
export const exposureAggregateEnvelope = envelope(
  exposureAggregatePayload,
  EXPOSURE_AGGREGATE_SCHEMA,
);

/* ==================================================================== TradeSummary */

/**
 * §4.5 `TradeSummary`.
 *
 * **A fill is never counted as a separate trade**, and **a partial exit reduces a trade; it
 * does not close it and does not create a second one**. Six invariants are enforced here:
 *
 *   STATUS AND SHARES AGREE            OPEN holds everything it ever filled,
 *                                      PARTIALLY_EXITED holds part of it, CLOSED holds none
 *   AN ADD NEVER RESTATES THE ENTRY    `shares_at_entry` and `entry_price` are the ORIGINAL
 *                                      entry stage's filled quantity and price. A later add
 *                                      is carried by `shares_acquired` and its own retained
 *                                      risk record, and it changes neither of them (12.4)
 *   BUSINESS STATUS IS NOT COMPLETENESS  they are separate fields and neither is inferred
 *                                      from the other (§9.4)
 *   A CLOSED TRADE HAS AN EXIT         and an open one has no exit to report, so its exit
 *                                      fields are NOT_APPLICABLE rather than empty
 *   REALIZED NEEDS A CLOSED PORTION    an open trade reports NOT_YET_AVAILABLE, never zero
 *   UNREALIZED NEEDS AN OPEN PORTION   a closed trade has none, so the question does not
 *                                      apply to it
 *   R NEEDS ITS DENOMINATOR            with no initial planned risk record there is no R,
 *                                      and it is NEVER computed from a current stop
 */
export const tradeSummary = z
  .object({
    trade_id: safeId,
    security_ref: ref,
    security: securityIdentity,
    direction: z.enum(["LONG", "SHORT"]),
    /** BUSINESS status only, and never a data-completeness state. */
    trade_status: z.enum(TRADE_STATUSES),
    /** A SEPARATE field: a complete trade with a missing bar is not a partially exited one. */
    data_completeness: z.enum(DATA_COMPLETENESS),
    strategy_module: reasonCoded,
    alpha_family: reasonCoded,
    trade_template: reasonCoded,
    entry_time: instant,
    entry_price: metricOf("trade.entry_price"),
    exit_time: metricOf("trade.exit_time"),
    exit_price: metricOf("trade.exit_price"),
    /**
     * Filled AT ENTRY, not ordered — and **not** the trade's whole filled quantity.
     *
     * 4.5 names this "filled at entry" and names `PositionSnapshot.entry_price` a
     * "position-weighted basis" in the same document, so the two are different questions
     * and this one is answered about the original entry stage alone.
     */
    shares_at_entry: quantity,
    /**
     * ADDITIVE (5, additive within a version): the whole quantity ever filled — the entry
     * stage plus every add.
     *
     * Absent on a trade that never added, where it would equal `shares_at_entry`. It exists
     * because a pyramided trade holds more than it entered with, and the alternative was to
     * restate its entry quantity, which 12.4 forbids.
     */
    shares_acquired: quantity.optional(),
    shares_open: quantity,
    /**
     * ADDITIVE: the position-weighted basis of what is still held.
     *
     * Present only where it differs from `entry_price` — that is, where an add moved it.
     * The screen never derives it from the two prices it is shown beside.
     */
    current_basis: metricOf("position.entry_price").optional(),
    /**
     * The capital this trade put to work, summed over every stage that filled.
     *
     * 12.4 aggregates a stage-level fact to trade level by summing the retained stage
     * records — that is how the R denominator is defined — and this follows the same rule,
     * so `return_pct` divides the trade's whole outcome by the whole capital that produced
     * it rather than by the entry stage alone.
     */
    initial_position_value: money,
    /** CLOSED portion only. */
    realized_pnl: metricOf("pnl.realized"),
    /** OPEN portion only. */
    unrealized_pnl: metricOf("pnl.unrealized"),
    /** Denominator INITIAL_POSITION_VALUE. */
    return_pct: metricOf("trade.return_pct"),
    /**
     * The ORIGINAL entry-time record, **retained unchanged** (12.4).
     *
     * A later add carries its own record and never edits this one, so its `risk_money`,
     * `reference_price`, `invalidation_ref` and `risk_policy_ref` are the entry stage's and
     * are not a blend of the stages that followed.
     */
    initial_planned_risk: recordValue(initialPlannedRisk),
    /**
     * ADDITIVE: the retained record of each ADD, in stage order.
     *
     * 12.4 requires each add to carry "its own `risk.initial_planned` record, at its own
     * reference price and its own as-of". Without somewhere to put them, a pyramided trade
     * could only show one record, and the only way to make that one record cover the whole
     * trade is to blend it — which is what this field exists to avoid. Absent on a trade
     * with no adds.
     */
    add_planned_risk: z
      .array(z.object({ stage_ordinal: z.number().int().positive(), record: initialPlannedRisk }))
      .optional(),
    open_planned_risk: recordValue(currentOpenPlannedRisk),
    /**
     * ADDITIVE: the denominator `r_multiple` was actually divided by.
     *
     * 12.4 makes it "the sum of the retained per-stage initial planned risks", which for a
     * pyramided trade is NOT the `initial_planned_risk` record shown beside it. It is served
     * rather than derived because a screen that computed it would be a screen computing a
     * metric.
     */
    r_denominator: money.optional(),
    /** Denominator INITIAL_PLANNED_RISK, per §12.3. A moving stop never moves it. */
    r_multiple: metricOf("r_multiple"),
    holding_period: metricOf("holding_period"),
    mfe: metricOf("mfe"),
    mae: metricOf("mae"),
    capture_ratio: metricOf("capture_ratio"),
    entry_reason: reasonCoded,
    exit_reason: metricOf("trade.exit_reason"),
    stop_outcome: reasonCoded,
    environment: environmentEnum,
    pins: versionPins,
    detail_ref: ref,
  })
  .superRefine((candidate, ctx) => {
    const closed = candidate.trade_status === "CLOSED";
    const open = candidate.trade_status === "OPEN";
    /*
     * THE QUANTITY EVERY STATUS RULE IS ABOUT.
     *
     * It is what the trade ever FILLED, not what it filled at entry. An earlier revision
     * compared the open quantity against `shares_at_entry`, so a legitimate pyramid — an
     * entry of 60 followed by an add of 40, holding 100 — was refused at admission unless
     * its entry quantity was restated as 100. Restating it is what 12.4 forbids, so the
     * comparison moved instead of the fact.
     */
    const acquired = candidate.shares_acquired ?? candidate.shares_at_entry;
    if (candidate.shares_at_entry <= 0) {
      ctx.addIssue({ code: "custom", message: "a trade filled a positive entry quantity" });
    }
    if (candidate.shares_acquired !== undefined && candidate.shares_acquired <= candidate.shares_at_entry) {
      ctx.addIssue({
        code: "custom",
        message:
          "a stated acquired quantity exceeds the entry quantity; a trade that never added " +
          "states none",
      });
    }
    if (candidate.shares_open < 0 || candidate.shares_open > acquired) {
      ctx.addIssue({
        code: "custom",
        message: "open shares lie between none and the whole quantity the trade filled",
      });
    }
    if (closed !== (candidate.shares_open === 0)) {
      ctx.addIssue({
        code: "custom",
        message: "a CLOSED trade holds no open shares, and a trade holding none is CLOSED",
      });
    }
    if (open && candidate.shares_open !== acquired) {
      ctx.addIssue({
        code: "custom",
        message:
          "an OPEN trade still holds everything it filled; a reduced one is PARTIALLY_EXITED",
      });
    }
    if (candidate.trade_status === "PARTIALLY_EXITED" && candidate.shares_open >= acquired) {
      ctx.addIssue({
        code: "custom",
        message: "a PARTIALLY_EXITED trade holds fewer shares than it filled",
      });
    }
    /*
     * A TRADE THAT ADDED SAYS SO IN BOTH PLACES, OR IN NEITHER.
     *
     * `add_planned_risk` carries the retained record of each add, so its presence and the
     * presence of an acquired quantity larger than the entry quantity are the same fact, and
     * one of them appearing alone would mean a stage was recorded in one place and not the
     * other.
     */
    const adds = candidate.add_planned_risk ?? [];
    if (adds.length > 0 && candidate.shares_acquired === undefined) {
      ctx.addIssue({
        code: "custom",
        message: "a trade carrying an add record states the quantity that add brought it to",
      });
    }
    if (adds.length === 0 && candidate.shares_acquired !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "a trade that acquired more than it entered with retains that add's record",
      });
    }
    for (let index = 0; index < adds.length; index += 1) {
      if (adds[index].stage_ordinal !== index + 1) {
        ctx.addIssue({
          code: "custom",
          message: "add records are ordered by stage, and the entry stage is not one of them",
        });
        break;
      }
    }
    /*
     * R IS DIVIDED BY THE SUM, AND THE SUM IS STATED WHEREVER IT IS NOT THE ONE RECORD.
     *
     * 12.4 makes the trade-level denominator the sum of every retained stage record. On a
     * trade with adds that sum is not the record displayed beside it, so the denominator is
     * carried explicitly rather than left to a reader to assume.
     */
    if (adds.length > 0 && candidate.r_denominator === undefined && isValueBearing(candidate.r_multiple.availability)) {
      ctx.addIssue({
        code: "custom",
        message:
          "a pyramided trade reporting an R states the summed denominator it was divided by",
      });
    }
    for (const [name, metric] of [
      ["exit_time", candidate.exit_time],
      ["exit_price", candidate.exit_price],
      ["exit_reason", candidate.exit_reason],
    ] as const) {
      if (closed && !isValueBearing(metric.availability)) {
        ctx.addIssue({ code: "custom", message: `a CLOSED trade reports its ${name}` });
      }
      if (open && isValueBearing(metric.availability)) {
        ctx.addIssue({
          code: "custom",
          message: `an OPEN trade has no ${name}: the question does not apply to it yet`,
        });
      }
    }
    if (open && isValueBearing(candidate.realized_pnl.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "an OPEN trade has closed no portion, so it reports no realized result",
      });
    }
    if (closed && isValueBearing(candidate.unrealized_pnl.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "a CLOSED trade holds no open portion, so unrealized does not apply to it",
      });
    }
    if (closed && isValueBearing(candidate.open_planned_risk.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "a CLOSED trade carries no remaining exposure for an assessment to be about",
      });
    }
    if (
      !isValueBearing(candidate.initial_planned_risk.availability) &&
      isValueBearing(candidate.r_multiple.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "R divides by the INITIAL planned risk record; with none, R is unavailable and is " +
          "never computed from a current stop",
      });
    }
    if (candidate.data_completeness !== "COMPLETE") {
      for (const [name, metric] of [
        ["mfe", candidate.mfe],
        ["mae", candidate.mae],
      ] as const) {
        if (metric.availability === "AVAILABLE") {
          ctx.addIssue({
            code: "custom",
            message: `${name} is path-dependent: an incomplete price path is PARTIAL, never an optimistic value`,
          });
        }
      }
    }
  });
export type TradeSummary = z.infer<typeof tradeSummary>;

export const tradeSummaryPayload = collectionPayload(tradeSummary, {
  as_of: instant,
  /**
   * The window the ledger was drawn over, and the population it defines.
   *
   * A ledger with no stated window is a ledger a reader assumes is complete.
   */
  window: analysisWindow,
  trade_population: reasonCoded,
  open_count: metricOf("trade.open_count"),
  closed_count: metricOf("trade.closed_count"),
});
export type TradeSummaryPayload = z.infer<typeof tradeSummaryPayload>;

export const TRADE_SUMMARY_SCHEMA = "cockpit.trade_summary.v1";
export const tradeSummaryEnvelope = envelope(tradeSummaryPayload, TRADE_SUMMARY_SCHEMA);

/* ===================================================================== TradeDetail */

export const BENCHMARK_RETURN_BASES = ["PRICE_RETURN", "TOTAL_RETURN"] as const;

/**
 * §4.5 `TradeDetail` — one trade's story, joined **by reference**.
 *
 * "Every downstream fact arrives by reference and no sizing or execution field is added to
 * `CandidateIntent`." Most of those references resolve to an availability state today,
 * because the Brain, risk and execution runtimes do not exist — which is what
 * `UNRESOLVABLE_V1` MEANS (§4.3), and why the reference stays visible rather than omitted.
 *
 * `gaps` is the field that keeps this honest: **a missing event renders as a gap and never
 * as an inference**.
 */
export const tradeDetailPayload = z
  .object({
    trade_id: safeId,
    /** EMBEDDED, from the same `snapshot_version` as the ledger row it came from. */
    summary: tradeSummary,
    candidate_ref: ref,
    brain_decision_ref: ref,
    risk_decision_ref: ref,
    /**
     * The RESOLVED downstream risk decision, where one was recorded.
     *
     * ADDITIVE and documented (§12.6), for the reason `execution_quality` is already carried
     * beside its own reference: §4.3 resolves this reference under an `AUTHORIZED_READ` on
     * `risk:read`, and "the join is a read-model concern" is exactly what §4.5's TradeDetail
     * invariant says a whole-trade view does. **The record arrives here and NOWHERE ELSE**:
     * `CandidateIntent` acquires no field of it, and `CandidateDetail` carries the reference
     * alone.
     */
    risk_decision: riskDecision.optional(),
    order_refs: refList,
    fill_refs: refList,
    protection_refs: refList,
    add_refs: refList,
    /** Required when CLOSED. */
    exit_ref: ref.optional(),
    reconciliation_refs: refList,
    execution_quality_ref: ref,
    /**
     * The EMBEDDED resolution of that reference, at `AGGREGATE` scope, where one exists.
     *
     * ADDITIVE, and narrower than the reference it resolves: it is **this trade's** execution
     * quality, not the Area 9 aggregate over a window of fills. Present exactly when the
     * reference states it is embedded, so the two cannot disagree about whether it exists.
     */
    execution_quality: executionQuality.optional(),
    /**
     * One record per recorded fill, at `FILL` scope.
     *
     * A trade-level aggregate hides the case §12.3 cares about: a fill with no resolvable
     * reference is EXCLUDED and COUNTED, and an average over a silently reduced population is
     * a different metric. The per-fill records are what make that visible.
     */
    fill_quality: z.array(executionQuality),
    attribution: z.object({
      strategy: metricValue,
      factor: metricValue,
      regime: metricValue,
      execution: metricValue,
      cost: metricValue,
      /** A provisional attribution is labelled, and finalization is a recorded event. */
      state: z.enum(["PROVISIONAL", "FINAL"]),
    }),
    /** Aligned to the exact holding-period boundaries used. */
    benchmark_movement: metricOf("benchmark.movement"),
    /** A price-return benchmark is never compared against a total-return portfolio. */
    benchmark_basis: z.enum(BENCHMARK_RETURN_BASES),
    benchmark_series_ref: ref,
    /**
     * The EMBEDDED benchmark path, where one exists, and the window it was aligned to.
     *
     * §12.4: "the benchmark is aligned to the **exact** boundaries the subject used". The
     * window is carried so a reader can check that alignment rather than assume it, and the
     * basis travels on `benchmark_basis` so a price-return benchmark is never read against a
     * total-return portfolio.
     *
     * **It is a synthetic demonstration index, not a real one.** No provider is selected, G1
     * is OPEN, and no benchmark price history is requested from anywhere.
     */
    benchmark_series: series.optional(),
    benchmark_window: analysisWindow.optional(),
    benchmark_label: reasonCoded.optional(),
    lineage: versionPins,
    audit_refs: refList,
    /** OHLC with entry, add, protection and exit markers. */
    chart_series_ref: ref,
    /**
     * The EMBEDDED resolution of that reference, where one exists.
     *
     * ADDITIVE, and narrower than the reference it resolves: **it is a mark line, not OHLC**.
     * Open, high, low and close need a market-data provider, no provider is selected and G1
     * is OPEN, so a demonstration carries one mark per session and says so. Present exactly
     * when the reference states it is embedded, so the two cannot disagree about whether a
     * series exists.
     */
    chart_series: series.optional(),
    gaps: z.array(
      z.object({
        expected: reasonCoded,
        availability: availabilityState,
        reason: fieldReasonCode,
      }),
    ),
  })
  .superRefine((candidate, ctx) => {
    if (
      (candidate.chart_series_ref.resolution === "EMBEDDED") !==
      (candidate.chart_series !== undefined)
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "an EMBEDDED chart reference carries its series, and a reference that resolves " +
          "elsewhere carries none",
      });
    }
    if (
      (candidate.execution_quality_ref.resolution === "EMBEDDED") !==
      (candidate.execution_quality !== undefined)
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "an EMBEDDED execution-quality reference carries its record, and a reference that " +
          "resolves elsewhere carries none",
      });
    }
    if (
      (candidate.benchmark_series_ref.resolution === "EMBEDDED") !==
      (candidate.benchmark_series !== undefined)
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "an EMBEDDED benchmark reference carries its series, and a reference that resolves " +
          "elsewhere carries none",
      });
    }
    /*
     * A BENCHMARK MOVEMENT IS A STATEMENT ABOUT A SERIES OVER A WINDOW.
     *
     * A movement with no series is a number nobody can check, and a movement with no window is
     * a number aligned to boundaries nobody stated -- which is exactly what 12.4 forbids.
     */
    if (isValueBearing(candidate.benchmark_movement.availability)) {
      if (candidate.benchmark_series === undefined) {
        ctx.addIssue({
          code: "custom",
          message: "a benchmark movement is reported against a series that exists",
        });
      }
      if (candidate.benchmark_window === undefined || candidate.benchmark_label === undefined) {
        ctx.addIssue({
          code: "custom",
          message: "a benchmark movement names its window and the benchmark it moved",
        });
      }
    }
    /*
     * THE BENCHMARK IS ALIGNED TO THE EXACT BOUNDARIES THE SUBJECT USED (12.4).
     *
     * The trade's own entry instant is one of them, and a window that does not start there is
     * measuring a different holding period from the one it is being compared with.
     */
    if (
      candidate.benchmark_window !== undefined &&
      candidate.benchmark_window.from !== candidate.summary.entry_time
    ) {
      ctx.addIssue({
        code: "custom",
        message: "the benchmark window opens at the instant the trade's holding period did",
      });
    }
    for (const record of candidate.fill_quality) {
      if (record.scope !== "FILL") {
        ctx.addIssue({
          code: "custom",
          message: "a per-fill execution record is at FILL scope",
        });
      }
    }
    if (candidate.execution_quality !== undefined && candidate.execution_quality.scope !== "AGGREGATE") {
      ctx.addIssue({
        code: "custom",
        message: "the trade-level execution record is the AGGREGATE over its fills",
      });
    }
    if (candidate.summary.trade_id !== candidate.trade_id) {
      ctx.addIssue({
        code: "custom",
        message: "the embedded summary describes the trade this detail is about",
      });
    }
    if (candidate.summary.trade_status === "CLOSED" && candidate.exit_ref === undefined) {
      ctx.addIssue({ code: "custom", message: "a CLOSED trade carries its exit reference" });
    }
    for (const gap of candidate.gaps) {
      if (isValueBearing(gap.availability)) {
        ctx.addIssue({
          code: "custom",
          message: "a gap is an absence; a value-bearing state is not a gap",
        });
      }
    }
  });
export type TradeDetailPayload = z.infer<typeof tradeDetailPayload>;

export const TRADE_DETAIL_SCHEMA = "cockpit.trade_detail.v1";
export const tradeDetailEnvelope = envelope(tradeDetailPayload, TRADE_DETAIL_SCHEMA);

/* ================================================================== TradeLifecycle */

/**
 * §4.5 `TradeLifecycle`, in the **basic** form C5 owns.
 *
 * **No broker-native order id is rendered anywhere**, ordering is by `event_time` with
 * `observed_time` retained, and **a correction appends a new event referencing the corrected
 * one and never overwrites it**.
 *
 * The events carried here are the trade-level stages a recorded trade actually has — entry,
 * add, partial exit and exit. **Order and fill mechanics, protective-order events and
 * reconciliation are not carried**: they belong to Execution History and to C6's complete
 * lifecycle, and their absence is stated as a gap on the detail rather than filled in.
 */
export const tradeLifecycleEvent = z.object({
  event_id: safeId,
  event_kind: reasonCoded,
  event_time: instant,
  /** Retained, because a late event advances no watermark it did not cover. */
  observed_time: instant,
  quantity,
  price: metricValue,
  downstream_stage: downstreamStage,
  /** A correction references the event it corrects. The corrected one is never mutated. */
  correction_of: ref.optional(),
  source_ref: ref,
});
export type TradeLifecycleEvent = z.infer<typeof tradeLifecycleEvent>;

export const tradeLifecyclePayload = z
  .object({
    trade_id: safeId,
    events: z.array(tradeLifecycleEvent),
    /** Intervals in which the trade was observed by nothing. Never interpolated. */
    gaps: z.array(
      z.object({
        between: z.tuple([instant, instant]),
        reason: fieldReasonCode,
      }),
    ),
    /**
     * ADDITIVE and load-bearing: the event kinds this basic lifecycle does **not** carry.
     *
     * Without it, a timeline showing four events reads as a complete one. Each entry is a
     * closed reason code and an availability state, so an absent stage is named as absent
     * rather than inferred.
     */
    absent_kinds: z.array(
      z.object({
        kind: reasonCoded,
        availability: availabilityState,
        reason: fieldReasonCode,
      }),
    ),
  })
  .superRefine((candidate, ctx) => {
    for (let index = 1; index < candidate.events.length; index += 1) {
      if (candidate.events[index].event_time < candidate.events[index - 1].event_time) {
        ctx.addIssue({ code: "custom", message: "lifecycle events are ordered by event_time" });
        return;
      }
    }
    for (const gap of candidate.gaps) {
      if (gap.between[0] >= gap.between[1]) {
        ctx.addIssue({ code: "custom", message: "a gap's first instant precedes its second" });
      }
    }
    /*
     * AN ABSENT KIND NEVER CLAIMS TO BE PRESENT.
     *
     * `EMPTY_VERIFIED` is admitted and the other three value-bearing states are not, because
     * they are different answers. "We looked for corrections and there are none" is a
     * COMPLETED QUERY OVER AN EMPTY POPULATION, and it belongs in a list of what this
     * lifecycle does not carry. `AVAILABLE`, `STALE` or `PARTIAL` would say the kind IS
     * carried -- while sitting in the list of kinds that are not.
     */
    for (const missing of candidate.absent_kinds) {
      if (missing.availability !== "EMPTY_VERIFIED" && isValueBearing(missing.availability)) {
        ctx.addIssue({
          code: "custom",
          message:
            "an absent event kind is unavailable, or verified empty -- never a kind the " +
            "lifecycle is carrying",
        });
      }
    }
  });
export type TradeLifecyclePayload = z.infer<typeof tradeLifecyclePayload>;

export const TRADE_LIFECYCLE_SCHEMA = "cockpit.trade_lifecycle.v1";
export const tradeLifecycleEnvelope = envelope(tradeLifecyclePayload, TRADE_LIFECYCLE_SCHEMA);
