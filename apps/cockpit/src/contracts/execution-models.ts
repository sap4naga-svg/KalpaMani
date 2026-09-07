/**
 * `ExecutionQuality` — `read-model-contracts.md` §4.5 *Trade and execution*, and §12.3.1.
 *
 * The one trade's execution quality that Trade Detail carries. **It is not Area 9**: the
 * `/execution/quality` screen is the aggregate surface over every fill in a window, it belongs
 * to a later cycle, and nothing here implements it. This is the per-trade record §4.5 declares
 * `TradeDetail.execution_quality_ref` resolves to.
 *
 * THREE THINGS THIS FILE EXISTS TO GET RIGHT.
 *
 *   SIDE SIGN, NOT DIRECTION       §12.3.1's `side_sign` is `+1` for **every buy** and `−1` for
 *                                  **every sell**. A short trade OPENS with a sell and CLOSES
 *                                  with a buy, so the order side is not the position direction
 *                                  and the two are separate fields. Without the sign, an
 *                                  equally weighted book of adverse buys and adverse sells
 *                                  averages to zero and reports perfect execution
 *   BASIS POINTS, NOT A RATIO      the ratio is multiplied by **10,000**. A formula that
 *                                  divides two prices and calls the quotient `BPS` is out by
 *                                  four orders of magnitude, and the error is invisible on any
 *                                  single fill
 *   A REFERENCE, OR NO NUMBER      slippage without a named reference price carrying its own
 *                                  timestamp is "not a number this contract admits". A missing
 *                                  reference is `UPSTREAM_INPUT_MISSING`; a zero reference is
 *                                  `DENOMINATOR_ZERO`, never a division
 */
import { z } from "zod";

import {
  instant,
  metricOf,
  metricValue,
  reasonCoded,
  ref,
} from "./values";
import { isValueBearing } from "./validity";

/**
 * The four order sides §12.3.1 names, and the sign each carries.
 *
 * ADDITIVE and documented: §4.5 requires a `side_convention` on every reference price and does
 * not enumerate the sides. The four below are exactly the four the metric dictionary works
 * through, and the sign is derived from the side rather than stored beside it — two fields that
 * can disagree is how a book of adverse fills reports zero.
 */
export const ORDER_SIDES = [
  "BUY_TO_OPEN",
  "BUY_TO_COVER",
  "SELL_TO_CLOSE",
  "SELL_TO_OPEN",
] as const;
export const orderSide = z.enum(ORDER_SIDES);
export type OrderSide = z.infer<typeof orderSide>;

/** `+1` for every buy, `−1` for every sell. **Never derived from the position's direction.** */
export function sideSign(side: OrderSide): 1 | -1 {
  return side === "BUY_TO_OPEN" || side === "BUY_TO_COVER" ? 1 : -1;
}

/**
 * Slippage in basis points, from integer cents, rounded **once** at the declared scale.
 *
 * Returns hundredths of a basis point — the declared minimum scale — or `null` where the
 * reference is zero, because a zero denominator is `DENOMINATOR_ZERO` and never a division.
 *
 * The arithmetic is done in integers and the single rounding is half-even at the final scale,
 * exactly as §12.3.1 requires: never to an intermediate quotient, and never per fill before
 * aggregation.
 */
export function slippageHundredthBps(
  side: OrderSide,
  fillCents: number,
  referenceCents: number,
): number | null {
  if (referenceCents === 0) {
    return null;
  }
  // (fill − reference) / reference × 10,000 × 100, as one quotient in hundredths of a bp.
  const numerator = sideSign(side) * (fillCents - referenceCents) * 1_000_000;
  return halfEven(numerator, referenceCents);
}

/** Half-even division of two integers. Rounding happens once, at the declared scale. */
export function halfEven(numerator: number, denominator: number): number {
  const sign = numerator < 0 !== denominator < 0 ? -1 : 1;
  const absNumerator = Math.abs(numerator);
  const absDenominator = Math.abs(denominator);
  const quotient = Math.floor(absNumerator / absDenominator);
  const remainder = absNumerator - quotient * absDenominator;
  const twice = remainder * 2;
  let rounded = quotient;
  if (twice > absDenominator || (twice === absDenominator && quotient % 2 === 1)) {
    rounded = quotient + 1;
  }
  return sign * rounded;
}

/**
 * The named reference a fill is measured against.
 *
 * §4.5 declares `{ name, at, side_convention }`. The PRICE itself is additive and load-bearing:
 * a reader shown a slippage figure and the fill price cannot check the arithmetic without the
 * third number, and "slippage without a named reference price, timestamp and side convention is
 * not a number this contract admits" is a rule about what a reader can verify.
 */
export const referencePrice = z.object({
  name: reasonCoded,
  at: instant,
  side_convention: reasonCoded,
  price: metricOf("execution.reference_price"),
});

export const EXECUTION_SCOPES = ["ORDER", "FILL", "AGGREGATE"] as const;
export const executionScope = z.enum(EXECUTION_SCOPES);

export const executionQuality = z
  .object({
    scope: executionScope,
    /** Which order, fill or trade this record is about. */
    subject_ref: ref,
    /** The order side, from which the sign is derived. **Never the position's direction.** */
    side: orderSide,
    quantity: metricOf("execution.quantity"),
    /** The fill this measures. ABSENT at `AGGREGATE`, which measures no single fill. */
    fill_price: metricValue,
    reference_price: referencePrice,
    /** `slippage` at `ORDER` and `FILL`; `slippage.aggregate` at `AGGREGATE`. */
    slippage: metricValue,
    fill_rate: metricOf("execution.fill_rate"),
    signal_to_order_latency: metricOf("latency.signal_to_order"),
    order_to_fill_latency: metricOf("latency.order_to_fill"),
    clock_source: reasonCoded,
    clock_accuracy: metricOf("clock.accuracy"),
    /** Required when the scope is `AGGREGATE`. */
    aggregation_method: reasonCoded.optional(),
    /**
     * Fills excluded from an aggregate because their reference could not be resolved.
     *
     * §12.3: "Fills with no reference are excluded and counted, and the result is `PARTIAL`
     * naming how many — an average over a silently reduced population is a different metric."
     */
    excluded_fills: metricOf("execution.excluded_fills").optional(),
    /** The declared minimum this metric's rule requires, shown beside the outcome (§12.1). */
    minimum_observations: metricOf("performance.minimum_observations"),
    observation_count: metricOf("performance.observation_count"),
  })
  .superRefine((candidate, ctx) => {
    const aggregate = candidate.scope === "AGGREGATE";
    if (aggregate && candidate.aggregation_method === undefined) {
      ctx.addIssue({
        code: "custom",
        message: "an aggregate names the method it was aggregated by",
      });
    }
    if (!aggregate && candidate.aggregation_method !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "a single fill or order is not aggregated, and names no method",
      });
    }
    /*
     * TWO METRICS, TWO IDENTIFIERS (12.2).
     *
     * A per-fill slippage and a quantity-weighted aggregate are different quantities with
     * different minimum-observation rules, so they never share a `metric_id`.
     */
    const expected = aggregate ? "slippage.aggregate" : "slippage";
    if (candidate.slippage.metric_id !== expected) {
      ctx.addIssue({
        code: "custom",
        message: `a ${candidate.scope} record carries ${expected}, not ${candidate.slippage.metric_id}`,
      });
    }
    if (candidate.slippage.unit !== "BPS") {
      ctx.addIssue({ code: "custom", message: "slippage is carried in basis points" });
    }
    if (aggregate && isValueBearing(candidate.fill_price.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "an aggregate measures no single fill, so it carries no fill price",
      });
    }
    if (!aggregate && candidate.fill_price.metric_id !== "execution.fill_price") {
      ctx.addIssue({
        code: "custom",
        message: "a fill or order record carries the price it filled at",
      });
    }
    /*
     * A ZERO REFERENCE IS NOT A DIVISION.
     *
     * 12.3.1 fixes the outcome: `NOT_APPLICABLE` with `DENOMINATOR_ZERO`, never a substituted
     * price and never a large number.
     */
    if (
      candidate.reference_price.price.value === "0.00" &&
      isValueBearing(candidate.slippage.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a zero reference price yields no slippage",
      });
    }
    /*
     * A METRIC BELOW ITS DECLARED MINIMUM REPORTS THE STATE, NOT A NUMBER (12.1).
     */
    const observed = candidate.observation_count.value;
    const minimum = candidate.minimum_observations.value;
    if (
      typeof observed === "number" &&
      typeof minimum === "number" &&
      observed < minimum &&
      isValueBearing(candidate.slippage.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a value below its declared minimum observation count is not computed",
      });
    }
  });
export type ExecutionQuality = z.infer<typeof executionQuality>;
