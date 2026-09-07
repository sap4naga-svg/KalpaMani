/**
 * The §4.1.1 validity matrix, transcribed exhaustively.
 *
 * Availability and reason are two separate typed axes and neither is ever spelled in the
 * other's vocabulary. A combination absent from this matrix is INVALID and is refused at
 * the boundary rather than rendered.
 *
 * ADR-0029 §2.1 governs the value axis: a zero is a MEASUREMENT and never an availability
 * state. `AVAILABLE` with `NONE` may carry a numeric zero, and the number alone never
 * determines availability.
 */
import type { AvailabilityState, FieldReasonCode } from "./vocabularies";

/**
 * Value-bearing states carry their value; every other state carries none at all.
 * `STALE` and `PARTIAL` are answers WITH a qualification, not absences.
 */
export const VALUE_BEARING_STATES = [
  "AVAILABLE",
  "STALE",
  "PARTIAL",
  "EMPTY_VERIFIED",
] as const satisfies readonly AvailabilityState[];

export function isValueBearing(state: AvailabilityState): boolean {
  return (VALUE_BEARING_STATES as readonly AvailabilityState[]).includes(state);
}

/**
 * §4.1.1, exhaustive. Every state maps to the closed set of reasons it admits.
 *
 * `AVAILABLE` admits `NONE` and nothing else: `NONE` exists so a producer never has to
 * invent a failure to fill a required field, and a fabricated failure reason on a good
 * value is a false report.
 */
export const PERMITTED_REASONS: Readonly<
  Record<AvailabilityState, readonly FieldReasonCode[]>
> = {
  AVAILABLE: ["NONE"],
  STALE: ["UPSTREAM_INPUT_STALE"],
  PARTIAL: [
    "EXTENT_PARTIALLY_COVERED",
    "UPSTREAM_INPUT_MISSING",
    "UPSTREAM_INPUT_STALE",
    "PRICE_PATH_INCOMPLETE",
    "CORPORATE_ACTION_UNRESOLVED",
  ],
  EMPTY_VERIFIED: ["EMPTY_RESULT_VERIFIED"],
  NOT_YET_AVAILABLE: [
    "UPSTREAM_INPUT_MISSING",
    "SOURCE_TIMESTAMP_MISSING",
    "CLOCK_UNSYNCHRONIZED",
    "PRICE_PATH_INCOMPLETE",
    "CORPORATE_ACTION_UNRESOLVED",
    "EXTENT_NOT_DETERMINABLE",
    "POLICY_REFERENCE_MISSING",
    /*
     * ADR-0030 R9 — a reference is well formed and its identifier names nothing.
     *
     * It reaches this state and NO OTHER. It is an ABSENCE of a target, never an
     * INAPPLICABILITY, so `NOT_APPLICABLE` keeps its two ADR-0028 routes and this is not one
     * of them; and it is never `NOT_IMPLEMENTED`, which asserts that the PRODUCER does not
     * exist rather than that this record was not written.
     */
    "REFERENT_NOT_FOUND",
  ],
  NOT_IMPLEMENTED: ["PRODUCER_NOT_IMPLEMENTED"],
  NOT_AUTHORIZED: ["PRODUCER_NOT_AUTHORIZED", "CLASSIFICATION_WITHHELD"],
  UNEVALUATED: ["NOT_YET_ASSESSED"],
  INSUFFICIENT_OBSERVATIONS: ["BELOW_MINIMUM_OBSERVATIONS"],
  NOT_APPLICABLE: ["NOT_DEFINED_FOR_SUBJECT", "DENOMINATOR_ZERO"],
  ERROR: ["PROJECTION_ERROR"],
};

export function reasonIsPermitted(
  state: AvailabilityState,
  reason: FieldReasonCode,
): boolean {
  return PERMITTED_REASONS[state].includes(reason);
}

/**
 * The one place the matrix is enforced over a (state, reason, value-presence) triple.
 *
 * Returns `null` when the combination is valid, and the refusal reason otherwise. It is
 * deliberately not a boolean: a caller that refuses a payload should be able to say why.
 */
export function validityFailure(
  state: AvailabilityState,
  reason: FieldReasonCode,
  valuePresent: boolean,
): string | null {
  if (!reasonIsPermitted(state, reason)) {
    return `availability ${state} does not admit reason ${reason}`;
  }
  const bearing = isValueBearing(state);
  if (bearing && !valuePresent) {
    return `availability ${state} is value-bearing and requires a value`;
  }
  if (!bearing && valuePresent) {
    // Absence stays absent, and is never filled with a zero (ADR-0029 §2.1).
    return `availability ${state} carries no value, and one was supplied`;
  }
  return null;
}
