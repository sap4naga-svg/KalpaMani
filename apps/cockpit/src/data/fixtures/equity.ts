/**
 * The equity, return and drawdown arithmetic, over the demonstration book.
 *
 * ONE PLACE, because three screens read these numbers and a second implementation is a second
 * answer. The portfolio performance page, the executive overview's chart and every
 * `PerformanceSummary` in the application take their window return and their maximum drawdown
 * from here.
 *
 * THE CASH FLOW IS THE INTERESTING PART, and it behaves exactly as §4.5 and §12.3 require:
 *
 *   the EQUITY series steps up by it        -- that is what equity did
 *   the RETURN series does not              -- "a deposit or withdrawal never appears in a
 *                                              return or profit series"
 *   the DRAWDOWN series sees no new peak    -- the equity used for drawdown is cash-flow
 *                                              adjusted, so "a withdrawal that looked like a
 *                                              20% loss" cannot happen
 *
 * All three follow from chain-linking the index on `(equity - flow) / previous equity`, which
 * is `return.time_weighted` as §12.3 defines it: the product of flow-free sub-period returns.
 */
import { PERIOD_TRADING_DAYS, type PerformancePeriod, type ScopeGranularity } from "@/lib/scope";

import { BOOK, bookSessions, SESSION_COUNT } from "./book";

/** The scale the time-weighted index is carried at. Integer throughout. */
const INDEX_SCALE = 100_000_000;

export interface WindowFlow {
  readonly day: string;
  readonly amountCents: number;
  readonly kind: "DEPOSIT" | "WITHDRAWAL";
}

export interface EquityWindow {
  /** The daily sessions in the window, oldest first. */
  readonly days: readonly string[];
  readonly equityCents: readonly number[];
  /** Chain-linked time-weighted return since the window opened, in hundredths of a percent. */
  readonly returnHundredths: readonly number[];
  /** `equity / running_peak - 1` on the adjusted index, in hundredths. Never positive. */
  readonly drawdownHundredths: readonly number[];
  /** Per-session simple returns of the adjusted index, as plain ratios. */
  readonly periodReturns: readonly number[];
  readonly cashFlows: readonly WindowFlow[];
  readonly totalReturnHundredths: number;
  readonly maxDrawdownHundredths: number;
}

/**
 * The window's daily equity, return and drawdown.
 *
 * The window is the last `PERIOD_TRADING_DAYS[period]` sessions of the retained extent, and
 * the index restarts at the window's first session — a one-month return is the return over
 * that month, not a slice of a two-year curve.
 */
export function equityWindow(originMs: number, period: PerformancePeriod): EquityWindow {
  const requested = PERIOD_TRADING_DAYS[period];
  const allDays = bookSessions(originMs);
  const start = SESSION_COUNT - requested;
  const days = allDays.slice(start);
  const equityCents = BOOK.equityCents.slice(start);

  const flowBySession = new Map(
    BOOK.cashFlows.map((flow) => [flow.session, flow] as const),
  );
  const cashFlows: WindowFlow[] = [];

  let index = INDEX_SCALE;
  let peak = INDEX_SCALE;
  const returnHundredths: number[] = [];
  const drawdownHundredths: number[] = [];
  const periodReturns: number[] = [];

  for (let step = 0; step < days.length; step += 1) {
    const session = start + step;
    const flow = flowBySession.get(session);
    if (flow !== undefined) {
      cashFlows.push({
        day: days[step],
        amountCents: flow.amountCents,
        kind: flow.kind,
      });
    }
    if (step > 0) {
      const previous = equityCents[step - 1];
      const flowCents = flow?.amountCents ?? 0;
      /*
       * The chain-link that makes a flow invisible to return and drawdown: the numerator
       * removes the flow, so a deposit contributes no return and creates no new peak.
       */
      const nextIndex = Math.round((index * (equityCents[step] - flowCents)) / previous);
      periodReturns.push(nextIndex / index - 1);
      index = nextIndex;
      peak = Math.max(peak, index);
    }
    returnHundredths.push(Math.round(((index - INDEX_SCALE) * 10_000) / INDEX_SCALE));
    drawdownHundredths.push(Math.round(((index - peak) * 10_000) / peak));
  }

  return {
    days,
    equityCents,
    returnHundredths,
    drawdownHundredths,
    periodReturns,
    cashFlows,
    totalReturnHundredths: returnHundredths[returnHundredths.length - 1] ?? 0,
    maxDrawdownHundredths: Math.min(0, ...drawdownHundredths),
  };
}

/**
 * The session indices a granularity samples the window at.
 *
 * Weekly and monthly are **samples of the same index at period boundaries**, not different
 * measurements: the last completed session of each ISO week or calendar month, plus the
 * window's own last session so the series ends where the window ends. Nothing is
 * interpolated, and no period is invented for a week the book has no session in.
 */
export function granularitySamples(
  days: readonly string[],
  granularity: ScopeGranularity,
): number[] {
  if (granularity === "DAILY") {
    return days.map((_, index) => index);
  }
  const keyOf = (day: string): string =>
    granularity === "MONTHLY" ? day.slice(0, 7) : isoWeekKey(day);
  const samples: number[] = [];
  for (let index = 0; index < days.length; index += 1) {
    const last = index === days.length - 1 || keyOf(days[index + 1]) !== keyOf(days[index]);
    if (last) {
      samples.push(index);
    }
  }
  return samples;
}

/** The ISO week a session belongs to, as a sortable `YYYY-Www` key. */
function isoWeekKey(day: string): string {
  const date = new Date(`${day}T00:00:00.000Z`);
  const weekday = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - weekday + 3);
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const firstWeekday = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstWeekday + 3);
  const week =
    1 + Math.round((date.getTime() - firstThursday.getTime()) / (7 * 86_400_000));
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

/* ------------------------------------------- added by the C5 completion follow-up */

/**
 * The lookbacks a rolling window is offered over.
 *
 * NO NUMBER IS INVENTED HERE. These are the trading-day counts `PERIOD_TRADING_DAYS`
 * already carries for one month, three months and six months — repository-owned constants
 * that were reviewed when the period selector was accepted. What changes is what they COUNT:
 * a lookback counts PERIODS OF THE SERVED GRANULARITY, so twenty-one periods of a monthly
 * series are twenty-one months, and the interface says so rather than calling it "1M".
 */
export const ROLLING_LOOKBACKS = [21, 63, 126] as const;
export type RollingLookback = (typeof ROLLING_LOOKBACKS)[number];

/** What one rolling point is: a value, or the exact reason there is none. */
export type RollingOutcome =
  | { readonly kind: "VALUE"; readonly hundredths: number }
  /** Fewer than `lookback` earlier observations exist in the served extent. */
  | { readonly kind: "BELOW_MINIMUM" }
  /** The trailing window's requested extent has a session that carries no observation. */
  | { readonly kind: "EXTENT_GAPPED" };

export interface RollingWindowValues {
  readonly lookback: number;
  readonly returns: readonly RollingOutcome[];
  readonly drawdowns: readonly RollingOutcome[];
}

/**
 * The rolling return and rolling maximum drawdown at every carried point.
 *
 * THREE RULES, AND EACH ONE IS A THING THIS MUST NOT DO.
 *
 *   NO POINT LOOKS FORWARD          the window ending at ordinal `i` reads `i - lookback`
 *                                   through `i` and nothing later. Appending an observation
 *                                   changes no earlier point, which is asserted rather than
 *                                   asserted about
 *   A SHORT WINDOW IS NOT A WINDOW  fewer than `lookback` earlier observations reports
 *                                   `BELOW_MINIMUM` — never a shorter window quietly
 *                                   substituted, and never a zero
 *   A GAP IS NOT AN OBSERVATION     if the trailing window's requested sessions include one
 *                                   that carries no observation, the metric over that window
 *                                   is UNAVAILABLE. It is not computed from the surviving
 *                                   points, because that would be a different window wearing
 *                                   this one's label
 *
 * `carried` holds, for each carried point, its ordinal in the REQUESTED sample list — which
 * is how a gap is detected at all: consecutive carried points whose requested ordinals differ
 * by more than one have a missing observation between them.
 */
export function rollingWindowValues(
  indexReadings: readonly number[],
  carriedOrdinals: readonly number[],
  lookback: number,
): RollingWindowValues {
  const returns: RollingOutcome[] = [];
  const drawdowns: RollingOutcome[] = [];

  for (let position = 0; position < indexReadings.length; position += 1) {
    const start = position - lookback;
    if (start < 0) {
      returns.push({ kind: "BELOW_MINIMUM" });
      drawdowns.push({ kind: "BELOW_MINIMUM" });
      continue;
    }
    /*
     * The window spans `lookback` steps of the REQUESTED extent, so it is intact only when
     * the carried ordinals across it advance by exactly one each time.
     */
    const spanned = carriedOrdinals[position] - carriedOrdinals[start];
    if (spanned !== lookback) {
      returns.push({ kind: "EXTENT_GAPPED" });
      drawdowns.push({ kind: "EXTENT_GAPPED" });
      continue;
    }
    /*
     * `(1 + r_now) / (1 + r_then) - 1`, in hundredths of a percent, from the two index
     * readings — the SAME chain-link `return.time_weighted` is defined by, applied to one
     * trailing sub-window instead of to the whole one.
     */
    const now = 10_000 + indexReadings[position];
    const then = 10_000 + indexReadings[start];
    returns.push({
      kind: "VALUE",
      hundredths: Math.round((now * 10_000) / then - 10_000),
    });
    /*
     * The maximum drawdown INSIDE the trailing window: the peak is the running peak of the
     * window's own readings, never the whole series' peak. That is what makes this a
     * different metric from `drawdown.max`, and why it carries a different identifier.
     */
    let peak = 10_000 + indexReadings[start];
    let worst = 0;
    for (let step = start; step <= position; step += 1) {
      const reading = 10_000 + indexReadings[step];
      peak = Math.max(peak, reading);
      worst = Math.min(worst, Math.round((reading * 10_000) / peak - 10_000));
    }
    drawdowns.push({ kind: "VALUE", hundredths: worst });
  }

  return { lookback, returns, drawdowns };
}

/**
 * A series rebased to 100 at its first point, in hundredths.
 *
 * A NORMALIZATION, NOT A RETURN. `10_000` is 100.00, and a reading of `10_150` is an arm
 * that has moved 1.5% since the common start. Both arms go through this one function, so
 * neither can be rebased on a basis the other was not.
 */
export function rebasedToHundred(cumulativeHundredths: readonly number[]): number[] {
  const base = 10_000 + (cumulativeHundredths[0] ?? 0);
  return cumulativeHundredths.map((reading) =>
    Math.round(((10_000 + reading) * 1_000_000) / base / 100),
  );
}

/**
 * The movement of a cumulative-return arm between its first and last common observations.
 *
 * `(1 + r_last) / (1 + r_first) - 1`, in hundredths — the arm's own return over EXACTLY the
 * common boundaries, which is what §12.4 requires of a benchmark and what makes the two arms
 * measurable over one window rather than over two.
 */
export function movementOver(cumulativeHundredths: readonly number[]): number | null {
  if (cumulativeHundredths.length < 2) {
    return null;
  }
  const first = 10_000 + cumulativeHundredths[0];
  const last = 10_000 + cumulativeHundredths[cumulativeHundredths.length - 1];
  return Math.round((last * 10_000) / first - 10_000);
}
