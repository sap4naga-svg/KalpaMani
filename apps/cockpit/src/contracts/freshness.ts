/**
 * Freshness — `read-model-contracts.md` §3.1 and §3.1.1, as corrected by ADR-0029 §2.2.
 *
 * Two rules that answer DIFFERENT questions and never replace one another:
 *
 *   the OLDEST required input is REPORTED    -- "how old are the facts?"   (§3.1)
 *   the EARLIEST deadline BINDS              -- "how long stays fresh?"    (§3.1.1)
 *
 * A cache spends a budget it never refills: freshness eligibility belongs to the SOURCE
 * FACT, not to the entry holding it, so storing, building, serving, revalidating or
 * rebuilding never resets it.
 *
 * ONE CLAMP EXISTS IN THIS MODULE, and it is the one §3.1.1 puts there: `remaining_freshness`
 * is `max(0, ...)` because a spent budget is zero. AN AGE IS NEVER CLAMPED. A negative age is
 * a statement about two clocks, and §3.1 answers it with a flag or a refusal — never with a
 * zero that renders as "just now".
 */
import { z } from "zod";

import { availabilityState, fieldReasonCode } from "./vocabularies";
import type { AvailabilityState, FieldReasonCode } from "./vocabularies";
import { isValueBearing } from "./validity";
import { duration, instant, metricValue, parseInstantMs, safeId } from "./values";

export const freshnessInput = z.object({
  input_id: safeId,
  required: z.boolean(),
  /** ABSENT means no usable source time: the age is UNKNOWN, not zero. */
  source_effective_time: instant.optional(),
  source_age: metricValue,
  /** THIS input's own contract, never a shared one. */
  contract_max_age: duration,
  state: availabilityState,
  reason: fieldReasonCode,
  /**
   * §3.1: a source time later than `evaluation_time` by LESS than the declared tolerance is
   * "reported as an age of zero AND FLAGGED, because a small skew is ordinary and a silent
   * one is not". This carries that flag.
   *
   * It is a SEPARATE AXIS from `(state, reason)` on purpose. The §4.1.1 matrix admits only
   * `NONE` beside `AVAILABLE`, so a skew spelled as a reason code would have to either
   * fabricate a failure state or stay silent — and silence is the defect. Absent means NOT
   * flagged, and it is never inferred from the age.
   */
  clock_skew_flagged: z.boolean().optional(),
});
export type FreshnessInput = z.infer<typeof freshnessInput>;

/**
 * The declared clock-skew tolerance §3.1 refers to.
 *
 * A source time later than `evaluation_time` by more than this is `NOT_YET_AVAILABLE` with
 * `CLOCK_UNSYNCHRONIZED`, and its age is UNKNOWN rather than zero. Within it, the age is
 * zero AND FLAGGED. Declared here because "the declared tolerance" has to be declared
 * somewhere to be checkable.
 */
export const CLOCK_SKEW_TOLERANCE_SECONDS = 2;

const reportShape = z.object({
  inputs: z.array(freshnessInput),
  oldest_required: safeId.optional(),
  source_age: metricValue,
  projection_lag: metricValue,
  build_age: metricValue,
  composite_state: availabilityState,
  /** The origin's own compute instant. A cache reads `source_age` as of THIS, not as of now. */
  evaluation_time: instant,
});

/**
 * The whole-second age §3.1 reports for one exact, unrounded age in seconds.
 *
 * `null` means the age is UNKNOWN, and unknown is never zero. Three bands, and the middle one
 * is what was being silently collapsed into the third:
 *
 *   exact  <  -tolerance   UNKNOWN -- refused under §3.1, never clamped and never rendered
 *   -tol  <=  exact <  0   ZERO, and the caller must FLAG it: an ordinary, stated skew
 *   exact  >=  0           floor(exact) -- whole seconds, on a non-negative quantity
 *
 * `Math.floor` is applied ONLY to a non-negative quantity, so it can never deepen a negative
 * duration, and no `Math.max(0, ...)` appears here at all: the clamp that belongs to
 * `remaining_freshness` (§3.1.1) does not belong to an age.
 */
export function reportableAgeSeconds(exactSeconds: number): number | null {
  if (!Number.isFinite(exactSeconds)) {
    return null;
  }
  if (exactSeconds < -CLOCK_SKEW_TOLERANCE_SECONDS) {
    return null;
  }
  return exactSeconds < 0 ? 0 : Math.floor(exactSeconds);
}

/** Whether an exact age falls in the flagged-zero band: after `evaluation_time`, within tolerance. */
export function isFlaggedClockSkew(exactSeconds: number): boolean {
  return (
    Number.isFinite(exactSeconds) &&
    exactSeconds < 0 &&
    exactSeconds >= -CLOCK_SKEW_TOLERANCE_SECONDS
  );
}

export interface RequiredFailure {
  readonly state: AvailabilityState;
  readonly reason: FieldReasonCode;
}

/**
 * The DISTINCT ways this report's REQUIRED inputs failed, as `(state, reason)` pairs.
 *
 * Sorted by VALUE rather than by position, so the result is identical under every permutation
 * of `inputs`. That is the whole point. §3.1 says the composite "takes the WORST state any
 * required input reached", and accepted authority fixes `AVAILABLE` and `STALE` without
 * defining an ordering across the other nine states. Reading the FIRST failing entry made the
 * displayed diagnosis depend on array order; counting the DISTINCT ones makes the ambiguity
 * visible, so it can be refused rather than silently resolved.
 *
 * The pair — not the state alone — is the signature: `PARTIAL` admits five reasons, so two
 * required inputs that are both `PARTIAL` for different reasons still leave the composite
 * reason undetermined.
 */
export function requiredFailureSignatures(
  report: Pick<z.infer<typeof reportShape>, "inputs">,
): readonly RequiredFailure[] {
  const distinct = new Map<string, RequiredFailure>();
  for (const input of report.inputs) {
    if (!input.required || input.state === "AVAILABLE") {
      continue;
    }
    distinct.set(`${input.state}|${input.reason}`, { state: input.state, reason: input.reason });
  }
  return [...distinct.entries()]
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([, failure]) => failure);
}

/** One required input, checked against its OWN instants. `null` when it is consistent. */
function requiredInputFailure(input: FreshnessInput, evaluationMs: number): string | null {
  const flagged = input.clock_skew_flagged === true;
  const ageIsMeasured = isValueBearing(input.source_age.availability);
  const reportedAge = input.source_age.value;

  if (input.source_effective_time === undefined) {
    // §3.1: unknown timing has ONE state and ONE reason, and neither is invented.
    if (input.state !== "NOT_YET_AVAILABLE" || input.reason !== "SOURCE_TIMESTAMP_MISSING") {
      return (
        `required input ${input.input_id} has no source time and must be ` +
        "NOT_YET_AVAILABLE with SOURCE_TIMESTAMP_MISSING"
      );
    }
    // "Its age is UNKNOWN, not zero", and it is never treated as fresh.
    if (ageIsMeasured) {
      return (
        `required input ${input.input_id} has no source time, so its age is unknown and ` +
        `must not be reported as ${String(reportedAge)}`
      );
    }
    if (flagged) {
      return (
        `required input ${input.input_id} has no source time, so no clock skew was measured ` +
        "that could be flagged"
      );
    }
    return null;
  }

  const effectiveMs = parseInstantMs(input.source_effective_time);
  if (effectiveMs === null) {
    return `required input ${input.input_id} carries a source time that is not a real instant`;
  }
  if (!Number.isFinite(effectiveMs + input.contract_max_age * 1000)) {
    return `required input ${input.input_id} yields a deadline that is not finite`;
  }

  const exact = (evaluationMs - effectiveMs) / 1000;

  if (exact < -CLOCK_SKEW_TOLERANCE_SECONDS) {
    if (input.state !== "NOT_YET_AVAILABLE" || input.reason !== "CLOCK_UNSYNCHRONIZED") {
      return (
        `required input ${input.input_id} is dated after the evaluation time beyond ` +
        "tolerance and must be NOT_YET_AVAILABLE with CLOCK_UNSYNCHRONIZED"
      );
    }
    /*
     * A NEGATIVE AGE IS NEVER CLAMPED TO ZERO AND NEVER RENDERED (§3.1). The state alone was
     * not enough: a producer could declare CLOCK_UNSYNCHRONIZED and still hand a screen a
     * measured `0`, which reads as "just now" beside the very badge saying the clocks
     * disagree.
     */
    if (ageIsMeasured) {
      return (
        `required input ${input.input_id} is dated after the evaluation time beyond ` +
        `tolerance, so its age is unknown and must not be reported as ${String(reportedAge)}`
      );
    }
    return null;
  }

  if (isFlaggedClockSkew(exact)) {
    // Inside the tolerance: "an age of zero AND FLAGGED". A SILENT zero is the defect.
    if (!flagged) {
      return (
        `required input ${input.input_id} is dated after the evaluation time within ` +
        "tolerance, so its zero age is flagged rather than reported silently"
      );
    }
  } else if (flagged) {
    return (
      `required input ${input.input_id} is flagged for clock skew while its source time ` +
      "does not follow the evaluation time"
    );
  }

  const measured = reportableAgeSeconds(exact);
  if (ageIsMeasured && reportedAge !== measured) {
    return (
      `required input ${input.input_id} reports an age of ${String(reportedAge)} where its ` +
      `own instants measure ${String(measured)}`
    );
  }
  if (!ageIsMeasured && measured !== null) {
    return `required input ${input.input_id} has a measurable age and must report it`;
  }
  return null;
}

/** A duration a projection reports about itself: whole, non-negative seconds, or absent. */
function durationFailure(name: string, metric: z.infer<typeof metricValue>): string | null {
  if (!isValueBearing(metric.availability)) {
    return null;
  }
  const value = metric.value;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    return (
      `${name} is reported as ${String(value)}, and a measured duration is a whole, ` +
      "non-negative number of seconds -- a negative one is refused rather than clamped"
    );
  }
  return null;
}

/** §3.1: the composite `source_age` IS the oldest required input's own age. */
function compositeSourceAgeFailure(
  report: z.infer<typeof reportShape>,
  required: readonly FreshnessInput[],
): string | null {
  const named = report.oldest_required;
  if (named !== undefined && !required.some((input) => input.input_id === named)) {
    return `oldest_required names ${named}, which is not a required input of this report`;
  }
  const compositeFailure = durationFailure("source_age", report.source_age);
  if (compositeFailure !== null) {
    return compositeFailure;
  }
  if (!isValueBearing(report.source_age.availability)) {
    return null;
  }
  const ages = required.map((input) =>
    isValueBearing(input.source_age.availability) ? input.source_age.value : null,
  );
  if (ages.some((age) => typeof age !== "number")) {
    // An unknown age has no place in a maximum, so no composite age is determinable.
    return "a required input carries an unknown age, so the composite reports no measured one";
  }
  const oldest = Math.max(...(ages as number[]));
  if (report.source_age.value !== oldest) {
    return (
      `source_age reports ${String(report.source_age.value)} where the oldest required input ` +
      `measures ${oldest}`
    );
  }
  const namedInput = required.find((input) => input.input_id === named);
  if (namedInput !== undefined && namedInput.source_age.value !== oldest) {
    return `oldest_required names ${String(named)}, which is not the oldest required input`;
  }
  return null;
}

/**
 * Returns `null` when the report is internally consistent, and the refusal reason otherwise.
 *
 * FAIL CLOSED. A report is a CLAIM, and its claims can contradict each other while every
 * field is individually well-typed:
 *
 *   a required input carries NO source time      -- §3.1 fixes its state and its reason, and
 *                                                   a STALE guess is not that state
 *   a required input is STALE, MISSING or ERROR  -- and the composite still says AVAILABLE
 *   a source time is AFTER the evaluation time   -- and a negative age is reported as fresh
 *   a source time is after it WITHIN tolerance   -- and the zero is reported SILENTLY
 *   an age, lag or build age is NEGATIVE         -- and is clamped into a plausible zero
 *   required inputs fail in SEVERAL ways         -- and one of them is picked as "the" state
 *
 * NO PRECEDENCE POLICY IS INVENTED HERE. Where every required input is `AVAILABLE` the
 * composite is `AVAILABLE`. Where exactly one distinct failure occurred, that failure IS the
 * worst one, and the composite must be it. Where SEVERAL distinct failures occurred, §3.1
 * fixes no ordering between them, so the report is REFUSED rather than resolved to whichever
 * one happens to be listed first — and every individual input failure stays inspectable in
 * `inputs`, which is where a reader diagnoses it.
 */
export function freshnessReportFailure(report: z.infer<typeof reportShape>): string | null {
  const evaluationMs = parseInstantMs(report.evaluation_time);
  if (evaluationMs === null) {
    return "evaluation_time is not a real calendar instant";
  }
  const required = report.inputs.filter((input) => input.required);
  if (required.length === 0) {
    // No required input establishes no deadline, so nothing could bound this report.
    return "a freshness report states at least one required input";
  }
  for (const input of required) {
    const failure = requiredInputFailure(input, evaluationMs);
    if (failure !== null) {
      return failure;
    }
  }
  for (const [name, metric] of [
    ["projection_lag", report.projection_lag],
    ["build_age", report.build_age],
  ] as const) {
    const failure = durationFailure(name, metric);
    if (failure !== null) {
      return failure;
    }
  }
  const compositeAge = compositeSourceAgeFailure(report, required);
  if (compositeAge !== null) {
    return compositeAge;
  }

  const failures = requiredFailureSignatures(report);
  if (failures.length === 0) {
    if (report.composite_state !== "AVAILABLE") {
      return "every required input is AVAILABLE, so the composite cannot claim a worse state";
    }
    return null;
  }
  // One fresh input NEVER raises a view carrying a failing one, whatever the composite says.
  if (report.composite_state === "AVAILABLE") {
    return `composite_state claims AVAILABLE while a required input is ${failures[0].state}`;
  }
  if (failures.length > 1) {
    const ways = failures.map((failure) => `${failure.state}/${failure.reason}`).join(", ");
    return (
      `required inputs failed in ${failures.length} different ways (${ways}); §3.1 defines the ` +
      "composite as the WORST required state and defines no ordering across these, so this " +
      "report is refused rather than resolved to one of them"
    );
  }
  if (report.composite_state !== failures[0].state) {
    return (
      `composite_state ${report.composite_state} is not the one state its required inputs ` +
      `reached (${failures[0].state})`
    );
  }
  return null;
}

export const freshnessReport = reportShape.superRefine((candidate, ctx) => {
  const failure = freshnessReportFailure(candidate);
  if (failure !== null) {
    ctx.addIssue({ code: "custom", message: failure });
  }
});
export type FreshnessReport = z.infer<typeof freshnessReport>;

/** `input_deadline = source_effective_time + contract_max_age` — ABSOLUTE, and per input. */
export function inputDeadline(input: FreshnessInput): number | null {
  if (input.source_effective_time === undefined) {
    // Unknown timing establishes no deadline. No default TTL is invented for it.
    return null;
  }
  const effectiveMs = parseInstantMs(input.source_effective_time);
  if (effectiveMs === null) {
    // An unreal instant establishes no deadline. It is never arithmetic that quietly
    // produces NaN, because `serve_time >= NaN` is false and never expires.
    return null;
  }
  return effectiveMs + input.contract_max_age * 1000;
}

/**
 * `fresh_until = minimum(input_deadline over every REQUIRED input)`.
 *
 * Optional inputs answer for themselves and DO NOT set `fresh_until`. A required input
 * with no usable source time yields `null`: no deadline can be established, and the entry
 * is never cached as fresh.
 */
export function freshUntil(report: FreshnessReport): number | null {
  const required = report.inputs.filter((input) => input.required);
  if (required.length === 0) {
    return null;
  }
  let earliest: number | null = null;
  for (const input of required) {
    const deadline = inputDeadline(input);
    if (deadline === null || !Number.isFinite(deadline)) {
      return null;
    }
    earliest = earliest === null ? deadline : Math.min(earliest, deadline);
  }
  return earliest;
}

/**
 * `remaining_freshness = max(0, fresh_until - cache_or_serve_time)`, in whole seconds.
 *
 * THE ONE CLAMP. It bounds the REMAINING BUDGET and nothing else: it never hides clock skew
 * and never clamps an invalid, negative or unknown source age, which refuse under §3.1.
 */
export function remainingFreshnessSeconds(
  report: FreshnessReport,
  serveTimeMs: number,
): number | null {
  const until = freshUntil(report);
  if (until === null) {
    return null;
  }
  return Math.max(0, Math.floor((until - serveTimeMs) / 1000));
}

/**
 * The comparison, stated ONCE so two layers cannot disagree:
 *
 *   serve_time <  fresh_until   AVAILABLE is permitted, if every other rule already permits it
 *   serve_time >= fresh_until   the entry is EXPIRED -- revalidate, or downgrade to STALE
 *
 * At EQUALITY the entry is expired. That boundary is deliberate and is tested.
 */
export function isExpired(report: FreshnessReport, serveTimeMs: number): boolean {
  const until = freshUntil(report);
  if (until === null) {
    // No establishable deadline is never treated as fresh.
    return true;
  }
  return serveTimeMs >= until;
}

/**
 * The state a consumer must render at `serveTimeMs`.
 *
 * Retaining content is not claiming it is fresh: an expired entry may be kept and served,
 * explicitly `STALE` with `UPSTREAM_INPUT_STALE`, and NEVER `AVAILABLE`. A TTL upgrades
 * nothing — an input already `STALE`, `PARTIAL`, missing or in `ERROR` stays in that state.
 *
 * IT IS INDEPENDENT OF THE ORDER `inputs` ARRIVES IN. It reads the DISTINCT failures rather
 * than the first one, so permuting a report's inputs cannot change the diagnosis a reader
 * sees.
 */
export function effectiveComposite(
  report: FreshnessReport,
  serveTimeMs: number,
): { state: z.infer<typeof availabilityState>; reason: z.infer<typeof fieldReasonCode> } {
  const failures = requiredFailureSignatures(report);
  if (failures.length === 1) {
    /*
     * The failing input answers for itself. Reading the composite's own claim here would let
     * a producer upgrade a required failure by asserting AVAILABLE beside it, and a missing
     * source time would be reported as an invented STALE rather than as the
     * NOT_YET_AVAILABLE with SOURCE_TIMESTAMP_MISSING that §3.1 fixes for it.
     */
    return failures[0];
  }
  if (failures.length > 1) {
    /*
     * UNREACHABLE THROUGH ADMISSION, which refuses a report whose required inputs failed in
     * more than one way. A report arriving here anyway is internally contradictory, and
     * PICKING ONE OF ITS ANSWERS is exactly the order-dependence this function was corrected
     * for. It fails closed on the one state that means "production failed"; the individual
     * failures stay inspectable in `report.inputs`, which is where they are diagnosed.
     */
    return { state: "ERROR", reason: "PROJECTION_ERROR" };
  }
  if (report.composite_state !== "AVAILABLE") {
    // A remaining budget is a ceiling on freshness, never a grant of it.
    return { state: report.composite_state, reason: report.source_age.reason };
  }
  if (isExpired(report, serveTimeMs)) {
    return { state: "STALE", reason: "UPSTREAM_INPUT_STALE" };
  }
  return { state: "AVAILABLE", reason: "NONE" };
}

/** Whether any REQUIRED input reported an ordinary, within-tolerance clock skew (§3.1). */
export function hasFlaggedClockSkew(report: FreshnessReport): boolean {
  return report.inputs.some((input) => input.required && input.clock_skew_flagged === true);
}

/**
 * A configured TTL may SHORTEN and never extend: the effective lifetime is the smaller of
 * the configured TTL and `remaining_freshness`. A TTL longer than the remaining budget is
 * IGNORED, not honoured.
 */
export function effectiveCacheLifetimeSeconds(
  report: FreshnessReport,
  serveTimeMs: number,
  configuredTtlSeconds: number,
): number {
  const remaining = remainingFreshnessSeconds(report, serveTimeMs);
  if (remaining === null) {
    return 0;
  }
  return Math.min(configuredTtlSeconds, remaining);
}
