/**
 * The SYNTHETIC `PerformanceSeries`, projected from the demonstration book.
 *
 * DETERMINISTIC AND REPOSITORY-OWNED. No provider row, no broker record, no real price and
 * no copied trade history appears here. NOTHING IN THIS FILE IS A RESULT — it exists so the
 * chart states have something to draw, and it is labelled `SYNTHETIC` at page, panel and
 * component level wherever it is shown.
 *
 * **THE CURVE IS DERIVED FROM THE LEDGER, NOT INVENTED BESIDE IT.** Equity at each session is
 * `strategy capital + realized to date + open unrealized + external flows`, read from the
 * same book the positions, trades, exposure and strategy screens are projected from. That is
 * why the equity curve, the trade ledger and the position table cannot disagree: there is one
 * set of numbers and several projections of it.
 *
 * EVERY NUMBER IS COMPUTED IN INTEGERS AND RENDERED AS A DECIMAL STRING. §4.2 requires
 * "decimal string, never binary floating point", and a series is where floating point does
 * the most damage: an equity curve accumulates, so a rounding error at one point is carried
 * by every point after it.
 */
import type {
  BenchmarkComparison,
  PerformanceSeriesPayload,
  RollingWindow,
} from "@/contracts/read-models";
import type { MetricValue, Series, SeriesPoint } from "@/contracts/values";
import { available } from "@/contracts/factories";
import type { PerformancePeriod, ScopeGranularity } from "@/lib/scope";

import { centsToDecimal } from "./book";
import {
  CALENDAR,
  count,
  demoRef,
  demoReason,
  insufficient,
  percent,
  refListOf,
  sessionInstant,
  unavailable,
  windowOf,
} from "./common";
import {
  equityWindow,
  granularitySamples,
  movementOver,
  rebasedToHundred,
  ROLLING_LOOKBACKS,
  rollingWindowValues,
  type RollingOutcome,
} from "./equity";

function seriesOf(
  points: readonly SeriesPoint[],
  requested: number,
  granularity: ScopeGranularity,
): Series {
  return {
    points: [...points],
    granularity,
    calendar: CALENDAR,
    timezone: "UTC",
    coverage: { present: points.length, requested },
    completeness: points.length === requested ? "COMPLETE" : "PARTIAL",
  };
}

export interface SyntheticPerformanceOptions {
  readonly period: PerformancePeriod;
  readonly granularity: ScopeGranularity;
  /** The session origin. The series ends on the trading day before it (T−1). */
  readonly originMs: number;
  readonly asOf: string;
  /**
   * Draws a gap into the series, so `PARTIAL` coverage is reachable from the demonstration
   * rather than only from a unit test. A missing interval is NEVER filled with a zero.
   */
  readonly withGap?: boolean;
}

/**
 * The three benchmark references Area 2 names.
 *
 * **They resolve to nothing, and that is the correct answer.** No market-data provider is
 * selected, **G1 is OPEN**, and this application holds no SPY, QQQ or IWM price. Carrying a
 * synthetic curve under one of those names would be a claim about a real index, so the
 * references are carried as `UNRESOLVABLE_V1` — the join is specified, the producer does not
 * exist, and the reference resolves to an availability state rather than to a payload (§4.3).
 */
const NAMED_BENCHMARKS = [
  demoRef("benchmark-broad-market-large-cap", "benchmark_series"),
  demoRef("benchmark-growth-large-cap", "benchmark_series"),
  demoRef("benchmark-broad-market-small-cap", "benchmark_series"),
];


/* ------------------------------------------- added by the C5 completion follow-up */

/**
 * One rolling point's `MetricValue`.
 *
 * THE THREE OUTCOMES ARE THREE DIFFERENT ANSWERS, and they are never collapsed:
 *
 *   a value                    the window is intact and the metric is computed over it
 *   BELOW_MINIMUM_OBSERVATIONS the served extent does not reach back far enough YET
 *   UPSTREAM_INPUT_MISSING     it reaches back far enough, and a session inside the window
 *                              carries no observation, so an input the window declares was
 *                              absent and the metric over THAT window has no value. It is
 *                              not computed from the surviving points
 *
 * WHY NOT `EXTENT_PARTIALLY_COVERED`: the §4.1.1 matrix admits that reason only under
 * `PARTIAL`, which is VALUE-BEARING and therefore requires a value. A rolling window that
 * spans an unobserved session has no value to carry, so the pairing would be invalid — and
 * `PARTIAL` with a number would report a window that was never observed as one that was.
 * The series ITSELF still reports its coverage, which is where partial extent belongs.
 *
 * A ZERO IS NONE OF THEM. §12.1: "a missing input yields an availability state and its
 * reason code, never a zero."
 */
function rollingPoint(metricId: string, outcome: RollingOutcome, asOf: string): MetricValue {
  if (outcome.kind === "VALUE") {
    return percent(metricId, outcome.hundredths, asOf);
  }
  if (outcome.kind === "BELOW_MINIMUM") {
    return insufficient(metricId, "PERCENT");
  }
  return unavailable(metricId, "PERCENT", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING");
}

/**
 * The rolling windows Area 2 names, over one already-built sample list.
 *
 * IT ROLLS OVER WHAT WAS SERVED, and that is the point of the whole panel: the requested
 * period is the extent, the lookback is how far each point looks back INSIDE it, and the two
 * are different numbers that a reader must never have to guess between. A three-month extent
 * carrying a 126-period lookback reports `INSUFFICIENT_OBSERVATIONS` at every point, and
 * that is the correct answer to what was asked rather than a defect to be smoothed over.
 */
function buildRollingWindows(
  indexReadings: readonly number[],
  carriedOrdinals: readonly number[],
  days: readonly string[],
  requested: number,
  granularity: ScopeGranularity,
  asOf: string,
): RollingWindow[] {
  return ROLLING_LOOKBACKS.map((lookback) => {
    const values = rollingWindowValues(indexReadings, carriedOrdinals, lookback);
    const returnPoints: SeriesPoint[] = days.map((day, position) => ({
      t: day,
      v: rollingPoint("return.rolling", values.returns[position], asOf),
    }));
    const drawdownPoints: SeriesPoint[] = days.map((day, position) => ({
      t: day,
      v: rollingPoint("drawdown.rolling_max", values.drawdowns[position], asOf),
    }));
    return {
      lookback: count("performance.rolling_lookback", lookback, asOf),
      minimum_observations: count("performance.minimum_observations", lookback, asOf),
      observation_unit: "SERIES_PERIOD" as const,
      population: demoReason("SERIES_PERIODS_AT_THE_SERVED_GRANULARITY"),
      return_series: seriesOf(returnPoints, requested, granularity),
      drawdown_series: seriesOf(drawdownPoints, requested, granularity),
    };
  });
}

/**
 * The portfolio benchmark comparison.
 *
 * WHAT IS COMPARED, AND WHAT IS REFUSED.
 *
 * Both arms are aligned to the instants they BOTH carry, rebased to 100 at the first of
 * them, and reported with their own movement over exactly those boundaries — which is what
 * §12.4 asks of a benchmark: "aligned to the **exact** boundaries the subject used".
 *
 * THE DIFFERENCE IS REFUSED, ON PURPOSE, AND IT IS NOT AN OVERSIGHT. The portfolio arm is
 * `NET_ALL_COSTS`; the demonstration index is an invented curve with no costs in it at all,
 * so it is `GROSS`. §12.3: "two values with different cost treatments are never compared,
 * summed or placed in one series". Nothing about the arithmetic prevents the subtraction;
 * what prevents it is that the result would mean nothing, and a screen that prints it
 * teaches a reader that it does. The refusal follows the merged `MissedOpportunity`
 * precedent exactly: `comparable: false`, a named refusal, and no value.
 *
 * IT IS NOT ALPHA, AND IT IS NOT EVIDENCE. No metric in this dictionary defines alpha, the
 * index is repository-owned and invented, and comparing against it establishes nothing about
 * any strategy.
 */
function buildBenchmarkComparison(
  days: readonly string[],
  portfolioCumulative: readonly number[],
  benchmarkCumulative: readonly number[],
  granularity: ScopeGranularity,
  label: ReturnType<typeof demoReason>,
  asOf: string,
): BenchmarkComparison {
  const rebasedPortfolio = rebasedToHundred(portfolioCumulative);
  const rebasedBenchmark = rebasedToHundred(benchmarkCumulative);
  const observations = days.length;
  const portfolioMovement = movementOver(portfolioCumulative);
  const benchmarkMovement = movementOver(benchmarkCumulative);

  const arm = (values: readonly number[]): Series =>
    seriesOf(
      days.map((day, index) => ({
        t: day,
        v: available({
          metricId: "comparison.rebased_index",
          unit: "DIMENSIONLESS",
          value: centsToDecimal(values[index]),
          asOf,
        }),
      })),
      observations,
      granularity,
    );

  return {
    benchmark_label: label,
    common_window: windowOf(days),
    common_observations: count("performance.observation_count", observations, asOf),
    /*
     * §12.3 gives `benchmark.movement` a two-point minimum. The portfolio arm is the same
     * question asked of the portfolio, so it is held to the same rule rather than to a
     * looser one that happens to be satisfiable.
     */
    portfolio_movement:
      portfolioMovement === null
        ? insufficient("return.time_weighted", "PERCENT")
        : percent("return.time_weighted", portfolioMovement, asOf),
    benchmark_movement:
      benchmarkMovement === null
        ? insufficient("benchmark.movement", "PERCENT")
        : percent("benchmark.movement", benchmarkMovement, asOf),
    /** Neither the index nor the demonstration securities pay a dividend. */
    portfolio_basis: "PRICE_RETURN" as const,
    benchmark_basis: "PRICE_RETURN" as const,
    portfolio_cost_treatment: "NET_ALL_COSTS" as const,
    benchmark_cost_treatment: "GROSS" as const,
    portfolio_series: arm(rebasedPortfolio),
    benchmark_series: arm(rebasedBenchmark),
    /** Stated ON the comparison, so they travel with it wherever it is drawn. */
    comparability_limits: [
      demoReason("THE_BENCHMARK_IS_A_REPOSITORY_OWNED_INVENTED_CURVE_NOT_A_MARKET_INDEX"),
      demoReason("THE_ARMS_DIFFER_IN_COST_TREATMENT_NET_ALL_COSTS_AGAINST_GROSS"),
      demoReason("BOTH_ARMS_ARE_PRICE_RETURN_AND_NEITHER_CARRIES_A_DIVIDEND"),
      demoReason("THE_COMPARISON_COVERS_ONLY_THE_INSTANTS_BOTH_ARMS_OBSERVED"),
      demoReason("A_SYNTHETIC_COMPARISON_ESTABLISHES_NOTHING_ABOUT_ANY_STRATEGY"),
    ],
    comparable: false,
    refusal: demoReason("ARMS_DIFFER_IN_COST_TREATMENT"),
    difference: unavailable(
      "return.time_weighted",
      "PERCENT",
      "NOT_APPLICABLE",
      "NOT_DEFINED_FOR_SUBJECT",
    ),
  };
}

/**
 * One internally consistent `PerformanceSeries`.
 *
 * The three series are ALIGNED by construction — one sample list, one point per sampled
 * session — so a reader comparing equity against drawdown at a point is comparing the same
 * period.
 */
export function syntheticPerformanceSeries(
  options: SyntheticPerformanceOptions,
): PerformanceSeriesPayload {
  const window = equityWindow(options.originMs, options.period);
  const samples = granularitySamples(window.days, options.granularity);
  const requested = samples.length;

  const equityPoints: SeriesPoint[] = [];
  const returnPoints: SeriesPoint[] = [];
  const periodReturnPoints: SeriesPoint[] = [];
  const drawdownPoints: SeriesPoint[] = [];
  const benchmarkPoints: SeriesPoint[] = [];
  /** The cumulative reading at the previous SAMPLE, for the per-period return. */
  let previousCumulative = 0;
  /*
   * WHAT THE ROLLING WINDOWS AND THE COMPARISON ROLL OVER: the observations actually
   * CARRIED, and the ordinal each one occupies in the requested sample list.
   *
   * The ordinals are what make a gap detectable. Two carried points whose ordinals differ by
   * more than one have a missing observation between them, and a rolling window that spans
   * one is refused rather than computed from the survivors.
   */
  const carriedDays: string[] = [];
  const carriedOrdinals: number[] = [];
  const carriedCumulative: number[] = [];
  const carriedBenchmark: number[] = [];

  /*
   * A SAMPLED DRAWDOWN IS A DRAWDOWN OF THE SAMPLED CLOSES.
   *
   * The daily peak is not carried into a monthly series: a monthly close-only drawdown is
   * measured against the running peak of monthly closes, which is what `drawdown_basis`
   * states. Reporting the daily figure on a monthly axis would report a low the monthly
   * series never shows.
   */
  let peakReturn = window.returnHundredths[samples[0] ?? 0] ?? 0;

  samples.forEach((sessionIndex, ordinal) => {
    const day = window.days[sessionIndex];
    const returnHundredths = window.returnHundredths[sessionIndex];
    peakReturn = Math.max(peakReturn, returnHundredths);
    /*
     * `(1 + r) / (1 + peak) - 1` in hundredths of a percent, from the two index readings the
     * window already carries. It is never positive, because `peak` is a running maximum.
     */
    const drawdown = Math.min(
      0,
      Math.round(((10_000 + returnHundredths) * 10_000) / (10_000 + peakReturn) - 10_000),
    );
    // A gap is a MISSING POINT, never a zero. The series reports PARTIAL coverage for it.
    if (options.withGap === true && ordinal > 0 && ordinal % 7 === 0) {
      return;
    }
    equityPoints.push({
      t: day,
      v: available({
        metricId: "portfolio.equity",
        unit: "USD",
        value: centsToDecimal(window.equityCents[sessionIndex]),
        asOf: options.asOf,
      }),
    });
    returnPoints.push({
      t: day,
      v: available({
        metricId: "return.time_weighted",
        unit: "PERCENT",
        value: centsToDecimal(returnHundredths),
        asOf: options.asOf,
      }),
    });
    /*
     * `(1 + cumulative) / (1 + previous cumulative) - 1`, in hundredths of a percent.
     *
     * The first sampled period has no earlier sample to chain from, so its own return IS the
     * cumulative reading — which is what a chain-link of one sub-period is.
     */
    periodReturnPoints.push({
      t: day,
      v: available({
        metricId: "return.period",
        unit: "PERCENT",
        value: centsToDecimal(
          Math.round(
            ((10_000 + returnHundredths) * 10_000) / (10_000 + previousCumulative) - 10_000,
          ),
        ),
        asOf: options.asOf,
      }),
    });
    previousCumulative = returnHundredths;
    drawdownPoints.push({
      t: day,
      v: available({
        metricId: "drawdown.current",
        unit: "PERCENT",
        value: centsToDecimal(drawdown),
        asOf: options.asOf,
      }),
    });
    /*
     * A SEPARATE, FLATTER CURVE, AND AN OBVIOUSLY INVENTED ONE. It is drawn as its OWN line
     * and is never spliced into the portfolio's. It is not SPY, QQQ or IWM, and it is not a
     * claim about any real index. Hoisted out of the push below because the comparison needs
     * the same reading, and deriving it twice is two chances to derive it differently.
     */
    const benchmarkCumulative = Math.round(ordinal * 3.5);
    benchmarkPoints.push({
      t: day,
      v: available({
        metricId: "benchmark.return",
        unit: "PERCENT",
        value: centsToDecimal(benchmarkCumulative),
        asOf: options.asOf,
      }),
    });
    carriedDays.push(day);
    carriedOrdinals.push(ordinal);
    carriedCumulative.push(returnHundredths);
    carriedBenchmark.push(benchmarkCumulative);
  });

  return {
    series_id: `demo-performance-${options.period.toLowerCase()}-${options.granularity.toLowerCase()}`,
    granularity: options.granularity,
    calendar: CALENDAR,
    window: windowOf(window.days),
    equity: seriesOf(equityPoints, requested, options.granularity),
    return_series: seriesOf(returnPoints, requested, options.granularity),
    period_return_series: seriesOf(periodReturnPoints, requested, options.granularity),
    drawdown_series: seriesOf(drawdownPoints, requested, options.granularity),
    drawdown_basis: "CLOSE_ONLY",
    cash_flows: window.cashFlows.map((flow) => ({
      at: sessionInstant(flow.day),
      amount: {
        amount: centsToDecimal(
          flow.kind === "WITHDRAWAL" ? -flow.amountCents : flow.amountCents,
        ),
        currency: "USD" as const,
        sign_convention: "INFLOW_POSITIVE_OUTFLOW_NEGATIVE" as const,
      },
      kind: flow.kind,
    })),
    /** Stated, because two summaries with different treatments are never compared (§4.5). */
    cost_treatment: "NET_ALL_COSTS",
    benchmark_refs: refListOf(NAMED_BENCHMARKS, "ZERO_OR_MORE", options.asOf),
    benchmark_series: seriesOf(benchmarkPoints, requested, options.granularity),
    benchmark_label: demoReason("DEMONSTRATION_BROAD_MARKET_INDEX"),
    rolling_windows: buildRollingWindows(
      carriedCumulative,
      carriedOrdinals,
      carriedDays,
      requested,
      options.granularity,
      options.asOf,
    ),
    benchmark_comparison:
      /*
       * §12.3 gives `benchmark.movement` a two-point minimum, and a comparison of one
       * observation is not a comparison. Below it the block is OMITTED rather than served
       * with a hollow shell, and the panel says the extent was too short to compare over.
       */
      carriedDays.length < 2
        ? undefined
        : buildBenchmarkComparison(
            carriedDays,
            carriedCumulative,
            carriedBenchmark,
            options.granularity,
            demoReason("DEMONSTRATION_BROAD_MARKET_INDEX"),
            options.asOf,
          ),
  };
}
