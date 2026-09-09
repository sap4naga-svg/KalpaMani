import { describe, expect, it } from "vitest";

import { performanceSeriesEnvelope, PERFORMANCE_SERIES_SCHEMA } from "@/contracts/read-models";
import {
  strategyPerformanceEnvelope,
  STRATEGY_PERFORMANCE_SCHEMA,
} from "@/contracts/strategy-models";
import { C3_METRIC_DICTIONARY } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { BOOK, bookSessions } from "@/data/fixtures/book";
import {
  movementOver,
  rebasedToHundred,
  ROLLING_LOOKBACKS,
  rollingWindowValues,
} from "@/data/fixtures/equity";
import { buildPerformanceSummary, OBSERVATION_MINIMUMS } from "@/data/fixtures/summary";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

/**
 * The C5 completion follow-up — rolling windows, the portfolio benchmark comparison and the
 * capacity disposition.
 *
 * EVERY EXPECTED VALUE IS COMPUTED INDEPENDENTLY, and most of them are small enough to be
 * computed by hand. A test that calls the same helper the fixture called would agree with the
 * fixture whatever the fixture did; these recompute the arithmetic from readings written out
 * in the test, so a defect in the projection is a disagreement rather than a shared mistake.
 */

const ORIGIN = "2026-09-06T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };

function client() {
  return new FixtureReadClient({ clock: fixedClock(ORIGIN) });
}

/** Every carried point occupies its own ordinal — the ungapped case. */
function contiguous(count: number): number[] {
  return Array.from({ length: count }, (_, index) => index);
}

/* ==================================================== the rolling arithmetic, by hand */

describe("rolling window arithmetic", () => {
  /*
   * A WORKED EXAMPLE, SMALL ENOUGH TO CHECK ON PAPER.
   *
   * Cumulative readings in hundredths of a percent, so the index at each point is
   * `10000 + reading`:
   *
   *   ordinal    0      1      2      3      4
   *   reading    0    500   1000    600   1200
   *   index  10000  10500  11000  10600  11200
   *
   * With a lookback of 2, the point at ordinal 2 is `11000 / 10000 - 1 = +10.00%`, which is
   * 1000 hundredths; the point at ordinal 3 is `10600 / 10500 - 1 = +0.952...%`, which
   * rounds to 95 hundredths; and the point at ordinal 4 is `11200 / 11000 - 1 = +1.818...%`,
   * which rounds to 182.
   */
  const readings = [0, 500, 1_000, 600, 1_200];

  it("computes the trailing return from the two index readings the window spans", () => {
    const values = rollingWindowValues(readings, contiguous(5), 2);
    expect(values.returns[2]).toEqual({ kind: "VALUE", hundredths: 1_000 });
    expect(values.returns[3]).toEqual({ kind: "VALUE", hundredths: 95 });
    expect(values.returns[4]).toEqual({ kind: "VALUE", hundredths: 182 });
  });

  it("refuses every point with fewer than the lookback behind it, and never returns zero", () => {
    const values = rollingWindowValues(readings, contiguous(5), 2);
    expect(values.returns[0]).toEqual({ kind: "BELOW_MINIMUM" });
    expect(values.returns[1]).toEqual({ kind: "BELOW_MINIMUM" });
    expect(values.drawdowns[0]).toEqual({ kind: "BELOW_MINIMUM" });
    expect(values.drawdowns[1]).toEqual({ kind: "BELOW_MINIMUM" });
  });

  it("measures the rolling drawdown against the peak INSIDE the window, not the series peak", () => {
    /*
     * At ordinal 3 the window is ordinals 1..3 — indices 10500, 11000, 10600. The window's
     * peak is 11000, so the worst reading is `10600 / 11000 - 1 = -3.636...%`, which rounds
     * to -364 hundredths.
     *
     * The SERIES peak at that point is also 11000, so this case alone would not separate the
     * two definitions. The point at ordinal 4 does: its window is ordinals 2..4 — 11000,
     * 10600, 11200 — whose peak is 11200 only at the last reading, and whose worst is
     * `10600 / 11000 - 1`, again -364. A whole-series drawdown at ordinal 4 would be 0,
     * because 11200 IS the series peak.
     */
    const values = rollingWindowValues(readings, contiguous(5), 2);
    expect(values.drawdowns[3]).toEqual({ kind: "VALUE", hundredths: -364 });
    expect(values.drawdowns[4]).toEqual({ kind: "VALUE", hundredths: -364 });
  });

  it("never reports a positive rolling drawdown, on a strictly rising series", () => {
    const rising = [0, 100, 200, 300, 400];
    const values = rollingWindowValues(rising, contiguous(5), 2);
    for (const outcome of values.drawdowns) {
      if (outcome.kind === "VALUE") {
        expect(outcome.hundredths).toBeLessThanOrEqual(0);
      }
    }
  });

  it("refuses a window that spans a missing observation rather than computing over the survivors", () => {
    /*
     * The same five readings, but the observation at requested ordinal 2 was never made, so
     * the carried points occupy ordinals 0, 1, 3, 4, 5. With a lookback of 2, the point at
     * carried position 2 spans requested ordinals 1 to 3 — three requested periods for a
     * two-period window — so the window it names was never fully observed.
     */
    const gapped = rollingWindowValues(readings, [0, 1, 3, 4, 5], 2);
    expect(gapped.returns[2]).toEqual({ kind: "EXTENT_GAPPED" });
    expect(gapped.returns[3]).toEqual({ kind: "EXTENT_GAPPED" });
    /** Positions 0 and 1 are still below the minimum — a gap does not overwrite that. */
    expect(gapped.returns[0]).toEqual({ kind: "BELOW_MINIMUM" });
  });

  it("computes across the gap once the window clears it", () => {
    /*
     * Carried positions 2, 3 and 4 sit at requested ordinals 3, 4 and 5 — contiguous — so
     * the window ending at carried position 4 is intact. It spans readings 1000 and 1200,
     * which is `11200 / 11000 - 1 = +1.818...%`, rounding to 182 hundredths.
     */
    const gapped = rollingWindowValues(readings, [0, 1, 3, 4, 5], 2);
    expect(gapped.returns[4]).toEqual({ kind: "VALUE", hundredths: 182 });
  });

  it("changes no earlier point when a later observation is appended", () => {
    const before = rollingWindowValues(readings, contiguous(5), 2);
    const after = rollingWindowValues([...readings, 4_000], contiguous(6), 2);
    expect(after.returns.slice(0, readings.length)).toEqual(before.returns);
    expect(after.drawdowns.slice(0, readings.length)).toEqual(before.drawdowns);
  });

  it("reads no observation later than the point it is computing", () => {
    /*
     * A DIRECT NO-LOOKAHEAD PROOF. Replacing every reading AFTER a point changes nothing at
     * or before it, which is a stronger statement than appending: it says the later values
     * were never consulted, not merely that new ones were not.
     */
    const perturbed = [...readings.slice(0, 3), -9_000, -9_500];
    const original = rollingWindowValues(readings, contiguous(5), 2);
    const altered = rollingWindowValues(perturbed, contiguous(5), 2);
    expect(altered.returns.slice(0, 3)).toEqual(original.returns.slice(0, 3));
    expect(altered.drawdowns.slice(0, 3)).toEqual(original.drawdowns.slice(0, 3));
    /** And the points that DO span the changed readings differ, so the test is not vacuous. */
    expect(altered.returns[3]).not.toEqual(original.returns[3]);
  });

  it("reports every point below the minimum when the extent is shorter than the lookback", () => {
    const short = rollingWindowValues([0, 100, 200], contiguous(3), 21);
    expect(short.returns.every((outcome) => outcome.kind === "BELOW_MINIMUM")).toBe(true);
  });
});

/* ================================================== rebasing and movement, by hand */

describe("rebasing and movement", () => {
  it("rebases to exactly 100.00 at the first observation, whatever it started from", () => {
    expect(rebasedToHundred([0, 500, 1_000])[0]).toBe(10_000);
    expect(rebasedToHundred([2_500, 3_000])[0]).toBe(10_000);
  });

  it("rebases the later points onto the same base", () => {
    /** `10500 / 10000 x 100 = 105.00`, and `11000 / 10000 x 100 = 110.00`. */
    expect(rebasedToHundred([0, 500, 1_000])).toEqual([10_000, 10_500, 11_000]);
    /** From a non-zero start: `10300 / 10250 x 100 = 100.487...`, which rounds to 100.49. */
    expect(rebasedToHundred([250, 300])).toEqual([10_000, 10_049]);
  });

  it("measures movement between the first and last common readings, not from zero", () => {
    /** `11000 / 10500 - 1 = +4.761...%`, which rounds to 476 hundredths. */
    expect(movementOver([500, 800, 1_000])).toBe(476);
  });

  it("refuses a movement over fewer than two observations", () => {
    expect(movementOver([500])).toBeNull();
    expect(movementOver([])).toBeNull();
  });
});

/* ============================================ the served PerformanceSeries payload */

describe("the performance series carries its rolling windows", () => {
  it("admits the extended payload and carries its own new schema version", async () => {
    const envelope = await client().performanceSeries(DEMO);
    expect(() => performanceSeriesEnvelope.parse(envelope)).not.toThrow();
    expect(envelope.schema_version).toBe(PERFORMANCE_SERIES_SCHEMA);
    expect(PERFORMANCE_SERIES_SCHEMA).toBe("cockpit.performance_series.v3");
  });

  it("serves one window per declared lookback, each stating its own minimum", async () => {
    const payload = (await client().performanceSeries(DEMO)).payload;
    expect(payload?.rolling_windows?.map((window) => window.lookback.value)).toEqual([
      ...ROLLING_LOOKBACKS,
    ]);
    for (const window of payload?.rolling_windows ?? []) {
      expect(window.minimum_observations.value).toBe(window.lookback.value);
      expect(window.observation_unit).toBe("SERIES_PERIOD");
    }
  });

  it("aligns every rolling point to the instant of the series it rolls over", async () => {
    const payload = (await client().performanceSeries(DEMO)).payload;
    const instants = payload?.equity.points.map((point) => point.t) ?? [];
    expect(instants.length).toBeGreaterThan(0);
    for (const window of payload?.rolling_windows ?? []) {
      expect(window.return_series.points.map((point) => point.t)).toEqual(instants);
      expect(window.drawdown_series.points.map((point) => point.t)).toEqual(instants);
    }
  });

  it("reports the first lookback-many points below their minimum, and none of them as zero", async () => {
    const payload = (await client().performanceSeries({ ...DEMO, period: "1Y" })).payload;
    const window = payload?.rolling_windows?.[0];
    expect(window?.lookback.value).toBe(21);
    for (let index = 0; index < 21; index += 1) {
      const point = window?.return_series.points[index];
      expect(point?.v.availability).toBe("INSUFFICIENT_OBSERVATIONS");
      expect(point?.v.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
      expect(point?.v.value).toBeUndefined();
    }
    expect(window?.return_series.points[21].v.availability).toBe("AVAILABLE");
  });

  it("computes nothing at all when the extent is shorter than every lookback", async () => {
    /** One month requests 21 periods; the shortest lookback needs 21 earlier ones plus a point. */
    const payload = (await client().performanceSeries({ ...DEMO, period: "1M" })).payload;
    for (const window of payload?.rolling_windows ?? []) {
      const computed = window.return_series.points.filter((point) =>
        isValueBearing(point.v.availability),
      );
      expect(computed).toHaveLength(0);
    }
  });

  it("separates a point below its minimum from a point whose window spans a gap", async () => {
    /** The `ALL` period is the gapped one, so both absences are reachable in one payload. */
    const payload = (await client().performanceSeries({ ...DEMO, period: "ALL" })).payload;
    const window = payload?.rolling_windows?.[0];
    const reasons = new Set(
      (window?.return_series.points ?? [])
        .filter((point) => !isValueBearing(point.v.availability))
        .map((point) => point.v.reason),
    );
    expect(reasons.has("BELOW_MINIMUM_OBSERVATIONS")).toBe(true);
    expect(reasons.has("UPSTREAM_INPUT_MISSING")).toBe(true);
    for (const point of window?.return_series.points ?? []) {
      if (!isValueBearing(point.v.availability)) {
        expect(point.v.value).toBeUndefined();
      }
    }
  });

  it("agrees with the whole-window return when the lookback spans the whole extent", async () => {
    /*
     * A CROSS-CHECK AGAINST AN ALREADY-ACCEPTED FIGURE. Over one year the series carries 252
     * daily periods; a 126-period rolling return at the last point is the chain-linked return
     * of the second half, and the same figure computed from the payload's own cumulative
     * return series must equal it. Two routes to one number, and they must agree.
     */
    const payload = (await client().performanceSeries({ ...DEMO, period: "1Y" })).payload;
    const window = payload?.rolling_windows?.find((entry) => entry.lookback.value === 126);
    const points = window?.return_series.points ?? [];
    const last = points.length - 1;
    const cumulative = payload?.return_series.points ?? [];
    const now = 10_000 + Math.round(Number(cumulative[last].v.value) * 100);
    const then = 10_000 + Math.round(Number(cumulative[last - 126].v.value) * 100);
    const expected = Math.round((now * 10_000) / then - 10_000);
    expect(Math.round(Number(points[last].v.value) * 100)).toBe(expected);
  });

  it("registers every metric it serves in the dictionary", () => {
    for (const id of [
      "return.rolling",
      "drawdown.rolling_max",
      "expectancy.rolling",
      "comparison.rebased_index",
      "performance.rolling_lookback",
      "performance.observation_ordinal",
    ] as const) {
      expect(C3_METRIC_DICTIONARY[id]).toBeDefined();
    }
  });
});

/* ================================================== the benchmark comparison */

describe("the portfolio benchmark comparison", () => {
  it("aligns both arms to the same instants, and to nothing wider", async () => {
    const payload = (await client().performanceSeries(DEMO)).payload;
    const comparison = payload?.benchmark_comparison;
    expect(comparison).toBeDefined();
    const left = comparison?.portfolio_series.points.map((point) => point.t) ?? [];
    const right = comparison?.benchmark_series.points.map((point) => point.t) ?? [];
    expect(left).toEqual(right);
    expect(comparison?.common_observations.value).toBe(left.length);
    const observed = new Set(payload?.equity.points.map((point) => point.t));
    for (const instant of left) {
      expect(observed.has(instant)).toBe(true);
    }
  });

  it("rebases both arms to 100.00 at the first common observation", async () => {
    const comparison = (await client().performanceSeries(DEMO)).payload?.benchmark_comparison;
    expect(comparison?.portfolio_series.points[0].v.value).toBe("100.00");
    expect(comparison?.benchmark_series.points[0].v.value).toBe("100.00");
  });

  it("opens and closes on the boundaries the compared series actually carries", async () => {
    const payload = (await client().performanceSeries(DEMO)).payload;
    const points = payload?.equity.points ?? [];
    const comparison = payload?.benchmark_comparison;
    expect(comparison?.common_window.from.slice(0, 10)).toBe(String(points[0].t));
    expect(comparison?.common_window.to.slice(0, 10)).toBe(
      String(points[points.length - 1].t),
    );
  });

  it("refuses the difference because the arms carry different cost treatments", async () => {
    const comparison = (await client().performanceSeries(DEMO)).payload?.benchmark_comparison;
    expect(comparison?.portfolio_cost_treatment).toBe("NET_ALL_COSTS");
    expect(comparison?.benchmark_cost_treatment).toBe("GROSS");
    expect(comparison?.comparable).toBe(false);
    expect(comparison?.refusal?.code).toBe("ARMS_DIFFER_IN_COST_TREATMENT");
    expect(comparison?.difference.availability).toBe("NOT_APPLICABLE");
    expect(comparison?.difference.value).toBeUndefined();
  });

  it("states its limits on the comparison rather than leaving them to a reader", async () => {
    const comparison = (await client().performanceSeries(DEMO)).payload?.benchmark_comparison;
    const codes = comparison?.comparability_limits.map((limit) => limit.code) ?? [];
    expect(codes.length).toBeGreaterThan(0);
    expect(codes.join(" ")).toContain("COST_TREATMENT");
    expect(codes.join(" ")).toContain("NOT_A_MARKET_INDEX");
  });

  it("names no benchmark it does not hold, and calls nothing alpha", async () => {
    const payload = (await client().performanceSeries(DEMO)).payload;
    const serialized = JSON.stringify(payload);
    expect(serialized).not.toContain("ALPHA");
    expect(serialized).not.toContain("alpha");
    for (const ticker of ["SPY", "QQQ", "IWM"]) {
      expect(serialized).not.toContain(ticker);
    }
    /** The three named references are still carried, and still resolve to nothing. */
    expect(payload?.benchmark_refs.items).toHaveLength(3);
    for (const reference of payload?.benchmark_refs.items ?? []) {
      expect(reference.resolution).toBe("UNRESOLVABLE_V1");
    }
  });

  it("measures each arm's movement over exactly the common boundaries", async () => {
    const payload = (await client().performanceSeries({ ...DEMO, period: "3M" })).payload;
    const comparison = payload?.benchmark_comparison;
    const cumulative = payload?.return_series.points ?? [];
    const first = 10_000 + Math.round(Number(cumulative[0].v.value) * 100);
    const last =
      10_000 + Math.round(Number(cumulative[cumulative.length - 1].v.value) * 100);
    const expected = Math.round((last * 10_000) / first - 10_000);
    expect(Math.round(Number(comparison?.portfolio_movement.value) * 100)).toBe(expected);
  });
});

/* ================================================== the strategy rolling expectancy */

describe("rolling expectancy over closed trades", () => {
  it("admits the extended payload and carries its own new schema version", async () => {
    const envelope = await client().strategyPerformance(DEMO);
    expect(() => strategyPerformanceEnvelope.parse(envelope)).not.toThrow();
    expect(envelope.schema_version).toBe(STRATEGY_PERFORMANCE_SCHEMA);
    /*
     * v4 SINCE ADR-0032, and the original property this test guards is unchanged: the payload
     * this cycle extended still carries ITS OWN schema version rather than a shared one. The
     * later bump came from `capacity_declaration`, not from `rolling_expectancy`, and asserting
     * the current version keeps the guard exact rather than weakening it to a prefix.
     */
    expect(STRATEGY_PERFORMANCE_SCHEMA).toBe("cockpit.strategy_performance.v4");
  });

  it("uses the dictionary's own thirty-trade minimum as its lookback", async () => {
    const payload = (await client().strategyPerformance(DEMO)).payload;
    expect(OBSERVATION_MINIMUMS["expectancy.currency"]).toBe(30);
    for (const entry of payload?.items ?? []) {
      expect(entry.rolling_expectancy?.lookback.value).toBe(30);
      expect(entry.rolling_expectancy?.minimum_observations.value).toBe(30);
      expect(entry.rolling_expectancy?.observation_unit).toBe("CLOSED_TRADE");
    }
  });

  it("carries one point per closed trade, ordinalled consecutively from one", async () => {
    const payload = (await client().strategyPerformance(DEMO)).payload;
    for (const entry of payload?.items ?? []) {
      const rolling = entry.rolling_expectancy;
      expect(rolling?.points).toHaveLength(Number(rolling?.observed.value));
      rolling?.points.forEach((point, index) => {
        expect(point.ordinal.value).toBe(index + 1);
      });
    }
  });

  it("refuses every point with fewer than thirty trades behind it", async () => {
    const payload = (await client().strategyPerformance(DEMO)).payload;
    for (const entry of payload?.items ?? []) {
      for (const point of entry.rolling_expectancy?.points.slice(0, 29) ?? []) {
        expect(point.value.availability).toBe("INSUFFICIENT_OBSERVATIONS");
        expect(point.value.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
        expect(point.value.value).toBeUndefined();
      }
    }
  });

  it("reaches both outcomes across the book, so neither branch is untested", async () => {
    const payload = (await client().strategyPerformance(DEMO)).payload;
    const computed = (payload?.items ?? []).map((entry) =>
      (entry.rolling_expectancy?.points ?? []).filter((point) =>
        isValueBearing(point.value.availability),
      ).length,
    );
    expect(computed.some((count) => count > 0)).toBe(true);
    expect(computed.some((count) => count === 0)).toBe(true);
  });

  it("orders its points by exit, so a later close never lands before an earlier one", async () => {
    const payload = (await client().strategyPerformance(DEMO)).payload;
    for (const entry of payload?.items ?? []) {
      const exits = (entry.rolling_expectancy?.points ?? []).map((point) =>
        String(point.at.value),
      );
      const sorted = [...exits].sort();
      expect(exits).toEqual(sorted);
    }
  });

  it("agrees with the accepted summary builder over the same trailing thirty trades", async () => {
    /*
     * A CROSS-CHECK AGAINST AN ALREADY-ACCEPTED FIGURE, AND ONE THAT RUNS.
     *
     * THE EARLIER FORM OF THIS TEST NEVER EXECUTED ITS COMPARISON. It guarded on the version
     * carrying exactly thirty closed trades, and no version in this book does — the counts are
     * 26, 13, 39, 39, 39 and 39 — so the loop `continue`d every time and the only assertion
     * that ran was `checked >= 0`, which is true of every implementation. A rolling expectancy
     * computed over twenty-nine trades, or over thirty-one, passed it unchanged.
     *
     * WHAT HOLDS FOR EVERY VALUED POINT, and is checked here instead: the point at ordinal `n`
     * is `expectancy.currency` over exactly the thirty closed trades ending there, so
     * `buildPerformanceSummary` — the accepted builder the version summary on screen already
     * uses, in another file — must return the same figure when it is given those same thirty.
     * Two functions, one number, and a denominator or a window that moved makes them disagree.
     */
    const payload = (await client().strategyPerformance(DEMO)).payload;
    const days = bookSessions(Date.parse(ORIGIN));
    const lookback = OBSERVATION_MINIMUMS["expectancy.currency"];
    let checked = 0;
    let versionsWithAValuedPoint = 0;
    for (const entry of payload?.items ?? []) {
      const points = entry.rolling_expectancy?.points ?? [];
      /*
       * The exit-ordered closed population this version's rolling points are indexed by. The
       * ordering is the one the payload publishes — ordinal `n` is the `n`-th point — so the
       * slice below is read off the served axis rather than reconstructed from a guess.
       */
      const ordered = [...BOOK.trades]
        .filter(
          (trade) => trade.versionId === entry.strategy_version && trade.status === "CLOSED",
        )
        .sort((left, right) => {
          const bySession =
            left.exits[left.exits.length - 1].session -
            right.exits[right.exits.length - 1].session;
          return bySession !== 0 ? bySession : left.tradeId.localeCompare(right.tradeId);
        });
      expect(ordered).toHaveLength(points.length);

      let valuedOnThisVersion = 0;
      for (const point of points) {
        if (!isValueBearing(point.value.availability)) {
          continue;
        }
        valuedOnThisVersion += 1;
        const ordinal = Number(point.ordinal.value);
        const window = ordered.slice(ordinal - lookback, ordinal);
        expect(window).toHaveLength(lookback);
        const summary = buildPerformanceSummary({
          days,
          asOf: ORIGIN,
          closed: window,
          /** A trade population has no return series, so its Sharpe is insufficient. */
          periodReturns: [],
          totalReturnHundredths: 0,
          maxDrawdownHundredths: 0,
          populationCode: "CLOSED_TRADES_OF_THIS_EXACT_VERSION",
        });
        expect(summary.expectancy.availability).toBe("AVAILABLE");
        expect(point.value.value, `${entry.strategy_version} #${ordinal}`).toBe(
          summary.expectancy.value,
        );
        checked += 1;
      }
      if (valuedOnThisVersion > 0) {
        versionsWithAValuedPoint += 1;
      }
    }
    /*
     * THE GUARD THAT KEEPS THIS TEST FROM GOING QUIET. If the book stops producing valued
     * rolling points the comparison stops running, and a test that stops running must fail
     * rather than pass — which is exactly what the form it replaces did not do.
     */
    expect(checked).toBeGreaterThan(0);
    expect(versionsWithAValuedPoint).toBeGreaterThan(1);
  });

  it("excludes a trade with no retained risk record rather than averaging over fewer", async () => {
    /*
     * Recomputed by hand from the served points: a window whose thirty trades include an
     * excluded one has only twenty-nine qualifying, so it reports INSUFFICIENT_OBSERVATIONS
     * rather than an expectancy labelled thirty and computed over twenty-nine.
     */
    const payload = (await client().strategyPerformance(DEMO)).payload;
    const withGap = (payload?.items ?? []).flatMap((entry) =>
      (entry.rolling_expectancy?.points ?? []).filter(
        (point, index) =>
          index >= 30 && !isValueBearing(point.value.availability),
      ),
    );
    for (const point of withGap) {
      expect(point.value.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
      expect(point.value.value).toBeUndefined();
    }
  });
});

/* ================================================== capacity stays unavailable */

describe("strategy capacity", () => {
  it("is served unavailable for every version, and never as a number", async () => {
    const payload = (await client().strategyPerformance(DEMO)).payload;
    expect(payload?.items.length).toBeGreaterThan(0);
    for (const entry of payload?.items ?? []) {
      expect(isValueBearing(entry.module_metrics.capacity.availability)).toBe(false);
      expect(entry.module_metrics.capacity.value).toBeUndefined();
      expect(entry.module_metrics.capacity.metric_id).toBe("strategy.capacity");
    }
  });

  it("is never substituted by strategy capital, cash or a position limit", async () => {
    /*
     * THE SUBSTITUTION THIS GUARDS is the one that looks helpful: a screen with no capacity
     * quietly showing the capital it could deploy instead. Capacity carries no value at all,
     * so no figure of any kind can be read from it.
     */
    const payload = (await client().strategyPerformance(DEMO)).payload;
    for (const entry of payload?.items ?? []) {
      expect(entry.module_metrics.capacity.value).toBeUndefined();
      expect(entry.module_metrics.capacity.availability).not.toBe("AVAILABLE");
    }
  });

  it("registers a unit and no computable rule, which is why it stays unavailable", () => {
    /** The dictionary knows what a capacity would be measured in, and not how to compute one. */
    expect(C3_METRIC_DICTIONARY["strategy.capacity"].unit).toBe("USD");
  });
});
