/**
 * Builders for contract-shaped values.
 *
 * These exist so a fixture cannot accidentally construct a combination the §4.1.1 matrix
 * forbids: an absence carries no value, and a value-bearing state carries one.
 */
import type { MetricValue } from "@/contracts/values";
import type { AvailabilityState, FieldReasonCode, Unit } from "@/contracts/vocabularies";

export const METRIC_DEFINITION_VERSION = "metrics.v1";

interface AvailableArgs {
  readonly metricId: string;
  readonly unit: Unit;
  readonly value: unknown;
  readonly asOf: string;
}

/**
 * `AVAILABLE` with `NONE`. ADR-0029 §2.1: this MAY carry a numeric zero — a producer that
 * ran, measured the subject and got zero has answered the question.
 */
export function available({ metricId, unit, value, asOf }: AvailableArgs): MetricValue {
  return {
    value,
    unit,
    availability: "AVAILABLE",
    reason: "NONE",
    as_of: asOf,
    metric_id: metricId,
    metric_definition_version: METRIC_DEFINITION_VERSION,
  };
}

/** A value-bearing state that qualifies its value. A zero carried by STALE is still stale. */
export function qualified(
  state: Extract<AvailabilityState, "STALE" | "PARTIAL" | "EMPTY_VERIFIED">,
  reason: FieldReasonCode,
  args: AvailableArgs,
): MetricValue {
  return {
    value: args.value,
    unit: args.unit,
    availability: state,
    reason,
    as_of: args.asOf,
    metric_id: args.metricId,
    metric_definition_version: METRIC_DEFINITION_VERSION,
  };
}

/**
 * An absence. It carries NO value at all — a producer that cannot answer never substitutes
 * zero for the answer (ADR-0029 §2.1).
 */
export function absent(
  state: Exclude<
    AvailabilityState,
    "AVAILABLE" | "STALE" | "PARTIAL" | "EMPTY_VERIFIED"
  >,
  reason: FieldReasonCode,
  metricId: string,
  unit: Unit,
): MetricValue {
  return {
    unit,
    availability: state,
    reason,
    metric_id: metricId,
    metric_definition_version: METRIC_DEFINITION_VERSION,
  };
}

/** The producing subsystem does not exist. This is the honest state for most of C3. */
export function notImplemented(metricId: string, unit: Unit): MetricValue {
  return absent("NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED", metricId, unit);
}

export function reason(code: string, vocabulary: string): {
  code: string;
  vocabulary: string;
  vocabulary_version: string;
} {
  return { code, vocabulary, vocabulary_version: "v1" };
}

export function instantOf(ms: number): string {
  return new Date(ms).toISOString().replace(/\.(\d{3})\d*Z$/, ".$1Z");
}
