/**
 * The SYNTHETIC performance series.
 *
 * DETERMINISTIC AND REPOSITORY-OWNED. No provider row, no broker record, no real price and
 * no copied trade history appears here. NOTHING IN THIS FILE IS A RESULT — it exists so the
 * chart states have something to draw, and it is labelled `SYNTHETIC` at page, panel and
 * component level wherever it is shown.
 *
 * IT IS ARITHMETIC, NOT A SIMULATION. There is no model, no alpha and no claim that a
 * strategy would produce anything resembling this. A fixed seed and a fixed step function
 * generate a curve; that is the whole of it.
 *
 * EVERY NUMBER IS COMPUTED IN INTEGERS AND RENDERED AS A DECIMAL STRING. §4.2 requires
 * "decimal string, never binary floating point", and a series is where floating point does
 * the most damage: an equity curve accumulates, so a rounding error at one point is carried
 * by every point after it. Cents and hundredths-of-a-percent are exact in a `double` at these
 * magnitudes; the ratios that combine them are the only place rounding happens, and it
 * happens once per step rather than at render time.
 */
import type { PerformanceSeriesPayload } from "@/contracts/read-models";
import type { Series, SeriesPoint } from "@/contracts/values";
import { available, refListOf } from "@/contracts/factories";
import { reason } from "@/contracts/factories";
import type { PerformancePeriod } from "@/lib/scope";
import { PERIOD_TRADING_DAYS } from "@/lib/scope";

const DEMO = "kalpamani.demo";

/** The named market calendar. A date range without one is not a date range (§4.2). */
const CALENDAR = reason("XNYS_EQUITY_REGULAR_SESSION", DEMO);

/** The scale the time-weighted return index is carried at. Integer throughout. */
const INDEX_SCALE = 100_000_000;

/** A decimal string with exactly two places, built from an integer count of hundredths. */
function decimalFromHundredths(hundredths: number): string {
  const sign = hundredths < 0 ? "-" : "";
  const magnitude = Math.abs(hundredths);
  const whole = Math.floor(magnitude / 100);
  const fraction = magnitude % 100;
  return `${sign}${whole}.${String(fraction).padStart(2, "0")}`;
}

/**
 * A small deterministic step generator.
 *
 * A named LCG rather than `Math.random`, because a fixture that differs between runs cannot
 * be reviewed, screenshotted or asserted on. The constants are the well-known Numerical
 * Recipes ones; nothing about the choice is meaningful beyond "the same input gives the same
 * curve".
 */
function stepSequence(seed: number, count: number): number[] {
  const steps: number[] = [];
  let state = seed >>> 0;
  for (let index = 0; index < count; index += 1) {
    state = (Math.imul(state, 1_664_525) + 1_013_904_223) >>> 0;
    // A daily step in hundredths of a percent, roughly -90bp to +110bp, with a slight drift.
    steps.push((state % 201) - 90);
  }
  return steps;
}

/** The last `count` weekdays ending on or before `endMs`, oldest first. */
function tradingDays(endMs: number, count: number): string[] {
  const days: string[] = [];
  const cursor = new Date(endMs);
  cursor.setUTCHours(0, 0, 0, 0);
  while (days.length < count) {
    const weekday = cursor.getUTCDay();
    if (weekday !== 0 && weekday !== 6) {
      days.push(cursor.toISOString().slice(0, 10));
    }
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  return days.reverse();
}

function seriesOf(points: readonly SeriesPoint[], requested: number): Series {
  return {
    points: [...points],
    granularity: "DAILY",
    calendar: CALENDAR,
    timezone: "UTC",
    coverage: { present: points.length, requested },
    completeness: points.length === requested ? "COMPLETE" : "PARTIAL",
  };
}

export interface SyntheticPerformanceOptions {
  readonly period: PerformancePeriod;
  /** The session origin. The series ends on the trading day before it (T-1). */
  readonly originMs: number;
  readonly asOf: string;
  /**
   * Draws a gap into the series, so `PARTIAL` coverage is reachable from the demonstration
   * rather than only from a unit test. A missing interval is NEVER filled with a zero.
   */
  readonly withGap?: boolean;
}

/**
 * One internally consistent `PerformanceSeries`.
 *
 * The three series are ALIGNED by construction — one loop, one date list, one point per day —
 * so a reader comparing equity against drawdown at a point is comparing the same session.
 *
 * THE CASH FLOW IS THE INTERESTING PART. A deposit lands mid-window, and:
 *
 *   the EQUITY series steps up by it        -- that is what equity did
 *   the RETURN series does not              -- 4.5: "a deposit or withdrawal never appears
 *                                              in a return or profit series"
 *   the DRAWDOWN series sees no new peak    -- 12.3: the equity used for drawdown is
 *                                              cash-flow adjusted, so "a withdrawal that
 *                                              looked like a 20% loss" cannot happen
 *
 * All three follow from computing return and drawdown on the time-weighted INDEX, which is
 * chain-linked from `(equity - flow) / previous equity` and therefore ignores the flow.
 */
export function syntheticPerformanceSeries(
  options: SyntheticPerformanceOptions,
): PerformanceSeriesPayload {
  const requested = PERIOD_TRADING_DAYS[options.period];
  // T-1: a series ends at the last completed session, never at an in-progress one.
  const days = tradingDays(options.originMs - 86_400_000, requested);
  const steps = stepSequence(0x4b_41_4c_50, requested);

  /** One deposit, roughly a third of the way in, on a window long enough to show it. */
  const flowIndex = requested >= 21 ? Math.floor(requested / 3) : -1;
  const flowCents = 5_000_00;

  let equityCents = 80_000_00;
  let indexValue = INDEX_SCALE;
  let peakIndex = INDEX_SCALE;

  const equityPoints: SeriesPoint[] = [];
  const returnPoints: SeriesPoint[] = [];
  const drawdownPoints: SeriesPoint[] = [];
  const cashFlows: PerformanceSeriesPayload["cash_flows"] = [];

  days.forEach((day, index) => {
    const previousEquity = equityCents;
    if (index > 0) {
      // The market move, in hundredths of a percent, applied to the previous equity.
      equityCents = Math.round((equityCents * (10_000 + steps[index])) / 10_000);
    }
    const flow = index === flowIndex ? flowCents : 0;
    if (flow !== 0) {
      equityCents += flow;
      cashFlows.push({
        at: `${day}T21:00:00.000Z`,
        amount: {
          amount: decimalFromHundredths(flow),
          currency: "USD",
          sign_convention: "INFLOW_POSITIVE_OUTFLOW_NEGATIVE",
        },
        kind: "DEPOSIT",
      });
    }
    if (index > 0) {
      /*
       * The chain-link that makes the flow invisible to return and drawdown: the numerator
       * removes the flow, so a deposit contributes no return and creates no new peak.
       */
      indexValue = Math.round((indexValue * (equityCents - flow)) / previousEquity);
      peakIndex = Math.max(peakIndex, indexValue);
    }

    // A gap is a MISSING POINT, never a zero. The series reports PARTIAL coverage for it.
    if (options.withGap === true && index > 0 && index % 7 === 0) {
      return;
    }

    equityPoints.push({
      t: day,
      v: available({
        metricId: "portfolio.equity",
        unit: "USD",
        value: decimalFromHundredths(equityCents),
        asOf: options.asOf,
      }),
    });
    returnPoints.push({
      t: day,
      v: available({
        metricId: "return.time_weighted",
        unit: "PERCENT",
        value: decimalFromHundredths(
          Math.round(((indexValue - INDEX_SCALE) * 10_000) / INDEX_SCALE),
        ),
        asOf: options.asOf,
      }),
    });
    drawdownPoints.push({
      t: day,
      v: available({
        metricId: "drawdown.current",
        unit: "PERCENT",
        // equity / running_peak - 1, on the cash-flow-adjusted index. Never positive.
        value: decimalFromHundredths(Math.round(((indexValue - peakIndex) * 10_000) / peakIndex)),
        asOf: options.asOf,
      }),
    });
  });

  const benchmarkPoints: SeriesPoint[] = equityPoints.map((point, index) => ({
    t: point.t,
    v: available({
      metricId: "benchmark.return",
      unit: "PERCENT",
      // A separate, flatter curve. Drawn as its OWN line, never spliced into the portfolio's.
      value: decimalFromHundredths(Math.round(index * 3.5)),
      asOf: options.asOf,
    }),
  }));

  const benchmarkRef = {
    ref_id: "demo-benchmark-broad-market",
    ref_kind: "benchmark_series",
    resolution: "EMBEDDED" as const,
    classification: "PUBLIC_SAFE" as const,
  };

  return {
    series_id: `demo-performance-${options.period.toLowerCase()}`,
    granularity: "DAILY",
    calendar: CALENDAR,
    window: {
      from: `${days[0]}T00:00:00.000Z`,
      to: `${days[days.length - 1]}T21:00:00.000Z`,
      calendar: CALENDAR,
      timezone: "UTC",
    },
    equity: seriesOf(equityPoints, requested),
    return_series: seriesOf(returnPoints, requested),
    drawdown_series: seriesOf(drawdownPoints, requested),
    drawdown_basis: "CLOSE_ONLY",
    cash_flows: cashFlows,
    /** Stated, because two summaries with different treatments are never compared (§4.5). */
    cost_treatment: "NET_ALL_COSTS",
    benchmark_refs: refListOf([benchmarkRef], "ZERO_OR_ONE", options.asOf),
    benchmark_series: seriesOf(benchmarkPoints, requested),
    benchmark_label: reason("DEMONSTRATION_BROAD_MARKET_INDEX", DEMO),
  };
}
