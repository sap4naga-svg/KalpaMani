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
import { isValueBearing, validityFailure } from "./validity";

/** A safe internal identifier. NEVER a broker order id, account id, locator or vendor key. */
export const safeId = z
  .string()
  .min(1)
  .regex(/^[a-z0-9][a-z0-9._:-]*$/i, "SafeId must be a safe internal identifier");

/** RFC 3339 UTC instant, millisecond precision. */
export const instant = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/, "Instant must be RFC 3339 UTC ms");

/** ISO 8601 calendar date. NEVER widened into an instant. */
export const dateOnly = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "DateOnly must be ISO 8601");

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
