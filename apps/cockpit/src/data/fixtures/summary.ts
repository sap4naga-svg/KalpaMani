/**
 * The `PerformanceSummary` projection, over one defined population and one window.
 *
 * ONE BUILDER, USED BY BOTH SCREENS. The portfolio summary and every per-strategy and
 * per-slice summary come through here, so a ratio cannot be computed one way on the
 * portfolio page and another way on the strategy page. §12.2: "a screen that computes its
 * own variant of a metric is a screen reporting a different metric under the same name."
 *
 * THE POPULATION IS DEFINED BEFORE ANYTHING IS DIVIDED. §12.3 refuses an R-based figure for
 * any trade lacking `risk.initial_planned`, so the population is **closed trades in the
 * window that carry a recorded initial planned risk record**, and every trade the definition
 * excludes is counted and reason-coded rather than silently dropped.
 */
import type { PerformanceSummaryPayload } from "@/contracts/portfolio-models";

import type { BookTrade } from "./book";
import { centsToDecimal } from "./book";
import {
  count,
  demoReason,
  denominatorZero,
  insufficient,
  percent,
  scaled,
  usd,
  windowOf,
} from "./common";

/** The declared minimum observations of §12.3, transcribed. Each governs its own metric. */
export const OBSERVATION_MINIMUMS = {
  win_rate: 20,
  profit_factor: 20,
  "expectancy.currency": 30,
  sharpe: 60,
} as const;

/** The R buckets the distribution is reported over. Break-even has its own bucket. */
const R_BUCKETS = [
  { code: "R_AT_OR_BELOW_MINUS_1", test: (r: number) => r <= -100 },
  { code: "R_BETWEEN_MINUS_1_AND_0", test: (r: number) => r > -100 && r < 0 },
  { code: "R_EXACTLY_ZERO", test: (r: number) => r === 0 },
  { code: "R_BETWEEN_0_AND_1", test: (r: number) => r > 0 && r < 100 },
  { code: "R_BETWEEN_1_AND_2", test: (r: number) => r >= 100 && r < 200 },
  { code: "R_AT_OR_ABOVE_2", test: (r: number) => r >= 200 },
] as const;

/**
 * The annualization factor and the risk-free assumption a Sharpe is computed under.
 *
 * §12.3 requires both to be stated, along with the sample convention. They are constants
 * here and they are **presentation assumptions of a demonstration**, not governed values:
 * 252 sessions a year on the named calendar, and a zero risk-free rate.
 */
const ANNUALIZATION_SESSIONS = 252;
const RISK_FREE_RATE = 0;

export interface SummaryInputs {
  readonly days: readonly string[];
  readonly asOf: string;
  /** Closed trades whose exit falls inside the window. */
  readonly closed: readonly BookTrade[];
  /** Period returns over the window, in hundredths of a percent, one per session step. */
  readonly periodReturns: readonly number[];
  /** The window's chain-linked time-weighted return, in hundredths of a percent. */
  readonly totalReturnHundredths: number;
  /** The window's maximum drawdown, in hundredths of a percent. Never positive. */
  readonly maxDrawdownHundredths: number;
  /** The population's own name, so two summaries are never compared across populations. */
  readonly populationCode: string;
}

function sampleStdDev(values: readonly number[]): number | null {
  if (values.length < 2) {
    return null;
  }
  const mean = values.reduce((total, value) => total + value, 0) / values.length;
  const variance =
    values.reduce((total, value) => total + (value - mean) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

/**
 * Builds one summary.
 *
 * Every ratio is either computed over the defined population or returned as
 * `INSUFFICIENT_OBSERVATIONS` against its own declared minimum. Nothing is rounded up to a
 * number, and a zero denominator is `NOT_APPLICABLE` with `DENOMINATOR_ZERO` — **never
 * infinity, never a sentinel, never a large number**.
 */
export function buildPerformanceSummary(inputs: SummaryInputs): PerformanceSummaryPayload {
  const { asOf } = inputs;
  const excluded = inputs.closed.filter((trade) => !trade.initialRiskRecorded);
  const population = inputs.closed.filter((trade) => trade.initialRiskRecorded);
  const n = population.length;

  const winners = population.filter((trade) => trade.realizedCents > 0);
  const losers = population.filter((trade) => trade.realizedCents < 0);
  const grossProfit = winners.reduce((total, trade) => total + trade.realizedCents, 0);
  const grossLoss = losers.reduce((total, trade) => total - trade.realizedCents, 0);
  const netCents = population.reduce((total, trade) => total + trade.realizedCents, 0);

  const rules = [
    {
      metric_id: "win_rate",
      population: demoReason("CLOSED_TRADES_IN_WINDOW"),
      observed: count("performance.observation_count", n, asOf),
      minimum: count("performance.minimum_observations", OBSERVATION_MINIMUMS.win_rate, asOf),
      met: n >= OBSERVATION_MINIMUMS.win_rate,
    },
    {
      metric_id: "profit_factor",
      population: demoReason("CLOSED_TRADES_IN_WINDOW"),
      observed: count("performance.observation_count", n, asOf),
      minimum: count(
        "performance.minimum_observations",
        OBSERVATION_MINIMUMS.profit_factor,
        asOf,
      ),
      met: n >= OBSERVATION_MINIMUMS.profit_factor,
    },
    {
      metric_id: "expectancy.currency",
      population: demoReason("CLOSED_TRADES_IN_WINDOW"),
      observed: count("performance.observation_count", n, asOf),
      minimum: count(
        "performance.minimum_observations",
        OBSERVATION_MINIMUMS["expectancy.currency"],
        asOf,
      ),
      met: n >= OBSERVATION_MINIMUMS["expectancy.currency"],
    },
    {
      /** A DIFFERENT population: return periods, not trades. The two never substitute. */
      metric_id: "sharpe",
      population: demoReason("RETURN_PERIODS_IN_WINDOW"),
      observed: count("performance.observation_count", inputs.periodReturns.length, asOf),
      minimum: count("performance.minimum_observations", OBSERVATION_MINIMUMS.sharpe, asOf),
      met: inputs.periodReturns.length >= OBSERVATION_MINIMUMS.sharpe,
    },
  ];

  const winRateMet = rules[0].met;
  const profitFactorMet = rules[1].met;
  const expectancyMet = rules[2].met;
  const sharpeMet = rules[3].met;

  const stdev = sampleStdDev(inputs.periodReturns);
  const meanReturn =
    inputs.periodReturns.length === 0
      ? 0
      : inputs.periodReturns.reduce((total, value) => total + value, 0) /
        inputs.periodReturns.length;
  const sharpeValue =
    stdev === null || stdev === 0
      ? null
      : ((meanReturn - RISK_FREE_RATE) / stdev) * Math.sqrt(ANNUALIZATION_SESSIONS);

  const distribution = R_BUCKETS.map((bucket) => {
    const inBucket = population.filter((trade) => {
      const r = Math.round((trade.realizedCents * 100) / trade.initialRiskCents);
      return bucket.test(r);
    });
    return {
      bucket: demoReason(bucket.code),
      count: count("r_multiple.bucket_count", inBucket.length, asOf),
    };
  });

  return {
    window: windowOf(inputs.days),
    total_return: percent("return.time_weighted", inputs.totalReturnHundredths, asOf),
    max_drawdown: percent("drawdown.max", inputs.maxDrawdownHundredths, asOf),
    expectancy: expectancyMet
      ? usd("expectancy.currency", Math.round(netCents / n), asOf)
      : insufficient("expectancy.currency", "USD"),
    profit_factor:
      !profitFactorMet
        ? insufficient("profit_factor", "RATIO")
        : grossLoss === 0
          ? // A profit factor with zero gross loss is undefined, and is never an infinity.
            denominatorZero("profit_factor", "RATIO")
          : scaled("profit_factor", "RATIO", Math.round((grossProfit * 100) / grossLoss), asOf),
    win_rate: winRateMet
      ? scaled("win_rate", "RATIO", Math.round((winners.length * 100) / n), asOf)
      : insufficient("win_rate", "RATIO"),
    sharpe:
      sharpeMet && sharpeValue !== null
        ? scaled("sharpe", "DIMENSIONLESS", Math.round(sharpeValue * 100), asOf)
        : insufficient("sharpe", "DIMENSIONLESS"),
    average_winner:
      winners.length === 0
        ? denominatorZero("pnl.average_winner", "USD")
        : usd("pnl.average_winner", Math.round(grossProfit / winners.length), asOf),
    average_loser:
      losers.length === 0
        ? denominatorZero("pnl.average_loser", "USD")
        : usd("pnl.average_loser", Math.round(-grossLoss / losers.length), asOf),
    r_multiple_distribution: distribution,
    trade_population: demoReason(inputs.populationCode),
    minimum_observations_met: rules.every((rule) => rule.met),
    /**
     * Every economic figure in the book is net of the modelled commission and financing the
     * fixture applies once, at the trade level. Two summaries with different treatments are
     * never compared, so the treatment travels with the summary rather than with the screen.
     */
    cost_treatment: "NET_ALL_COSTS",
    observation_rules: rules,
    observation_count: count("performance.observation_count", n, asOf),
    exclusions:
      excluded.length === 0
        ? []
        : [
            {
              reason: demoReason("INITIAL_PLANNED_RISK_RECORD_NEVER_WRITTEN"),
              count: count("trade.count", excluded.length, asOf),
            },
          ],
  };
}

/** The R multiple of one closed trade, in hundredths, or `null` where there is no record. */
export function rMultipleHundredths(trade: BookTrade): number | null {
  if (!trade.initialRiskRecorded || trade.initialRiskCents === 0) {
    return null;
  }
  return Math.round(
    ((trade.realizedCents + trade.unrealizedCents) * 100) / trade.initialRiskCents,
  );
}

/** A decimal string for an R multiple, from its hundredths. */
export function rMultipleDecimal(hundredths: number): string {
  return centsToDecimal(hundredths);
}
