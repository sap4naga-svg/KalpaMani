/**
 * The C8 execution-quality and reconciliation projections — Areas 9 and 10.
 *
 * **They are projections of the EXISTING recorded book.** Every fill, order, reference price,
 * latency and protective event below is read from the C6 execution evidence in
 * `execution.ts`; nothing is regenerated, no economics are restated, and the ledger, risk
 * denominators and trade population are untouched.
 *
 * THREE ILLUSTRATIVE ROWS ARE ADDED, AND THEY ARE NAMED AS SUCH. The recorded evidence
 * contains no rejected order, no cancelled order and no fill whose reference price went
 * unrecorded — three lifecycle outcomes Area 9 exists to show. They carry
 * `demo-exec-illustrative-` identifiers, they are listed in `illustrative_record_ids`, and
 * **the aggregate population is computed over the recorded fills only**, so an illustrative
 * row cannot move a headline.
 *
 * **NOTHING HERE IS A RESULT.** No execution runtime exists, no broker session exists, no
 * order has ever been submitted by this system beyond the certified Phase 2 scope, and the
 * broker is flat.
 */
import {
  halfEven,
  slippageHundredthBps,
  type ExecutionQuality,
} from "@/contracts/execution-models";
import type {
  ExecutionQualityPagePayload,
  ExecutionQualityRecord,
  ExecutionWindowAggregate,
  ReconciliationPayload,
  ReconciliationStatus,
} from "@/contracts/execution-quality-page";
import { instantOf } from "@/contracts/factories";
import type { Ref } from "@/contracts/values";

import { BOOK, type BookTrade } from "./book";
import {
  CALENDAR,
  count,
  demoRef,
  demoReason,
  instantValue,
  notApplicable,
  percent,
  refListOf,
  scaled,
  seconds,
  sessionInstant,
  shares,
  unavailable,
  usd,
} from "./common";
import {
  EXECUTION_SPECS,
  executionSpecFor,
  resolvedFills,
  type ResolvedFill,
} from "./execution";

/** §12.3's declared minimum for `slippage.aggregate`. Twenty fills, and it is not lowered. */
const AGGREGATE_MINIMUM_FILLS = 20;
/** §12.3's declared minimum for a per-fill `slippage`. One fill. */
const FILL_MINIMUM = 1;

const CLOCK_SOURCE = "FIXTURE_MONOTONIC_SESSION_CLOCK";
const CLOCK_ACCURACY_SECONDS = 1;
const REFERENCE_NAME = "DECISION_INSTANT_CONSOLIDATED_MARK";
const SIDE_CONVENTION = "BUY_POSITIVE_SELL_NEGATIVE_ADVERSE_IS_POSITIVE";
const AGGREGATION_METHOD = "QUANTITY_WEIGHTED_OVER_FILLS_WITH_A_RESOLVABLE_REFERENCE";
const COST_TREATMENT = "NET_COMMISSIONS";

/** §5.1: `/execution/quality` serves 50 rows by default. */
const EXECUTION_PAGE_SIZE = 50;
/** §5.1: `/execution/reconciliation` serves 25. */
const RECONCILIATION_PAGE_SIZE = 25;

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/** A protective confirmation that was never recorded. It is an absence, never a zero. */
function noConfirmation() {
  return unavailable(
    "execution.protection_confirmed_at",
    "DIMENSIONLESS",
    "NOT_YET_AVAILABLE",
    "UPSTREAM_INPUT_MISSING",
  );
}

/* ============================================================== Area 9 — the rows === */

/** Every trade whose execution evidence exists, in the ledger's own order. */
function tradesWithExecution(): readonly BookTrade[] {
  return BOOK.trades.filter((trade) => executionSpecFor(trade.tradeId) !== undefined);
}

/**
 * A per-fill quality measurement, built from the recorded fill.
 *
 * The arithmetic is `execution-models.ts`'s, unchanged: integer cents in, hundredths of a
 * basis point out, half-even at the declared scale, and `side_sign` derived from the SIDE
 * rather than from the position's direction.
 */
function fillQualityOf(fill: ResolvedFill, asOf: string): ExecutionQuality {
  const hundredths = slippageHundredthBps(fill.side, fill.priceCents, fill.referenceCents);
  return {
    scope: "FILL",
    subject_ref: demoRef(fill.fillId, "fill", "ENDPOINT"),
    side: fill.side,
    quantity: shares("execution.quantity", fill.shares, asOf),
    fill_price: usd("execution.fill_price", fill.priceCents, asOf),
    reference_price: {
      name: demoReason(REFERENCE_NAME),
      at: instantOf(fill.signalMs),
      side_convention: demoReason(SIDE_CONVENTION),
      price: usd("execution.reference_price", fill.referenceCents, asOf),
    },
    slippage:
      hundredths === null
        ? unavailable("slippage", "BPS", "NOT_APPLICABLE", "DENOMINATOR_ZERO")
        : scaled("slippage", "BPS", hundredths, asOf),
    /**
     * HOW MUCH OF THE ORDER HAD FILLED ONCE THIS FILL LANDED.
     *
     * A first fill of two reports the fraction it reached, not 100%: an order that is 69%
     * filled has not filled, and a per-fill record reporting 100% for every fill could never
     * show the partially filled state at all.
     */
    fill_rate: percent(
      "execution.fill_rate",
      halfEven(fill.cumulativeShares * 100 * 100, fill.orderedShares),
      asOf,
    ),
    signal_to_order_latency: seconds(
      "latency.signal_to_order",
      (fill.submittedMs - fill.signalMs) / 1000,
      asOf,
    ),
    order_to_fill_latency: seconds(
      "latency.order_to_fill",
      (fill.eventMs - fill.submittedMs) / 1000,
      asOf,
    ),
    clock_source: demoReason(CLOCK_SOURCE),
    clock_accuracy: seconds("clock.accuracy", CLOCK_ACCURACY_SECONDS, asOf),
    minimum_observations: count("performance.minimum_observations", FILL_MINIMUM, asOf),
    observation_count: count("performance.observation_count", 1, asOf),
  };
}

function protectionRefsFor(trade: BookTrade, asOf: string) {
  const events = executionSpecFor(trade.tradeId)?.protection ?? [];
  const refs: Ref[] = events.map((_event, index) =>
    demoRef(`${trade.tradeId}-protection-${index}`, "protection", "ENDPOINT"),
  );
  return refListOf(refs, "ZERO_OR_MORE", asOf);
}

/** The strategy module a trade's version belongs to, as a closed code. */
function moduleCodeOf(trade: BookTrade): string {
  return trade.versionId.replace(/-v\d+$/, "").replace(/-/g, "_").toUpperCase();
}

/**
 * The RECORDED cost of a fill: the commission the book charges it.
 *
 * A cent per hundred shares, floored at one cent, so the figure is legible and exact in
 * integers. **It is never netted against the modelled cost beside it** (§12.4).
 */
function recordedCostCents(fill: ResolvedFill): number {
  return Math.max(1, Math.round(fill.shares / 100));
}

/**
 * A MODELLED cost, where one applies — the spread a model would have assumed.
 *
 * §12.4: "an actual fill price already incorporates the spread crossed and the slippage
 * realized", so this is reported BESIDE the recorded cost and is never subtracted from it.
 * The book records no cost model for the short side, and those rows state the absence rather
 * than a zero.
 */
function modelledCostOf(fill: ResolvedFill, asOf: string) {
  if (fill.side === "SELL_TO_OPEN" || fill.side === "BUY_TO_COVER") {
    return unavailable(
      "execution.modelled_cost",
      "USD",
      "NOT_YET_AVAILABLE",
      "UPSTREAM_INPUT_MISSING",
    );
  }
  return usd("execution.modelled_cost", Math.max(1, Math.round(fill.shares / 50)), asOf);
}

/**
 * One row per recorded fill.
 *
 * **A fill is never counted as a trade** (§4.5): the trade it belongs to arrives by reference,
 * and the row's own identity is the fill's.
 */
function recordedRows(asOf: string, days: readonly string[]): ExecutionQualityRecord[] {
  const rows: ExecutionQualityRecord[] = [];
  for (const trade of tradesWithExecution()) {
    const spec = executionSpecFor(trade.tradeId);
    const protectionRefs = protectionRefsFor(trade, asOf);
    const events = spec?.protection ?? [];
    const protectionRecorded = events.length > 0;
    const cancelled = events.some((event) => event.kind === "CANCELLED");
    /*
     * A CONFIRMATION IS WHAT MAKES PROTECTION "WORKING", AND NOTHING ELSE IS.
     *
     * The book records a PLACED protective order for these trades, and a placement is a
     * submission. Only a trade whose protection was AMENDED after placement carries a later
     * recorded event this projection reads as a confirmation that the order was working.
     */
    const confirmed = events.some((event) => event.kind === "AMENDED");
    const state = !protectionRecorded
      ? "NONE_RECORDED"
      : cancelled
        ? "CANCELLED_RECORDED"
        : confirmed
          ? "CONFIRMED_WORKING"
          : "SUBMITTED_NOT_CONFIRMED";
    for (const fill of resolvedFills(trade, days)) {
      rows.push({
        record_id: `${fill.fillId}-quality`,
        quality: fillQualityOf(fill, asOf),
        trade_ref: demoRef(trade.tradeId, "trade", "ENDPOINT"),
        order_ref: demoRef(fill.orderId, "order", "ENDPOINT"),
        lifecycle_state: fill.completesOrder ? "FILLED" : "PARTIALLY_FILLED",
        side: fill.side,
        ordered_quantity: shares("execution.ordered_quantity", fill.orderedShares, asOf),
        filled_quantity: shares("execution.quantity", fill.cumulativeShares, asOf),
        event_time: instantOf(fill.eventMs),
        observed_time: instantOf(fill.observedMs),
        strategy_module: demoReason(moduleCodeOf(trade)),
        duplicate_protection: demoReason("DETERMINISTIC_IDENTITY_ACCEPTED"),
        protective_order_state: demoReason(state),
        protective_order_refs: protectionRefs,
        protection_confirmed_at:
          state === "CONFIRMED_WORKING"
            ? instantValue(
                "execution.protection_confirmed_at",
                instantOf(fill.acknowledgedMs),
                asOf,
              )
            : noConfirmation(),
        modelled_cost: modelledCostOf(fill, asOf),
        recorded_cost: usd("execution.recorded_cost", recordedCostCents(fill), asOf),
        cost_treatment: demoReason(COST_TREATMENT),
        cost_comparison_basis: demoReason("MODELLED_AND_RECORDED_REPORTED_SEPARATELY"),
      });
    }
  }
  return rows;
}

/* ------------------------------------------------------- the three illustrative rows */

const ILLUSTRATIVE_REJECTED = "demo-exec-illustrative-rejected";
const ILLUSTRATIVE_CANCELLED = "demo-exec-illustrative-cancelled";
const ILLUSTRATIVE_UNREFERENCED = "demo-exec-illustrative-unreferenced";

export const ILLUSTRATIVE_EXECUTION_RECORDS: readonly string[] = [
  ILLUSTRATIVE_REJECTED,
  ILLUSTRATIVE_CANCELLED,
  ILLUSTRATIVE_UNREFERENCED,
];

function illustrativeRows(asOf: string, originMs: number): ExecutionQualityRecord[] {
  const emptyRefs = refListOf([], "ZERO_OR_MORE", asOf);
  const eventMs = originMs - 2 * HOUR_MS;
  const shared = {
    protective_order_state: demoReason("NONE_RECORDED"),
    protective_order_refs: emptyRefs,
    protection_confirmed_at: noConfirmation(),
    cost_treatment: demoReason(COST_TREATMENT),
  };

  /**
   * A REJECTED order.
   *
   * Slippage measures a FILL against a reference, and there is no fill — so there is no
   * slippage, stated as `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` and never as a zero.
   * The fill rate IS a measured zero: the order filled none of what it asked for.
   */
  const rejected: ExecutionQualityRecord = {
    ...shared,
    record_id: ILLUSTRATIVE_REJECTED,
    quality: {
      scope: "ORDER",
      subject_ref: demoRef(`${ILLUSTRATIVE_REJECTED}-order`, "order", "ENDPOINT"),
      side: "BUY_TO_OPEN",
      quantity: shares("execution.quantity", 0, asOf),
      fill_price: unavailable(
        "execution.fill_price",
        "USD",
        "NOT_YET_AVAILABLE",
        "UPSTREAM_INPUT_MISSING",
      ),
      reference_price: {
        name: demoReason(REFERENCE_NAME),
        at: instantOf(eventMs),
        side_convention: demoReason(SIDE_CONVENTION),
        price: usd("execution.reference_price", 41_85, asOf),
      },
      slippage: unavailable("slippage", "BPS", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"),
      fill_rate: percent("execution.fill_rate", 0, asOf),
      signal_to_order_latency: seconds("latency.signal_to_order", 9, asOf),
      order_to_fill_latency: unavailable(
        "latency.order_to_fill",
        "SECONDS",
        "NOT_YET_AVAILABLE",
        "UPSTREAM_INPUT_MISSING",
      ),
      clock_source: demoReason(CLOCK_SOURCE),
      clock_accuracy: seconds("clock.accuracy", CLOCK_ACCURACY_SECONDS, asOf),
      minimum_observations: count("performance.minimum_observations", FILL_MINIMUM, asOf),
      observation_count: count("performance.observation_count", 0, asOf),
    },
    trade_ref: demoRef("demo-trade-arb-0001", "trade", "ENDPOINT"),
    order_ref: demoRef(`${ILLUSTRATIVE_REJECTED}-order`, "order", "ENDPOINT"),
    lifecycle_state: "REJECTED",
    side: "BUY_TO_OPEN",
    ordered_quantity: shares("execution.ordered_quantity", 145, asOf),
    filled_quantity: shares("execution.quantity", 0, asOf),
    event_time: instantOf(eventMs),
    observed_time: instantOf(eventMs),
    strategy_module: demoReason("BREAKOUT_LONG"),
    duplicate_protection: demoReason("DUPLICATE_SUPPRESSED_BY_DETERMINISTIC_IDENTITY"),
    modelled_cost: unavailable(
      "execution.modelled_cost",
      "USD",
      "NOT_YET_AVAILABLE",
      "UPSTREAM_INPUT_MISSING",
    ),
    recorded_cost: notApplicable("execution.recorded_cost", "USD"),
    cost_comparison_basis: demoReason("MODELLED_NOT_AVAILABLE_FOR_THIS_ORDER"),
  };

  /**
   * A CANCELLED order that had already filled part of its quantity.
   *
   * **A cancellation is not an exit.** The row reports what the order filled before it was
   * cancelled, and says nothing at all about the position it touched.
   */
  const cancelled: ExecutionQualityRecord = {
    ...shared,
    record_id: ILLUSTRATIVE_CANCELLED,
    quality: {
      scope: "ORDER",
      subject_ref: demoRef(`${ILLUSTRATIVE_CANCELLED}-order`, "order", "ENDPOINT"),
      side: "BUY_TO_OPEN",
      quantity: shares("execution.quantity", 24, asOf),
      fill_price: usd("execution.fill_price", 62_46, asOf),
      reference_price: {
        name: demoReason(REFERENCE_NAME),
        at: instantOf(eventMs - HOUR_MS),
        side_convention: demoReason(SIDE_CONVENTION),
        price: usd("execution.reference_price", 62_40, asOf),
      },
      slippage: scaled(
        "slippage",
        "BPS",
        slippageHundredthBps("BUY_TO_OPEN", 62_46, 62_40) ?? 0,
        asOf,
      ),
      fill_rate: percent("execution.fill_rate", halfEven(24 * 100 * 100, 60), asOf),
      signal_to_order_latency: seconds("latency.signal_to_order", 11, asOf),
      order_to_fill_latency: seconds("latency.order_to_fill", 4, asOf),
      clock_source: demoReason(CLOCK_SOURCE),
      clock_accuracy: seconds("clock.accuracy", CLOCK_ACCURACY_SECONDS, asOf),
      minimum_observations: count("performance.minimum_observations", FILL_MINIMUM, asOf),
      observation_count: count("performance.observation_count", 1, asOf),
    },
    trade_ref: demoRef("demo-trade-nvl-0002", "trade", "ENDPOINT"),
    order_ref: demoRef(`${ILLUSTRATIVE_CANCELLED}-order`, "order", "ENDPOINT"),
    lifecycle_state: "CANCELLED",
    side: "BUY_TO_OPEN",
    ordered_quantity: shares("execution.ordered_quantity", 60, asOf),
    filled_quantity: shares("execution.quantity", 24, asOf),
    event_time: instantOf(eventMs - HOUR_MS),
    observed_time: instantOf(eventMs - HOUR_MS),
    strategy_module: demoReason("PULLBACK_LONG"),
    duplicate_protection: demoReason("NO_DUPLICATE_OBSERVED"),
    modelled_cost: usd("execution.modelled_cost", 1, asOf),
    recorded_cost: usd("execution.recorded_cost", 1, asOf),
    cost_comparison_basis: demoReason("MODELLED_AND_RECORDED_REPORTED_SEPARATELY"),
  };

  /**
   * A FILL whose reference price was never recorded.
   *
   * §12.3: fills with no reference are EXCLUDED from the aggregate and COUNTED, and the
   * aggregate names how many. This is the row that count is about.
   */
  const unreferenced: ExecutionQualityRecord = {
    ...shared,
    record_id: ILLUSTRATIVE_UNREFERENCED,
    quality: {
      scope: "FILL",
      subject_ref: demoRef(`${ILLUSTRATIVE_UNREFERENCED}-fill`, "fill", "ENDPOINT"),
      side: "SELL_TO_CLOSE",
      quantity: shares("execution.quantity", 30, asOf),
      fill_price: usd("execution.fill_price", 95_12, asOf),
      reference_price: {
        name: demoReason("REFERENCE_PRICE_NOT_RECORDED"),
        at: instantOf(eventMs - 2 * HOUR_MS),
        side_convention: demoReason(SIDE_CONVENTION),
        price: unavailable(
          "execution.reference_price",
          "USD",
          "NOT_YET_AVAILABLE",
          "UPSTREAM_INPUT_MISSING",
        ),
      },
      slippage: unavailable("slippage", "BPS", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"),
      fill_rate: percent("execution.fill_rate", 100_00, asOf),
      signal_to_order_latency: seconds("latency.signal_to_order", 7, asOf),
      order_to_fill_latency: seconds("latency.order_to_fill", 3, asOf),
      clock_source: demoReason(CLOCK_SOURCE),
      clock_accuracy: seconds("clock.accuracy", CLOCK_ACCURACY_SECONDS, asOf),
      minimum_observations: count("performance.minimum_observations", FILL_MINIMUM, asOf),
      observation_count: count("performance.observation_count", 1, asOf),
    },
    trade_ref: demoRef("demo-trade-cir-0003", "trade", "ENDPOINT"),
    order_ref: demoRef(`${ILLUSTRATIVE_UNREFERENCED}-order`, "order", "ENDPOINT"),
    lifecycle_state: "FILLED",
    side: "SELL_TO_CLOSE",
    ordered_quantity: shares("execution.ordered_quantity", 30, asOf),
    filled_quantity: shares("execution.quantity", 30, asOf),
    event_time: instantOf(eventMs - 2 * HOUR_MS),
    observed_time: instantOf(eventMs - 2 * HOUR_MS),
    strategy_module: demoReason("PEAD_LONG"),
    duplicate_protection: demoReason("PROTECTION_OUTCOME_NOT_RECORDED"),
    modelled_cost: usd("execution.modelled_cost", 1, asOf),
    recorded_cost: usd("execution.recorded_cost", 1, asOf),
    cost_comparison_basis: demoReason("MODELLED_AND_RECORDED_REPORTED_SEPARATELY"),
  };

  return [rejected, cancelled, unreferenced];
}

/**
 * The window aggregate over the RECORDED fills.
 *
 * Quantity-weighted in integer hundredths of a basis point, rounded once at the end. Below the
 * declared twenty-fill minimum it reports `INSUFFICIENT_OBSERVATIONS` and **no number** — the
 * rule working, and never a headline manufactured from a smaller sample.
 */
function windowAggregate(
  fills: readonly ResolvedFill[],
  asOf: string,
): ExecutionWindowAggregate {
  let weightedHundredths = 0;
  let weight = 0;
  let filled = 0;
  let signalToOrderMs = 0;
  let orderToFillMs = 0;
  const orderedByOrder = new Map<string, number>();
  for (const fill of fills) {
    const hundredths = slippageHundredthBps(fill.side, fill.priceCents, fill.referenceCents);
    if (hundredths !== null) {
      weightedHundredths += hundredths * fill.shares;
      weight += fill.shares;
    }
    filled += fill.shares;
    signalToOrderMs += fill.submittedMs - fill.signalMs;
    orderToFillMs += fill.eventMs - fill.submittedMs;
    orderedByOrder.set(fill.orderId, fill.orderedShares);
  }
  const ordered = [...orderedByOrder.values()].reduce((total, value) => total + value, 0);
  const sufficient = fills.length >= AGGREGATE_MINIMUM_FILLS && weight > 0;
  const divisor = Math.max(fills.length, 1);
  return {
    aggregation_method: demoReason(AGGREGATION_METHOD),
    slippage: sufficient
      ? scaled("slippage.aggregate", "BPS", halfEven(weightedHundredths, weight), asOf)
      : unavailable(
          "slippage.aggregate",
          "BPS",
          "INSUFFICIENT_OBSERVATIONS",
          "BELOW_MINIMUM_OBSERVATIONS",
        ),
    fill_rate: percent(
      "execution.fill_rate",
      ordered === 0 ? 0 : halfEven(filled * 100 * 100, ordered),
      asOf,
    ),
    signal_to_order_latency: seconds(
      "latency.signal_to_order",
      signalToOrderMs / (divisor * 1000),
      asOf,
    ),
    order_to_fill_latency: seconds(
      "latency.order_to_fill",
      orderToFillMs / (divisor * 1000),
      asOf,
    ),
    quantity: shares("execution.quantity", filled, asOf),
    clock_source: demoReason(CLOCK_SOURCE),
    clock_accuracy: seconds("clock.accuracy", CLOCK_ACCURACY_SECONDS, asOf),
  };
}

export function syntheticExecutionQuality(
  asOf: string,
  days: readonly string[],
  originMs: number,
): ExecutionQualityPagePayload {
  const recorded = recordedRows(asOf, days);
  const rows = [...recorded, ...illustrativeRows(asOf, originMs)];
  const fills = tradesWithExecution().flatMap((trade) => resolvedFills(trade, days));
  /* The one illustrative fill whose reference went unrecorded is excluded and counted. */
  const excluded = 1;
  const delivered = rows.slice(0, EXECUTION_PAGE_SIZE);
  const outcome = (code: string, value: number) => ({
    outcome: demoReason(code),
    count: count("execution.outcome_count", value, asOf),
  });
  const withState = (state: ExecutionQualityRecord["lifecycle_state"]) =>
    rows.filter((row) => row.lifecycle_state === state).length;
  return {
    items: delivered,
    page: {
      page_size: EXECUTION_PAGE_SIZE,
      total: count("reference.total", rows.length, asOf),
      truncated: rows.length > EXECUTION_PAGE_SIZE,
      sort: demoReason("EVENT_TIME_DESCENDING"),
      tiebreak: demoReason("RECORD_ID_ASCENDING"),
    },
    window: {
      from: instantOf(originMs - 30 * DAY_MS),
      to: asOf,
      calendar: CALENDAR,
      timezone: "UTC",
    },
    aggregate: windowAggregate(fills, asOf),
    aggregate_population: {
      observed: count("performance.observation_count", fills.length, asOf),
      excluded: count("execution.excluded_fills", excluded, asOf),
      minimum: count("performance.minimum_observations", AGGREGATE_MINIMUM_FILLS, asOf),
      exclusion_reasons: [demoReason("REFERENCE_PRICE_NOT_RECORDED")],
    },
    outcomes: [
      outcome("ORDERS_FILLED", withState("FILLED")),
      outcome("ORDERS_PARTIALLY_FILLED", withState("PARTIALLY_FILLED")),
      outcome("ORDERS_REJECTED", withState("REJECTED")),
      outcome("ORDERS_CANCELLED", withState("CANCELLED")),
      outcome(
        "DUPLICATES_SUPPRESSED",
        rows.filter(
          (row) =>
            row.duplicate_protection.code === "DUPLICATE_SUPPRESSED_BY_DETERMINISTIC_IDENTITY",
        ).length,
      ),
      {
        /**
         * A MISSED FILL IS NOT MEASURED HERE, AND THAT IS AN ABSENCE.
         *
         * Establishing that a fill was missed needs a market path nobody holds, so the count
         * is `UNEVALUATED` rather than a zero standing in for an unasked question.
         */
        outcome: demoReason("MISSED_FILLS"),
        count: unavailable(
          "execution.outcome_count",
          "COUNT",
          "UNEVALUATED",
          "NOT_YET_ASSESSED",
        ),
      },
    ],
    reference_basis: {
      name: demoReason(REFERENCE_NAME),
      side_convention: demoReason(SIDE_CONVENTION),
      clock_source: demoReason(CLOCK_SOURCE),
    },
    runtime_state: {
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
      note: demoReason("NO_AUTOMATED_EXECUTION_RUNTIME_EXISTS"),
    },
    illustrative_record_ids: [...ILLUSTRATIVE_EXECUTION_RECORDS],
  };
}

/* ================================================== Area 10 — recorded reconciliation === */

/** The identifiers the narrative links to, reused by the operations and audit projections. */
export const RECONCILIATION_MISMATCH_RUN = "demo-recon-0001";
export const RECONCILIATION_ORPHAN_INCIDENT = "demo-incident-0002";

function balance(measure: string, internalCents: number, brokerCents: number, asOf: string) {
  return {
    measure: demoReason(measure),
    internal: usd("reconciliation.internal_amount", internalCents, asOf),
    broker_reported: usd("reconciliation.broker_amount", brokerCents, asOf),
    difference: usd("reconciliation.amount_difference", brokerCents - internalCents, asOf),
    informational_only: true as const,
  };
}

function brokerAsOf(ms: number, asOf: string) {
  return instantValue("reconciliation.broker_as_of", instantOf(ms), asOf);
}

function noBrokerAsOf() {
  return unavailable(
    "reconciliation.broker_as_of",
    "DIMENSIONLESS",
    "NOT_YET_AVAILABLE",
    "UPSTREAM_INPUT_MISSING",
  );
}

function noOrphanCount() {
  return unavailable(
    "reconciliation.orphans",
    "COUNT",
    "NOT_YET_AVAILABLE",
    "UPSTREAM_INPUT_MISSING",
  );
}

function quantityMetric(metricId: string, value: number, asOf: string) {
  return shares(metricId, value, asOf);
}

/**
 * The per-trade sweeps the recorded book already references.
 *
 * `TradeDetail.reconciliation_refs` has named `<trade-id>-reconciliation` since C6 and
 * declared an `ENDPOINT` resolution for it. Until this cycle no endpoint existed; now one
 * does, so the reference is bound to **an actual matching record** rather than left pointing
 * at an identifier nothing holds.
 *
 * Each run reports exactly what the book records: a clean sweep over ONE trade, with a
 * measured zero orphans and no difference of any kind.
 */
function perTradeRuns(
  asOf: string,
  days: readonly string[],
  evaluated: number,
): ReconciliationStatus[] {
  const runs: ReconciliationStatus[] = [];
  for (const spec of EXECUTION_SPECS) {
    if (spec.reconciliation === null) {
      continue;
    }
    const trade = BOOK.trades.find((candidate) => candidate.tradeId === spec.tradeId);
    if (trade === undefined) {
      continue;
    }
    const session = trade.lastSession + spec.reconciliation.sessionOffset;
    const at = Date.parse(sessionInstant(days[Math.min(session, days.length - 1)]));
    runs.push({
      run_id: `${spec.tradeId}-reconciliation`,
      as_of: instantOf(at),
      result: demoReason(spec.reconciliation.result),
      comparison_scope: demoReason("ONE_TRADE_POSITION_AND_ORDERS"),
      internal_as_of: instantOf(at),
      broker_as_of: brokerAsOf(at, asOf),
      as_of_alignment: demoReason("AS_OF_TIMES_ALIGNED"),
      position_diffs: [],
      order_diffs: [],
      ownership_findings: [],
      balances: [],
      /** A MEASURED zero: this sweep ran over one trade and found no orphan. */
      orphans: count("reconciliation.orphans", 0, asOf),
      session_state: demoReason("SESSION_RECORDED_CONNECTED"),
      session_events: [],
      missing_inputs: [],
      incident_refs: refListOf([], "ZERO_OR_MORE", asOf),
      trade_refs: refListOf(
        [demoRef(spec.tradeId, "trade", "ENDPOINT")],
        "EXACTLY_ONE",
        asOf,
      ),
      age: seconds("reconciliation.age", (evaluated - at) / 1000, asOf),
    });
  }
  return runs;
}

export function syntheticReconciliation(
  asOf: string,
  originMs: number,
  days: readonly string[],
): ReconciliationPayload {
  const emptyIncidents = refListOf([], "ZERO_OR_MORE", asOf);
  const emptyTrades = refListOf([], "ZERO_OR_MORE", asOf);
  const subject = BOOK.openTrades[0];
  const evaluated = Date.parse(asOf);
  const mismatchAt = originMs - HOUR_MS;
  const reconciledAt = originMs - 25 * HOUR_MS;
  const missingAt = originMs - 49 * HOUR_MS;
  const notAttemptedAt = originMs - 73 * HOUR_MS;
  const ageOf = (at: number) => seconds("reconciliation.age", (evaluated - at) / 1000, asOf);

  /**
   * The newest run, and it found something.
   *
   * The orphan it records is the same condition the executive attention list carries as
   * `RECONCILIATION_ORPHAN_OBSERVED`, so the two views describe one finding rather than two.
   */
  const mismatch: ReconciliationStatus = {
    run_id: RECONCILIATION_MISMATCH_RUN,
    as_of: instantOf(mismatchAt),
    result: demoReason("MISMATCH_RECORDED"),
    comparison_scope: demoReason("OPEN_POSITIONS_ORDERS_AND_CASH"),
    internal_as_of: instantOf(mismatchAt),
    /** Two minutes apart, and the alignment field SAYS SO rather than letting it pass. */
    broker_as_of: brokerAsOf(mismatchAt - 2 * MINUTE_MS, asOf),
    as_of_alignment: demoReason("AS_OF_TIMES_DIFFER"),
    position_diffs: [
      {
        security_ref: demoRef(`security-${subject.symbol}`, "evidence", "AUTHORIZED_READ"),
        expected: quantityMetric("reconciliation.expected_quantity", subject.sharesOpen, asOf),
        observed: quantityMetric(
          "reconciliation.observed_quantity",
          subject.sharesOpen - 5,
          asOf,
        ),
        difference: quantityMetric("reconciliation.quantity_difference", -5, asOf),
        finding: demoReason("BROKER_QUANTITY_BELOW_INTERNAL"),
      },
    ],
    order_diffs: [
      {
        local_ref: demoRef("demo-trade-arb-0001-order-0", "order", "ENDPOINT"),
        disposition: demoReason("LOCAL_ORDER_NOT_PRESENT_BROKER_SIDE"),
      },
    ],
    ownership_findings: [
      {
        local_ref: demoRef("demo-trade-nvl-0002-order-1", "order", "ENDPOINT"),
        finding: demoReason("BROKER_ORDER_WITHOUT_LOCAL_OWNER"),
        disposition: demoReason("RECORDED_FOR_HUMAN_REVIEW"),
      },
    ],
    balances: [
      balance("SETTLED_CASH", 12_400_00, 12_400_00, asOf),
      /**
       * BROKER-REPORTED EQUITY, OBSERVED AND INFORMATIONAL.
       *
       * The broker reports a simulated million; KalpaMani strategy capital is USD 80,000 and
       * is authoritative (CLAUDE.md §6). The difference is displayed as a difference, and
       * neither figure participates in sizing anywhere in this application.
       */
      balance("BROKER_REPORTED_EQUITY", 80_000_00, 1_000_000_00, asOf),
    ],
    orphans: count("reconciliation.orphans", 1, asOf),
    session_state: demoReason("SESSION_RECORDED_RECONNECTED"),
    session_events: [
      { at: instantOf(mismatchAt - 3 * HOUR_MS), event: demoReason("GATEWAY_RESTART_RECORDED") },
      { at: instantOf(mismatchAt - 2 * HOUR_MS), event: demoReason("SESSION_RECONNECT_RECORDED") },
      {
        at: instantOf(mismatchAt - HOUR_MS + MINUTE_MS),
        event: demoReason("AUTHENTICATION_CHALLENGE_RECORDED"),
      },
    ],
    missing_inputs: [],
    incident_refs: refListOf(
      [demoRef(RECONCILIATION_ORPHAN_INCIDENT, "incident", "ENDPOINT", "SYSTEM_OPERATIONS")],
      "ZERO_OR_MORE",
      asOf,
    ),
    trade_refs: refListOf(
      [
        demoRef("demo-trade-arb-0001", "trade", "ENDPOINT"),
        demoRef("demo-trade-nvl-0002", "trade", "ENDPOINT"),
      ],
      "ZERO_OR_MORE",
      asOf,
    ),
    age: ageOf(mismatchAt),
  };

  /** An older run that reconciled cleanly. It is a HISTORICAL success and nothing more. */
  const reconciled: ReconciliationStatus = {
    run_id: "demo-recon-0002",
    as_of: instantOf(reconciledAt),
    result: demoReason("RECONCILED"),
    comparison_scope: demoReason("OPEN_POSITIONS_ORDERS_AND_CASH"),
    internal_as_of: instantOf(reconciledAt),
    broker_as_of: brokerAsOf(reconciledAt, asOf),
    as_of_alignment: demoReason("AS_OF_TIMES_ALIGNED"),
    position_diffs: [],
    order_diffs: [],
    ownership_findings: [],
    balances: [balance("SETTLED_CASH", 12_400_00, 12_400_00, asOf)],
    /** A MEASURED zero — the sweep ran and found no orphan. */
    orphans: count("reconciliation.orphans", 0, asOf),
    session_state: demoReason("SESSION_RECORDED_CONNECTED"),
    session_events: [],
    missing_inputs: [],
    incident_refs: emptyIncidents,
    trade_refs: emptyTrades,
    age: ageOf(reconciledAt),
  };

  /** A run that could not read one side. A missing input is neither zero nor a match. */
  const missingInput: ReconciliationStatus = {
    run_id: "demo-recon-0003",
    as_of: instantOf(missingAt),
    result: demoReason("COMPARISON_INPUT_MISSING"),
    comparison_scope: demoReason("OPEN_POSITIONS_ONLY"),
    internal_as_of: instantOf(missingAt),
    broker_as_of: noBrokerAsOf(),
    as_of_alignment: demoReason("BROKER_AS_OF_NOT_RECORDED"),
    position_diffs: [],
    order_diffs: [],
    ownership_findings: [],
    balances: [],
    orphans: noOrphanCount(),
    session_state: demoReason("SESSION_RECORDED_DISCONNECTED"),
    session_events: [
      { at: instantOf(missingAt - HOUR_MS), event: demoReason("SESSION_DISCONNECT_RECORDED") },
    ],
    missing_inputs: [demoReason("BROKER_POSITION_SNAPSHOT_NOT_RECORDED")],
    incident_refs: emptyIncidents,
    trade_refs: emptyTrades,
    age: ageOf(missingAt),
  };

  /** A scheduled sweep that never ran. It compared nothing and counted nothing. */
  const notAttempted: ReconciliationStatus = {
    run_id: "demo-recon-0004",
    as_of: instantOf(notAttemptedAt),
    result: demoReason("NOT_ATTEMPTED"),
    comparison_scope: demoReason("OPEN_POSITIONS_ORDERS_AND_CASH"),
    internal_as_of: instantOf(notAttemptedAt),
    broker_as_of: noBrokerAsOf(),
    as_of_alignment: demoReason("BROKER_AS_OF_NOT_RECORDED"),
    position_diffs: [],
    order_diffs: [],
    ownership_findings: [],
    balances: [],
    orphans: noOrphanCount(),
    session_state: demoReason("SESSION_STATE_NOT_RECORDED"),
    session_events: [],
    missing_inputs: [demoReason("SWEEP_DID_NOT_RUN")],
    incident_refs: emptyIncidents,
    trade_refs: emptyTrades,
    age: ageOf(notAttemptedAt),
  };

  const items = [
    mismatch,
    reconciled,
    missingInput,
    notAttempted,
    ...perTradeRuns(asOf, days, evaluated),
  ];
  return {
    items,
    page: {
      page_size: RECONCILIATION_PAGE_SIZE,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("AS_OF_DESCENDING"),
      tiebreak: demoReason("RUN_ID_ASCENDING"),
    },
    latest_run_id: RECONCILIATION_MISMATCH_RUN,
    /**
     * PRESENT HEALTH IS NOT ESTABLISHED BY A PAST RUN.
     *
     * The newest recorded run found a mismatch an hour ago, nothing observes the broker now,
     * and no run since has been recorded. The honest present state is an absence.
     */
    current_health: {
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
      note: demoReason("NO_LIVE_RECONCILIATION_OBSERVES_THE_BROKER_NOW"),
    },
    broker_session: {
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
      note: demoReason("THE_COCKPIT_HOLDS_NO_BROKERAGE_CREDENTIAL_AND_OPENS_NO_SESSION"),
    },
    absent_controls: [
      demoReason("CONNECT"),
      demoReason("RECONNECT"),
      demoReason("AUTHENTICATE"),
      demoReason("REFRESH_FROM_BROKER"),
      demoReason("REPAIR"),
    ],
  };
}
