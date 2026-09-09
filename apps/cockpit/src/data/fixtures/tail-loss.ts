/**
 * `strategy.tail_loss`, projected from the demonstration book — Area 5, ADR-0032 §D1.
 *
 * **THE VALUES ON THIS ROW ARE CALCULATED, NOT RECORDED.** Until ADR-0032 was accepted the
 * health fixture carried four hand-written tail-loss literals that were not computed under
 * any declared rule; §5.3 of that decision says so in as many words. They are gone, and what
 * replaces them is the accepted statistic evaluated over the same repository-owned synthetic
 * book every other C5 and C7 number is projected from.
 *
 * **THE BOOK IS UNCHANGED BY THIS FILE.** No trade is added, removed, reordered, re-signed
 * or re-priced; no entry fact, add-stage fact, exit, risk denominator or strategy version is
 * touched; and the book is **not enlarged to make a window full**. Where the population is
 * short, the answer is `INSUFFICIENT_OBSERVATIONS` and the screen says so.
 *
 * **ONE DEFINITION, TWO PRESENTATIONS.** The headline value and every point of the series
 * come out of `computeRollingTailLoss` in `@/contracts/tail-loss`, so a chart point and the
 * number beside it cannot be computed two ways — which is the drift §12.2 exists to prevent.
 */
import type { RollingTailLoss } from "@/contracts/strategy-models";
import {
  computeRollingTailLoss,
  TAIL_LOSS_OBSERVATION_UNIT,
  TAIL_LOSS_PARAMETERS,
  type TailLossObservation,
  type TailLossResult,
} from "@/contracts/tail-loss";
import type { MetricValue } from "@/contracts/values";

import type { BookTrade } from "./book";
import {
  count,
  demoRef,
  demoReason,
  insufficient,
  instantValue,
  qualified,
  scaled,
  sessionInstant,
} from "./common";
import { rMultipleHundredths } from "./summary";

/** The session a closed trade's final exit landed on. An observation enters at its close. */
function closeSession(trade: BookTrade): number {
  return trade.exits[trade.exits.length - 1].session;
}

/**
 * The book's closed trades of one exact version, as observations.
 *
 * **ELIGIBILITY IS `expectancy.r`'S, REUSED RATHER THAN REINVENTED** (§D1.2): a trade with
 * no recorded `risk.initial_planned`, or a recorded zero, has no denominator to divide by, so
 * it carries `null` and is EXCLUDED AND COUNTED rather than treated as a zero observation.
 * `rMultipleHundredths` is the helper the trade ledger and the R distribution already use, so
 * one trade cannot carry one R on the ledger and another here.
 *
 * OPEN AND PARTIALLY EXITED TRADES CONTRIBUTE NOTHING. A partial exit reduces a trade; it
 * does not close it and does not create a second one (§12.4, §D1.9).
 */
export function tailLossObservations(
  closed: readonly BookTrade[],
  days: readonly string[],
): TailLossObservation[] {
  return closed.map((trade) => ({
    tradeId: trade.tradeId,
    closedAtMs: Date.parse(sessionInstant(days[closeSession(trade)])),
    rMultipleHundredths: rMultipleHundredths(trade),
  }));
}

/** The `MetricValue` a result renders as. An absence carries NO value (§4.1.2). */
function tailLossMetric(result: TailLossResult, asOf: string): MetricValue {
  if (result.valueHundredths === null) {
    return insufficient("strategy.tail_loss", "R_MULTIPLE");
  }
  if (result.availability === "PARTIAL") {
    /*
     * `PARTIAL` CARRIES ITS VALUE AND KEEPS ITS QUALIFICATION (§4.1.1).
     *
     * It is reachable only once the minimum is met, and it names how many closed trades the
     * walk-back excluded — the `slippage.aggregate` precedent, reused.
     */
    return qualified("PARTIAL", "UPSTREAM_INPUT_MISSING", {
      metricId: "strategy.tail_loss",
      unit: "R_MULTIPLE",
      value: (result.valueHundredths / 100).toFixed(2),
      asOf,
    });
  }
  /*
   * A COMPUTED ZERO IS `AVAILABLE`, and so is a POSITIVE tail (§D1.5, ADR-0029 §2.1).
   *
   * The tail is selected by ORDERING and never by filtering on sign, so a version whose three
   * most adverse observations all made money reports a positive number rather than nothing.
   */
  return scaled("strategy.tail_loss", "R_MULTIPLE", result.valueHundredths, asOf);
}

/**
 * The rolling tail loss for one exact strategy version, with everything it must be read with.
 *
 * The disclosure is not decoration. §D1's acceptance criterion 9 requires the window, the
 * population, the tail fraction and the observation count beside the value, and the exclusion
 * count is disclosed **whether or not** it changed the availability — so a reader is never
 * told a window was merely short when part of it was also unusable (§D1.10).
 */
export function buildRollingTailLoss(
  closed: readonly BookTrade[],
  days: readonly string[],
  asOf: string,
): RollingTailLoss {
  /*
   * THE RECENCY ORDER OF §D1.8: close instant ascending, ties by trade identifier ascending.
   *
   * Two trades of one version routinely close on the same session, so the tie-break is what
   * makes window membership deterministic rather than incidental.
   */
  const ordered = [...tailLossObservations(closed, days)].sort((left, right) =>
    left.closedAtMs !== right.closedAtMs
      ? left.closedAtMs - right.closedAtMs
      : left.tradeId.localeCompare(right.tradeId),
  );

  const cutoffMs =
    ordered.length === 0
      ? Date.parse(sessionInstant(days[days.length - 1]))
      : ordered[ordered.length - 1].closedAtMs;
  const result = computeRollingTailLoss(ordered, cutoffMs);

  /*
   * ONE POINT PER CLOSED TRADE, in the declared recency order.
   *
   * NO POINT LOOKS FORWARD: the point at position `i` is evaluated over the PREFIX
   * `ordered.slice(0, i + 1)`, so a later observation is not merely filtered out — it is not
   * in the array at all. The first points are `INSUFFICIENT_OBSERVATIONS` and stay visible;
   * no early point is fabricated and no absence is drawn as a zero.
   */
  const points = ordered.map((observation, position) => {
    const prefix = ordered.slice(0, position + 1);
    const at = computeRollingTailLoss(prefix, observation.closedAtMs);
    return {
      ordinal: count("performance.observation_ordinal", position + 1, asOf),
      at: instantValue("trade.exit_time", new Date(observation.closedAtMs).toISOString(), asOf),
      value: tailLossMetric(at, asOf),
    };
  });

  /*
   * THE TWO EXCLUSION REASONS ARE SEPARATED, because they are different facts about a record:
   * one was never written, the other was written as a zero. Both leave no denominator to
   * divide by, and neither becomes a zero observation.
   */
  const walked = ordered.slice(Math.max(0, ordered.length - result.walkedBack));
  const neverWritten = walked.filter(
    (observation) => observation.rMultipleHundredths === null,
  ).length;

  return {
    window: count("performance.rolling_lookback", TAIL_LOSS_PARAMETERS.windowObservations, asOf),
    minimum_observations: count(
      "performance.minimum_observations",
      TAIL_LOSS_PARAMETERS.minimumObservations,
      asOf,
    ),
    observation_unit: TAIL_LOSS_OBSERVATION_UNIT,
    population: demoReason("CLOSED_TRADES_OF_THIS_EXACT_VERSION_WITH_A_RISK_RECORD"),
    /** Each observation's own denominator — never a pooled one (§D1.7). */
    r_basis: demoReason("RETAINED_INITIAL_PLANNED_RISK_SUMMED_ACROSS_STAGES"),
    tail_fraction_hundredths: TAIL_LOSS_PARAMETERS.tailFractionHundredths,
    eligible_observations: count(
      "performance.observation_count",
      result.eligibleObservations,
      asOf,
    ),
    tail_observations: count("trade.count", result.tailObservations, asOf),
    excluded_observations: count("trade.count", result.excludedObservations, asOf),
    exclusions:
      neverWritten === 0
        ? []
        : [
            {
              reason: demoReason("INITIAL_PLANNED_RISK_RECORD_NEVER_WRITTEN"),
              count: count("trade.count", neverWritten, asOf),
            },
          ],
    value: tailLossMetric(result, asOf),
    points,
    tail_members: result.members.map((member) => ({
      trade_ref: demoRef(member.tradeId, "trade", "ENDPOINT"),
      at: instantValue("trade.exit_time", new Date(member.closedAtMs).toISOString(), asOf),
      r_multiple: scaled("r_multiple", "R_MULTIPLE", member.rMultipleHundredths, asOf),
    })),
    /**
     * The accepted limitation, carried with the value rather than left to a reader.
     *
     * Thirty is the count §12.3 declares sufficient for a mean over a WHOLE population; this
     * averages THREE, so one observation is a third of the estimate. It is descriptive of the
     * window it measured — no predictive reliability, no qualification, no threshold (§D1.12).
     */
    support_limitation: demoReason("A_THREE_OBSERVATION_TAIL_IS_A_DESCRIPTIVE_ESTIMATE"),
  };
}
