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
 */
import { z } from "zod";

import { availabilityState, fieldReasonCode } from "./vocabularies";
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
});
export type FreshnessInput = z.infer<typeof freshnessInput>;

/**
 * The declared clock-skew tolerance 3.1 refers to.
 *
 * A source time later than `evaluation_time` by more than this is `NOT_YET_AVAILABLE` with
 * `CLOCK_UNSYNCHRONIZED`, and its age is UNKNOWN rather than zero. Declared here because
 * "the declared tolerance" has to be declared somewhere to be checkable.
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
 * Returns `null` when the report is internally consistent, and the refusal reason otherwise.
 *
 * FAIL CLOSED. A report is a CLAIM, and three of its claims can contradict each other while
 * every field is individually well-typed:
 *
 *   a required input carries NO source time      -- 3.1 fixes its state and its reason, and
 *                                                   a STALE guess is not that state
 *   a required input is STALE, MISSING or ERROR  -- and the composite still says AVAILABLE
 *   a source time is AFTER the evaluation time   -- and a negative age is reported as fresh
 *
 * Rejecting the contradiction is enough; no new precedence policy is invented here. Where
 * every required input is AVAILABLE the composite is AVAILABLE, where any is not the
 * composite must be one of the states its required inputs actually reached, and anything
 * else is refused rather than resolved.
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
    if (input.source_effective_time === undefined) {
      // 3.1: unknown timing has ONE state and ONE reason, and neither is invented.
      if (input.state !== "NOT_YET_AVAILABLE" || input.reason !== "SOURCE_TIMESTAMP_MISSING") {
        return `required input ${input.input_id} has no source time and must be ` +
          "NOT_YET_AVAILABLE with SOURCE_TIMESTAMP_MISSING";
      }
      continue;
    }
    const effectiveMs = parseInstantMs(input.source_effective_time);
    if (effectiveMs === null) {
      return `required input ${input.input_id} carries a source time that is not a real instant`;
    }
    if (!Number.isFinite(effectiveMs + input.contract_max_age * 1000)) {
      return `required input ${input.input_id} yields a deadline that is not finite`;
    }
    const ageSeconds = (evaluationMs - effectiveMs) / 1000;
    if (ageSeconds < -CLOCK_SKEW_TOLERANCE_SECONDS) {
      // A negative age is never clamped to zero and never rendered (3.1).
      if (input.state !== "NOT_YET_AVAILABLE" || input.reason !== "CLOCK_UNSYNCHRONIZED") {
        return `required input ${input.input_id} is dated after the evaluation time beyond ` +
          "tolerance and must be NOT_YET_AVAILABLE with CLOCK_UNSYNCHRONIZED";
      }
    }
  }
  const unhealthy = required.filter((input) => input.state !== "AVAILABLE");
  if (unhealthy.length === 0) {
    if (report.composite_state !== "AVAILABLE") {
      return "every required input is AVAILABLE, so the composite cannot claim a worse state";
    }
    return null;
  }
  // One fresh input NEVER raises a view carrying a failing one, whatever the composite says.
  if (report.composite_state === "AVAILABLE") {
    return `composite_state claims AVAILABLE while required input ${unhealthy[0].input_id} ` +
      `is ${unhealthy[0].state}`;
  }
  if (!unhealthy.some((input) => input.state === report.composite_state)) {
    return "composite_state names a state no required input reached";
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
 * The clamp at zero bounds the REMAINING BUDGET and nothing else. It never hides clock
 * skew and never clamps an invalid, negative or unknown source age.
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
 */
export function effectiveComposite(
  report: FreshnessReport,
  serveTimeMs: number,
): { state: z.infer<typeof availabilityState>; reason: z.infer<typeof fieldReasonCode> } {
  const failing = report.inputs.find(
    (input) => input.required && input.state !== "AVAILABLE",
  );
  if (failing !== undefined) {
    /*
     * The failing input answers for itself. Reading the composite's own claim here would
     * let a producer upgrade a required failure by asserting AVAILABLE beside it, and a
     * missing source time would be reported as an invented STALE rather than as the
     * NOT_YET_AVAILABLE with SOURCE_TIMESTAMP_MISSING that 3.1 fixes for it.
     */
    return { state: failing.state, reason: failing.reason };
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
