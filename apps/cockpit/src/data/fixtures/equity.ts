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
