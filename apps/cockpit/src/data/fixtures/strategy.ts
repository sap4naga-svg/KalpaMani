/**
 * `StrategyPerformance`, projected from the demonstration book.
 *
 * **EVERY RESULT IS ATTRIBUTED TO AN EXACT STRATEGY VERSION.** Breakout Long appears twice —
 * once at the superseded `-v2` and once at the production `-v3` — and their trades, their
 * observation counts and their ratios stay apart. A superseded version's record is not folded
 * into its successor's.
 *
 * **BREAKOUT AND PULLBACK KEEP SEPARATE MODULE ATTRIBUTION AND SHARE A FAMILY CONTEXT**, and
 * the family roll-up carries **no diversification figure at all**: two modules in one family
 * are one exposure with two names until measured otherwise, and whether they are economically
 * distinct is **open gate G7**. Nothing here decides it, and the roll-up says so in a field
 * rather than leaving a reader to infer it.
 *
 * **HEALTH IS CONTEXT, NOT A HEALTH SCREEN.** A recorded state and its reason travel with the
 * results so a reader does not read a degraded module's numbers as a healthy one's. The
 * transitions, the drift measures, the failure clusters and the research-queue entry a
 * degradation creates are **Area 5, and this cycle implements none of them**.
 */
import type {
  AlphaFamilyRollup,
  StrategyPerformance,
  StrategyPerformancePayload,
} from "@/contracts/strategy-models";

import type { BookTrade } from "./book";
import { BOOK, STRATEGY_VERSIONS, securityOf, strategyVersionOf } from "./book";
import {
  count,
  demoRef,
  demoReason,
  denominatorZero,
  insufficient,
  partialPath,
  scaled,
  sessionInstant,
  token,
  tradingDays,
  unavailable,
  usd,
  windowOf,
} from "./common";
import { buildPerformanceSummary } from "./summary";

/** The slice axes Area 4 names. Each is a VIEW of one module's trades, never a new one. */
const SLICE_AXES = [
  "SECTOR",
  "REGIME",
  "VOLATILITY_REGIME",
  "TRADE_TEMPLATE",
  "FACTOR_BUCKET",
] as const;

/**
 * The regime a trade's entry session fell in.
 *
 * It is READ from the versioned regime context the demonstration book records, and it is
 * never recomputed from a price: **the regime is an input, not a conclusion** (Area 11). The
 * mapping is a fixed partition of the retained extent, which is what a recorded regime history
 * looks like from the ledger's side.
 */
export function regimeAtSession(session: number): string {
  if (session < 130) return "RANGE_BOUND";
  if (session < 270) return "TRENDING_UP";
  if (session < 360) return "HIGH_VOLATILITY_STRESS";
  return "TRENDING_UP";
}

export function volatilityRegimeAtSession(session: number): string {
  return session >= 270 && session < 360 ? "ELEVATED_VOLATILITY" : "NORMAL_VOLATILITY";
}

function sliceBucket(trade: BookTrade, axis: (typeof SLICE_AXES)[number]): string {
  const security = securityOf(trade.symbol);
  const version = strategyVersionOf(trade.versionId);
  switch (axis) {
    case "SECTOR":
      return security.sector;
    case "REGIME":
      return regimeAtSession(trade.stages[0].session);
    case "VOLATILITY_REGIME":
      return volatilityRegimeAtSession(trade.stages[0].session);
    case "TRADE_TEMPLATE":
      return version.template;
    case "FACTOR_BUCKET":
      return security.factorBucket;
  }
}

/**
 * The per-module figures Area 4 names beside the summary.
 *
 * Each is measured over the module's own closed trades. Where a contributing trade's price
 * path is incomplete, the excursion figures are `PARTIAL` rather than optimistic — the same
 * rule the individual trade obeys, applied to the aggregate that contains it.
 */
function moduleMetrics(trades: readonly BookTrade[], asOf: string) {
  const closed = trades.filter((trade) => trade.status === "CLOSED");
  const anyPartial = trades.some((trade) => trade.dataCompleteness === "PARTIAL");
  const realized = trades.reduce((total, trade) => total + trade.realizedCents, 0);
  const unrealized = trades.reduce((total, trade) => total + trade.unrealizedCents, 0);
  const mfe = trades.reduce((total, trade) => total + trade.mfeCents, 0);
  const mae = trades.reduce((total, trade) => total + trade.maeCents, 0);
  const holding =
    trades.length === 0
      ? 0
      : Math.round(
          trades.reduce((total, trade) => total + trade.holdingSessions, 0) / trades.length,
        );
  const notional = trades.reduce(
    (total, trade) => total + trade.sharesAcquired * trade.basisCents,
    0,
  );

  return {
    realized_pnl:
      closed.length === 0
        ? unavailable("pnl.realized", "USD", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING")
        : usd("pnl.realized", realized, asOf),
    unrealized_pnl: usd("pnl.unrealized", unrealized, asOf),
    average_holding_period: tradingDays("holding_period", holding, asOf),
    /**
     * How many entries this version took. It is a COUNT OF TAKEN OPPORTUNITIES and not a
     * count of opportunities that existed: the second needs a candidate stream, the Brain
     * runtime does not exist, and Missed Opportunities (Area 8) owns that question.
     */
    opportunity_count: count("strategy.opportunity_count", trades.length, asOf),
    /** Entry notional against the authoritative strategy capital, over the retained extent. */
    turnover: scaled(
      "strategy.turnover",
      "RATIO",
      Math.round((notional * 100) / 80_000_00),
      asOf,
    ),
    /**
     * Capacity needs a liquidity and market-impact model over qualified provider data. None
     * exists, **no provider is selected and G1 is OPEN**, so it is unavailable rather than
     * estimated from a fixture.
     */
    capacity: unavailable(
      "strategy.capacity",
      "USD",
      "NOT_YET_AVAILABLE",
      "UPSTREAM_INPUT_MISSING",
    ),
    mfe: anyPartial
      ? partialPath("mfe", "USD", (mfe / 100).toFixed(2), asOf)
      : usd("mfe", mfe, asOf),
    mae: anyPartial
      ? partialPath("mae", "USD", (mae / 100).toFixed(2), asOf)
      : usd("mae", mae, asOf),
    capture_ratio:
      mfe <= 0
        ? denominatorZero("capture_ratio", "RATIO")
        : scaled(
            "capture_ratio",
            "RATIO",
            Math.round(((realized + unrealized) * 100) / mfe),
            asOf,
          ),
    /**
     * Slippage needs a named reference price with its own timestamp for every fill, and an
     * execution runtime to record them. Neither exists, so it is unavailable — **never a
     * modelled estimate presented beside realized results** (§12.4).
     */
    slippage: unavailable(
      "slippage.aggregate",
      "BPS",
      "NOT_IMPLEMENTED",
      "PRODUCER_NOT_IMPLEMENTED",
    ),
  };
}

function healthContext(versionId: string, asOf: string) {
  const version = strategyVersionOf(versionId);
  return {
    state: token("strategy.health_state", version.healthState, asOf),
    reason: demoReason(version.healthReason),
    detail_ref: demoRef(`${versionId}-health`, "health_transition"),
    /** What this context deliberately does not carry, named rather than left blank. */
    omitted: (
      [
        ["HEALTH_TRANSITION_HISTORY", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
        ["FACTOR_AND_BEHAVIOUR_DRIFT", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
        ["FAILURE_CLUSTERS", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
        ["RESEARCH_QUEUE_ENTRY", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
        ["RECOVERY_AUTHORITY", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
      ] as const
    ).map(([subject, availability, reason]) => ({
      subject: demoReason(subject),
      availability,
      reason,
    })),
  };
}

export function syntheticStrategyPerformance(
  asOf: string,
  days: readonly string[],
): StrategyPerformancePayload {
  const items: StrategyPerformance[] = STRATEGY_VERSIONS.map((version) => {
    const trades = BOOK.trades.filter((trade) => trade.versionId === version.versionId);
    const closed = trades.filter((trade) => trade.status === "CLOSED");
    const slices = SLICE_AXES.flatMap((axis) => {
      const buckets = [...new Set(trades.map((trade) => sliceBucket(trade, axis)))].sort();
      return buckets.map((bucket) => ({
        axis: demoReason(axis),
        bucket: demoReason(bucket),
        summary: buildPerformanceSummary({
          days,
          asOf,
          closed: closed.filter((trade) => sliceBucket(trade, axis) === bucket),
          /*
           * A SLICE HAS NO RETURN SERIES OF ITS OWN, so its Sharpe has no periods to be
           * computed over and reports INSUFFICIENT_OBSERVATIONS. A per-slice equity curve
           * would need a per-slice portfolio, which this book does not model.
           */
          periodReturns: [],
          totalReturnHundredths: 0,
          maxDrawdownHundredths: 0,
          populationCode: "CLOSED_TRADES_OF_THIS_VERSION_IN_THIS_SLICE",
        }),
      }));
    });

    return {
      strategy_module: demoReason(version.module),
      alpha_family: demoReason(version.family),
      strategy_version: version.versionId,
      summary: buildPerformanceSummary({
        days,
        asOf,
        closed,
        /*
         * A MODULE HAS NO EQUITY CURVE OF ITS OWN in this book: the portfolio holds one
         * equity path, and slicing it per module would need a per-module portfolio nobody
         * recorded. The module's Sharpe is therefore INSUFFICIENT_OBSERVATIONS, and its
         * window return and drawdown are reported as the trade population's, at zero
         * periods.
         */
        periodReturns: [],
        totalReturnHundredths: 0,
        maxDrawdownHundredths: 0,
        populationCode: "CLOSED_TRADES_OF_THIS_EXACT_VERSION",
      }),
      slices,
      trade_population: demoReason("CLOSED_TRADES_OF_THIS_EXACT_VERSION"),
      module_metrics: moduleMetrics(trades, asOf),
      health_context: healthContext(version.versionId, asOf),
    };
  });

  const families: AlphaFamilyRollup[] = [
    ...new Set(STRATEGY_VERSIONS.map((version) => version.family)),
  ].map((family) => {
    const members = STRATEGY_VERSIONS.filter((version) => version.family === family);
    const memberIds = members.map((version) => version.versionId);
    const closed = BOOK.closedTrades.filter((trade) =>
      memberIds.includes(trade.versionId),
    );
    return {
      alpha_family: demoReason(family),
      member_versions: memberIds,
      summary: buildPerformanceSummary({
        days,
        asOf,
        closed,
        periodReturns: [],
        totalReturnHundredths: 0,
        maxDrawdownHundredths: 0,
        populationCode: "CLOSED_TRADES_OF_EVERY_VERSION_IN_THIS_FAMILY",
      }),
      /**
       * **NO DIVERSIFICATION CLAIM IS MADE, AND NONE IS DERIVABLE.** The field states the
       * gate that owns the question rather than leaving a blank a reader would fill in.
       */
      diversification_claim: {
        availability: "UNEVALUATED",
        reason: "NOT_YET_ASSESSED",
        gate: demoReason("G7_STRATEGY_TAXONOMY_EVIDENCE"),
      },
    };
  });

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("STRATEGY_VERSION_ASCENDING"),
      tiebreak: demoReason("STRATEGY_MODULE_ASCENDING"),
    },
    window: windowOf(days),
    families,
  };
}

export { insufficient, sessionInstant };
