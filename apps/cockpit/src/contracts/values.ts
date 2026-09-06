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
  dataClassification,
  fieldReasonCode,
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

export const ref = z.object({
  ref_id: safeId,
  ref_kind: z.string().min(1),
  resolution,
  classification: dataClassification,
});
export type Ref = z.infer<typeof ref>;

export const refList = z.object({
  items: z.array(ref),
  cardinality,
  truncated: z.boolean(),
});

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
export type MetricShape = "DECIMAL_STRING" | "INTEGER" | "TOKEN" | "DATE_ONLY";

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
