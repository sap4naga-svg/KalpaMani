/**
 * `strategy.tail_loss` — the rolling tail loss, as ADR-0032 §D1 accepted it.
 *
 * **The question it answers is *when this strategy version goes wrong, how wrong*** — which
 * is not the question `expectancy.r` answers, not the question `drawdown.max` answers, and
 * not the question the single worst trade answers (§12.3.2).
 *
 * THIS MODULE IS THE STATISTIC AND NOTHING ELSE. It takes observations a caller has already
 * attributed to ONE EXACT strategy version, and returns what the contract says the answer
 * is. It builds no `MetricValue`, reads no book, names no strategy and reaches no screen: a
 * projection maps records into `TailLossObservation`s and renders the outcome, so the
 * arithmetic is testable against hand-calculated values with no fixture in the way.
 *
 * **NOTHING HERE CAUSES A TRANSITION.** ADR-0032 §D1.11: Area 5's seven health states and
 * every transition rule are ADR-0026 §13's and are unchanged. No threshold is evaluated, no
 * promotion is decided, no risk limit is read and no entry rule is created.
 *
 * **NO PREDICTIVE CLAIM IS MADE.** The window is thirty observations and the tail averages
 * three of them, so **one observation is a third of the estimate**. The value is descriptive
 * of the window it measured and carries no reliability, qualification or threshold (§D1.12).
 */
import type { AvailabilityState, FieldReasonCode } from "./vocabularies";

/**
 * The PROPOSED MEASUREMENT DECISIONS of ADR-0032 §D1.12, transcribed once.
 *
 * Each is a choice the accepted contract made, and **none of them is a trading rule, a
 * promotion criterion, a health-state transition, a risk limit or a capital authorization**.
 * Lowering or raising any of them is an ADR amendment rather than a configuration change.
 */
export const TAIL_LOSS_PARAMETERS = {
  /** `q`, the declared tail fraction, in hundredths. `0.10` — a decile. */
  tailFractionHundredths: 10,
  /** `N`, the window: the trailing thirty ELIGIBLE CLOSED TRADES. Never a calendar window. */
  windowObservations: 30,
  /** The declared minimum. The same reused count, so the window is a window. */
  minimumObservations: 30,
} as const;

/** The observation unit, displayed rather than assumed. Never sessions, never periods. */
export const TAIL_LOSS_OBSERVATION_UNIT = "CLOSED_TRADE";

/**
 * `k = ceil(q * n)` — an INTEGER COUNT OF ORDER STATISTICS.
 *
 * Because it is a count rather than a position, **no quantile interpolation rule is needed
 * anywhere** (§D1.6), and no convention is left for a later implementation to pick
 * differently. The multiplication happens in hundredths so a binary float never decides
 * which observations are in the tail.
 */
export function tailObservationCount(eligible: number): number {
  return Math.ceil((eligible * TAIL_LOSS_PARAMETERS.tailFractionHundredths) / 100);
}

/**
 * One observation: one CLOSED trade of one exact strategy version, at its close.
 *
 * A trade contributes **exactly one** observation. An open trade and a partially exited
 * trade contribute NONE — a partial exit reduces a trade, it does not close it (§D1.9).
 */
export interface TailLossObservation {
  /** The trade identifier. The recency tie-break, so window membership is deterministic. */
  readonly tradeId: string;
  /** The close instant, in epoch milliseconds. An observation enters the window here. */
  readonly closedAtMs: number;
  /**
   * The trade's own `r_multiple`, in hundredths.
   *
   * `null` where the trade carries no recorded `risk.initial_planned` or a zero one — the
   * eligibility `expectancy.r` already imposes, reused rather than reinvented. Such a trade
   * is EXCLUDED and COUNTED; it is never treated as a zero observation.
   */
  readonly rMultipleHundredths: number | null;
}

/** One member of the computed tail, for the evidence listing the value is displayed with. */
export interface TailLossMember {
  readonly tradeId: string;
  readonly closedAtMs: number;
  readonly rMultipleHundredths: number;
}

export interface TailLossResult {
  readonly availability: AvailabilityState;
  readonly reason: FieldReasonCode;
  /**
   * The statistic in hundredths of an R multiple, or `null` where the state carries none.
   *
   * A `null` here is an ABSENCE and is never rendered as a zero. A computed `0` is a
   * MEASUREMENT and arrives as the number zero with `AVAILABLE` (§D1.5, §D1.10).
   */
  readonly valueHundredths: number | null;
  /** `n` — eligible observations inside the window, after the cutoff and the walk-back. */
  readonly eligibleObservations: number;
  /** `k` — the contributing tail count, zero where no value was produced. */
  readonly tailObservations: number;
  /**
   * How many CLOSED trades the walk-back excluded for a missing or zero initial planned risk.
   *
   * **Disclosed either way, and never the metric value.** It is stated in the insufficient
   * case too, so a reader is never told a window was merely short when part of it was also
   * unusable — and disclosing it **never** converts an absent value into a valued `PARTIAL`.
   */
  readonly excludedObservations: number;
  /** The observations that formed the tail, most adverse first. Empty without a value. */
  readonly members: readonly TailLossMember[];
  /** How far back the walk went, in CLOSED trades — eligible plus excluded. */
  readonly walkedBack: number;
}

/**
 * The severity order: `r_multiple` ASCENDING, most adverse first.
 *
 * Ties need no tie-break for the VALUE — tied observations carry the same `r_multiple`, so
 * the mean over any `k`-subset of a tie is identical (§D1.8, §3.3). The trade identifier
 * settles the order anyway, so a LISTING of which observations formed the tail is
 * reproducible rather than incidental.
 */
function bySeverity(left: TailLossMember, right: TailLossMember): number {
  if (left.rMultipleHundredths !== right.rMultipleHundredths) {
    return left.rMultipleHundredths - right.rMultipleHundredths;
  }
  return left.tradeId < right.tradeId ? -1 : left.tradeId > right.tradeId ? 1 : 0;
}

/**
 * The recency order: close instant ASCENDING, ties by trade identifier ASCENDING.
 *
 * Window membership is decided on this order, so it stays deterministic for a population
 * whose trades closed at one instant.
 */
function byRecency(left: TailLossObservation, right: TailLossObservation): number {
  if (left.closedAtMs !== right.closedAtMs) {
    return left.closedAtMs - right.closedAtMs;
  }
  return left.tradeId < right.tradeId ? -1 : left.tradeId > right.tradeId ? 1 : 0;
}

/**
 * The rolling tail loss at one evaluation point.
 *
 * ```text
 * n    eligible observations in the window        k = ceil(q * n)
 * r(1) <= r(2) <= ... <= r(n)                     ascending eligible r_multiple values
 * strategy.tail_loss = ( r(1) + ... + r(k) ) / k
 * ```
 *
 * **NO POINT LOOKS FORWARD.** Only observations whose close instant is at or before
 * `cutoffMs` are eligible, in the strong form §D1.8 states and §12.3.2 asks to be tested:
 * **replacing every observation after the cutoff changes nothing at or before it.**
 *
 * **IT IS A MEAN OF RATIOS AND NEVER A RATIO OF SUMS.** Each observation carries its own
 * denominator — that trade's retained `risk.initial_planned`, summed across stages — so the
 * caller supplies `r_multiple`s and this averages them. Dividing total tail dollars by total
 * tail risk dollars would weight the tail by position size and report a different quantity
 * under this name (§D1.7).
 *
 * **THE POPULATION IS EVERY ELIGIBLE OBSERVATION AND NEVER LOSSES ONLY.** The tail is
 * selected by ORDERING, so a POSITIVE result is a measured value meaning even the worst
 * observations made money (§D1.3, §D1.5).
 */
export function computeRollingTailLoss(
  observations: readonly TailLossObservation[],
  cutoffMs: number,
): TailLossResult {
  const { windowObservations, minimumObservations } = TAIL_LOSS_PARAMETERS;

  /*
   * THE CUTOFF IS APPLIED BEFORE ANYTHING ELSE, on the close instant.
   *
   * An observation enters at its CLOSE, not at its entry: a trade's outcome is not known
   * until it closes, and admitting it earlier would place information in a window before it
   * existed (§D1.8).
   */
  const atOrBefore = observations
    .filter((observation) => observation.closedAtMs <= cutoffMs)
    .sort(byRecency);

  /*
   * THE WALK-BACK, from the most recent closed trade backwards.
   *
   * It walks CLOSED trades and collects ELIGIBLE ones until the window is full, counting the
   * ineligible ones it passed. It stops at the window rather than at the first thirty closed
   * trades: an excluded trade must not silently consume a window slot, because "an average
   * over a silently reduced population is a different metric" (§12.3.2, the
   * `slippage.aggregate` precedent).
   */
  const eligible: TailLossMember[] = [];
  let excluded = 0;
  let walkedBack = 0;
  for (let index = atOrBefore.length - 1; index >= 0; index -= 1) {
    if (eligible.length >= windowObservations) {
      break;
    }
    const observation = atOrBefore[index];
    walkedBack += 1;
    if (observation.rMultipleHundredths === null) {
      excluded += 1;
      continue;
    }
    eligible.push({
      tradeId: observation.tradeId,
      closedAtMs: observation.closedAtMs,
      rMultipleHundredths: observation.rMultipleHundredths,
    });
  }

  const n = eligible.length;

  /*
   * SUFFICIENCY IS DECIDED BEFORE EXCLUSION, AND THE TWO ANSWERS ARE NEVER BOTH RETURNED.
   *
   * Below the minimum the value is `INSUFFICIENT_OBSERVATIONS` with
   * `BELOW_MINIMUM_OBSERVATIONS` and **carries no value at all**, WHETHER OR NOT closed
   * trades were also excluded during the walk-back. `PARTIAL` is reachable only when the
   * minimum is met, because §4.1.1 requires a `PARTIAL` value to be PRESENT and an
   * insufficient population has none to qualify (§D1.10).
   *
   * The exclusion count is still carried out of here, because it is a POPULATION DISCLOSURE
   * beside the metric rather than the metric — but it manufactures no value.
   */
  if (n < minimumObservations) {
    return {
      availability: "INSUFFICIENT_OBSERVATIONS",
      reason: "BELOW_MINIMUM_OBSERVATIONS",
      valueHundredths: null,
      eligibleObservations: n,
      tailObservations: 0,
      excludedObservations: excluded,
      members: [],
      walkedBack,
    };
  }

  const k = tailObservationCount(n);
  const members = [...eligible].sort(bySeverity).slice(0, k);
  /*
   * The mean of the `k` most adverse eligible observations.
   *
   * Summed in integer hundredths and rounded ONCE, at the end. `k >= 1` whenever the minimum
   * is met, so **`DENOMINATOR_ZERO` is unreachable for this metric** (§D1.6) and there is no
   * zero-denominator branch here to reach.
   */
  const total = members.reduce((sum, member) => sum + member.rMultipleHundredths, 0);
  const valueHundredths = Math.round(total / k);

  /*
   * `PARTIAL` NAMES HOW MANY WERE EXCLUDED, and only once the minimum is met.
   *
   * A computed ZERO is `AVAILABLE`, distinctly from insufficiency: a producer that ran and
   * measured zero has answered the question (§4.1.2, ADR-0029 §2.1).
   */
  return {
    availability: excluded > 0 ? "PARTIAL" : "AVAILABLE",
    reason: excluded > 0 ? "UPSTREAM_INPUT_MISSING" : "NONE",
    valueHundredths,
    eligibleObservations: n,
    tailObservations: k,
    excludedObservations: excluded,
    members,
    walkedBack,
  };
}
