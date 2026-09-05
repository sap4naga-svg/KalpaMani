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
import { duration, instant, metricValue, safeId } from "./values";

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

export const freshnessReport = z.object({
  inputs: z.array(freshnessInput),
  oldest_required: safeId.optional(),
  source_age: metricValue,
  projection_lag: metricValue,
  build_age: metricValue,
  composite_state: availabilityState,
  /** The origin's own compute instant. A cache reads `source_age` as of THIS, not as of now. */
  evaluation_time: instant,
});
export type FreshnessReport = z.infer<typeof freshnessReport>;

/** `input_deadline = source_effective_time + contract_max_age` — ABSOLUTE, and per input. */
export function inputDeadline(input: FreshnessInput): number | null {
  if (input.source_effective_time === undefined) {
    // Unknown timing establishes no deadline. No default TTL is invented for it.
    return null;
  }
  return Date.parse(input.source_effective_time) + input.contract_max_age * 1000;
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
    if (deadline === null) {
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
  if (report.composite_state !== "AVAILABLE") {
    // A remaining budget is a ceiling on freshness, never a grant of it.
    const reason = report.inputs.find((input) => input.required && input.state !== "AVAILABLE")
      ?.reason;
    return { state: report.composite_state, reason: reason ?? "UPSTREAM_INPUT_STALE" };
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
