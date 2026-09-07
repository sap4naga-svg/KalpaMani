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
 * WHAT C6 ADDED, AND FOR WHICH TRADES. Orders, fills, protective-order events, reconciliation,
 * appended corrections, per-fill execution quality and a declared attribution are carried for
 * the **six** trades that have a declared execution record in `execution.ts`. **Every other
 * trade keeps exactly what C5 carried**, with each of those kinds named as absent — because a
 * trade ledger row does not say how many fills it took, and inferring one would manufacture an
 * execution history out of a position size.
 *
 * Execution History and the Audit Trail remain separate screens (Area 36.3). This carries ONE
 * TRADE's execution quality, embedded; it does not implement the Area 9 aggregate surface, and
 * the audit reference still resolves to an availability state rather than to a payload.
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
  BENCHMARK_INDEX,
  BOOK,
  MISSING_RISK_RECORD_TRADE,
  PARTIAL_PATH_TRADE,
  centsToDecimal,
  securityOf,
  strategyVersionOf,
} from "./book";
import {
  aggregateQuality,
  attributionCents,
  declaredAbsentKinds,
  executionEvents,
  executionRefs,
  fillQuality,
  hasExecutionRecord,
} from "./execution";
import { candidateForTrade } from "./signals";
import {
  CALENDAR,
  count,
  demoRef,
  percent as percentValue,
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
import { demoPins, initialRiskRecord, openRiskRecord, stageRiskRecord } from "./positions";

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
  /** Whether this trade ever pyramided. The additive add fields exist only when it did. */
  const added = trade.stages.length > 1;

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
    /** The ORIGINAL entry stage's filled price. A later add never restates it (§12.4). */
    entry_price: usd("trade.entry_price", trade.stages[0].priceCents, asOf),
    exit_time: exitTime,
    exit_price: exitPrice,
    /** Filled AT ENTRY. What the trade went on to acquire is `shares_acquired`. */
    shares_at_entry: trade.stages[0].shares,
    ...(added
      ? {
          shares_acquired: trade.sharesAcquired,
          current_basis: usd("position.entry_price", trade.basisCents, asOf),
        }
      : {}),
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
    ...(added
      ? {
          /** Each add's own retained record, at its own reference price and as-of (§12.4). */
          add_planned_risk: trade.stages.slice(1).map((_stage, index) => ({
            stage_ordinal: index + 1,
            record: stageRiskRecord(trade, index + 1, days),
          })),
        }
      : {}),
    open_planned_risk: openRiskRecord(trade, days, asOf),
    ...(added && trade.initialRiskRecorded
      ? {
          /** The SUM of every retained stage record — what `r_multiple` was divided by. */
          r_denominator: {
            amount: centsToDecimal(trade.initialRiskCents),
            currency: "USD" as const,
          },
        }
      : {}),
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
 * The stages a trade WITH a declared execution record still does not carry.
 *
 * Four of the ten above are answered for those six trades; the rest are not. **The risk
 * decision is the one that matters most and is still absent**: no risk engine exists, so
 * nothing recorded why this size rather than another, and a trade whose orders and fills are
 * fully described still cannot say that.
 */
const RECORDED_DETAIL_GAPS = [
  ["RISK_ENGINE_DECISION", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["IMMUTABLE_AUDIT_EVENTS", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
] as const;

/** The one gap a trade with no journaled candidate carries, and one with a candidate does not. */
const NO_CANDIDATE_GAPS = [
  ["CANDIDATE_AND_THESIS", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
  ["BRAIN_DECISION_RECORD", "NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED"],
] as const;

/** The gaps a trade with no execution record carries, on top of the two above. */
const NO_EXECUTION_GAPS = [
  ["ORDER_AND_FILL_MECHANICS", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["PROTECTIVE_ORDER_EVENTS", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["BROKER_RECONCILIATION", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["EXECUTION_QUALITY", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["PERFORMANCE_ATTRIBUTION", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
] as const;

/**
 * The benchmark slice aligned to EXACTLY this trade's holding period.
 *
 * §12.4: "the benchmark is aligned to the **exact** boundaries the subject used". The slice
 * starts at the trade's own entry session and ends at its own last session, and the values are
 * the index's return SINCE THAT ENTRY — so the first point is a measured zero rather than an
 * index level a reader would have to normalise themselves.
 */
export function benchmarkSeries(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): { series: Series; movementHundredths: number } {
  const first = trade.stages[0].session;
  const last = trade.lastSession;
  const base = BENCHMARK_INDEX[first];
  const points = [];
  for (let session = first; session <= last; session += 1) {
    points.push({
      t: days[session],
      v: percentValue(
        "benchmark.return",
        Math.round(((BENCHMARK_INDEX[session] - base) * 10_000) / base),
        asOf,
      ),
    });
  }
  return {
    series: {
      points,
      granularity: "DAILY",
      calendar: CALENDAR,
      timezone: "UTC",
      coverage: { present: points.length, requested: points.length },
      completeness: "COMPLETE",
    },
    movementHundredths: Math.round(
      ((BENCHMARK_INDEX[last] - base) * 10_000) / base,
    ),
  };
}

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
  const recorded = hasExecutionRecord(trade.tradeId);
  const candidate = candidateForTrade(trade.tradeId);
  const refs = executionRefs(trade, days, asOf);
  const quality = aggregateQuality(trade, days, asOf);
  const attribution = attributionCents(trade);
  const benchmark = benchmarkSeries(trade, days, asOf);
  const unavailableMetric = (metricId: string) =>
    unavailable(metricId, "USD", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING");

  const gaps = [
    ...(candidate === undefined ? NO_CANDIDATE_GAPS : []),
    ...(recorded ? RECORDED_DETAIL_GAPS : [...NO_EXECUTION_GAPS, ...RECORDED_DETAIL_GAPS]),
  ];

  return {
    trade_id: trade.tradeId,
    summary,
    /*
     * THE CANDIDATE RESOLVES BY ENDPOINT WHERE ONE WAS JOURNALED.
     *
     * §4.3 assigns `candidate` an ENDPOINT resolution, and C6 implements that endpoint, so a
     * trade with a journaled candidate carries a reference a reader can actually follow. Most
     * trades have none, and theirs stays UNRESOLVABLE_V1.
     */
    candidate_ref:
      candidate === undefined
        ? demoRef(`${trade.tradeId}-candidate`, "candidate")
        : demoRef(candidate.candidateId, "candidate", "ENDPOINT"),
    /*
     * §4.3 assigns `brain_decision` an EMBEDDED resolution, because the journaled decision
     * status lives INSIDE `CandidateDetail`. It is not inside THIS response, so calling it
     * EMBEDDED here would claim a payload this response does not carry. Where a candidate was
     * journaled it is one authorized read away and is carried as ENDPOINT; where none was, it
     * resolves to an availability state like every other absent producer.
     */
    brain_decision_ref:
      candidate === undefined
        ? demoRef(`${trade.tradeId}-brain-decision`, "brain_decision")
        : demoRef(candidate.candidateId, "brain_decision", "ENDPOINT"),
    /** No risk engine exists, so nothing recorded why this size rather than another. */
    risk_decision_ref: demoRef(`${trade.tradeId}-risk-decision`, "risk_decision"),
    order_refs: refs.order_refs,
    fill_refs: refs.fill_refs,
    protection_refs: refs.protection_refs,
    add_refs: refListOf(
      trade.stages
        .filter((stage) => stage.kind === "ADD")
        .map((stage, index) => demoRef(`${trade.tradeId}-add-${index}`, "add", "EMBEDDED")),
      "ZERO_OR_MORE",
      asOf,
    ),
    exit_ref: closed ? demoRef(`${trade.tradeId}-exit`, "exit", "EMBEDDED") : undefined,
    reconciliation_refs: refs.reconciliation_refs,
    execution_quality_ref:
      quality === undefined
        ? demoRef(`${trade.tradeId}-execution-quality`, "execution_quality")
        : demoRef(`${trade.tradeId}-execution-quality`, "execution_quality", "EMBEDDED"),
    execution_quality: quality,
    fill_quality: [...fillQuality(trade, days, asOf)],
    attribution:
      attribution === null
        ? {
            /*
             * NOTHING IS ATTRIBUTED FOR THIS TRADE. Strategy, factor, regime, execution and
             * cost attribution each need a producer that does not exist; a provisional zero
             * would be a decomposition nobody computed.
             */
            strategy: unavailableMetric("pnl.combined"),
            factor: unavailableMetric("pnl.combined"),
            regime: unavailableMetric("pnl.combined"),
            execution: unavailableMetric("pnl.combined"),
            cost: unavailableMetric("pnl.combined"),
            state: "PROVISIONAL",
          }
        : {
            strategy: usd("pnl.combined", attribution.strategy, asOf),
            factor: usd("pnl.combined", attribution.factor, asOf),
            regime: usd("pnl.combined", attribution.regime, asOf),
            execution: usd("pnl.combined", attribution.execution, asOf),
            cost: usd("pnl.combined", attribution.cost, asOf),
            state: attribution.state,
          },
    /*
     * THE BENCHMARK MOVED OVER EXACTLY THIS TRADE'S HOLDING PERIOD.
     *
     * `PRICE_RETURN`, because the index pays no dividend and reinvests nothing -- and so do
     * the demonstration securities it is measured beside. §12.4 forbids comparing a
     * price-return benchmark against a total-return subject, and the way to obey that is for
     * both sides to be the same kind of return rather than for the label to be adjusted.
     */
    benchmark_movement: percentValue(
      "benchmark.movement",
      benchmark.movementHundredths,
      asOf,
    ),
    benchmark_basis: "PRICE_RETURN",
    benchmark_series_ref: demoRef(`${trade.tradeId}-benchmark`, "benchmark_series", "EMBEDDED"),
    benchmark_series: benchmark.series,
    benchmark_window: {
      from: summary.entry_time,
      to: sessionInstant(days[trade.lastSession]),
      calendar: CALENDAR,
      timezone: "UTC",
    },
    benchmark_label: demoReason("DEMONSTRATION_BROAD_MARKET_INDEX"),
    lineage: demoPins(trade.versionId),
    /** The audit trail is a separate screen and a separate read model, and neither exists. */
    audit_refs: refListOf([], "ZERO_OR_MORE", asOf),
    chart_series_ref: demoRef(`${trade.tradeId}-marks`, "chart_series", "EMBEDDED"),
    chart_series: tradeChartSeries(trade, days, asOf),
    gaps: gaps.map(([expected, availability, reason]) => ({
      expected: demoReason(expected),
      availability,
      reason,
    })),
  };
}

/* --------------------------------------------------------------- TradeLifecycle */

/**
 * The kinds a trade with NO declared execution record does not carry.
 *
 * `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` rather than `NOT_IMPLEMENTED`: C6 does
 * implement the producer — six trades in this very book have these events — so the honest
 * statement for the other one hundred and ninety-four is that **this trade's evidence was
 * never written**, not that nothing can write it.
 */
const ABSENT_LIFECYCLE_KINDS = [
  ["ORDER_SUBMITTED", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["ORDER_ACKNOWLEDGED", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["INDIVIDUAL_FILL", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["PROTECTIVE_ORDER_PLACED", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["PROTECTIVE_ORDER_AMENDED", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
  ["BROKER_RECONCILIATION", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"],
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
    ...trade.exits.map((exit, index) => {
      /*
       * PARTIAL OR FINAL IS A QUESTION ABOUT WHAT IS LEFT.
       *
       * An earlier revision compared this exit's quantity against the trade's whole filled
       * quantity, which answers a different question: an exit that closes the remainder
       * after earlier partial exits is smaller than the entry and is still the final one,
       * and an exit of 70 out of 100 held is larger than a 60-share entry and is still
       * partial. The remaining position after this exit decides it, and nothing else does.
       */
      const releasedThrough = trade.exits
        .slice(0, index + 1)
        .reduce((total, earlier) => total + earlier.shares, 0);
      const remaining = trade.sharesAcquired - releasedThrough;
      return {
        event_id: `${trade.tradeId}-exit-${index}`,
        event_kind: demoReason(remaining > 0 ? "PARTIAL_EXIT_RECORDED" : "EXIT_RECORDED"),
        event_time: sessionInstant(days[exit.session]),
        observed_time: sessionInstant(days[exit.session]),
        quantity: exit.shares,
        price: usd("trade.mark_price", exit.priceCents, asOf),
        /*
         * A POSITION REDUCTION IS NOT AN ORDER FILL STATE.
         *
         * An earlier revision reported `ORDER_PARTIALLY_FILLED` whenever an exit was smaller
         * than the trade's quantity — but a partial exit is routinely executed by an order
         * that filled completely, and the two facts are recorded by different producers.
         * This book records completed stage and exit fills and nothing else; per-order and
         * per-fill evidence has no producer here, which `absent_kinds` states below as
         * `INDIVIDUAL_FILL` / `PRODUCER_NOT_IMPLEMENTED`. So every recorded event reports
         * the fill state it actually has, and no order state is inferred from a quantity
         * comparison.
         */
        downstream_stage: "ORDER_FILLED" as const,
        source_ref: demoRef(`${trade.tradeId}-exit-${index}-source`, "source_fact"),
      };
    }),
    ...executionEvents(trade, days, asOf),
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
    absent_kinds: (hasExecutionRecord(trade.tradeId)
      ? declaredAbsentKinds(trade.tradeId)
      : ABSENT_LIFECYCLE_KINDS
    ).map(([kind, availability, reason]) => ({
      kind: demoReason(kind),
      availability,
      reason,
    })),
  };
}

export { MISSING_RISK_RECORD_TRADE, PARTIAL_PATH_TRADE };
