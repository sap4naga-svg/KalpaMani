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
import type { PerformanceSeriesPayload } from "@/contracts/read-models";
import type { Series, SeriesPoint } from "@/contracts/values";
import { available } from "@/contracts/factories";
import type { PerformancePeriod, ScopeGranularity } from "@/lib/scope";

import { centsToDecimal } from "./book";
import { CALENDAR, demoRef, demoReason, refListOf, sessionInstant, windowOf } from "./common";
import { equityWindow, granularitySamples } from "./equity";

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
    benchmarkPoints.push({
      t: day,
      v: available({
        metricId: "benchmark.return",
        unit: "PERCENT",
        /*
         * A SEPARATE, FLATTER CURVE, AND AN OBVIOUSLY INVENTED ONE. It is drawn as its OWN
         * line and is never spliced into the portfolio's. It is not SPY, QQQ or IWM, and it
         * is not a claim about any real index.
         */
        value: centsToDecimal(Math.round(ordinal * 3.5)),
        asOf: options.asOf,
      }),
    });
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
  };
}
