/**
 * Builders for contract-shaped values.
 *
 * These exist so a fixture cannot accidentally construct a combination the §4.1.1 matrix
 * forbids: an absence carries no value, and a value-bearing state carries one.
 */
import type { MetricValue, Ref, VersionPins } from "@/contracts/values";
import { METRIC_DEFINITION_VERSION } from "@/contracts/values";
import type { AvailabilityState, FieldReasonCode, Unit } from "@/contracts/vocabularies";
import type { CARDINALITIES } from "@/contracts/vocabularies";

type Cardinality = (typeof CARDINALITIES)[number];

/** The §4.2 `RefList` shape, as a plain type — the schema lives in `values.ts`. */
export interface RefList {
  readonly items: Ref[];
  readonly cardinality: Cardinality;
  readonly total: MetricValue;
  readonly truncated: boolean;
}

/**
 * Re-exported from the contracts, where the VALIDATOR that enforces it also lives. Two
 * spellings of one dictionary version is how a factory and its boundary come to disagree.
 */
export { METRIC_DEFINITION_VERSION };

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

/* ------------------------------------------------------------------ added by C4 */

/**
 * A `RefList` that counts itself.
 *
 * `total` is derived from the items ONLY because nothing here truncates. A real producer
 * states the population it drew from, and a truncated list whose total equals its length is
 * exactly what §4.2's `total` exists to prevent — so the builder refuses that combination
 * rather than quietly agreeing with itself.
 */
export function refListOf(
  items: readonly Ref[],
  cardinality: Cardinality,
  asOf: string,
  options: { readonly truncated?: boolean; readonly total?: number } = {},
): RefList {
  const truncated = options.truncated ?? false;
  const total = options.total ?? items.length;
  if (truncated && total <= items.length) {
    throw new RangeError("a truncated reference list states a total greater than its items");
  }
  return {
    items: [...items],
    cardinality,
    total: available({
      metricId: "reference.total",
      unit: "COUNT",
      value: total,
      asOf,
    }),
    truncated,
  };
}

/** The empty reference list an envelope carries when it references no source fact. */
export function emptyRefList(asOf: string): RefList {
  return refListOf([], "ZERO_OR_MORE", asOf);
}

/**
 * A `VersionPins` in which every pin is stated as NOT APPLYING.
 *
 * This is the honest pin set for the Cockpit today: no strategy version, factor definition,
 * risk policy, entry or exit policy, model or prompt exists to pin, because none of those
 * subsystems exists. §4.2 asks for exactly that statement rather than an omitted key, an
 * empty string or a `"none"` — each of which reads as a pin nobody recorded instead of one
 * that has no subject. Overrides name the pins that DO apply.
 */
export function pinsOf(overrides: Partial<VersionPins> = {}): VersionPins {
  const notApplicable = absent(
    "NOT_APPLICABLE",
    "NOT_DEFINED_FOR_SUBJECT",
    "governance.version_pin",
    "DIMENSIONLESS",
  );
  return {
    strategy_version: notApplicable,
    factor_definition_version: notApplicable,
    risk_policy_version: notApplicable,
    entry_policy_version: notApplicable,
    exit_policy_version: notApplicable,
    model_version: notApplicable,
    prompt_version: notApplicable,
    code_identity: notApplicable,
    config_identity: notApplicable,
    ...overrides,
  };
}
