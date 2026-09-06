/**
 * `TradeSummary`, `TradeDetail` and the **basic** `TradeLifecycle`, from the demonstration
 * book.
 *
 * FOUR RULES THIS PROJECTION EXISTS TO OBEY.
 *
 *   A FILL IS NEVER A TRADE            one trade has an entry, an add and a partial exit, and
 *                                      it is ONE row in the ledger with ONE identity
 *   A PARTIAL EXIT REDUCES A TRADE     it does not close it and does not create a second one,
 *                                      so `PARTIALLY_EXITED` carries realized AND unrealized
 *   STATUS IS NOT COMPLETENESS         one trade is `COMPLETE` in status and `PARTIAL` in
 *                                      completeness, and neither is inferred from the other
 *   R DIVIDES BY THE INITIAL RECORD    one historical trade's entry-time record was never
 *                                      written, so its R is unavailable and is **never
 *                                      computed from a current stop**
 *
 * WHAT IS DELIBERATELY ABSENT. Order and fill mechanics, protective-order events,
 * reconciliation and finalized attribution are **not carried**, because the producers do not
 * exist and because Execution History and the Audit Trail are separate screens (Area 36.3).
 * Every one of them is named as a gap rather than filled in.
 */
import type {
  TradeDetailPayload,
  TradeLifecyclePayload,
  TradeSummary,
  TradeSummaryPayload,
} from "@/contracts/portfolio-models";
import type { Series } from "@/contracts/values";

import type { BookTrade } from "./book";
import {
  BOOK,
  MISSING_RISK_RECORD_TRADE,
  PARTIAL_PATH_TRADE,
  centsToDecimal,
  securityOf,
  strategyVersionOf,
} from "./book";
import {
  CALENDAR,
  count,
  demoRef,
  demoReason,
  instantValue,
  notApplicable,
  partialPath,
  percent,
  refListOf,
  scaled,
  sessionInstant,
  token,
  tradingDays,
  unavailable,
  usd,
  windowOf,
} from "./common";
import { demoPins, initialRiskRecord, openRiskRecord } from "./positions";

/** The trade the ledger's page is sorted by, and the tiebreak that makes it deterministic. */
const LEDGER_SORT = "ENTRY_TIME_DESCENDING";
const LEDGER_TIEBREAK = "TRADE_ID_ASCENDING";

/** §5.1's declared maximum for `/portfolio/trades`. A larger page is refused, not truncated. */
const LEDGER_PAGE_SIZE = 200;

function initialPositionValueCents(trade: BookTrade): number {
  return trade.stages.reduce((total, stage) => total + stage.shares * stage.priceCents, 0);
}

/** The trade's whole outcome so far: realized on what closed, unrealized on what is open. */
function outcomeCents(trade: BookTrade): number {
  return trade.realizedCents + trade.unrealizedCents;
}

export function buildTradeSummary(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): TradeSummary {
  const security = securityOf(trade.symbol);
  const version = strategyVersionOf(trade.versionId);
  const closed = trade.status === "CLOSED";
  const open = trade.status === "OPEN";
  const entryAt = sessionInstant(days[trade.stages[0].session]);
  const finalExit = trade.exits[trade.exits.length - 1];
  const positionValue = initialPositionValueCents(trade);
  const partialPathTrade = trade.dataCompleteness === "PARTIAL";

  /*
   * THE EXIT FIELDS OF A TRADE THAT HAS NOT EXITED.
   *
   * An open or partially exited trade has no exit: the question does not apply to it, which
   * is `NOT_APPLICABLE` with `NOT_DEFINED_FOR_SUBJECT`. A PARTIAL exit is an event in the
   * lifecycle, not the trade's exit, so it never fills these in.
   */
  const exitTime = closed
    ? instantValue("trade.exit_time", sessionInstant(days[finalExit.session]), asOf)
    : notApplicable("trade.exit_time", "DIMENSIONLESS");
  const exitPrice = closed
    ? usd("trade.exit_price", finalExit.priceCents, asOf)
    : notApplicable("trade.exit_price", "USD");
  const exitReason = closed
    ? token("trade.exit_reason", finalExit.reason, asOf)
    : notApplicable("trade.exit_reason", "DIMENSIONLESS");

  const captureRatio =
    trade.mfeCents <= 0
      ? /* A capture ratio over a zero or negative MFE is undefined, never a division. */
        unavailable("capture_ratio", "RATIO", "NOT_APPLICABLE", "DENOMINATOR_ZERO")
      : partialPathTrade
        ? partialPath(
            "capture_ratio",
            "RATIO",
            centsToDecimal(Math.round((outcomeCents(trade) * 100) / trade.mfeCents)),
            asOf,
          )
        : scaled(
            "capture_ratio",
            "RATIO",
            Math.round((outcomeCents(trade) * 100) / trade.mfeCents),
            asOf,
          );

  return {
    trade_id: trade.tradeId,
    security_ref: demoRef(`security-${trade.symbol.toLowerCase()}`, "evidence", "EMBEDDED"),
    security: { symbol: trade.symbol, display_name: security.displayName },
    direction: trade.direction,
    trade_status: trade.status,
    /** A SEPARATE field. A complete trade with a missing bar is not a partially exited one. */
    data_completeness: trade.dataCompleteness,
    strategy_module: demoReason(version.module),
    alpha_family: demoReason(version.family),
    trade_template: demoReason(version.template),
    entry_time: entryAt,
    entry_price: usd("trade.entry_price", trade.basisCents, asOf),
    exit_time: exitTime,
    exit_price: exitPrice,
    shares_at_entry: trade.sharesAtEntry,
    shares_open: trade.sharesOpen,
    initial_position_value: { amount: centsToDecimal(positionValue), currency: "USD" },
    /** CLOSED portion only. An OPEN trade has closed none, so it reports no realized result. */
    realized_pnl: open
      ? unavailable("pnl.realized", "USD", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING")
      : usd("pnl.realized", trade.realizedCents, asOf),
    /** OPEN portion only. A CLOSED trade holds none, so the question does not apply to it. */
    unrealized_pnl: closed
      ? notApplicable("pnl.unrealized", "USD")
      : usd("pnl.unrealized", trade.unrealizedCents, asOf),
    return_pct:
      positionValue === 0
        ? unavailable("trade.return_pct", "PERCENT", "NOT_APPLICABLE", "DENOMINATOR_ZERO")
        : percent(
            "trade.return_pct",
            Math.round((outcomeCents(trade) * 10_000) / positionValue),
            asOf,
          ),
    initial_planned_risk: trade.initialRiskRecorded
      ? {
          record: initialRiskRecord(trade, days),
          availability: "AVAILABLE",
          reason: "NONE",
          as_of: entryAt,
        }
      : {
          /*
           * A HISTORICAL TRADE WHOSE RECORD WAS NEVER WRITTEN (§4.4, case 3).
           *
           * It is NOT `NOT_APPLICABLE`: the trade opened, so the question applies and nobody
           * answered it. There is no `recorded_at` to report, and the response's own times
           * are not substituted for one.
           */
          availability: "NOT_YET_AVAILABLE",
          reason: "UPSTREAM_INPUT_MISSING",
        },
    open_planned_risk: openRiskRecord(trade, days, asOf),
    r_multiple: trade.initialRiskRecorded
      ? scaled(
          "r_multiple",
          "R_MULTIPLE",
          Math.round((outcomeCents(trade) * 100) / trade.initialRiskCents),
          asOf,
        )
      : unavailable("r_multiple", "R_MULTIPLE", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"),
    holding_period: tradingDays("holding_period", trade.holdingSessions, asOf),
    /** Path-dependent: an incomplete price path is PARTIAL, never an optimistic value. */
    mfe: partialPathTrade
      ? partialPath("mfe", "USD", centsToDecimal(trade.mfeCents), asOf)
      : usd("mfe", trade.mfeCents, asOf),
    mae: partialPathTrade
      ? partialPath("mae", "USD", centsToDecimal(trade.maeCents), asOf)
      : usd("mae", trade.maeCents, asOf),
    capture_ratio: captureRatio,
    entry_reason: demoReason(version.entryReason),
    exit_reason: exitReason,
    stop_outcome: demoReason(trade.stopOutcome),
    /** From the envelope's environment. Every trade in this book is a RESEARCH-scope record. */
    environment: "RESEARCH",
    pins: demoPins(trade.versionId),
    detail_ref: demoRef(`${trade.tradeId}-detail`, "source_fact", "ENDPOINT"),
  };
}

export function syntheticTrades(asOf: string, days: readonly string[]): TradeSummaryPayload {
  /** Newest first, with a deterministic tiebreak, so two identical reads agree. */
  const ordered = [...BOOK.trades].sort((left, right) => {
    const delta = right.stages[0].session - left.stages[0].session;
    return delta !== 0 ? delta : left.tradeId.localeCompare(right.tradeId);
  });
  const items = ordered
    .slice(0, LEDGER_PAGE_SIZE)
    .map((trade) => buildTradeSummary(trade, days, asOf));

  return {
    items,
    page: {
      page_size: LEDGER_PAGE_SIZE,
      total: count("reference.total", ordered.length, asOf),
      truncated: ordered.length > LEDGER_PAGE_SIZE,
      sort: demoReason(LEDGER_SORT),
      tiebreak: demoReason(LEDGER_TIEBREAK),
    },
    as_of: sessionInstant(days[days.length - 1]),
    window: windowOf(days),
    trade_population: demoReason("ALL_RECORDED_TRADES_IN_THE_RETAINED_EXTENT"),
    open_count: count(
      "trade.open_count",
      BOOK.trades.filter((trade) => trade.status !== "CLOSED").length,
      asOf,
    ),
    closed_count: count(
      "trade.closed_count",
      BOOK.trades.filter((trade) => trade.status === "CLOSED").length,
      asOf,
    ),
  };
}

export function findBookTrade(tradeId: string): BookTrade | undefined {
  return BOOK.trades.find((trade) => trade.tradeId === tradeId);
}

/* ------------------------------------------------------------------ TradeDetail */

/**
 * The stages of one trade's story this cycle does **not** reconstruct.
 *
 * Each is named with the availability state that explains it, so a reader sees the shape of
 * the whole lifecycle and which parts of it are missing. **A missing event renders as a gap
 * and never as an inference.**
 */
const DETAIL_GAPS = [
  ["CANDIDATE_AND_THESIS", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["BRAIN_DECISION_RECORD", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["RISK_ENGINE_DECISION", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["ORDER_AND_FILL_MECHANICS", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["PROTECTIVE_ORDER_EVENTS", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["BROKER_RECONCILIATION", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["EXECUTION_QUALITY", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["PERFORMANCE_ATTRIBUTION", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["BENCHMARK_PRICE_HISTORY", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["IMMUTABLE_AUDIT_EVENTS", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
] as const;

/**
 * The trade's own mark path, as an EMBEDDED `Series`.
 *
 * **It is a mark line, not OHLC.** Open, high, low and close need a market-data provider,
 * **no provider is selected and G1 is OPEN**, so the demonstration carries one mark per
 * session and says so. The markers drawn on it come from the recorded stages and exits and
 * from nothing else.
 */
export function tradeChartSeries(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): Series {
  const first = trade.stages[0].session;
  const points = trade.path.map((price, offset) => ({
    t: days[first + offset],
    v: usd("trade.mark_price", price, asOf),
  }));
  return {
    points,
    granularity: "DAILY",
    calendar: CALENDAR,
    timezone: "UTC",
    coverage: { present: points.length, requested: points.length },
    completeness: trade.dataCompleteness === "PARTIAL" ? "PARTIAL" : "COMPLETE",
  };
}

export function syntheticTradeDetail(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): TradeDetailPayload {
  const summary = buildTradeSummary(trade, days, asOf);
  const closed = trade.status === "CLOSED";
  const unavailableMetric = (metricId: string) =>
    unavailable(metricId, "USD", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED");

  return {
    trade_id: trade.tradeId,
    summary,
    candidate_ref: demoRef(`${trade.tradeId}-candidate`, "candidate"),
    brain_decision_ref: demoRef(`${trade.tradeId}-brain-decision`, "brain_decision"),
    risk_decision_ref: demoRef(`${trade.tradeId}-risk-decision`, "risk_decision"),
    order_refs: refListOf([], "ZERO_OR_MORE", asOf),
    fill_refs: refListOf([], "ZERO_OR_MORE", asOf),
    protection_refs: refListOf([], "ZERO_OR_MORE", asOf),
    add_refs: refListOf(
      trade.stages
        .filter((stage) => stage.kind === "ADD")
        .map((stage, index) => demoRef(`${trade.tradeId}-add-${index}`, "add", "EMBEDDED")),
      "ZERO_OR_MORE",
      asOf,
    ),
    exit_ref: closed ? demoRef(`${trade.tradeId}-exit`, "exit", "EMBEDDED") : undefined,
    reconciliation_refs: refListOf([], "ZERO_OR_MORE", asOf),
    execution_quality_ref: demoRef(`${trade.tradeId}-execution-quality`, "execution_quality"),
    attribution: {
      /*
       * NOTHING IS ATTRIBUTED. Strategy, factor, regime, execution and cost attribution each
       * need a producer that does not exist; a provisional zero would be a decomposition
       * nobody computed.
       */
      strategy: unavailableMetric("pnl.combined"),
      factor: unavailableMetric("pnl.combined"),
      regime: unavailableMetric("pnl.combined"),
      execution: unavailableMetric("pnl.combined"),
      cost: unavailableMetric("pnl.combined"),
      state: "PROVISIONAL",
    },
    /** No benchmark price history exists, so no benchmark movement is computed. */
    benchmark_movement: unavailable(
      "benchmark.movement",
      "PERCENT",
      "NOT_YET_AVAILABLE",
      "UPSTREAM_INPUT_MISSING",
    ),
    benchmark_basis: "TOTAL_RETURN",
    benchmark_series_ref: demoRef(`${trade.tradeId}-benchmark`, "benchmark_series"),
    lineage: demoPins(trade.versionId),
    audit_refs: refListOf([], "ZERO_OR_MORE", asOf),
    chart_series_ref: demoRef(`${trade.tradeId}-marks`, "chart_series", "EMBEDDED"),
    chart_series: tradeChartSeries(trade, days, asOf),
    gaps: DETAIL_GAPS.map(([expected, availability, reason]) => ({
      expected: demoReason(expected),
      availability,
      reason,
    })),
  };
}

/* --------------------------------------------------------------- TradeLifecycle */

const ABSENT_LIFECYCLE_KINDS = [
  ["ORDER_SUBMITTED", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["ORDER_ACKNOWLEDGED", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["INDIVIDUAL_FILL", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["PROTECTIVE_ORDER_PLACED", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["PROTECTIVE_ORDER_AMENDED", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["BROKER_RECONCILIATION", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["CORRECTION_APPENDED", "EMPTY_VERIFIED", "EMPTY_RESULT_VERIFIED"],
] as const;

export function syntheticTradeLifecycle(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): TradeLifecyclePayload {
  const events = [
    ...trade.stages.map((stage, index) => ({
      event_id: `${trade.tradeId}-stage-${index}`,
      event_kind: demoReason(stage.kind === "ENTRY" ? "ENTRY_RECORDED" : "PYRAMID_ADD_RECORDED"),
      event_time: sessionInstant(days[stage.session]),
      observed_time: sessionInstant(days[stage.session]),
      quantity: stage.shares,
      price: usd("trade.mark_price", stage.priceCents, asOf),
      downstream_stage: "ORDER_FILLED" as const,
      source_ref: demoRef(`${trade.tradeId}-stage-${index}-source`, "source_fact"),
    })),
    ...trade.exits.map((exit, index) => ({
      event_id: `${trade.tradeId}-exit-${index}`,
      event_kind: demoReason(
        exit.shares < trade.sharesAtEntry ? "PARTIAL_EXIT_RECORDED" : "EXIT_RECORDED",
      ),
      event_time: sessionInstant(days[exit.session]),
      observed_time: sessionInstant(days[exit.session]),
      quantity: exit.shares,
      price: usd("trade.mark_price", exit.priceCents, asOf),
      downstream_stage:
        exit.shares < trade.sharesAtEntry
          ? ("ORDER_PARTIALLY_FILLED" as const)
          : ("ORDER_FILLED" as const),
      source_ref: demoRef(`${trade.tradeId}-exit-${index}-source`, "source_fact"),
    })),
  ].sort((left, right) => left.event_time.localeCompare(right.event_time));

  /**
   * The one interval nothing observed.
   *
   * Only the trade whose price path is incomplete carries a gap, and it is a REAL absence in
   * this fixture rather than a decoration: its mark path has missing sessions, so every
   * path-dependent value on it is `PARTIAL`.
   */
  const gaps =
    trade.tradeId === PARTIAL_PATH_TRADE && trade.holdingSessions > 3
      ? [
          {
            between: [
              sessionInstant(days[trade.stages[0].session + 1]),
              sessionInstant(days[trade.stages[0].session + 2]),
            ] as [string, string],
            reason: "PRICE_PATH_INCOMPLETE" as const,
          },
        ]
      : [];

  return {
    trade_id: trade.tradeId,
    events,
    gaps,
    absent_kinds: ABSENT_LIFECYCLE_KINDS.map(([kind, availability, reason]) => ({
      kind: demoReason(kind),
      availability,
      reason,
    })),
  };
}

export { MISSING_RISK_RECORD_TRADE, PARTIAL_PATH_TRADE };
