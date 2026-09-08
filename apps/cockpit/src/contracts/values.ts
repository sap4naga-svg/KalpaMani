/**
 * The reusable defined types of `read-model-contracts.md` §4.2, scoped to what C3 uses.
 *
 * Defined once, used everywhere. A view that redefines one of these is defining a second
 * type with the same name, so nothing below is re-spelled elsewhere in this application.
 *
 * SCOPE: this is the subset the C3 foundation actually consumes. The full §4.2 catalog is
 * larger, and no claim is made here that every catalogued type exists.
 */
import { z } from "zod";

import {
  availabilityState,
  cardinality,
  completeness,
  dataClassification,
  fieldReasonCode,
  owningArea,
  refKind,
  resolution,
  unit,
} from "./vocabularies";
import type { Unit } from "./vocabularies";
import { isValueBearing, validityFailure } from "./validity";

/** A safe internal identifier. NEVER a broker order id, account id, locator or vendor key. */
export const safeId = z
  .string()
  .min(1)
  .regex(/^[a-z0-9][a-z0-9._:-]*$/i, "SafeId must be a safe internal identifier");

/**
 * The metric dictionary version every number in this application obeys.
 *
 * Defined here rather than beside the factories, because the boundary that VALIDATES a
 * `MetricValue` needs it and a validator that imported the factory would be a cycle.
 */
export const METRIC_DEFINITION_VERSION = "metrics.v1";

/**
 * Parses an instant, or refuses it. Returns milliseconds, or `null`.
 *
 * A REGEX VALIDATES SPELLING, NOT A CALENDAR. `Date.parse` fails two different ways on a
 * well-spelled string and BOTH of them reach arithmetic:
 *
 *   "2026-13-01T00:00:00.000Z"   ->  NaN, and every later comparison is silently false
 *   "2026-02-30T00:00:00.000Z"   ->  SILENTLY ROLLED OVER to 2026-03-02
 *
 * A NaN deadline makes `serve_time >= fresh_until` false forever, so an entry that can
 * never expire reads as fresh. A rolled-over date is worse: it is a real number computed
 * from a day that does not exist. The round-trip below refuses both, because a real
 * instant is the only string `toISOString()` reproduces exactly.
 */
export function parseInstantMs(value: string): number | null {
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) {
    return null;
  }
  return new Date(ms).toISOString() === value ? ms : null;
}

/** Whether a `DateOnly` names a real calendar day, rather than merely being spelled like one. */
export function isRealCalendarDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && parseInstantMs(`${value}T00:00:00.000Z`) !== null;
}

/** RFC 3339 UTC instant, millisecond precision, and a REAL calendar instant. */
export const instant = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/, "Instant must be RFC 3339 UTC ms")
  .refine(
    (candidate) => parseInstantMs(candidate) !== null,
    "Instant must name a real UTC calendar instant, not merely be spelled like one",
  );

/** ISO 8601 calendar date, and a REAL one. NEVER widened into an instant. */
export const dateOnly = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, "DateOnly must be ISO 8601")
  .refine(isRealCalendarDate, "DateOnly must name a real calendar day");

/** Whole seconds. */
export const duration = z.number().int().nonnegative();

/** Decimal string, never binary floating point. */
export const decimalString = z
  .string()
  .regex(/^-?\d+(\.\d+)?$/, "decimal must be a decimal string, never a float");

export const money = z.object({ amount: decimalString, currency: z.literal("USD") });
export type Money = z.infer<typeof money>;

/** A ratio with no named denominator is refused at the boundary. */
export const ratio = z.object({ value: decimalString, denominator: z.string().min(1) });

export const magnitude = z.object({
  amount: decimalString,
  currency: z.literal("USD"),
  direction: z.enum(["LONG", "SHORT"]),
});
export type Magnitude = z.infer<typeof magnitude>;

/**
 * `Ref` — §4.2, with `ref_kind` CLOSED at the twenty-seven §4.3 rows (ADR-0030 R1).
 *
 * It was `z.string().min(1)` — an OPEN string where the contract says closed, which is what
 * admitted a trade reference labelled `source_fact` carrying a resolution `source_fact`'s
 * own row does not list. Closing it was blocked until ADR-0030 fixed WHICH members the set
 * has and WHICH resolutions each admits; both are now accepted, so it is closed here.
 *
 * **The kind is closed at this shape; the per-HOST-FIELD rules are not enforceable here.**
 * Which kinds a given field may carry, and which resolutions each kind admits, depend on the
 * field the reference sits in — so they are enforced by `refOf` and `refListFieldOf` in
 * `references.ts`, which know the host field. This shape is the floor, never the whole rule.
 *
 * **A `Ref` carries NO `availability` and NO `reason`** (ADR-0030 R9). An unresolvable
 * target is stated by the value-bearing field it would have filled, or by a §5 error, and
 * the reference itself stays VISIBLE.
 *
 * **`owning_area` is OPTIONAL DESCRIPTIVE metadata** — §4.3.2, under ADR-0031 A1. It names
 * the AREA responsible for the referenced record, and it is a SECOND axis from `ref_kind`
 * rather than a second spelling of it.
 *
 * **Association is by containment and by nothing else.** The reference it describes is the
 * object it is a field of, so it survives filtering, truncation and reordering — which a
 * positional pairing against a parallel array would not. It is at most ONE per reference,
 * and where accepted authority does not determine a single area the reference DECLARES NONE:
 * never a list, never a first-of, never a nearest match.
 *
 * **It is closed here, and the rest of the rule is not enforceable at this shape.** A value
 * outside `OwningArea` is refused by this enum. The contradiction rule — two references
 * sharing a `ref_id` AND a `ref_kind` while DECLARING DIFFERENT areas — spans the whole
 * ADMISSION UNIT, which a single reference cannot see, so it is enforced by
 * `owningAreaContradiction` in `references.ts` and applied by `admit`.
 *
 * **It is never an access grant** (§4.3.2, A5), it never changes what the reference means or
 * how it resolves, and it is not availability, freshness, completeness, materiality,
 * severity, ranking input or authorization. It is deliberately NOT a scope field: §4.3.4's
 * limitation stays open, and closing it is an ADR's act rather than an implementation's.
 */
export const ref = z.object({
  ref_id: safeId,
  ref_kind: refKind,
  resolution,
  classification: dataClassification,
  owning_area: owningArea.optional(),
});
export type Ref = z.infer<typeof ref>;

/**
 * `RefList` — §4.2, now including the `total` C3 omitted.
 *
 * "A list of references states how many there are, so a truncated list is never read as a
 * complete one." C3 carried `items`, `cardinality` and `truncated` and asserted that nothing
 * was truncated; C4 renders reference COUNTS, and a count taken from `items.length` is the
 * length of what survived truncation rather than how many exist.
 *
 * `total` is a `CountValue`, so a producer that cannot count them says so with a state
 * instead of reporting the page size as the population.
 */
export const refList = z
  .object({
    items: z.array(ref),
    cardinality,
    total: z.lazy(() => countValue),
    truncated: z.boolean(),
  })
  .superRefine((candidate, ctx) => {
    if (typeof candidate.total.value !== "number") {
      return;
    }
    if (candidate.total.value < candidate.items.length) {
      ctx.addIssue({
        code: "custom",
        message: "a reference list cannot hold more items than it states a total of",
      });
    }
    if (!candidate.truncated && candidate.total.value !== candidate.items.length) {
      ctx.addIssue({
        code: "custom",
        message: "an untruncated reference list states a total equal to the items it carries",
      });
    }
    if (candidate.truncated && candidate.total.value === candidate.items.length) {
      /*
       * "There are more than this" and "there are exactly this many" are two claims about
       * one population, and a list that makes both has told a reader nothing was left out
       * while flagging that something was.
       */
      ctx.addIssue({
        code: "custom",
        message: "a truncated reference list states a total greater than the items it carries",
      });
    }
  });
export type RefList = z.infer<typeof refList>;

export const reasonCoded = z.object({
  code: z.string().min(1),
  vocabulary: z.string().min(1),
  vocabulary_version: z.string().min(1),
});
export type ReasonCoded = z.infer<typeof reasonCoded>;

/**
 * `MetricValue` — the ONLY wrapper a nullable number arrives in.
 *
 * The §4.1.1 matrix is enforced here as a refinement rather than in each consumer, so an
 * invalid (state, reason, value) triple is refused at the boundary. `value` is `unknown`
 * at the schema level because a metric's typed value is per-metric; presence, not shape,
 * is what the matrix governs.
 */
const metricValueBase = z.object({
  value: z.unknown().optional(),
  unit,
  availability: availabilityState,
  reason: fieldReasonCode,
  as_of: instant.optional(),
  metric_id: z.string().min(1),
  metric_definition_version: z.string().min(1),
});

/**
 * The shape a metric's value is actually carried in.
 *
 * `unknown` is what the SCHEMA can say; it is not what a METRIC may be. A payload field
 * typed only by the 4.1.1 matrix admits `null`, an arbitrary object, a boolean and `NaN`
 * on an AVAILABLE reading, and every one of those reaches a formatter with no honest
 * answer for it.
 */
/**
 * `INSTANT` follows the precedent `DATE_ONLY` already set.
 *
 * §4.2's `Unit` vocabulary is closed and holds no unit for a POINT IN TIME — it has
 * `SECONDS`, `CALENDAR_DAYS` and `TRADING_DAYS`, which are all DURATIONS. C3 hit this with a
 * run's date gate: carrying `2026-09-12` under `CALENDAR_DAYS` stated a count of days nobody
 * measured. It is carried under `DIMENSIONLESS` with a `DATE_ONLY` shape instead, and
 * `last_decision.at` and `last_scout_run.at` are the same question at instant precision.
 */
export type MetricShape = "DECIMAL_STRING" | "INTEGER" | "TOKEN" | "DATE_ONLY" | "INSTANT";

export interface MetricSpec {
  readonly unit: Unit;
  readonly shape: MetricShape;
  /** Exact decimal places a DECIMAL_STRING carries, where the metric states a precision. */
  readonly fractionDigits?: number;
}

/**
 * The C3 metric dictionary -- CLOSED, and every metric this application renders is in it.
 *
 * `metric_id` is a DICTIONARY KEY (4.2), so an unregistered identifier is refused rather
 * than rendered. Where 12.3 names a metric, ITS key and ITS unit are used:
 * `drawdown.current` rather than an invented `risk.drawdown`, and `risk.open_planned` and
 * `risk.permitted` rather than longer restatements of them. Where 4.5 states a payload
 * field's unit, 4.5 governs that field -- `return_pct` and `drawdown` are carried as
 * PERCENT because the payload contract says so, and a Percent is a Ratio whose display
 * format is a presentation concern (4.2).
 *
 * SCOPE: the metrics the C3 foundation actually renders. The 12.3 dictionary is larger,
 * and no claim is made here that every catalogued metric exists.
 */
export const C3_METRIC_DICTIONARY: Readonly<Record<string, MetricSpec>> = {
  // Money -- decimal strings, never binary floating point (4.2).
  "portfolio.broker_reported_equity": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "portfolio.cash": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "pnl.realized": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "pnl.unrealized": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "risk.open_planned": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "risk.permitted": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  // Percent-carried ratios -- 4.5 states the unit for these two payload fields.
  "return.time_weighted": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "drawdown.current": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  // R-multiples.
  "strategy.health_impact": { unit: "R_MULTIPLE", shape: "DECIMAL_STRING", fractionDigits: 2 },
  // Whole-second ages (12.3). Integers, never decimal strings.
  "freshness.source_age": { unit: "SECONDS", shape: "INTEGER" },
  "freshness.projection_lag": { unit: "SECONDS", shape: "INTEGER" },
  "freshness.build_age": { unit: "SECONDS", shape: "INTEGER" },
  // Counts.
  "strategy.active_count": { unit: "COUNT", shape: "INTEGER" },
  "operations.open_incidents": { unit: "COUNT", shape: "INTEGER" },
  "attention.occurrence_count": { unit: "COUNT", shape: "INTEGER" },
  "trade.closed_count": { unit: "COUNT", shape: "INTEGER" },
  // Section 12.3 defines `win_rate` in RATIO against a named population.
  "win_rate": { unit: "RATIO", shape: "DECIMAL_STRING" },
  // Closed-vocabulary tokens carried as a metric's value.
  "attention.impact": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  "strategy.health_state": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  /**
   * A run's date gate is a DATE, and a date is not a duration. Carrying `2026-09-12`
   * under CALENDAR_DAYS states a count of days nobody measured, and renders a calendar
   * date with a "d" suffix.
   */
  "governance.run_date_gate": { unit: "DIMENSIONLESS", shape: "DATE_ONLY" },

  /* ---------------------------------------------------------------- added by C4 */

  /** The portfolio valuation a `PerformanceSeries` point carries (§4.5). */
  "portfolio.equity": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** A benchmark's own time-weighted return. NEVER drawn on one line with the portfolio's. */
  "benchmark.return": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** An attention item whose impact is a dollar figure rather than an R-multiple. */
  "attention.impact_usd": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Governance counts, so a summary tile never derives one from an array it rendered. */
  "governance.gates_open": { unit: "COUNT", shape: "INTEGER" },
  "governance.gates_total": { unit: "COUNT", shape: "INTEGER" },
  "governance.provider_tests_unevaluated": { unit: "COUNT", shape: "INTEGER" },
  /** The named regime state, as a closed-vocabulary token. */
  "market.regime_state": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  /** Points in time, under the `DATE_ONLY` precedent above. */
  "decision.last_at": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  "scout.last_run_at": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  /** A `VersionPins` entry that genuinely does not apply to the subject (§4.2). */
  "governance.version_pin": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  /** `RefList.total` — how many references EXIST, which a truncated page's length is not. */
  "reference.total": { unit: "COUNT", shape: "INTEGER" },
  /**
   * The separation a run must keep from the one before it. A genuine DURATION in calendar
   * days, unlike `governance.run_date_gate`, which is a date and is carried as one.
   */
  "governance.minimum_separation": { unit: "CALENDAR_DAYS", shape: "INTEGER" },

  /* ---------------------------------------------------------------- added by C5 */

  /*
   * TWO GROUPS, AND THE DIFFERENCE BETWEEN THEM IS STATED RATHER THAN BLURRED.
   *
   * The first group is transcribed from 12.3: the identifier, the unit and the rule are
   * the dictionary's, and nothing here restates them differently. The second group is a
   * PRESENTATION DEFINITION PROPOSED BY THIS CYCLE, for a 4.5 payload field 12.3 carries
   * no row for -- 12.6 asks for exactly that to be labelled, and each one below names the
   * payload field it serves. A presentation definition changes no strategy, risk or sizing
   * rule, and adopting one for a screen adopts it nowhere else.
   */

  /* ---- 12.3 rows, transcribed */

  /** Realized plus unrealized, LABELLED COMBINED and never presented as realized. */
  "pnl.combined": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /**
   * The time-weighted return of ONE period, rather than since the window opened.
   *
   * A SEPARATE IDENTIFIER, because it is a separate quantity. `return.time_weighted` on a
   * series point is the chain-linked return SINCE THE WINDOW OPENED; this is the return of
   * that period alone. 12.2 forbids two values sharing a `metric_id` and meaning different
   * things, so a monthly heat map reads this one and never derives it from the other.
   */
  "return.period": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Returned only when explicitly requested, and always labelled as such (12.4). */
  "return.money_weighted": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Deposits and withdrawals, dated and signed. NEVER profit. */
  "cashflow.external": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** The minimum of `drawdown.current` over the stated window. Never positive. */
  "drawdown.max": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /**
   * Exposure carries a MAGNITUDE and a DIRECTION and never a profit sign (12.1), so a
   * short exposure is a positive magnitude whose `direction` says `SHORT`.
   */
  "exposure.long": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "exposure.short": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "exposure.gross": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "exposure.net": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /**
   * The three risk quantities of 4.4, each in BOTH units 12.3 names for it.
   *
   * 12.3 gives one row per quantity, reading "USD and PERCENT". A dictionary entry maps
   * one identifier to ONE unit, so the percent limb carries its own identifier rather than
   * a second unit under the same name -- two values with one `metric_id` and different
   * units are two metrics wearing one name, which 12.2 exists to prevent.
   */
  "risk.initial_planned": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "risk.initial_planned_pct": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "risk.open_planned_pct": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "risk.permitted_pct": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Expectancy in both offered units. Never mixed in one value. */
  "expectancy.currency": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "expectancy.r": { unit: "R_MULTIPLE", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** `gross_profit / gross_loss`. NOT_APPLICABLE with DENOMINATOR_ZERO on a zero loss. */
  "profit_factor": { unit: "RATIO", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Sample convention, frequency, annualization and risk-free assumption all stated. */
  "sharpe": { unit: "DIMENSIONLESS", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Outcome over INITIAL planned risk. A moving stop never moves the denominator. */
  "r_multiple": { unit: "R_MULTIPLE", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Exit-or-as-of minus entry, on the stated calendar, in whole trading days. */
  "holding_period": { unit: "TRADING_DAYS", shape: "INTEGER" },
  /** Excursions in USD. `capture_ratio` divides an outcome by `mfe` IN THE SAME UNIT. */
  "mfe": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "mae": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "capture_ratio": { unit: "RATIO", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Quantity-weighted by default, with the aggregation method named. Signed. */
  "slippage.aggregate": { unit: "BPS", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Benchmark return over EXACTLY the subject's boundaries, stating its return basis. */
  "benchmark.movement": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },

  /* ---- presentation definitions proposed by this cycle (12.6) */

  /**
   * 4.5 `PositionSnapshot.entry_price` -- position-weighted basis, unit USD.
   *
   * It is ONE metric asked in two places: it is also `TradeSummary.current_basis`, the basis a
   * trade holds after an add. It is deliberately NOT `trade.entry_price`, which is the price
   * the ORIGINAL entry filled at and a different question (12.4).
   */
  "position.entry_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `PositionSnapshot.current_price` -- the mark, carrying its OWN as-of. */
  "position.current_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `PositionSnapshot.quantity` -- whole shares currently held. */
  "position.quantity": { unit: "SHARES", shape: "INTEGER" },
  /** How many positions an exposure bucket was aggregated over. */
  "position.count": { unit: "COUNT", shape: "INTEGER" },
  /** 4.5 `TradeSummary.entry_price` and `exit_price` -- filled-quantity weighted. */
  "trade.entry_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "trade.exit_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `TradeSummary.exit_time` -- a point in time, under the `DATE_ONLY` precedent. */
  "trade.exit_time": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  /**
   * The mark a trade's own price path carries for one session.
   *
   * Distinct from `position.current_price`, which is the CURRENT mark of an open position:
   * this is a point on a historical path, and a closed trade has one while it has no current
   * mark at all.
   */
  "trade.mark_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `TradeSummary.return_pct` -- denominator INITIAL_POSITION_VALUE. */
  "trade.return_pct": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `TradeSummary.exit_reason` -- a closed vocabulary member carried as a value. */
  "trade.exit_reason": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  /** Trade population sizes. A ratio's denominator is a count somebody can read. */
  "trade.count": { unit: "COUNT", shape: "INTEGER" },
  "trade.open_count": { unit: "COUNT", shape: "INTEGER" },
  /** 4.4 `GapEventRisk.modelled_loss` -- a SEPARATE model, never folded into planned risk. */
  "gap_event.modelled_loss": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `RiskSnapshot.concentration` and `portfolio_volatility`. */
  "risk.concentration": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "risk.portfolio_volatility": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `RiskSnapshot.loss_thresholds[].value` -- a governed policy value, displayed. */
  "risk.loss_threshold": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `ShortSideSnapshot.borrow[]` -- every figure from a RECORD, never from price. */
  "borrow.fee": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "borrow.quantity": { unit: "SHARES", shape: "INTEGER" },
  "borrow.deterioration": { unit: "BPS", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `ShortSideSnapshot.crowding` and `utilization`. */
  "short.crowding": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "short.utilization": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `MarketRegime.components[].value` and `stress`, both dimensionless scores. */
  "market.component_score": { unit: "DIMENSIONLESS", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "market.stress": { unit: "DIMENSIONLESS", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** Area 4 asks for opportunities, turnover and capacity, per strategy module. */
  "strategy.opportunity_count": { unit: "COUNT", shape: "INTEGER" },
  "strategy.turnover": { unit: "RATIO", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "strategy.capacity": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `PerformanceSummary.average_winner` and `average_loser`. */
  "pnl.average_winner": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "pnl.average_loser": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /**
   * The observation count a ratio was computed over, and the minimum its rule declares.
   * 12.1 requires a declared minimum and an `INSUFFICIENT_OBSERVATIONS` outcome below it;
   * a screen showing the ratio without either number has shown half the rule.
   */
  "performance.observation_count": { unit: "COUNT", shape: "INTEGER" },
  "performance.minimum_observations": { unit: "COUNT", shape: "INTEGER" },
  /**
   * The governed research values of `CLAUDE.md` 6, reproduced for display context.
   *
   * THREE IDENTIFIERS, BECAUSE THE VALUES ARE IN THREE UNITS. They are REAL tracked facts and
   * they are **research parameters, not permitted limits**: a permitted limit is a separately
   * governed policy value carried with its `PolicyRef`, and no such policy exists. Displaying
   * one of these grants nothing and changes nothing.
   */
  "governance.research_parameter_usd": {
    unit: "USD",
    shape: "DECIMAL_STRING",
    fractionDigits: 2,
  },
  "governance.research_parameter_pct": {
    unit: "PERCENT",
    shape: "DECIMAL_STRING",
    fractionDigits: 2,
  },
  "governance.research_parameter_state": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  /** 4.5 `PerformanceSummary.r_multiple_distribution[].count`. */
  "r_multiple.bucket_count": { unit: "COUNT", shape: "INTEGER" },

  /* ---------------------------------------------------------------- added by C6 */

  /*
   * THE SAME TWO GROUPS THE C5 BLOCK ABOVE ESTABLISHED, AND THE SAME LABELLING RULE.
   *
   * The first group is transcribed from 12.3 -- the identifier, the unit and the rule are the
   * dictionary's. The second is a PRESENTATION DEFINITION PROPOSED BY THIS CYCLE for a 4.5
   * payload field 12.3 carries no row for; 12.6 asks for exactly that to be labelled, and each
   * one names the payload field it serves. A presentation definition changes no strategy, risk
   * or sizing rule, and adopting one for a screen adopts it nowhere else.
   */

  /* ---- 12.3 rows, transcribed */

  /**
   * `side_sign x (fill_price - reference_price) / reference_price x 10,000`.
   *
   * SIGNED, AND THE SIGN IS THE POINT (12.3.1): positive is ADVERSE for a buy AND for a sell,
   * so an equally weighted book of adverse buys and adverse sells does not average to zero.
   * The declared minimum scale is two decimal places of a basis point, so 8.42 survives.
   */
  slippage: { unit: "BPS", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** `order_submitted_at - signal_at`. Whole seconds, with its clock source stated. */
  "latency.signal_to_order": { unit: "SECONDS", shape: "INTEGER" },
  /** `first_fill_at - order_submitted_at`. Whole seconds, with its clock source stated. */
  "latency.order_to_fill": { unit: "SECONDS", shape: "INTEGER" },

  /* ---- presentation definitions proposed by this cycle (12.6) */

  /**
   * 4.5 `CandidateFunnel` stage and axis counts.
   *
   * THREE IDENTIFIERS, BECAUSE THEY COUNT THREE DIFFERENT SUBJECTS. A funnel stage counts
   * securities or candidate decisions depending on the stage; a Brain-axis entry counts
   * CANDIDATES; a reason entry counts REASON OCCURRENCES, and one candidate may carry several.
   * 12.2 forbids two values sharing a `metric_id` and meaning different things, so a screen
   * that adds reason counts never reads them as a candidate population.
   */
  "funnel.stage_count": { unit: "COUNT", shape: "INTEGER" },
  "funnel.state_count": { unit: "COUNT", shape: "INTEGER" },
  "funnel.reason_count": { unit: "COUNT", shape: "INTEGER" },
  /** 4.5 `CandidateFunnel.conversion[].rate`, always carried with both of its counts. */
  "funnel.conversion_rate": { unit: "RATIO", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /*
   * 4.3 resolves a `risk_decision` reference to `RiskSnapshot.decisions[]`, and 4.4 already
   * defines every quantity such a decision assigns. These six are the DOWNSTREAM sizing
   * dictionary, kept under their own prefix so a risk decision's assigned risk can never be
   * read as `risk.initial_planned` -- 12.2 forbids two values sharing a `metric_id` and
   * meaning different things, and "the risk a decision assigned" and "the risk a stage
   * retained" are different facts even when their numbers agree.
   */
  "risk_decision.assigned_risk": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "risk_decision.assigned_risk_pct": {
    unit: "PERCENT",
    shape: "DECIMAL_STRING",
    fractionDigits: 2,
  },
  "risk_decision.shares": { unit: "SHARES", shape: "INTEGER" },
  "risk_decision.reference_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "risk_decision.invalidation_price": {
    unit: "USD",
    shape: "DECIMAL_STRING",
    fractionDigits: 2,
  },
  "risk_decision.notional": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** How many candidates a page or a slice was drawn over. */
  "candidate.count": { unit: "COUNT", shape: "INTEGER" },
  /**
   * 4.5 `CandidateDetail` ranking context -- an ORDINAL and the POPULATION it was taken over.
   *
   * A rank with no population is a position in a list nobody can size. The ordinal is
   * DIMENSIONLESS because it counts nothing; the population is a COUNT because it counts
   * securities.
   */
  "candidate.rank": { unit: "DIMENSIONLESS", shape: "INTEGER" },
  "candidate.rank_population": { unit: "COUNT", shape: "INTEGER" },
  /** Closed-vocabulary tokens a candidate carries. */
  "candidate.setup_quality": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  "candidate.conviction_band": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  "candidate.liquidity_state": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  /**
   * 4.5 `CandidateSummary.downstream_stage` -- "a DownstreamStage or its availability".
   *
   * A SEPARATE TYPED AXIS (2.7). It is carried as a token so a candidate with no downstream
   * record reports an availability state instead of a stage, and the two vocabularies never
   * merge into one.
   */
  "candidate.downstream_stage": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  /** Points in time, under the `DATE_ONLY` precedent 4.2's closed `Unit` list forces. */
  "candidate.decided_at": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  /** 4.5 `CandidateDetail` expected holding period, on the named calendar. */
  "candidate.expected_horizon": { unit: "TRADING_DAYS", shape: "INTEGER" },
  /**
   * The entry-to-invalidation distance a later risk decision would size AGAINST.
   *
   * CARRIED AS A PERCENTAGE OF THE ENTRY REFERENCE, DELIBERATELY. The Brain specification's
   * 6.2 forbids `CandidateIntent` from carrying a share count, a dollar amount or a position
   * size, and the exclusion is structural. A percentage distance is a property of the thesis;
   * a dollar figure beside it invites a reader to multiply.
   */
  "candidate.invalidation_distance": {
    unit: "PERCENT",
    shape: "DECIMAL_STRING",
    fractionDigits: 2,
  },
  /** 4.5 `CandidateDetail.deterministic_evidence[].value` -- a dimensionless factor score. */
  "candidate.factor_score": {
    unit: "DIMENSIONLESS",
    shape: "DECIMAL_STRING",
    fractionDigits: 2,
  },
  /** The Brain specification's 19 gap-risk estimate, as a dimensionless score. */
  "candidate.gap_risk": { unit: "DIMENSIONLESS", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /**
   * AI evidence provenance -- the Brain specification's 14.3 requires source publish time,
   * model and prompt versions, confidence and evidence quality on EVERY AI output.
   *
   * The publish time and the observation time are two identifiers because they are two facts:
   * when the source said it, and when this system saw it.
   */
  "evidence.published_at": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  "evidence.observed_at": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  "evidence.confidence": { unit: "DIMENSIONLESS", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "evidence.quality": { unit: "DIMENSIONLESS", shape: "TOKEN" },
  /** 4.5 `MissedOpportunity` populations and timing. */
  "miss.count": { unit: "COUNT", shape: "INTEGER" },
  "miss.detected_at": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  "miss.decided_at": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  "miss.expired_at": { unit: "DIMENSIONLESS", shape: "INSTANT" },
  /** `decided_at - detected_at`, in whole seconds. A delay, never a duration of exposure. */
  "miss.decision_delay": { unit: "SECONDS", shape: "INTEGER" },
  /**
   * OBSERVED PRICE MOVEMENT AFTER A DECISION. **NOT PROFIT THAT WAS AVAILABLE.**
   *
   * Two identifiers, because a favourable excursion and an adverse one are two measurements
   * and a single signed number hides one of them behind the other.
   */
  "miss.favourable_movement": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "miss.adverse_movement": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /**
   * 4.5 `MissedOpportunity.counterfactual` -- HYPOTHETICAL, and never placed in a series with
   * a realized result.
   *
   * TWO IDENTIFIERS AND ONE OF THEM IS NEVER SERVED. The percentage limb is a price movement
   * over the registered window under stated assumptions. The money limb needs a permitted
   * SIZING BASIS, which is a risk decision no producer here makes -- so it exists as a field
   * that reports `POLICY_REFERENCE_MISSING` rather than as a number nobody approved.
   */
  "miss.counterfactual": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "miss.counterfactual_money": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** A rate over a DEFINED evaluable population. Refused where no population is defined. */
  "miss.rate": { unit: "RATIO", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** The follow-up mark path a missed candidate was observed over. */
  "miss.follow_up_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `ExecutionQuality.reference_price` and the fill measured against it. */
  "execution.reference_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  "execution.fill_price": { unit: "USD", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `ExecutionQuality.fill_rate` -- filled quantity over ordered quantity. */
  "execution.fill_rate": { unit: "PERCENT", shape: "DECIMAL_STRING", fractionDigits: 2 },
  /** 4.5 `ExecutionQuality.clock_accuracy`. A latency without one is not a latency. */
  "clock.accuracy": { unit: "SECONDS", shape: "INTEGER" },
  /** Quantities carried by an order or a fill event, in whole shares. */
  "execution.quantity": { unit: "SHARES", shape: "INTEGER" },
  /**
   * Fills an aggregate could not measure and therefore excluded.
   *
   * 12.3 requires them to be "excluded and counted", because "an average over a silently
   * reduced population is a different metric". A measured zero here is a RESULT (ADR-0029 2.1).
   */
  "execution.excluded_fills": { unit: "COUNT", shape: "INTEGER" },
} as const;

const DECIMAL = /^-?\d+(\.\d+)?$/;
const TOKEN = /^[A-Z][A-Z0-9_]*$/;

/** Returns `null` when the value fits its metric's shape, and the refusal reason otherwise. */
export function metricShapeFailure(value: unknown, spec: MetricSpec): string | null {
  switch (spec.shape) {
    case "INTEGER":
      // Number.isInteger already refuses NaN, Infinity, null and every non-number.
      return Number.isInteger(value) ? null : "requires an integer value";
    case "DECIMAL_STRING": {
      if (typeof value !== "string" || !DECIMAL.test(value)) {
        return "requires a decimal string, never a binary float";
      }
      if (spec.fractionDigits !== undefined) {
        const decimals = value.includes(".") ? (value.split(".")[1] ?? "").length : 0;
        if (decimals !== spec.fractionDigits) {
          return `states ${spec.fractionDigits} decimal places`;
        }
      }
      return null;
    }
    case "TOKEN":
      return typeof value === "string" && TOKEN.test(value)
        ? null
        : "requires a closed-vocabulary token";
    case "DATE_ONLY":
      return typeof value === "string" && isRealCalendarDate(value)
        ? null
        : "requires a real ISO 8601 calendar date";
    case "INSTANT":
      // The same round-trip a timestamp field gets: a spelled instant is not a real one.
      return typeof value === "string" && parseInstantMs(value) !== null
        ? null
        : "requires a real RFC 3339 UTC instant";
  }
}

/**
 * `MetricValue`, validated to the metric it claims to be.
 *
 * The 4.1.1 matrix governs PRESENCE; the dictionary governs IDENTITY, UNIT and SHAPE. Both
 * are enforced here, at the one boundary every read model passes through, so no consumer
 * has to defend itself against a payload the admission step already saw.
 */
export const metricValue = metricValueBase.superRefine((candidate, ctx) => {
  const failure = validityFailure(
    candidate.availability,
    candidate.reason,
    candidate.value !== undefined,
  );
  if (failure !== null) {
    ctx.addIssue({ code: "custom", message: failure });
  }
  // A value-bearing state states the instant its value was true at.
  if (isValueBearing(candidate.availability) && candidate.as_of === undefined) {
    ctx.addIssue({ code: "custom", message: "a value-bearing MetricValue requires an as_of" });
  }
  if (candidate.metric_definition_version !== METRIC_DEFINITION_VERSION) {
    ctx.addIssue({
      code: "custom",
      message: `unknown metric_definition_version ${candidate.metric_definition_version}`,
    });
    return;
  }
  const spec = C3_METRIC_DICTIONARY[candidate.metric_id];
  if (spec === undefined) {
    // A number whose metric_id is not a dictionary key is not a metric (4.2, 12.2).
    ctx.addIssue({ code: "custom", message: `unknown metric_id ${candidate.metric_id}` });
    return;
  }
  if (candidate.unit !== spec.unit) {
    ctx.addIssue({
      code: "custom",
      message: `${candidate.metric_id} is defined in ${spec.unit}, not ${candidate.unit}`,
    });
  }
  // An absence carries no value to shape-check; the matrix above already refused a stray one.
  if (candidate.value === undefined) {
    return;
  }
  const shapeFailure = metricShapeFailure(candidate.value, spec);
  if (shapeFailure !== null) {
    ctx.addIssue({ code: "custom", message: `${candidate.metric_id} ${shapeFailure}` });
  }
});
export type MetricValue = z.infer<typeof metricValue>;

/** A `MetricValue` whose unit is COUNT and whose value is an integer. */
export const countValue = metricValue.superRefine((candidate, ctx) => {
  if (candidate.unit !== "COUNT") {
    ctx.addIssue({ code: "custom", message: "CountValue requires unit COUNT" });
  }
  if (candidate.value !== undefined && !Number.isInteger(candidate.value)) {
    ctx.addIssue({ code: "custom", message: "CountValue requires an integer value" });
  }
});

/**
 * `RecordValue` — the ONLY wrapper a nested record arrives in (ADR-0028 §2.5.2).
 *
 * The record is present exactly when the availability state is value-bearing, and is
 * ABSENT otherwise — never a skeleton, never a placeholder, never a zeroed record.
 */
export function recordValue<T extends z.ZodTypeAny>(record: T) {
  return z
    .object({
      record: record.optional(),
      availability: availabilityState,
      reason: fieldReasonCode,
      as_of: instant.optional(),
    })
    .superRefine((candidate, ctx) => {
      const failure = validityFailure(
        candidate.availability,
        candidate.reason,
        candidate.record !== undefined,
      );
      if (failure !== null) {
        ctx.addIssue({ code: "custom", message: failure });
      }
    });
}

/** A separately governed policy value is ALWAYS carried with its versioned reference. */
export const policyRef = z.object({
  policy_id: safeId,
  policy_version: z.string().min(1),
  as_of: instant,
});

/* ------------------------------------------------------------------ added by C4 */

/** §4.2 `SeriesPoint` — `{ t: Instant or DateOnly, v: MetricValue }`, and never a bare number. */
export const seriesPoint = z.object({
  t: z.union([instant, dateOnly]),
  v: metricValue,
});
export type SeriesPoint = z.infer<typeof seriesPoint>;

export const SERIES_GRANULARITIES = ["DAILY", "WEEKLY", "MONTHLY"] as const;
export const seriesGranularity = z.enum(SERIES_GRANULARITIES);
export type SeriesGranularity = z.infer<typeof seriesGranularity>;

/**
 * §4.2 `Series`.
 *
 * A chart is a read model like any other, and this is the shape it arrives in. Three
 * properties are enforced here rather than trusted to whichever component draws it:
 *
 *   MIXED PROVENANCE IS NOT ONE LINE   a point's provenance rides on the envelope carrying
 *                                      the series, so a series is single-provenance by
 *                                      construction. `series_id` separates them (4.5).
 *   MISSING POINTS ARE PARTIAL         `coverage` and `completeness` say how much of the
 *                                      requested extent is present. A gap is never a zero.
 *   TIME IS ORDERED AND UNIQUE         two points at one instant are two answers to one
 *                                      question, and an unordered series draws as a scribble.
 */
export const series = z
  .object({
    points: z.array(seriesPoint),
    granularity: seriesGranularity,
    /** The named market calendar. A date range without one is not a date range. */
    calendar: z.lazy(() => reasonCoded),
    timezone: z.literal("UTC"),
    coverage: z.object({
      present: z.number().int().nonnegative(),
      requested: z.number().int().nonnegative(),
    }),
    completeness,
  })
  .superRefine((candidate, ctx) => {
    const keys = candidate.points.map((point) => point.t);
    for (let index = 1; index < keys.length; index += 1) {
      if (keys[index] <= keys[index - 1]) {
        ctx.addIssue({
          code: "custom",
          message: "series points are strictly ordered in time, with no duplicate instant",
        });
        return;
      }
    }
    if (candidate.coverage.present !== candidate.points.length) {
      ctx.addIssue({
        code: "custom",
        message: "series coverage.present states the number of points actually carried",
      });
    }
    if (candidate.coverage.present > candidate.coverage.requested) {
      ctx.addIssue({ code: "custom", message: "series coverage exceeds the requested extent" });
    }
    const complete = candidate.coverage.present === candidate.coverage.requested;
    if (candidate.completeness === "COMPLETE" && !complete) {
      ctx.addIssue({
        code: "custom",
        message: "a COMPLETE series covers its whole requested extent -- a gap is PARTIAL",
      });
    }
  });
export type Series = z.infer<typeof series>;

/**
 * §4.2 `VersionPins`.
 *
 * "Each a `SafeId` or a `MetricValue` carrying `NOT_APPLICABLE` with `NOT_DEFINED_FOR_SUBJECT`
 * where a pin genuinely does not apply." A pin that does not apply is stated as not applying;
 * it is never an empty string, a `"none"` or an omitted key, because each of those reads as a
 * pin nobody recorded rather than as one that has no subject.
 */
export const versionPin = z.union([
  safeId,
  metricValue.superRefine((candidate, ctx) => {
    if (
      candidate.availability !== "NOT_APPLICABLE" ||
      candidate.reason !== "NOT_DEFINED_FOR_SUBJECT"
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "a VersionPins entry is a SafeId, or NOT_APPLICABLE with NOT_DEFINED_FOR_SUBJECT",
      });
    }
  }),
]);

export const versionPins = z.object({
  strategy_version: versionPin,
  factor_definition_version: versionPin,
  risk_policy_version: versionPin,
  entry_policy_version: versionPin,
  exit_policy_version: versionPin,
  model_version: versionPin,
  prompt_version: versionPin,
  code_identity: versionPin,
  config_identity: versionPin,
});
export type VersionPins = z.infer<typeof versionPins>;

/* ------------------------------------------------------------------ added by C5 */

/**
 * 4.2 `Quantity` -- whole shares. Signed only where the field says so.
 *
 * A share count is a COUNT OF INDIVISIBLE THINGS. Carrying it as a decimal string would
 * admit a fractional share this system does not trade, and carrying it as a float would
 * admit 99.99999999 shares.
 */
export const quantity = z.number().int();

/**
 * 4.2 `Bps` -- SIGNED basis points, as a decimal string with a stated scale.
 *
 * "A decimal string with a stated scale, NEVER a bare integer: truncating 8.4 bps to 8
 * discards four tenths of a basis point on every fill." The declared minimum scale is two
 * (12.3.1), so a scale below it is refused rather than rounded to.
 */
export const bps = z.object({
  value: decimalString,
  scale: z.number().int().min(2),
});
export type Bps = z.infer<typeof bps>;

/**
 * The exact integer number of hundredths a decimal string carries, or `null`.
 *
 * INVARIANTS OVER MONEY ARE CHECKED IN INTEGERS. `Number("31200.00") + Number("8400.00")`
 * is exact at these magnitudes, and `0.1 + 0.2` is not -- the difference is not visible
 * until a refinement that should have failed passes, or one that should have passed fails.
 * Every cross-field money check below goes through this, so the comparison happens between
 * two integers and never between two doubles.
 *
 * It refuses anything carrying more than two decimal places rather than rounding it: a
 * value this cannot represent exactly is a value this must not compare.
 */
export function hundredths(value: string): number | null {
  const parts = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value);
  if (parts === null) {
    return null;
  }
  const [, sign, whole, fraction = ""] = parts;
  const magnitude = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(magnitude)) {
    return null;
  }
  return sign === "-" ? -magnitude : magnitude;
}

/**
 * A `MetricValue` that must be the named metric, in its dictionary unit.
 *
 * A payload field declared "unit USD, `risk.open_planned`" is not satisfied by a correctly
 * shaped `MetricValue` carrying some other metric. The dictionary already checks that the
 * unit matches the identifier; this checks that the IDENTIFIER matches the FIELD, which is
 * the half a per-field contract owns.
 */
export function metricOf(metricId: string) {
  return metricValue.superRefine((candidate, ctx) => {
    if (candidate.metric_id !== metricId) {
      ctx.addIssue({
        code: "custom",
        message: `this field carries ${metricId}, not ${candidate.metric_id}`,
      });
    }
  });
}

/** A `Ratio` whose denominator is one exact named population. */
export function ratioOf(denominator: string) {
  return z.object({ value: decimalString, denominator: z.literal(denominator) });
}
