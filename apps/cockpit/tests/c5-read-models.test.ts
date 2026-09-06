import { describe, expect, it } from "vitest";

import {
  exposureAggregateEnvelope,
  performanceSummaryEnvelope,
  positionSnapshotEnvelope,
  tradeDetailEnvelope,
  tradeLifecycleEnvelope,
  tradeSummaryEnvelope,
} from "@/contracts/portfolio-models";
import { performanceSeriesEnvelope } from "@/contracts/read-models";
import { strategyPerformanceEnvelope } from "@/contracts/strategy-models";
import {
  marketRegimeEnvelope,
  riskSnapshotEnvelope,
  shortSideSnapshotEnvelope,
} from "@/contracts/risk-market-models";
import { C3_METRIC_DICTIONARY, hundredths, metricValue } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";
import { readModelKey } from "@/data/client/query-keys";
import {
  POSITION_SNAPSHOT_IDENTITY,
  READ_MODEL_IDENTITIES,
  TRADE_DETAIL_IDENTITY,
  TRADE_LIFECYCLE_IDENTITY,
} from "@/data/client/read-model-identity";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import {
  BOOK,
  MISSING_RISK_RECORD_TRADE,
  PARTIAL_PATH_TRADE,
  STALE_ASSESSMENT_TRADE,
  STRATEGY_CAPITAL_CENTS,
  centsToDecimal,
  positionValueCents,
} from "@/data/fixtures/book";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE, PERFORMANCE_PERIODS } from "@/lib/scope";

/**
 * The C5 read models, their invariants, and the fixture they are projected from.
 *
 * EVERY EXPECTED VALUE HERE IS COMPUTED INDEPENDENTLY. A test that reads the same helper the
 * fixture used would agree with the fixture whatever the fixture did; these recompute the
 * arithmetic from the book's raw stages, exits, marks and share counts, so a defect in a
 * projection is a disagreement rather than a shared mistake.
 */

const ORIGIN = "2026-09-06T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };
const PROJECT = DEFAULT_SCOPE;

function client() {
  return new FixtureReadClient({ clock: fixedClock(ORIGIN) });
}

/* ============================================================ admission */

describe("C5 admission", () => {
  it("admits every C5 read model in the demonstration scenario", async () => {
    const read = client();
    const responses = [
      await read.positions(DEMO),
      await read.exposure(DEMO),
      await read.trades(DEMO),
      await read.strategyPerformance(DEMO),
      await read.riskSnapshot(DEMO),
      await read.shortSide(DEMO),
      await read.marketRegime(DEMO),
      await read.performanceSummary(DEMO, "ALL"),
      await read.tradeDetail(DEMO, "demo-trade-cir-0003"),
      await read.tradeLifecycle(DEMO, "demo-trade-cir-0003"),
    ];
    for (const response of responses) {
      expect(response.payload).toBeDefined();
      expect(response.availability).toBe("AVAILABLE");
      expect(response.provenance).toBe("SYNTHETIC");
      expect(response.classification).toBe("PUBLIC_SAFE");
      expect(response.environment).toBe("RESEARCH");
    }
  });

  it("answers every C5 read model PAYLOADLESS in project scope", async () => {
    const read = client();
    const responses = [
      await read.positions(PROJECT),
      await read.exposure(PROJECT),
      await read.trades(PROJECT),
      await read.strategyPerformance(PROJECT),
      await read.riskSnapshot(PROJECT),
      await read.shortSide(PROJECT),
      await read.marketRegime(PROJECT),
      await read.performanceSummary(PROJECT, "3M"),
      await read.tradeDetail(PROJECT, "demo-trade-cir-0003"),
      await read.tradeLifecycle(PROJECT, "demo-trade-cir-0003"),
    ];
    for (const response of responses) {
      expect(response.payload).toBeUndefined();
      expect(response.availability).toBe("NOT_IMPLEMENTED");
      expect(response.availability_reason).toBe("PRODUCER_NOT_IMPLEMENTED");
      /*
       * A payloadless absence PINS NOTHING and has CONSUMED NOTHING to a position. It still
       * carries the runtime environment the question was asked in, which is a property of the
       * request rather than a claim about a strategy version.
       */
      expect(response.pins).toBeUndefined();
      expect(response.watermark).toBeUndefined();
      expect(response.completeness).toBe("UNKNOWN");
    }
  });

  it("answers an unpopulated environment PAYLOADLESS in the demonstration scenario too", async () => {
    const read = client();
    for (const environment of ["PAPER", "LIVE"] as const) {
      const scope = { ...DEMO, environment };
      expect((await read.positions(scope)).payload).toBeUndefined();
      expect((await read.trades(scope)).payload).toBeUndefined();
      expect((await read.riskSnapshot(scope)).payload).toBeUndefined();
    }
  });

  it("reports an unknown trade identity as inapplicable, never as an error", async () => {
    const read = client();
    for (const response of [
      await read.tradeDetail(DEMO, "demo-trade-does-not-exist"),
      await read.tradeLifecycle(DEMO, "demo-trade-does-not-exist"),
    ]) {
      expect(response.availability).toBe("NOT_APPLICABLE");
      expect(response.availability_reason).toBe("NOT_DEFINED_FOR_SUBJECT");
      expect(response.payload).toBeUndefined();
    }
  });
});

/* ================================================= malformed payload rejection */

describe("malformed C5 payloads are refused at the boundary", () => {
  async function admitted<T>(build: () => Promise<{ payload?: T }>) {
    const response = await build();
    expect(response.payload).toBeDefined();
    return JSON.parse(JSON.stringify(response)) as Record<string, unknown>;
  }

  it("refuses a position whose exposure magnitudes do not add up", async () => {
    const response = await admitted(() => client().exposure(DEMO));
    const payload = response.payload as {
      items: { buckets: { gross: { amount: string } }[] }[];
    };
    payload.items[0].buckets[0].gross.amount = "999999.00";
    expect(exposureAggregateEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a short position carrying no borrow state", async () => {
    const response = await admitted(() => client().positions(DEMO));
    const payload = response.payload as {
      items: { direction: string; borrow_state?: unknown }[];
    };
    const short = payload.items.find((item) => item.direction === "SHORT");
    expect(short).toBeDefined();
    delete short?.borrow_state;
    expect(positionSnapshotEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses an OPEN trade that reports a realized result", async () => {
    const response = await admitted(() => client().trades(DEMO));
    const payload = response.payload as {
      items: { trade_status: string; realized_pnl: Record<string, unknown> }[];
    };
    const open = payload.items.find((item) => item.trade_status === "OPEN");
    expect(open).toBeDefined();
    if (open !== undefined) {
      open.realized_pnl = { ...open.realized_pnl, value: "0.00", availability: "AVAILABLE", reason: "NONE", as_of: ORIGIN };
    }
    expect(tradeSummaryEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses an R multiple computed with no initial planned risk record", async () => {
    const response = await admitted(() => client().trades(DEMO));
    const payload = response.payload as {
      items: {
        trade_id: string;
        r_multiple: Record<string, unknown>;
      }[];
    };
    const orphan = payload.items.find((item) => item.trade_id === MISSING_RISK_RECORD_TRADE);
    expect(orphan, "the fixture carries one trade with no entry-time risk record").toBeDefined();
    if (orphan !== undefined) {
      orphan.r_multiple = {
        ...orphan.r_multiple,
        value: "1.00",
        availability: "AVAILABLE",
        reason: "NONE",
        as_of: ORIGIN,
      };
    }
    expect(tradeSummaryEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a summary whose ratio is value-bearing below its own declared minimum", async () => {
    const response = await admitted(() => client().performanceSummary(DEMO, "ALL"));
    const payload = response.payload as {
      observation_rules: { metric_id: string; met: boolean }[];
      win_rate: Record<string, unknown>;
    };
    const rule = payload.observation_rules.find((entry) => entry.metric_id === "win_rate");
    expect(rule).toBeDefined();
    if (rule !== undefined) {
      rule.met = false;
    }
    expect(performanceSummaryEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a lifecycle whose events are out of order", async () => {
    const response = await admitted(() =>
      client().tradeLifecycle(DEMO, "demo-trade-nvl-0002"),
    );
    const payload = response.payload as { events: { event_time: string }[] };
    expect(payload.events.length).toBeGreaterThan(1);
    payload.events.reverse();
    expect(tradeLifecycleEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a trade detail whose embedded summary describes another trade", async () => {
    const response = await admitted(() => client().tradeDetail(DEMO, "demo-trade-arb-0001"));
    const payload = response.payload as { summary: { trade_id: string } };
    payload.summary.trade_id = "demo-trade-nvl-0002";
    expect(tradeDetailEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a gap that claims to be a value-bearing state", async () => {
    const response = await admitted(() => client().tradeDetail(DEMO, "demo-trade-arb-0001"));
    const payload = response.payload as {
      gaps: { availability: string; reason: string }[];
    };
    payload.gaps[0].availability = "AVAILABLE";
    payload.gaps[0].reason = "NONE";
    expect(tradeDetailEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a threshold that states a value with no governing policy reference", async () => {
    const response = await admitted(() => client().riskSnapshot(DEMO));
    const payload = response.payload as {
      loss_thresholds: { value: Record<string, unknown> }[];
    };
    payload.loss_thresholds[0].value = {
      ...payload.loss_thresholds[0].value,
      value: "1000.00",
      availability: "AVAILABLE",
      reason: "NONE",
      as_of: ORIGIN,
    };
    expect(riskSnapshotEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses an unknown schema version rather than coercing it", async () => {
    const response = await admitted(() => client().shortSide(DEMO));
    response.schema_version = "cockpit.short_side_snapshot.v2";
    expect(shortSideSnapshotEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a regime whose declared information profile is not a member", async () => {
    const response = await admitted(() => client().marketRegime(DEMO));
    const payload = response.payload as { information_profile: string };
    payload.information_profile = "BEST_EFFORT";
    expect(marketRegimeEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a strategy summary whose expectancy carries the wrong metric identity", async () => {
    const response = await admitted(() => client().strategyPerformance(DEMO));
    const payload = response.payload as {
      items: { summary: { total_return: Record<string, unknown> } }[];
    };
    payload.items[0].summary.total_return = {
      ...payload.items[0].summary.total_return,
      metric_id: "return.money_weighted",
    };
    expect(strategyPerformanceEnvelope.safeParse(response).success).toBe(false);
  });

  it("refuses a series that claims a drawdown above zero", async () => {
    const response = await admitted(() => client().performanceSeries(DEMO));
    const payload = response.payload as {
      drawdown_series: { points: { v: Record<string, unknown> }[] };
    };
    payload.drawdown_series.points[1].v = {
      ...payload.drawdown_series.points[1].v,
      value: "4.20",
    };
    expect(performanceSeriesEnvelope.safeParse(response).success).toBe(false);
  });
});

/* ============================================ metric identity, unit and precision */

describe("metric identity, unit, precision and denominator", () => {
  /** Walks every `MetricValue` in a payload, so no field escapes the dictionary check. */
  function metrics(value: unknown, found: unknown[] = []): unknown[] {
    if (Array.isArray(value)) {
      for (const entry of value) metrics(entry, found);
      return found;
    }
    if (typeof value !== "object" || value === null) {
      return found;
    }
    const candidate = value as Record<string, unknown>;
    if (
      typeof candidate.metric_id === "string" &&
      typeof candidate.metric_definition_version === "string" &&
      typeof candidate.availability === "string"
    ) {
      found.push(candidate);
    }
    for (const entry of Object.values(candidate)) metrics(entry, found);
    return found;
  }

  it("carries only dictionary metrics, in their dictionary units, everywhere", async () => {
    const read = client();
    const payloads = [
      (await read.positions(DEMO)).payload,
      (await read.exposure(DEMO)).payload,
      (await read.trades(DEMO)).payload,
      (await read.strategyPerformance(DEMO)).payload,
      (await read.riskSnapshot(DEMO)).payload,
      (await read.shortSide(DEMO)).payload,
      (await read.marketRegime(DEMO)).payload,
      (await read.performanceSummary(DEMO, "ALL")).payload,
      (await read.tradeDetail(DEMO, "demo-trade-cir-0003")).payload,
    ];
    let checked = 0;
    for (const payload of payloads) {
      for (const candidate of metrics(payload)) {
        const parsed = metricValue.safeParse(candidate);
        expect(parsed.success, JSON.stringify(candidate)).toBe(true);
        const metric = candidate as { metric_id: string; unit: string };
        expect(C3_METRIC_DICTIONARY[metric.metric_id], metric.metric_id).toBeDefined();
        expect(metric.unit).toBe(C3_METRIC_DICTIONARY[metric.metric_id].unit);
        checked += 1;
      }
    }
    expect(checked).toBeGreaterThan(400);
  });

  it("states a decimal string at the precision its metric declares", async () => {
    const positions = await client().positions(DEMO);
    for (const item of positions.payload?.items ?? []) {
      for (const metric of [item.entry_price, item.current_price]) {
        expect(typeof metric.value).toBe("string");
        expect(String(metric.value)).toMatch(/^-?\d+\.\d{2}$/);
      }
    }
  });

  it("names the denominator of every ratio that carries one", async () => {
    const positions = await client().positions(DEMO);
    for (const item of positions.payload?.items ?? []) {
      const record = item.initial_planned_risk.record;
      expect(record?.risk_pct_of_capital.denominator).toBe("STRATEGY_CAPITAL_AT_ENTRY");
    }
  });

  it("returns INSUFFICIENT_OBSERVATIONS rather than a ratio below a declared minimum", async () => {
    const strategy = await client().strategyPerformance(DEMO);
    const items = strategy.payload?.items ?? [];
    const below = items.filter((item) =>
      item.summary.observation_rules.some((rule) => !rule.met),
    );
    expect(below.length, "the book is built so some populations fall short").toBeGreaterThan(0);
    for (const item of below) {
      for (const rule of item.summary.observation_rules.filter((entry) => !entry.met)) {
        const field =
          rule.metric_id === "win_rate"
            ? item.summary.win_rate
            : rule.metric_id === "profit_factor"
              ? item.summary.profit_factor
              : rule.metric_id === "sharpe"
                ? item.summary.sharpe
                : item.summary.expectancy;
        expect(field.availability).toBe("INSUFFICIENT_OBSERVATIONS");
        expect(field.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
        expect(field.value).toBeUndefined();
      }
    }
  });

  it("reports a slice with no trades as an empty population rather than a zero ratio", async () => {
    const strategy = await client().strategyPerformance(DEMO);
    const slices = (strategy.payload?.items ?? []).flatMap((item) => item.slices);
    const empty = slices.filter((slice) => slice.summary.observation_count.value === 0);
    expect(empty.length).toBeGreaterThanOrEqual(0);
    for (const slice of empty) {
      expect(isValueBearing(slice.summary.win_rate.availability)).toBe(false);
      expect(isValueBearing(slice.summary.expectancy.availability)).toBe(false);
    }
  });
});

/* ==================================================== cash flows are never profit */

describe("cash flows are never profit", () => {
  it("moves equity by the flow and moves neither return nor drawdown", async () => {
    const series = await client().performanceSeries({ ...DEMO, period: "3M" });
    const payload = series.payload;
    expect(payload).toBeDefined();
    if (payload === undefined) return;
    expect(payload.cash_flows.length, "the window contains one deposit").toBeGreaterThan(0);

    const flowDay = payload.cash_flows[0].at.slice(0, 10);
    const index = payload.equity.points.findIndex((point) => point.t === flowDay);
    expect(index).toBeGreaterThan(0);

    const flowCents = hundredths(payload.cash_flows[0].amount.amount) ?? 0;
    expect(flowCents).toBeGreaterThan(0);

    const equityBefore = hundredths(String(payload.equity.points[index - 1].v.value)) ?? 0;
    const equityAfter = hundredths(String(payload.equity.points[index].v.value)) ?? 0;
    /*
     * The equity step across the flow session contains the flow. It is not EXACTLY the flow,
     * because the book also marked to market that session — which is the point: equity moved
     * by the flow PLUS the market, and the two series below moved by the market alone.
     */
    expect(equityAfter - equityBefore).toBeGreaterThan(flowCents / 2);

    const returnBefore = hundredths(String(payload.return_series.points[index - 1].v.value)) ?? 0;
    const returnAfter = hundredths(String(payload.return_series.points[index].v.value)) ?? 0;
    const returnStepPct = Math.abs(returnAfter - returnBefore) / 100;
    /*
     * A USD 5,000 deposit on a book of roughly USD 90,000 is over 5%. If the flow reached the
     * return series, this step would be enormous; a market move on one session is not.
     */
    expect(returnStepPct).toBeLessThan(2);

    for (const point of payload.drawdown_series.points) {
      const value = hundredths(String(point.v.value)) ?? 0;
      expect(value, "a drawdown is never positive").toBeLessThanOrEqual(0);
    }
  });

  it("states the sign convention and agrees with the flow kind", async () => {
    const series = await client().performanceSeries({ ...DEMO, period: "ALL" });
    for (const flow of series.payload?.cash_flows ?? []) {
      expect(flow.amount.sign_convention).toBe("INFLOW_POSITIVE_OUTFLOW_NEGATIVE");
      const negative = flow.amount.amount.startsWith("-");
      expect(negative).toBe(flow.kind === "WITHDRAWAL");
    }
  });

  it("excludes external flows from every profit figure", async () => {
    const overview = await client().executiveOverview(DEMO);
    const cumulative = overview.payload?.pnl.find((entry) => entry.window === "CUMULATIVE");
    const realized = hundredths(String(cumulative?.realized.value)) ?? 0;
    /*
     * INDEPENDENTLY RECOMPUTED from the book's exits. If a deposit had reached the profit
     * figure it would exceed this sum by the flow.
     */
    const expected = BOOK.trades.reduce(
      (total, trade) =>
        total + trade.exits.reduce((subtotal, exit) => subtotal + exit.realizedCents, 0),
      0,
    );
    expect(realized).toBe(Math.round(expected));
  });
});

/* ==================================== long, short, gross and net; totals reconcile */

describe("exposure arithmetic and portfolio totals", () => {
  /** The expected magnitudes, recomputed from the book's own share counts and marks. */
  function expected() {
    const open = BOOK.openTrades;
    const long = open
      .filter((trade) => trade.direction === "LONG")
      .reduce((total, trade) => total + trade.sharesOpen * (trade.markCents ?? 0), 0);
    const short = open
      .filter((trade) => trade.direction === "SHORT")
      .reduce((total, trade) => total + trade.sharesOpen * (trade.markCents ?? 0), 0);
    return { long, short, gross: long + short, net: Math.abs(long - short) };
  }

  it("reconciles the exposure totals with the positions they were aggregated from", async () => {
    const read = client();
    const exposure = await read.exposure(DEMO);
    const positions = await read.positions(DEMO);
    const totals = exposure.payload?.totals;
    const want = expected();

    expect(hundredths(totals?.long.amount ?? "")).toBe(want.long);
    expect(hundredths(totals?.short.amount ?? "")).toBe(want.short);
    expect(hundredths(totals?.gross.amount ?? "")).toBe(want.gross);
    expect(hundredths(totals?.net.amount ?? "")).toBe(want.net);
    expect(totals?.position_count.value).toBe(positions.payload?.items.length);
  });

  it("reconciles the executive overview's exposure with the positions", async () => {
    const overview = await client().executiveOverview(DEMO);
    const want = expected();
    expect(hundredths(overview.payload?.exposure.long.amount ?? "")).toBe(want.long);
    expect(hundredths(overview.payload?.exposure.short.amount ?? "")).toBe(want.short);
    expect(hundredths(overview.payload?.exposure.gross.amount ?? "")).toBe(want.gross);
    expect(hundredths(overview.payload?.exposure.net.amount ?? "")).toBe(want.net);
  });

  it("counts every position exactly once on every grouping axis", async () => {
    const exposure = await client().exposure(DEMO);
    const totals = exposure.payload?.totals;
    for (const aggregate of exposure.payload?.items ?? []) {
      const positions = aggregate.buckets.reduce(
        (total, bucket) => total + Number(bucket.position_count.value ?? 0),
        0,
      );
      expect(positions, aggregate.grouping.code).toBe(totals?.position_count.value);

      const gross = aggregate.buckets.reduce(
        (total, bucket) => total + (hundredths(bucket.gross.amount) ?? 0),
        0,
      );
      expect(gross, aggregate.grouping.code).toBe(hundredths(totals?.gross.amount ?? ""));
    }
  });

  it("keeps every magnitude positive and carries the side in its direction", async () => {
    const exposure = await client().exposure(DEMO);
    for (const aggregate of exposure.payload?.items ?? []) {
      for (const bucket of aggregate.buckets) {
        for (const magnitude of [bucket.long, bucket.short, bucket.gross, bucket.net]) {
          expect(magnitude.amount.startsWith("-")).toBe(false);
        }
        expect(bucket.long.direction).toBe("LONG");
        expect(bucket.short.direction).toBe("SHORT");
      }
    }
  });

  it("keeps gross short inside the governed research parameter", async () => {
    const short = await client().shortSide(DEMO);
    const grossShort = hundredths(short.payload?.gross_short.amount ?? "") ?? 0;
    // CLAUDE.md section 6: at most 25% of the authoritative strategy capital.
    expect(grossShort).toBeLessThanOrEqual(STRATEGY_CAPITAL_CENTS / 4);
  });
});

/* ============================================ trades: identity, adds, partial exits */

describe("trade identity, adds and partial exits", () => {
  it("counts a fill as a fill and never as a trade", async () => {
    const trades = await client().trades(DEMO);
    const ids = (trades.payload?.items ?? []).map((item) => item.trade_id);
    expect(new Set(ids).size).toBe(ids.length);

    const pyramided = trades.payload?.items.find(
      (item) => item.trade_id === "demo-trade-nvl-0002",
    );
    const lifecycle = await client().tradeLifecycle(DEMO, "demo-trade-nvl-0002");
    // Two recorded stages, and ONE row in the ledger.
    expect(lifecycle.payload?.events.length).toBe(2);
    expect(pyramided).toBeDefined();
    expect(ids.filter((id) => id === "demo-trade-nvl-0002").length).toBe(1);
  });

  it("reduces a partially exited trade rather than closing it or splitting it", async () => {
    const trades = await client().trades(DEMO);
    const partial = trades.payload?.items.find(
      (item) => item.trade_id === "demo-trade-cir-0003",
    );
    expect(partial?.trade_status).toBe("PARTIALLY_EXITED");
    expect(partial?.shares_open).toBeLessThan(partial?.shares_at_entry ?? 0);
    expect(partial?.shares_open).toBeGreaterThan(0);
    // Realized on the closed portion AND unrealized on the remaining one.
    expect(isValueBearing(partial?.realized_pnl.availability ?? "ERROR")).toBe(true);
    expect(isValueBearing(partial?.unrealized_pnl.availability ?? "ERROR")).toBe(true);
    // And the trade has NOT exited: the exit fields do not apply to it.
    expect(partial?.exit_time.availability).toBe("NOT_APPLICABLE");
    expect(partial?.exit_price.availability).toBe("NOT_APPLICABLE");
  });

  it("keeps the initial planned risk record unchanged when the stop has moved", async () => {
    const positions = await client().positions(DEMO);
    const trailed = positions.payload?.items.find(
      (item) => item.security.symbol === "DEMO.ARB",
    );
    const book = BOOK.openTrades.find((trade) => trade.symbol === "DEMO.ARB");
    expect(book).toBeDefined();
    if (book === undefined) return;

    // The book moved this position's protective level away from its entry invalidation.
    expect(book.currentStopCents).not.toBe(book.stages[0].invalidationCents);

    /* INDEPENDENTLY RECOMPUTED: shares at entry x |entry - entry invalidation|. */
    const expectedInitial =
      book.stages[0].shares *
      Math.abs(book.stages[0].priceCents - book.stages[0].invalidationCents);
    expect(hundredths(trailed?.initial_planned_risk.record?.risk_money.amount ?? "")).toBe(
      expectedInitial,
    );

    /* And the assessment moved with the stop: shares open x |current stop - mark|. */
    const expectedOpen =
      book.sharesOpen * Math.abs((book.currentStopCents ?? 0) - (book.markCents ?? 0));
    expect(
      hundredths(String(trailed?.open_planned_risk.record?.risk_money.value ?? "")),
    ).toBe(expectedOpen);
    expect(expectedOpen).not.toBe(expectedInitial);
  });

  it("sums the retained per-stage initial risks for a pyramided trade", async () => {
    const trades = await client().trades(DEMO);
    const pyramided = trades.payload?.items.find(
      (item) => item.trade_id === "demo-trade-nvl-0002",
    );
    const book = BOOK.openTrades.find((trade) => trade.tradeId === "demo-trade-nvl-0002");
    expect(book?.stages.length).toBe(2);
    const expected = (book?.stages ?? []).reduce(
      (total, stage) =>
        total + stage.shares * Math.abs(stage.priceCents - stage.invalidationCents),
      0,
    );
    expect(hundredths(pyramided?.initial_planned_risk.record?.risk_money.amount ?? "")).toBe(
      expected,
    );
  });

  it("reports no R for a trade whose entry-time risk record was never written", async () => {
    const trades = await client().trades(DEMO);
    const orphan = trades.payload?.items.find(
      (item) => item.trade_id === MISSING_RISK_RECORD_TRADE,
    );
    expect(orphan).toBeDefined();
    expect(orphan?.initial_planned_risk.availability).toBe("NOT_YET_AVAILABLE");
    expect(orphan?.initial_planned_risk.reason).toBe("UPSTREAM_INPUT_MISSING");
    expect(orphan?.r_multiple.availability).toBe("NOT_YET_AVAILABLE");
    expect(orphan?.r_multiple.value).toBeUndefined();
  });

  it("keeps business status and data completeness as separate facts", async () => {
    const trades = await client().trades(DEMO);
    const incomplete = trades.payload?.items.find(
      (item) => item.trade_id === PARTIAL_PATH_TRADE,
    );
    expect(incomplete).toBeDefined();
    // COMPLETE in status, PARTIAL in completeness. Neither is inferred from the other.
    expect(incomplete?.trade_status).toBe("CLOSED");
    expect(incomplete?.data_completeness).toBe("PARTIAL");
    // And its path-dependent values are PARTIAL rather than optimistic.
    expect(incomplete?.mfe.availability).toBe("PARTIAL");
    expect(incomplete?.mae.availability).toBe("PARTIAL");
  });

  it("computes R against the initial planned risk and nothing else", async () => {
    const trades = await client().trades(DEMO);
    for (const item of trades.payload?.items ?? []) {
      if (!isValueBearing(item.r_multiple.availability)) {
        continue;
      }
      const book = BOOK.trades.find((trade) => trade.tradeId === item.trade_id);
      expect(book).toBeDefined();
      if (book === undefined) continue;
      /* INDEPENDENTLY RECOMPUTED from the raw book, at the metric's declared precision. */
      const expected = Math.round(
        ((book.realizedCents + book.unrealizedCents) * 100) / book.initialRiskCents,
      );
      expect(String(item.r_multiple.value)).toBe(centsToDecimal(expected));
    }
  });

  it("reconciles the ledger's realized total with the portfolio's", async () => {
    const read = client();
    const trades = await read.trades(DEMO);
    const overview = await read.executiveOverview(DEMO);
    const ledger = (trades.payload?.items ?? []).reduce((total, item) => {
      const value = item.realized_pnl.value;
      return total + (typeof value === "string" ? (hundredths(value) ?? 0) : 0);
    }, 0);
    const cumulative = overview.payload?.pnl.find((entry) => entry.window === "CUMULATIVE");
    expect(ledger).toBe(hundredths(String(cumulative?.realized.value)));
  });

  it("reconciles the ledger's unrealized total with the open positions", async () => {
    const read = client();
    const trades = await read.trades(DEMO);
    const positions = await read.positions(DEMO);
    const ledger = (trades.payload?.items ?? []).reduce((total, item) => {
      const value = item.unrealized_pnl.value;
      return total + (typeof value === "string" ? (hundredths(value) ?? 0) : 0);
    }, 0);
    const held = (positions.payload?.items ?? []).reduce(
      (total, item) => total + (hundredths(item.unrealized.amount) ?? 0),
      0,
    );
    expect(ledger).toBe(held);
  });

  it("reconciles the position market values with the book's own share counts", async () => {
    const positions = await client().positions(DEMO);
    for (const item of positions.payload?.items ?? []) {
      const book = BOOK.openTrades.find((trade) => trade.symbol === item.security.symbol);
      expect(book).toBeDefined();
      if (book === undefined) continue;
      expect(item.quantity).toBe(book.sharesOpen);
      expect(hundredths(String(item.current_price.value))).toBe(book.markCents);
      /* INDEPENDENTLY RECOMPUTED: shares open x (mark - basis), signed by direction. */
      const sign = book.direction === "LONG" ? 1 : -1;
      const expectedUnrealized =
        book.sharesOpen * ((book.markCents ?? 0) - book.basisCents) * sign;
      expect(hundredths(item.unrealized.amount)).toBe(expectedUnrealized);
      expect(positionValueCents(book)).toBe(book.sharesOpen * (book.markCents ?? 0));
    }
  });
});

/* ================================================= strategy attribution and totals */

describe("strategy attribution", () => {
  it("attributes every result to an exact strategy version and never merges two", async () => {
    const strategy = await client().strategyPerformance(DEMO);
    const items = strategy.payload?.items ?? [];
    const versions = items.map((item) => item.strategy_version);
    expect(new Set(versions).size).toBe(versions.length);

    const breakout = items.filter(
      (item) => item.strategy_module.code === "BREAKOUT_LONG",
    );
    expect(breakout.length, "one module, two exact versions").toBe(2);
    expect(new Set(breakout.map((item) => item.strategy_version)).size).toBe(2);

    for (const item of items) {
      const closed = BOOK.closedTrades.filter(
        (trade) => trade.versionId === item.strategy_version && trade.initialRiskRecorded,
      );
      expect(item.summary.observation_count.value, item.strategy_version).toBe(closed.length);
    }
  });

  it("sums each version's realized result to the portfolio's realized result", async () => {
    const read = client();
    const strategy = await read.strategyPerformance(DEMO);
    const overview = await read.executiveOverview(DEMO);
    const perVersion = (strategy.payload?.items ?? []).reduce((total, item) => {
      const value = item.module_metrics.realized_pnl.value;
      return total + (typeof value === "string" ? (hundredths(value) ?? 0) : 0);
    }, 0);
    const cumulative = overview.payload?.pnl.find((entry) => entry.window === "CUMULATIVE");
    expect(perVersion).toBe(hundredths(String(cumulative?.realized.value)));
  });

  it("makes no diversification claim on a family roll-up", async () => {
    const strategy = await client().strategyPerformance(DEMO);
    for (const family of strategy.payload?.families ?? []) {
      expect(isValueBearing(family.diversification_claim.availability)).toBe(false);
      expect(family.diversification_claim.gate.code).toContain("G7");
      expect(family.member_versions.length).toBeGreaterThan(0);
    }
  });

  it("carries a recorded health state and names what it does not carry", async () => {
    const strategy = await client().strategyPerformance(DEMO);
    for (const item of strategy.payload?.items ?? []) {
      const state = item.health_context.state.value;
      expect(typeof state).toBe("string");
      expect(
        [
          "HEALTHY",
          "WATCH",
          "DEGRADED",
          "NEW_ENTRIES_REDUCED",
          "NEW_ENTRIES_DISABLED",
          "SUSPENDED",
          "RETIRED",
        ],
        String(state),
      ).toContain(state);
      expect(item.health_context.omitted.length).toBeGreaterThan(0);
      for (const omitted of item.health_context.omitted) {
        expect(isValueBearing(omitted.availability)).toBe(false);
      }
    }
  });
});

/* =============================================================== borrow and risk */

describe("borrow and risk", () => {
  it("keeps an unknown borrow unknown, and never available", async () => {
    const read = client();
    const short = await read.shortSide(DEMO);
    const unknown = (short.payload?.borrow ?? []).filter((record) =>
      record.availability.code.includes("UNKNOWN"),
    );
    expect(unknown.length, "the fixture carries one short with no borrow record").toBe(1);
    for (const record of unknown) {
      expect(record.availability.code).not.toContain("AVAILABLE_FROM_RECORD");
      // Every figure that would have come from the missing record is unavailable.
      for (const metric of [record.fee, record.quantity, record.deterioration]) {
        expect(isValueBearing(metric.availability)).toBe(false);
        expect(metric.reason).toBe("UPSTREAM_INPUT_MISSING");
        expect(metric.value).toBeUndefined();
      }
      expect(record.record_ref.resolution).toBe("UNRESOLVABLE_V1");
    }

    const positions = await read.positions(DEMO);
    const shorts = (positions.payload?.items ?? []).filter(
      (item) => item.direction === "SHORT",
    );
    expect(shorts.length).toBeGreaterThan(0);
    for (const position of shorts) {
      expect(position.borrow_state).toBeDefined();
    }
    expect(
      shorts.some((position) => position.borrow_state?.code.includes("UNKNOWN")),
    ).toBe(true);
  });

  it("serves no permitted limit without a versioned policy reference", async () => {
    const read = client();
    const risk = await read.riskSnapshot(DEMO);
    for (const permitted of risk.payload?.permitted ?? []) {
      expect(permitted.value.record).toBeUndefined();
      expect(permitted.value.availability).toBe("NOT_YET_AVAILABLE");
      expect(permitted.value.reason).toBe("POLICY_REFERENCE_MISSING");
    }
    const short = await read.shortSide(DEMO);
    expect(short.payload?.permitted_gross_short.reason).toBe("POLICY_REFERENCE_MISSING");
    expect(short.payload?.permitted_gross_short_scope).toBe("GROSS_SHORT");
  });

  it("reports a stale assessment as stale, with the instant it was true at", async () => {
    const positions = await client().positions(DEMO);
    const stale = positions.payload?.items.find(
      (item) => item.trade_ref.ref_id === STALE_ASSESSMENT_TRADE,
    );
    expect(stale?.open_planned_risk.availability).toBe("STALE");
    expect(stale?.open_planned_risk.reason).toBe("UPSTREAM_INPUT_STALE");
    // The record is PRESENT, and it says so itself.
    expect(stale?.open_planned_risk.record?.staleness).toBe("STALE");
    expect(stale?.open_planned_risk.record?.as_of).toBeDefined();
  });

  it("reports an aggregate containing a stale component as PARTIAL", async () => {
    const read = client();
    const risk = await read.riskSnapshot(DEMO);
    expect(risk.payload?.open_planned_risk.availability).toBe("PARTIAL");
    expect(risk.payload?.open_planned_risk.reason).toBe("UPSTREAM_INPUT_STALE");

    /* INDEPENDENTLY RECOMPUTED: the sum of each open trade's assessed remaining risk. */
    const expected = BOOK.openTrades.reduce(
      (total, trade) => total + (trade.openPlannedRiskCents ?? 0),
      0,
    );
    expect(hundredths(String(risk.payload?.open_planned_risk.record?.risk_money.value))).toBe(
      expected,
    );
  });

  it("names every loss threshold while approving none of them", async () => {
    const risk = await client().riskSnapshot(DEMO);
    const thresholds = risk.payload?.loss_thresholds ?? [];
    expect(thresholds.length).toBeGreaterThan(0);
    for (const threshold of thresholds) {
      expect(threshold.policy_ref).toBeUndefined();
      expect(isValueBearing(threshold.value.availability)).toBe(false);
      expect(threshold.value.reason).toBe("POLICY_REFERENCE_MISSING");
    }
  });

  it("keeps each open trade's initial risk inside its governed research parameter", async () => {
    const risk = await client().riskSnapshot(DEMO);
    for (const entry of risk.payload?.initial_planned_risk_open ?? []) {
      const book = BOOK.openTrades.find((trade) => trade.tradeId === entry.trade_ref.ref_id);
      expect(book).toBeDefined();
      if (book === undefined) continue;
      // 0.50% of capital long, 0.25% short — CLAUDE.md section 6, obeyed and not changed.
      const ceiling =
        book.direction === "LONG" ? STRATEGY_CAPITAL_CENTS / 200 : STRATEGY_CAPITAL_CENTS / 400;
      expect(book.initialRiskCents, book.tradeId).toBeLessThanOrEqual(ceiling);
    }
  });
});

/* ================================================== market regime and its profile */

describe("market regime", () => {
  it("declares its information-set profile and never claims point-in-time", async () => {
    const regime = await client().marketRegime(DEMO);
    expect(regime.payload?.information_profile).toBe("FORWARD_SYSTEM");
    expect(regime.payload?.information_profile).not.toBe("PUBLIC_PIT");
    expect(regime.payload?.context_version.length).toBeGreaterThan(0);
  });

  it("agrees with the regime the strategy slices are read against", async () => {
    const read = client();
    const regime = await read.marketRegime(DEMO);
    const strategy = await read.strategyPerformance(DEMO);
    const buckets = new Set(
      (strategy.payload?.items ?? [])
        .flatMap((item) => item.slices)
        .filter((slice) => slice.axis.code === "REGIME")
        .map((slice) => slice.bucket.code),
    );
    expect(buckets.has(regime.payload?.regime.code ?? "")).toBe(true);
  });
});

/* ================================================ cache isolation and scope keying */

describe("cache isolation for the C5 read models", () => {
  it("gives every C5 read model its own key under one scope", () => {
    const keys = READ_MODEL_IDENTITIES.map((identity) =>
      JSON.stringify(readModelKey(identity, DEFAULT_SCOPE)),
    );
    expect(new Set(keys).size).toBe(READ_MODEL_IDENTITIES.length);
  });

  it("separates two trades under one read model", () => {
    const left = readModelKey(TRADE_DETAIL_IDENTITY, DEFAULT_SCOPE, ["demo-trade-a"]);
    const right = readModelKey(TRADE_DETAIL_IDENTITY, DEFAULT_SCOPE, ["demo-trade-b"]);
    expect(left).not.toEqual(right);
  });

  it("separates the execution scope from the portfolio scope", () => {
    const lifecycle = readModelKey(TRADE_LIFECYCLE_IDENTITY, DEFAULT_SCOPE, ["t"]);
    const detail = readModelKey(TRADE_DETAIL_IDENTITY, DEFAULT_SCOPE, ["t"]);
    expect(lifecycle).toContain("execution:read");
    expect(detail).toContain("portfolio:read");
    expect(lifecycle).not.toEqual(detail);
  });

  it("separates every trailing-window summary", () => {
    const keys = PERFORMANCE_PERIODS.map((period) =>
      JSON.stringify(
        readModelKey(
          READ_MODEL_IDENTITIES.find(
            (identity) => identity.readModel === "PerformanceSummary",
          ) ?? POSITION_SNAPSHOT_IDENTITY,
          DEFAULT_SCOPE,
          [period],
        ),
      ),
    );
    expect(new Set(keys).size).toBe(PERFORMANCE_PERIODS.length);
  });

  it("separates every granularity of the performance series", async () => {
    const read = client();
    const daily = await read.performanceSeries({ ...DEMO, granularity: "DAILY" });
    const monthly = await read.performanceSeries({ ...DEMO, granularity: "MONTHLY" });
    expect(daily.payload?.series_id).not.toBe(monthly.payload?.series_id);
    expect(daily.payload?.equity.points.length).toBeGreaterThan(
      monthly.payload?.equity.points.length ?? 0,
    );
    expect(monthly.payload?.granularity).toBe("MONTHLY");
  });
});
