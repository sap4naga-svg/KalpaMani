/**
 * Shared construction helpers for the C5 fixture projections.
 *
 * Every projection below the read-client boundary builds `MetricValue`s, references, policy
 * references and reason codes the same way. They are built HERE, once, so a metric cannot
 * carry one unit in the positions projection and another in the risk projection — which is
 * exactly the drift §12.2 exists to prevent.
 *
 * NOTHING HERE IS A RESULT. These are builders over the deterministic demonstration book.
 */
import { available, absent, qualified, reason, refListOf } from "@/contracts/factories";
import type { MetricValue, Ref } from "@/contracts/values";
import type { AvailabilityState, FieldReasonCode, Unit } from "@/contracts/vocabularies";

import { centsToDecimal, SESSION_COUNT, STRATEGY_CAPITAL_CENTS } from "./book";

/** The one vocabulary name every demonstration reason code is drawn from. */
export const DEMO = "kalpamani.demo";

/** The named market calendar. A date range without one is not a date range (§4.2). */
export const CALENDAR = reason("XNYS_EQUITY_REGULAR_SESSION", DEMO);

export function demoReason(code: string) {
  return reason(code, DEMO);
}

/**
 * A reference.
 *
 * The default resolution is `UNRESOLVABLE_V1`, and that is the honest default: most of the
 * producers these references point at do not exist, so the reference is carried "so the join
 * is specified, and it resolves to an availability state rather than to a payload" (§4.3).
 */
export function demoRef(
  refId: string,
  refKind: string,
  resolution: Ref["resolution"] = "UNRESOLVABLE_V1",
): Ref {
  return { ref_id: refId, ref_kind: refKind, resolution, classification: "PUBLIC_SAFE" };
}

export { refListOf };

/**
 * The demonstration risk policy every permitted and planned-risk record is carried with.
 *
 * A stage may name a LATER version than the one before it: §12.4 requires that a trade
 * "whose stages carry different `risk_policy_version` values reports its `r_multiple` with
 * every contributing policy version displayed", and a book in which every stage shares one
 * version can never show that. The pyramid's add is thirty sessions after its entry and
 * carries the version in force then.
 */
export function demoPolicyRef(asOf: string, policyVersion = "0.0.0-demo") {
  return { policy_id: "risk-policy-demo", policy_version: policyVersion, as_of: asOf };
}

/** A USD `MetricValue` from an integer number of cents. */
export function usd(metricId: string, cents: number, asOf: string): MetricValue {
  return available({ metricId, unit: "USD", value: centsToDecimal(cents), asOf });
}

/** A PERCENT `MetricValue` from an integer number of hundredths of a percent. */
export function percent(metricId: string, hundredths: number, asOf: string): MetricValue {
  return available({ metricId, unit: "PERCENT", value: centsToDecimal(hundredths), asOf });
}

/** A RATIO, R_MULTIPLE, BPS or DIMENSIONLESS value from an integer number of hundredths. */
export function scaled(
  metricId: string,
  unit: Extract<Unit, "RATIO" | "R_MULTIPLE" | "BPS" | "DIMENSIONLESS">,
  hundredths: number,
  asOf: string,
): MetricValue {
  return available({ metricId, unit, value: centsToDecimal(hundredths), asOf });
}

/** A COUNT. ADR-0029 §2.1: a measured zero is a RESULT, and stays `AVAILABLE`. */
export function count(metricId: string, value: number, asOf: string): MetricValue {
  return available({ metricId, unit: "COUNT", value, asOf });
}

/** A whole-share count. */
export function shares(metricId: string, value: number, asOf: string): MetricValue {
  return available({ metricId, unit: "SHARES", value, asOf });
}

/** A whole count of trading days. */
export function tradingDays(metricId: string, value: number, asOf: string): MetricValue {
  return available({ metricId, unit: "TRADING_DAYS", value, asOf });
}

/** A closed-vocabulary token carried as a metric's value. */
export function token(metricId: string, value: string, asOf: string): MetricValue {
  return available({ metricId, unit: "DIMENSIONLESS", value, asOf });
}

/** An instant carried as a metric's value, under the `DATE_ONLY` precedent. */
export function instantValue(metricId: string, value: string, asOf: string): MetricValue {
  return available({ metricId, unit: "DIMENSIONLESS", value, asOf });
}

/** An absence. It carries NO value — a producer that cannot answer substitutes no zero. */
export function unavailable(
  metricId: string,
  unit: Unit,
  state: Exclude<AvailabilityState, "AVAILABLE" | "STALE" | "PARTIAL" | "EMPTY_VERIFIED">,
  why: FieldReasonCode,
): MetricValue {
  return absent(state, why, metricId, unit);
}

/** The question does not apply to this subject. Reserved, and never used for an absence. */
export function notApplicable(metricId: string, unit: Unit): MetricValue {
  return absent("NOT_APPLICABLE", "NOT_DEFINED_FOR_SUBJECT", metricId, unit);
}

/** The arithmetic is undefined — a zero denominator, and never an infinity or a sentinel. */
export function denominatorZero(metricId: string, unit: Unit): MetricValue {
  return absent("NOT_APPLICABLE", "DENOMINATOR_ZERO", metricId, unit);
}

/** Computable, and it would not be meaningful. No ratio is shown. */
export function insufficient(metricId: string, unit: Unit): MetricValue {
  return absent("INSUFFICIENT_OBSERVATIONS", "BELOW_MINIMUM_OBSERVATIONS", metricId, unit);
}

/** A path-dependent value over an incomplete price path. Never an optimistic value. */
export function partialPath(
  metricId: string,
  unit: Extract<Unit, "USD" | "RATIO">,
  value: string,
  asOf: string,
): MetricValue {
  return qualified("PARTIAL", "PRICE_PATH_INCOMPLETE", { metricId, unit, value, asOf });
}

/** A value-bearing state that keeps its qualification. A stale figure is still stale. */
export { qualified };

/** The authoritative strategy capital, as `Money`. NEVER broker-reported equity. */
export const STRATEGY_CAPITAL_MONEY = {
  amount: centsToDecimal(STRATEGY_CAPITAL_CENTS),
  currency: "USD",
} as const;

/**
 * The instant a session's close is stated at.
 *
 * Sessions are calendar days on the named market calendar; a mark belongs to that session's
 * close, which is a real instant. Fixing it at one hour keeps every derived age deterministic
 * — a demonstration whose timestamps move between runs cannot be reviewed.
 */
export function sessionInstant(day: string): string {
  return `${day}T21:00:00.000Z`;
}

/** The half-open window a session slice covers, stated with its calendar and timezone. */
export function windowOf(days: readonly string[]) {
  return {
    from: `${days[0]}T00:00:00.000Z`,
    to: sessionInstant(days[days.length - 1]),
    calendar: CALENDAR,
    timezone: "UTC" as const,
  };
}

/** The session index the retained extent's last completed session sits at. */
export const LAST_SESSION = SESSION_COUNT - 1;
