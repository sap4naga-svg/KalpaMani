import { describe, expect, it } from "vitest";

import {
  CAPACITY_REQUIRED_INPUTS,
  capacityGate,
  currentCapacityRequest,
  type CapacityEvidence,
  type CapacityInputFact,
  type CapacityRequest,
} from "@/contracts/capacity";
import { strategyPerformanceEnvelope } from "@/contracts/strategy-models";
import {
  STRATEGY_HEALTH_SCHEMA,
  STRATEGY_PERFORMANCE_SCHEMA,
  strategyHealthEnvelope,
} from "@/contracts/strategy-models";
import { PERFORMANCE_SERIES_SCHEMA } from "@/contracts/read-models";
import { RESEARCH_RUN_SCHEMA, researchRunEnvelope } from "@/contracts/research-models";
import {
  computeRollingTailLoss,
  tailObservationCount,
  TAIL_LOSS_PARAMETERS,
  type TailLossObservation,
} from "@/contracts/tail-loss";
import { METRIC_DEFINITION_VERSION, metricValue } from "@/contracts/values";
import { admit, ContractViolationError } from "@/data/client/read-client";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { BOOK, centsToDecimal } from "@/data/fixtures/book";
import { rMultipleHundredths } from "@/data/fixtures/summary";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

/**
 * ADR-0032 — the rolling tail loss and the capacity admission gate.
 *
 * EVERY EXPECTED TAIL VALUE IS HAND-CALCULATED HERE, from observation lists written out in
 * full. Nothing below restates the implementation: the arithmetic is done independently and
 * the comparand is the number a reader can check by adding three values and dividing by three.
 *
 * WHERE A RULE IS ERROR-PRONE IN ONE SPECIFIC DIRECTION, THE TEST CARRIES A SEMANTIC NEGATIVE
 * CONTROL — the wrong denominator, the wrong window, a ratio of sums, a mixed version, a
 * forward-looking cutoff, a substituted zero — computed on the same population, and asserts
 * the accepted answer DIFFERS from it. A test that only asserted the accepted number would
 * pass under an implementation that had computed the wrong quantity and happened to agree.
 */

const ORIGIN = "2026-09-08T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };

function client() {
  return new FixtureReadClient({ clock: fixedClock(ORIGIN) });
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const DAY = 86_400_000;
const BASE = Date.parse("2026-01-01T21:00:00.000Z");

/** Observations in hundredths, one per day, in the order given. */
function observations(rs: readonly (number | null)[]): TailLossObservation[] {
  return rs.map((r, index) => ({
    tradeId: `t-${String(index + 1).padStart(3, "0")}`,
    closedAtMs: BASE + index * DAY,
    rMultipleHundredths: r,
  }));
}

/** Thirty observations whose three most adverse are exactly the three given. */
function windowWith(worst: readonly [number, number, number]): TailLossObservation[] {
  const rest = Array.from({ length: 27 }, () => 500);
  return observations([...worst, ...rest]);
}

/* ============================================================ the tail-loss statistic */

describe("the rolling tail loss is the accepted statistic and not a neighbouring one", () => {
  it("averages the k most adverse observations, hand-calculated", () => {
    /*
     * The ADR's own worked example: three most adverse at -3.10, -2.40 and -2.00.
     * (-3.10 + -2.40 + -2.00) / 3 = -7.50 / 3 = -2.50 R. Computed here by hand.
     */
    const result = computeRollingTailLoss(windowWith([-310, -240, -200]), Number.MAX_SAFE_INTEGER);
    expect(result.availability).toBe("AVAILABLE");
    expect(result.reason).toBe("NONE");
    expect(result.eligibleObservations).toBe(30);
    expect(result.tailObservations).toBe(3);
    expect(result.valueHundredths).toBe(-250);
  });

  it("is not the worst single observation, and is not the mean over the whole population", () => {
    const population = windowWith([-310, -240, -200]);
    const result = computeRollingTailLoss(population, Number.MAX_SAFE_INTEGER);
    /* NEGATIVE CONTROL: the minimum order statistic, computed independently. */
    const worstSingle = Math.min(
      ...population.map((o) => o.rMultipleHundredths ?? Number.POSITIVE_INFINITY),
    );
    /* NEGATIVE CONTROL: the mean over all thirty — what `expectancy.r` answers. */
    const wholeMean = Math.round(
      population.reduce((total, o) => total + (o.rMultipleHundredths ?? 0), 0) / 30,
    );
    expect(worstSingle).toBe(-310);
    expect(result.valueHundredths).not.toBe(worstSingle);
    expect(result.valueHundredths).not.toBe(wholeMean);
  });

  it("may coincide with the worst single observation without being the same definition", () => {
    /* Three tied worst: the mean of the tail IS the minimum, and k being three prevents nothing. */
    const population = windowWith([-200, -200, -200]);
    const result = computeRollingTailLoss(population, Number.MAX_SAFE_INTEGER);
    expect(result.valueHundredths).toBe(-200);
    const worstSingle = Math.min(
      ...population.map((o) => o.rMultipleHundredths ?? Number.POSITIVE_INFINITY),
    );
    expect(result.valueHundredths).toBe(worstSingle);
    /* And they diverge the moment the tail is not flat. */
    const unflat = computeRollingTailLoss(windowWith([-300, -200, -200]), Number.MAX_SAFE_INTEGER);
    expect(unflat.valueHundredths).not.toBe(-300);
  });

  it("is a mean of ratios and never a ratio of sums", () => {
    /*
     * Two tail trades with very different position sizes. A ratio of sums would weight the
     * tail by size; the accepted statistic weights each observation equally.
     *
     *   trade A   -400 cents outcome over  100 cents risk  ->  -4.00 R
     *   trade B   -100 cents outcome over 1000 cents risk  ->  -0.10 R
     *   trade C   -200 cents outcome over  200 cents risk  ->  -1.00 R
     *
     *   mean of ratios   (-400 + -10 + -100) / 3           =  -170 hundredths
     *   ratio of sums    (-700 * 100) / 1300               =  -53.8 hundredths
     */
    const dollars = [
      { outcome: -400, risk: 100 },
      { outcome: -100, risk: 1000 },
      { outcome: -200, risk: 200 },
    ];
    const tail = dollars.map((d) => Math.round((d.outcome * 100) / d.risk)) as [
      number,
      number,
      number,
    ];
    const result = computeRollingTailLoss(windowWith(tail), Number.MAX_SAFE_INTEGER);
    const meanOfRatios = Math.round(tail.reduce((a, b) => a + b, 0) / 3);
    /* NEGATIVE CONTROL: total tail dollars over total tail risk dollars. */
    const ratioOfSums = Math.round(
      (dollars.reduce((t, d) => t + d.outcome, 0) * 100) /
        dollars.reduce((t, d) => t + d.risk, 0),
    );
    expect(meanOfRatios).toBe(-170);
    expect(ratioOfSums).not.toBe(meanOfRatios);
    expect(result.valueHundredths).toBe(meanOfRatios);
    expect(result.valueHundredths).not.toBe(ratioOfSums);
  });

  it("uses the declared window and refuses a longer or shorter one", () => {
    /*
     * Thirty-five observations. The five OLDEST are catastrophic and sit OUTSIDE the trailing
     * thirty, so the accepted window must not see them.
     */
    const old = [-900, -900, -900, -900, -900];
    const recent = [-310, -240, -200, ...Array.from({ length: 27 }, () => 500)];
    const population = observations([...old, ...recent]);
    const result = computeRollingTailLoss(population, Number.MAX_SAFE_INTEGER);
    expect(result.eligibleObservations).toBe(TAIL_LOSS_PARAMETERS.windowObservations);
    expect(result.valueHundredths).toBe(-250);
    /* NEGATIVE CONTROL: a window over the whole population would find the ancient losses. */
    const wholePopulation = [...population]
      .map((o) => o.rMultipleHundredths ?? 0)
      .sort((a, b) => a - b)
      .slice(0, 3);
    const wrongWindow = Math.round(wholePopulation.reduce((a, b) => a + b, 0) / 3);
    expect(wrongWindow).toBe(-900);
    expect(result.valueHundredths).not.toBe(wrongWindow);
  });

  it("derives k as ceil(q * n) with no interpolation anywhere", () => {
    expect(tailObservationCount(30)).toBe(3);
    expect(tailObservationCount(31)).toBe(4);
    expect(tailObservationCount(1)).toBe(1);
    /* k is an integer COUNT: it never lands between two order statistics. */
    for (const n of [30, 31, 45, 100]) {
      expect(Number.isInteger(tailObservationCount(n))).toBe(true);
      expect(tailObservationCount(n)).toBeGreaterThanOrEqual(1);
    }
  });
});

describe("the tail is selected by ordering, never by filtering on sign", () => {
  it("reports a positive tail loss as a measured result", () => {
    const result = computeRollingTailLoss(windowWith([10, 15, 20]), Number.MAX_SAFE_INTEGER);
    expect(result.availability).toBe("AVAILABLE");
    expect(result.reason).toBe("NONE");
    expect(result.valueHundredths).toBe(15);
  });

  it("reports a computed zero as AVAILABLE, distinctly from insufficiency", () => {
    /* -0.10, 0.00, +0.10 -> exactly 0.00 R, and it is a measurement. */
    const zero = computeRollingTailLoss(windowWith([-10, 0, 10]), Number.MAX_SAFE_INTEGER);
    expect(zero.availability).toBe("AVAILABLE");
    expect(zero.valueHundredths).toBe(0);

    const short = computeRollingTailLoss(observations([-10, 0, 10]), Number.MAX_SAFE_INTEGER);
    expect(short.availability).toBe("INSUFFICIENT_OBSERVATIONS");
    /* THE DISTINCTION THAT MATTERS: an absence carries NO value, not a zero. */
    expect(short.valueHundredths).toBeNull();
    expect(zero.valueHundredths).not.toBeNull();
  });

  it("does not shrink its population to the losses", () => {
    /* Twenty-seven winners and three small losers: a losses-only rule would average only three. */
    const result = computeRollingTailLoss(windowWith([-5, -3, -1]), Number.MAX_SAFE_INTEGER);
    expect(result.eligibleObservations).toBe(30);
    expect(result.valueHundredths).toBe(-3);
  });
});

describe("insufficiency, exclusion, and the two answers that are never both returned", () => {
  it("refuses below the minimum and carries no value", () => {
    const twentyNine = computeRollingTailLoss(
      observations(Array.from({ length: 29 }, () => -100)),
      Number.MAX_SAFE_INTEGER,
    );
    expect(twentyNine.availability).toBe("INSUFFICIENT_OBSERVATIONS");
    expect(twentyNine.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
    expect(twentyNine.valueHundredths).toBeNull();
    expect(twentyNine.members).toHaveLength(0);
  });

  it("treats an empty population as insufficient rather than as a verified empty", () => {
    const empty = computeRollingTailLoss([], Number.MAX_SAFE_INTEGER);
    expect(empty.availability).toBe("INSUFFICIENT_OBSERVATIONS");
    expect(empty.availability).not.toBe("EMPTY_VERIFIED");
    expect(empty.valueHundredths).toBeNull();
  });

  it("reports PARTIAL naming the exclusions once the minimum is met", () => {
    const population = [
      ...observations([null, null]),
      ...windowWith([-310, -240, -200]).map((o, index) => ({
        ...o,
        tradeId: `w-${index}`,
        closedAtMs: o.closedAtMs + 10 * DAY,
      })),
      ...observations([null]).map((o) => ({
        ...o,
        tradeId: "x-1",
        closedAtMs: BASE + 60 * DAY,
      })),
    ];
    const result = computeRollingTailLoss(population, Number.MAX_SAFE_INTEGER);
    expect(result.availability).toBe("PARTIAL");
    expect(result.reason).toBe("UPSTREAM_INPUT_MISSING");
    expect(result.eligibleObservations).toBe(30);
    /* Only the ineligible trades the walk-back actually passed are counted. */
    expect(result.excludedObservations).toBe(1);
    expect(result.valueHundredths).toBe(-250);
  });

  it("stays INSUFFICIENT when the minimum is unmet AND trades were excluded", () => {
    const population = observations([null, -300, null, -200, -100, null]);
    const result = computeRollingTailLoss(population, Number.MAX_SAFE_INTEGER);
    expect(result.availability).toBe("INSUFFICIENT_OBSERVATIONS");
    expect(result.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
    /* SUFFICIENCY IS DECIDED FIRST: no value, and PARTIAL is not reachable here. */
    expect(result.valueHundredths).toBeNull();
    expect(result.availability).not.toBe("PARTIAL");
    /* AND THE EXCLUSION COUNT IS STILL DISCLOSED. */
    expect(result.excludedObservations).toBe(3);
  });

  it("never treats an ineligible trade as a zero observation", () => {
    const withNulls = computeRollingTailLoss(
      observations([...Array.from({ length: 30 }, () => 500), null, null]),
      Number.MAX_SAFE_INTEGER,
    );
    /* NEGATIVE CONTROL: reading a missing denominator as 0.00 R would drag the tail to zero. */
    const asZeros = computeRollingTailLoss(
      observations([...Array.from({ length: 30 }, () => 500), 0, 0]),
      Number.MAX_SAFE_INTEGER,
    );
    /*
     * Hand-calculated. With the two ineligible trades EXCLUDED, the walk-back reaches thirty
     * eligible observations of +5.00 R and the tail is (500 + 500 + 500) / 3 = 500.
     *
     * Reading a missing denominator as 0.00 R instead admits the two zeros into the window, so
     * the trailing thirty become {0, 0, and twenty-eight 500s} and the tail becomes
     * (0 + 0 + 500) / 3 = 166.67, which rounds to 167. The two answers are not close, and the
     * wrong one understates the tail by two thirds.
     */
    expect(withNulls.valueHundredths).toBe(500);
    expect(asZeros.valueHundredths).toBe(167);
    expect(withNulls.valueHundredths).not.toBe(asZeros.valueHundredths);
  });
});

describe("ordering, ties and the point-in-time cutoff", () => {
  it("breaks recency ties by trade identifier, deterministically", () => {
    const sameInstant: TailLossObservation[] = Array.from({ length: 31 }, (_, index) => ({
      tradeId: `t-${String(index).padStart(3, "0")}`,
      closedAtMs: BASE,
      rMultipleHundredths: index === 0 ? -999 : 100,
    }));
    /* `t-000` is the OLDEST by identifier, so the trailing thirty exclude it. */
    const result = computeRollingTailLoss(sameInstant, Number.MAX_SAFE_INTEGER);
    expect(result.eligibleObservations).toBe(30);
    expect(result.valueHundredths).toBe(100);
  });

  it("returns the same value whatever order the tied observations arrive in", () => {
    const tied = windowWith([-200, -200, -200]);
    const forward = computeRollingTailLoss(tied, Number.MAX_SAFE_INTEGER);
    const reversed = computeRollingTailLoss([...tied].reverse(), Number.MAX_SAFE_INTEGER);
    expect(forward.valueHundredths).toBe(reversed.valueHundredths);
    expect(forward.members.map((m) => m.tradeId)).toEqual(
      reversed.members.map((m) => m.tradeId),
    );
  });

  it("admits no observation after the cutoff, in the strong replacement form", () => {
    const upTo = windowWith([-310, -240, -200]);
    const cutoff = upTo[upTo.length - 1].closedAtMs;
    const before = computeRollingTailLoss(upTo, cutoff);

    /* REPLACE every later observation with anything at all: nothing at or before P moves. */
    for (const laterValues of [[-9999, -9999, -9999], [9999, 9999, 9999], [0, 0, 0]]) {
      const later = laterValues.map((r, index) => ({
        tradeId: `future-${index}`,
        closedAtMs: cutoff + (index + 1) * DAY,
        rMultipleHundredths: r,
      }));
      const after = computeRollingTailLoss([...upTo, ...later], cutoff);
      expect(after.valueHundredths).toBe(before.valueHundredths);
      expect(after.eligibleObservations).toBe(before.eligibleObservations);
      expect(after.members.map((m) => m.tradeId)).toEqual(before.members.map((m) => m.tradeId));
    }
    /* NEGATIVE CONTROL: a forward-looking cutoff WOULD move it, which is what is refused. */
    const leaking = computeRollingTailLoss(
      [
        ...upTo,
        { tradeId: "future-0", closedAtMs: cutoff + DAY, rMultipleHundredths: -9999 },
      ],
      Number.MAX_SAFE_INTEGER,
    );
    expect(leaking.valueHundredths).not.toBe(before.valueHundredths);
  });
});

/* ==================================================== the tail loss over the real book */

describe("the tail loss as projected from the demonstration book", () => {
  it("computes each version from its own closed trades, and never across versions", async () => {
    const read = client();
    const health = await read.strategyHealth(DEMO);
    const payload = health.payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;

    for (const entry of payload.items) {
      const closed = BOOK.trades.filter(
        (trade) => trade.versionId === entry.strategy_version && trade.status === "CLOSED",
      );
      /* THE EXPECTED VALUE IS DERIVED HERE, from the book, not read back from the payload. */
      const eligible = closed
        .map((trade) => rMultipleHundredths(trade))
        .filter((r): r is number => r !== null);
      const ordered = closed
        .map((trade) => ({
          tradeId: trade.tradeId,
          session: trade.exits[trade.exits.length - 1].session,
          r: rMultipleHundredths(trade),
        }))
        .sort((a, b) => (a.session !== b.session ? a.session - b.session : a.tradeId < b.tradeId ? -1 : 1));

      const window: number[] = [];
      let excluded = 0;
      for (let i = ordered.length - 1; i >= 0 && window.length < 30; i -= 1) {
        if (ordered[i].r === null) excluded += 1;
        else window.push(ordered[i].r as number);
      }

      const tail = entry.tail_loss;
      expect(tail.eligible_observations.value, entry.strategy_version).toBe(window.length);
      expect(tail.excluded_observations.value, entry.strategy_version).toBe(excluded);

      if (window.length < 30) {
        expect(tail.value.availability, entry.strategy_version).toBe(
          "INSUFFICIENT_OBSERVATIONS",
        );
        expect(tail.value.value, entry.strategy_version).toBeUndefined();
        expect(tail.tail_members, entry.strategy_version).toHaveLength(0);
        continue;
      }
      const worstThree = [...window].sort((a, b) => a - b).slice(0, 3);
      const expected = Math.round(worstThree.reduce((a, b) => a + b, 0) / 3);
      expect(tail.tail_observations.value, entry.strategy_version).toBe(3);
      expect(tail.value.value, entry.strategy_version).toBe((expected / 100).toFixed(2));
      expect(tail.tail_members, entry.strategy_version).toHaveLength(3);
      /* The population is never larger than this exact version's own closed trades. */
      expect(eligible.length).toBeLessThanOrEqual(closed.length);
    }
  });

  it("proves the book actually exercises the value-bearing and the insufficient answer", async () => {
    /*
     * A SUITE THAT NEVER REACHED EITHER BRANCH WOULD PASS VACUOUSLY. This asserts the
     * population under test really contains both cases before anything above is believed.
     */
    const read = client();
    const payload = (await read.strategyHealth(DEMO)).payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;
    const states = payload.items.map((entry) => entry.tail_loss.value.availability);
    expect(states).toContain("INSUFFICIENT_OBSERVATIONS");
    expect(states.some((state) => state === "AVAILABLE" || state === "PARTIAL")).toBe(true);
  });

  it("agrees with the drift entry and the TAIL_LOSSES health input, one value read three times", async () => {
    const read = client();
    const payload = (await read.strategyHealth(DEMO)).payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;
    for (const entry of payload.items) {
      const drift = entry.drift.find((d) => d.measure.code === "TAIL_LOSS_R_MULTIPLE");
      const input = entry.health_inputs.find((i) => i.input.code === "TAIL_LOSSES");
      expect(drift?.value).toEqual(entry.tail_loss.value);
      expect(input?.value).toEqual(entry.tail_loss.value);
    }
  });

  it("carries no unsupported recorded tail-loss literal anywhere", async () => {
    /*
     * The four hand-written values the fixture used to carry were -1.40, -2.10, -3.20 and
     * -1.80 R. None may appear as a tail loss unless the accepted formula actually produced it
     * from the book.
     *
     * THE REGRESSION THIS GUARDS IS A LITERAL COMING BACK, so it is asserted in both
     * directions: no retired literal appears on ANY tail-loss-bearing value, and every value
     * that IS rendered equals the statistic re-derived here from the accepted rule. The
     * derivation below does not call `computeRollingTailLoss`: it sorts this version's closed
     * trades into the declared recency order, walks back collecting eligible observations
     * until the window is full, takes the three most adverse and averages them.
     */
    const read = client();
    const payload = (await read.strategyHealth(DEMO)).payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;

    /* Every place a tail loss is rendered: the field, its points, and the drift entry. */
    const everyTailValue: string[] = [];
    for (const entry of payload.items) {
      const headline = entry.tail_loss.value.value;
      if (typeof headline === "string") everyTailValue.push(headline);
      for (const point of entry.tail_loss.points) {
        if (typeof point.value.value === "string") everyTailValue.push(point.value.value);
      }
      for (const measure of entry.drift) {
        if (measure.value.metric_id === "strategy.tail_loss" && typeof measure.value.value === "string") {
          everyTailValue.push(measure.value.value);
        }
      }
    }
    expect(everyTailValue.length).toBeGreaterThan(0);
    for (const retired of ["-1.40", "-2.10", "-3.20", "-1.80"]) {
      expect(everyTailValue, `the retired literal ${retired} must not reappear`).not.toContain(
        retired,
      );
    }

    /* And each rendered headline equals the independently re-derived statistic. */
    const closeSession = (trade: (typeof BOOK.trades)[number]) =>
      trade.exits[trade.exits.length - 1].session;
    let compared = 0;
    let insufficient = 0;
    for (const entry of payload.items) {
      const closed = BOOK.trades
        .filter(
          (trade) => trade.versionId === entry.strategy_version && trade.status === "CLOSED",
        )
        .slice()
        .sort((left, right) =>
          closeSession(left) !== closeSession(right)
            ? closeSession(left) - closeSession(right)
            : left.tradeId < right.tradeId
              ? -1
              : left.tradeId > right.tradeId
                ? 1
                : 0,
        );
      const eligible: number[] = [];
      for (let index = closed.length - 1; index >= 0; index -= 1) {
        if (eligible.length >= 30) break;
        const r = rMultipleHundredths(closed[index]);
        if (r === null) continue;
        eligible.push(r);
      }
      if (eligible.length < 30) {
        expect(entry.tail_loss.value.availability, entry.strategy_version).toBe(
          "INSUFFICIENT_OBSERVATIONS",
        );
        expect(entry.tail_loss.value.value, entry.strategy_version).toBeUndefined();
        insufficient += 1;
        continue;
      }
      const derived = Math.round(
        [...eligible].sort((a, b) => a - b).slice(0, 3).reduce((a, b) => a + b, 0) / 3,
      );
      expect(entry.tail_loss.value.value, entry.strategy_version).toBe(centsToDecimal(derived));
      compared += 1;
    }
    /* A COMPARISON THAT NEVER RAN WOULD PASS VACUOUSLY. Both branches must be exercised. */
    expect(compared, "no version reached a full window, so nothing was compared").toBeGreaterThan(
      0,
    );
    expect(insufficient, "no version exercised the short-population branch").toBeGreaterThan(0);
  });

  it("leaves the book economics, entry facts and risk denominators untouched", async () => {
    /*
     * The measurement READS the book. A projection that had adjusted a trade to make a window
     * full would show up here as a changed total, a changed risk record or a changed count.
     */
    const closed = BOOK.trades.filter((trade) => trade.status === "CLOSED");
    expect(BOOK.trades).toHaveLength(200);
    expect(closed.length + BOOK.openTrades.length).toBeLessThanOrEqual(BOOK.trades.length);
    const realized = BOOK.trades.reduce((total, trade) => total + trade.realizedCents, 0);
    const risk = BOOK.trades.reduce((total, trade) => total + trade.initialRiskCents, 0);
    const read = client();
    await read.strategyHealth(DEMO);
    await read.strategyPerformance(DEMO);
    expect(BOOK.trades.reduce((total, trade) => total + trade.realizedCents, 0)).toBe(realized);
    expect(BOOK.trades.reduce((total, trade) => total + trade.initialRiskCents, 0)).toBe(risk);
    /* Every stage still carries its own retained invalidation level, unmoved. */
    for (const trade of BOOK.trades) {
      for (const stage of trade.stages) {
        expect(Number.isFinite(stage.invalidationCents)).toBe(true);
      }
    }
  });
});

/* ================================================================ the capacity gate */

const BASIS = {
  referencePrice: "ARRIVAL_MID",
  sideConvention: "BUY_POSITIVE",
  aggregationMethod: "QUANTITY_WEIGHTED",
  weighting: "FILLED_QUANTITY",
} as const;

function present(input: (typeof CAPACITY_REQUIRED_INPUTS)[number]): CapacityInputFact {
  return { input, disposition: "PRESENT", provenance: "SYSTEM_RECORDED" };
}

/** A fully satisfied synthetic request. TEST-ONLY: no such evidence exists in the app. */
function satisfiedRequest(overrides: Partial<CapacityRequest> = {}): CapacityRequest {
  return {
    strategyVersion: "demo-version-v1",
    windowScope: "2026-01-01/2026-06-30",
    evaluationMs: Date.parse(ORIGIN),
    producer: "IMPLEMENTED",
    authorization: "AUTHORIZED",
    shortExposurePresent: false,
    inputs: [
      ...CAPACITY_REQUIRED_INPUTS.filter(
        (input) =>
          input !== "BORROW_AVAILABILITY_HISTORY" && input !== "PORTFOLIO_OVERLAP_SET",
      ).map(present),
      {
        input: "BORROW_AVAILABILITY_HISTORY",
        disposition: "NOT_APPLICABLE",
        absence: "NO_BORROW_HISTORY_G5_OPEN",
      },
      { input: "PORTFOLIO_OVERLAP_SET", disposition: "DETERMINED_EMPTY" },
    ],
    volumeCoversEverySecurity: true,
    windowCoverage: "COMPLETE",
    evidence: satisfiedEvidence(),
    ...overrides,
  };
}

function satisfiedEvidence(overrides: Partial<CapacityEvidence> = {}): CapacityEvidence {
  return {
    modelIdentity: "impact-model-synthetic-1",
    calibrationIdentity: "calibration-synthetic-1",
    qualification: {
      modelIdentity: "impact-model-synthetic-1",
      calibrationIdentity: "calibration-synthetic-1",
      evaluationSet: "locked-set-1",
      windowScope: "2026-01-01/2026-06-30",
      assessedOnMs: Date.parse("2026-07-01T00:00:00.000Z"),
      validUntilMs: Date.parse("2027-01-01T00:00:00.000Z"),
      decision: "ADMITTED",
    },
    search: {
      lowerEndpointCents: 0,
      upperEndpointCents: 100_000_000,
      granularityCents: 5_000_000,
      costFunction: "MONOTONE_NON_DECREASING",
      stoppingRule: "FIRST_INFEASIBLE_POINT",
      searchCompleted: true,
      capitalToScheduleMapping: "PRO_RATA_ACROSS_THE_RECORDED_POPULATION",
    },
    outcome: "INTERIOR_MAXIMUM",
    greatestFeasibleCents: 25_000_000,
    observedExecutionCostBasis: BASIS,
    modelledExecutionCostBasis: BASIS,
    costToleranceBpsHundredths: 400,
    observedExecutionCostBpsHundredths: 800,
    participationLimitHundredths: 500,
    executionHorizonSessions: 3,
    informationProfile: "PROVIDER_REALISTIC_PIT",
    ...overrides,
  };
}

describe("the capacity admission gate answers today's actual facts", () => {
  it("refuses at the required-input stage, because the inputs do not exist", () => {
    const result = capacityGate(
      currentCapacityRequest({
        strategyVersion: "breakout-long-v3",
        windowScope: "2026-01-01/2026-06-30",
        evaluationMs: Date.parse(ORIGIN),
        shortExposurePresent: true,
      }),
    );
    expect(result.availability).toBe("NOT_YET_AVAILABLE");
    expect(result.reason).toBe("UPSTREAM_INPUT_MISSING");
    expect(result.stage).toBe("REQUIRED_INPUTS");
    expect(result.valueCents).toBeNull();
    /* All nine are required when the population carries short exposure. */
    expect(result.missingInputs).toHaveLength(9);
    expect(result.notApplicableInputs).toHaveLength(0);
  });

  it("declares borrow history inapplicable for a long-only population, and is not blocked by it", () => {
    const longOnly = capacityGate(
      currentCapacityRequest({
        strategyVersion: "breakout-long-v3",
        windowScope: "w",
        evaluationMs: Date.parse(ORIGIN),
        shortExposurePresent: false,
      }),
    );
    expect(longOnly.missingInputs.map((f) => f.input)).not.toContain(
      "BORROW_AVAILABILITY_HISTORY",
    );
    expect(longOnly.notApplicableInputs.map((f) => f.input)).toEqual([
      "BORROW_AVAILABILITY_HISTORY",
    ]);
    expect(longOnly.missingInputs).toHaveLength(8);
  });

  it("distinguishes a determined-empty overlap set from an undetermined one", () => {
    const undetermined = capacityGate(
      satisfiedRequest({
        inputs: satisfiedRequest().inputs.map((fact) =>
          fact.input === "PORTFOLIO_OVERLAP_SET"
            ? { ...fact, disposition: "UNDETERMINED" as const, absence: "NO_STRATEGY_RUNTIME" as const }
            : fact,
        ),
      }),
    );
    expect(undetermined.availability).toBe("NOT_YET_AVAILABLE");
    expect(undetermined.stage).toBe("REQUIRED_INPUTS");
    /* NEGATIVE CONTROL: the determined-empty set is an ANSWER and admits. */
    expect(capacityGate(satisfiedRequest()).availability).toBe("AVAILABLE");
  });

  it("evaluates the stages in the declared order, first unmet condition answering", () => {
    /* No producer beats every other unmet condition. */
    const noProducer = capacityGate(
      satisfiedRequest({ producer: "NOT_IMPLEMENTED", authorization: "NOT_AUTHORIZED" }),
    );
    expect(noProducer.availability).toBe("NOT_IMPLEMENTED");
    expect(noProducer.reason).toBe("PRODUCER_NOT_IMPLEMENTED");
    expect(noProducer.stage).toBe("PRODUCER_EXISTENCE");

    /* Authorization beats a missing input. */
    const unauthorized = capacityGate(
      satisfiedRequest({ authorization: "NOT_AUTHORIZED", inputs: [] }),
    );
    expect(unauthorized.availability).toBe("NOT_AUTHORIZED");
    expect(unauthorized.stage).toBe("AUTHORIZATION");

    /* And a missing input beats an unqualified model. */
    const missing = capacityGate(satisfiedRequest({ inputs: [], evidence: undefined }));
    expect(missing.availability).toBe("NOT_YET_AVAILABLE");
    expect(missing.stage).toBe("REQUIRED_INPUTS");

    /*
     * AN INPUT-STAGE REFUSAL STILL BEATS AN UNQUALIFIED MODEL WHEN THE UNMET INPUT IS A
     * DECLARATION CARRIED ON THE EVIDENCE.
     *
     * §D2.11 puts every applicable input BEFORE model qualification, and a `PUBLIC_PIT`
     * profile and an incomparable cost basis each refuse AT the required-input stage. With
     * two conditions unmet at once the earlier stage is the answer — the ordering property
     * the whole gate rests on, tested where it is easiest to get wrong.
     */
    const refusedQualification = {
      modelIdentity: "impact-model-synthetic-1",
      calibrationIdentity: "calibration-synthetic-1",
      evaluationSet: "locked-set-1",
      windowScope: "2026-01-01/2026-06-30",
      assessedOnMs: Date.parse("2026-07-01T00:00:00.000Z"),
      validUntilMs: Date.parse("2027-01-01T00:00:00.000Z"),
      decision: "REFUSED" as const,
    };
    const forbiddenProfileAndUnassessed = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          informationProfile: "PUBLIC_PIT",
          qualification: undefined,
        }),
      }),
    );
    expect(forbiddenProfileAndUnassessed.availability).toBe("NOT_YET_AVAILABLE");
    expect(forbiddenProfileAndUnassessed.stage).toBe("REQUIRED_INPUTS");
    const incomparableAndRefused = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          modelledExecutionCostBasis: { ...BASIS, weighting: "EQUAL_WEIGHTED" },
          qualification: refusedQualification,
        }),
      }),
    );
    expect(incomparableAndRefused.availability).toBe("NOT_YET_AVAILABLE");
    expect(incomparableAndRefused.stage).toBe("REQUIRED_INPUTS");

    /*
     * NEGATIVE CONTROLS: with the input-stage condition met, the LATER stage answers. Without
     * these, an implementation that answered `REQUIRED_INPUTS` for everything would pass.
     */
    const unassessedOnly = capacityGate(
      satisfiedRequest({ evidence: satisfiedEvidence({ qualification: undefined }) }),
    );
    expect(unassessedOnly.availability).toBe("UNEVALUATED");
    expect(unassessedOnly.stage).toBe("MODEL_QUALIFICATION");
    const refusedOnly = capacityGate(
      satisfiedRequest({ evidence: satisfiedEvidence({ qualification: refusedQualification }) }),
    );
    expect(refusedOnly.availability).toBe("NOT_AUTHORIZED");
    expect(refusedOnly.stage).toBe("MODEL_QUALIFICATION");
  });

  it("treats an input nobody stated as missing rather than as satisfied", () => {
    const silent = capacityGate(satisfiedRequest({ inputs: [] }));
    expect(silent.availability).toBe("NOT_YET_AVAILABLE");
    expect(silent.missingInputs).toHaveLength(8);
  });
});

describe("model qualification is a recorded positive decision about this exact request", () => {
  it("refuses an unassessed model as UNEVALUATED, not as a missing input", () => {
    const result = capacityGate(
      satisfiedRequest({ evidence: satisfiedEvidence({ qualification: undefined }) }),
    );
    expect(result.availability).toBe("UNEVALUATED");
    expect(result.reason).toBe("NOT_YET_ASSESSED");
    expect(result.availability).not.toBe("NOT_YET_AVAILABLE");
    expect(result.valueCents).toBeNull();
  });

  it("refuses a record that refused the model as NOT_AUTHORIZED, not as unassessed", () => {
    const refused = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          qualification: { ...satisfiedEvidence().qualification!, decision: "REFUSED" },
        }),
      }),
    );
    expect(refused.availability).toBe("NOT_AUTHORIZED");
    expect(refused.reason).toBe("PRODUCER_NOT_AUTHORIZED");
    expect(refused.availability).not.toBe("UNEVALUATED");
  });

  it("refuses an expired qualification", () => {
    const expired = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          qualification: {
            ...satisfiedEvidence().qualification!,
            validUntilMs: Date.parse("2026-01-02T00:00:00.000Z"),
          },
        }),
      }),
    );
    expect(expired.availability).toBe("UNEVALUATED");
    expect(expired.reason).toBe("NOT_YET_ASSESSED");
  });

  it("refuses a qualification granted for a different model, calibration or window scope", () => {
    for (const wrong of [
      { modelIdentity: "some-other-model" },
      { calibrationIdentity: "some-other-calibration" },
      { windowScope: "1999-01-01/1999-12-31" },
    ]) {
      const result = capacityGate(
        satisfiedRequest({
          evidence: satisfiedEvidence({
            qualification: { ...satisfiedEvidence().qualification!, ...wrong },
          }),
        }),
      );
      expect(result.availability, JSON.stringify(wrong)).toBe("UNEVALUATED");
      expect(result.valueCents, JSON.stringify(wrong)).toBeNull();
    }
  });
});

describe("the declarations a produced value depends on are checked, not trusted", () => {
  it("refuses an incomparable cost basis", () => {
    const result = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          modelledExecutionCostBasis: { ...BASIS, weighting: "EQUAL_WEIGHTED" },
        }),
      }),
    );
    expect(result.availability).toBe("NOT_YET_AVAILABLE");
    expect(result.stage).toBe("REQUIRED_INPUTS");
    expect(result.valueCents).toBeNull();
  });

  it("refuses a missing capital-to-schedule mapping", () => {
    const result = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          search: { ...satisfiedEvidence().search, capitalToScheduleMapping: undefined },
        }),
      }),
    );
    expect(result.availability).toBe("NOT_YET_AVAILABLE");
    expect(result.valueCents).toBeNull();
  });

  it("refuses a non-monotone cost function stopped at the first infeasible point", () => {
    const stoppedEarly = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          search: {
            ...satisfiedEvidence().search,
            costFunction: "NON_MONOTONE",
            stoppingRule: "FIRST_INFEASIBLE_POINT",
          },
        }),
      }),
    );
    expect(stoppedEarly.availability).toBe("NOT_YET_AVAILABLE");
    /* NEGATIVE CONTROL: a full sweep of the same non-monotone function is admitted. */
    const swept = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          search: {
            ...satisfiedEvidence().search,
            costFunction: "NON_MONOTONE",
            stoppingRule: "FULL_DOMAIN_SWEEP",
          },
        }),
      }),
    );
    expect(swept.availability).toBe("AVAILABLE");
  });

  it("refuses an incomplete search and a grid whose lower endpoint is not zero", () => {
    for (const search of [
      { ...satisfiedEvidence().search, searchCompleted: false },
      { ...satisfiedEvidence().search, lowerEndpointCents: 1_000_000 },
      { ...satisfiedEvidence().search, granularityCents: 0 },
    ]) {
      const result = capacityGate(
        satisfiedRequest({ evidence: satisfiedEvidence({ search }) }),
      );
      expect(result.availability).toBe("NOT_YET_AVAILABLE");
      expect(result.valueCents).toBeNull();
    }
  });

  it("refuses a PUBLIC_PIT declaration", () => {
    const result = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({ informationProfile: "PUBLIC_PIT" }),
      }),
    );
    expect(result.availability).toBe("NOT_YET_AVAILABLE");
  });
});

describe("the search outcomes, and the one zero that is a measurement", () => {
  it("renders a computed zero as AVAILABLE carrying zero", () => {
    const result = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({ outcome: "ZERO_ONLY_FEASIBLE", greatestFeasibleCents: 0 }),
      }),
    );
    expect(result.availability).toBe("AVAILABLE");
    expect(result.reason).toBe("NONE");
    expect(result.valueCents).toBe(0);
    expect(result.computedZero).toBe(true);
  });

  it("renders an empty feasible set as NOT_APPLICABLE with no value, and never as zero", () => {
    const result = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          outcome: "EMPTY_FEASIBLE_SET",
          greatestFeasibleCents: undefined,
        }),
      }),
    );
    expect(result.availability).toBe("NOT_APPLICABLE");
    expect(result.reason).toBe("NOT_DEFINED_FOR_SUBJECT");
    expect(result.valueCents).toBeNull();
    expect(result.computedZero).toBe(false);
    /* THE DISTINCTION: a computed zero carries 0; an empty feasible set carries nothing. */
    const zero = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({ outcome: "ZERO_ONLY_FEASIBLE", greatestFeasibleCents: 0 }),
      }),
    );
    expect(zero.valueCents).not.toBe(result.valueCents);
  });

  it("renders a still-feasible upper endpoint as PARTIAL and a lower bound", () => {
    const result = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          outcome: "UPPER_ENDPOINT_FEASIBLE",
          greatestFeasibleCents: 100_000_000,
        }),
      }),
    );
    expect(result.availability).toBe("PARTIAL");
    expect(result.reason).toBe("EXTENT_PARTIALLY_COVERED");
    expect(result.lowerBoundOnly).toBe(true);
    expect(result.valueCents).toBe(100_000_000);
  });

  it("refuses a feasible outcome that carries no evaluated point rather than substituting zero", () => {
    const result = capacityGate(
      satisfiedRequest({
        evidence: satisfiedEvidence({
          outcome: "INTERIOR_MAXIMUM",
          greatestFeasibleCents: undefined,
        }),
      }),
    );
    expect(result.availability).toBe("NOT_YET_AVAILABLE");
    expect(result.valueCents).toBeNull();
  });

  it("refuses volume history that does not cover every security", () => {
    const result = capacityGate(satisfiedRequest({ volumeCoversEverySecurity: false }));
    expect(result.availability).toBe("INSUFFICIENT_OBSERVATIONS");
    expect(result.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
    expect(result.valueCents).toBeNull();
  });

  it("labels a value resting on synthetic inputs as synthetic", () => {
    const result = capacityGate(
      satisfiedRequest({
        inputs: satisfiedRequest().inputs.map((fact) =>
          fact.disposition === "PRESENT" ? { ...fact, provenance: "SYNTHETIC" as const } : fact,
        ),
      }),
    );
    expect(result.availability).toBe("AVAILABLE");
    expect(result.synthetic).toBe(true);
    expect(capacityGate(satisfiedRequest()).synthetic).toBe(false);
  });
});

/* =============================================== the real read path, and the versions */

describe("the capacity contract is enforced on the actual read path", () => {
  it("answers every strategy performance row through the gate, with its declaration", async () => {
    const read = client();
    const response = await read.strategyPerformance(DEMO);
    expect(() =>
      admit("StrategyPerformance", strategyPerformanceEnvelope, response, "PUBLIC_EDGE"),
    ).not.toThrow();
    const payload = response.payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;
    expect(payload.items.length).toBeGreaterThan(0);
    for (const entry of payload.items) {
      const metric = entry.module_metrics.capacity;
      const declaration = entry.module_metrics.capacity_declaration;
      expect(metric.availability, entry.strategy_version).toBe("NOT_YET_AVAILABLE");
      expect(metric.reason, entry.strategy_version).toBe("UPSTREAM_INPUT_MISSING");
      /* NO ABSENCE IS FILLED WITH A VALUE, of any kind. */
      expect(metric.value, entry.strategy_version).toBeUndefined();
      expect(declaration.stage.code, entry.strategy_version).toBe("REQUIRED_INPUTS");
      expect(declaration.missing_inputs.length, entry.strategy_version).toBeGreaterThan(0);
      expect(declaration.model, entry.strategy_version).toBeUndefined();
      expect(declaration.computed_zero, entry.strategy_version).toBe(false);
      for (const missing of declaration.missing_inputs) {
        expect(
          (CAPACITY_REQUIRED_INPUTS as readonly string[]).includes(missing.input.code),
        ).toBe(true);
      }
    }
    /* THE BORROW CONDITION IS EXERCISED IN BOTH DIRECTIONS BY THE REAL BOOK. */
    const applicability = payload.items.map(
      (entry) => entry.module_metrics.capacity_declaration.not_applicable_inputs.length,
    );
    expect(applicability.some((count) => count === 0)).toBe(true);
    expect(applicability.some((count) => count > 0)).toBe(true);
  });

  it("answers every research run through the same gate", async () => {
    const read = client();
    const response = await read.researchRuns(DEMO);
    expect(() =>
      admit("ResearchRun", researchRunEnvelope, response, "PUBLIC_EDGE"),
    ).not.toThrow();
    const payload = response.payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;
    expect(payload.items.length).toBeGreaterThan(0);
    for (const run of payload.items) {
      expect(run.capacity.availability).toBe("NOT_YET_AVAILABLE");
      expect(run.capacity.value).toBeUndefined();
      expect(run.capacity_declaration.stage.code).toBe("REQUIRED_INPUTS");
      expect(run.capacity_declaration.model).toBeUndefined();
    }
  });

  it("never fills a capacity from strategy capital, exposure or any limit", async () => {
    const read = client();
    const payload = (await read.strategyPerformance(DEMO)).payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;
    const forbidden = ["80000.00", "80,000.00", "0.00", "0"];
    for (const entry of payload.items) {
      expect(forbidden).not.toContain(String(entry.module_metrics.capacity.value));
      expect(entry.module_metrics.capacity.value).toBeUndefined();
    }
  });
});

describe("metric dictionary and read-model versions", () => {
  it("advanced the dictionary version, and refuses the stale one at the boundary", () => {
    expect(METRIC_DEFINITION_VERSION).toBe("metrics.v2");
    const good = {
      value: "-2.50",
      unit: "R_MULTIPLE",
      availability: "AVAILABLE",
      reason: "NONE",
      as_of: ORIGIN,
      metric_id: "strategy.tail_loss",
      metric_definition_version: METRIC_DEFINITION_VERSION,
    };
    expect(metricValue.safeParse(good).success).toBe(true);
    /* NEGATIVE CONTROL: the retired dictionary version is refused, never coerced. */
    const stale = { ...good, metric_definition_version: "metrics.v1" };
    expect(metricValue.safeParse(stale).success).toBe(false);
  });

  it("moved exactly the read models whose payload or meaning changed", () => {
    expect(STRATEGY_HEALTH_SCHEMA).toBe("cockpit.strategy_health.v2");
    expect(STRATEGY_PERFORMANCE_SCHEMA).toBe("cockpit.strategy_performance.v4");
    expect(RESEARCH_RUN_SCHEMA).toBe("cockpit.research_run.v2");
    /* AND LEFT THE ONE THAT DID NOT CHANGE ALONE. */
    expect(PERFORMANCE_SERIES_SCHEMA).toBe("cockpit.performance_series.v3");
  });

  it("refuses a response carrying a superseded schema version through the real admission path", async () => {
    const read = client();
    const response = await read.strategyHealth(DEMO);
    const stale = clone(response);
    (stale as { schema_version: string }).schema_version = "cockpit.strategy_health.v1";
    expect(() =>
      admit("StrategyHealth", strategyHealthEnvelope, stale, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses a health payload whose tail-loss disclosure disagrees with its own value", async () => {
    const read = client();
    const response = await read.strategyHealth(DEMO);
    const payload = response.payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;
    const valued = payload.items.find(
      (entry) => entry.tail_loss.value.value !== undefined,
    );
    expect(valued, "the book must contain at least one valued tail loss").toBeDefined();
    if (valued === undefined) return;

    /* NEGATIVE CONTROL: a tail count that is not ceil(q * n) is refused at the boundary. */
    const wrongCount = clone(response);
    const target = wrongCount.payload!.items.find(
      (entry) => entry.strategy_version === valued.strategy_version,
    )!;
    target.tail_loss.tail_observations.value = 5;
    expect(() =>
      admit("StrategyHealth", strategyHealthEnvelope, wrongCount, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);

    /* NEGATIVE CONTROL: a PARTIAL value naming no exclusion is refused. */
    const fakePartial = clone(response);
    const partialTarget = fakePartial.payload!.items.find(
      (entry) => entry.strategy_version === valued.strategy_version,
    )!;
    partialTarget.tail_loss.value.availability = "PARTIAL";
    partialTarget.tail_loss.value.reason = "UPSTREAM_INPUT_MISSING";
    partialTarget.tail_loss.excluded_observations.value = 0;
    expect(() =>
      admit("StrategyHealth", strategyHealthEnvelope, fakePartial, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses an insufficient tail loss that carries contributing observations", async () => {
    const read = client();
    const response = await read.strategyHealth(DEMO);
    const short = response.payload!.items.find(
      (entry) => entry.tail_loss.value.availability === "INSUFFICIENT_OBSERVATIONS",
    );
    expect(short, "the book must contain at least one insufficient tail loss").toBeDefined();
    if (short === undefined) return;
    const forged = clone(response);
    const target = forged.payload!.items.find(
      (entry) => entry.strategy_version === short.strategy_version,
    )!;
    target.tail_loss.tail_observations.value = 3;
    expect(() =>
      admit("StrategyHealth", strategyHealthEnvelope, forged, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });
});
