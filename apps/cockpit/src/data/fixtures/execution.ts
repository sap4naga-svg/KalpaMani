/**
 * THE DECLARED EXECUTION EVIDENCE.
 *
 * Orders, fills, protective-order events, reconciliation and appended corrections, for the
 * handful of demonstration trades that **have** such a record. Everything here is a fictional
 * record that was written down; **nothing is inferred from a trade's quantity**.
 *
 * WHY DECLARATION MATTERS MORE HERE THAN ANYWHERE ELSE IN THE BOOK. A trade ledger row says a
 * trade acquired 145 shares. It does not say whether that was one fill or four, what reference
 * price the order was measured against, whether a protective order was ever placed, or whether
 * anybody reconciled it. Deriving those from the quantity would manufacture an execution
 * history out of a position size — which is precisely the "missing event inferred" failure
 * Area 36.4 forbids. So a trade either has a declared record here, or its lifecycle names every
 * one of those kinds as absent.
 *
 * **MOST TRADES HAVE NO RECORD, AND THAT IS DELIBERATE.** Six do. The other one hundred and
 * ninety-four keep the trade-level stages C5 carried, with every execution kind named as
 * absent, so a reviewer can see that the interface does not manufacture completeness.
 *
 * THE ARITHMETIC IS CHECKED, NOT TRUSTED. A multi-fill order's quantity-weighted price must
 * equal the price the ledger recorded for that stage, and this module REFUSES a declaration
 * where it does not: a lifecycle whose fills disagree with the ledger row above them is two
 * different trades wearing one identity.
 */
import { instantOf } from "@/contracts/factories";
import type { ExecutionQuality, OrderSide } from "@/contracts/execution-models";
import { slippageHundredthBps, halfEven } from "@/contracts/execution-models";
import type { TradeLifecycleEvent } from "@/contracts/portfolio-models";
import type { Ref } from "@/contracts/values";
import type { AvailabilityState, FieldReasonCode } from "@/contracts/vocabularies";

import type { BookTrade } from "./book";
import {
  BOOK,
  MISSING_RISK_RECORD_TRADE,
  MULTI_EXIT_TRADE,
  PARTIAL_PATH_TRADE,
} from "./book";
import {
  count,
  demoRef,
  demoReason,
  percent,
  refListOf,
  scaled,
  seconds,
  sessionInstant,
  shares as sharesMetric,
  token,
  unavailable,
  usd,
} from "./common";

/* ------------------------------------------------------------------ declarations */

/** One fill of one order. `priceOffsetCents` is signed, against the ledger's recorded price. */
interface FillSpec {
  readonly shares: number;
  readonly priceOffsetCents: number;
  /** Seconds before the recorded stage instant this fill occurred at. */
  readonly beforeStageSeconds: number;
  /**
   * A fill that reached this system later than it happened.
   *
   * `observed_time` is retained separately from `event_time`, and **a late event advances no
   * watermark it did not cover**. Ordering stays by `event_time`, so a late fill sits where it
   * happened rather than where it arrived.
   */
  readonly observedLateSeconds?: number;
}

interface OrderSpec {
  /** Which recorded stage or exit of the trade this order produced. */
  readonly target: { readonly kind: "STAGE" | "EXIT"; readonly ordinal: number };
  readonly side: OrderSide;
  /** The named reference price, as a signed offset from the recorded price. */
  readonly referenceOffsetCents: number;
  /** Seconds between the journaled decision and the order leaving. */
  readonly signalToOrderSeconds: number;
  readonly acknowledgeSeconds: number;
  readonly fills: readonly FillSpec[];
}

interface ProtectionSpec {
  readonly kind: "PLACED" | "AMENDED" | "CANCELLED";
  /** The session this protective event was recorded on, as an offset into the trade's path. */
  readonly sessionOffset: number;
  readonly levelCents: number;
  readonly protectedShares: number;
  /** A later event that corrects this one. The corrected event is never mutated. */
  readonly correctedByLevelCents?: number;
}

/**
 * The DECLARED attribution decomposition of a trade's outcome.
 *
 * Four shares are declared in hundredths of a percent of the trade's combined result, and the
 * strategy limb takes whatever remains, so the five components sum to the outcome EXACTLY.
 * A decomposition that does not add up to the thing it decomposes is five numbers, not an
 * attribution.
 *
 * **It is a declared fictional record, not a computed one.** No factor model, no regime model
 * and no cost model exists; a real attribution needs all three, and inventing one would be the
 * fabrication every other absence in this book refuses.
 */
interface AttributionSpec {
  readonly factorHundredths: number;
  readonly regimeHundredths: number;
  readonly executionHundredths: number;
  readonly costHundredths: number;
  /** Finalization is a RECORDED EVENT, so an open trade's decomposition stays provisional. */
  readonly state: "PROVISIONAL" | "FINAL";
}

interface ExecutionSpec {
  readonly tradeId: string;
  readonly reconciliation: {
    readonly sessionOffset: number;
    readonly result: string;
  } | null;
  readonly attribution: AttributionSpec | null;
  readonly orders: readonly OrderSpec[];
  readonly protection: readonly ProtectionSpec[];
  /** Kinds this trade's record genuinely does not contain, each with the state that says why. */
  readonly absentKinds: readonly (readonly [string, AvailabilityState, FieldReasonCode])[];
}

/** No protective order is recorded, and that absence is stated rather than left blank. */
const NO_PROTECTION_RECORD = [
  "PROTECTIVE_ORDER_PLACED",
  "NOT_YET_AVAILABLE",
  "UPSTREAM_INPUT_MISSING",
] as const;

/** Nobody reconciled this trade against the broker, and nothing pretends otherwise. */
const NO_RECONCILIATION_RECORD = [
  "BROKER_RECONCILIATION",
  "NOT_YET_AVAILABLE",
  "UPSTREAM_INPUT_MISSING",
] as const;

/** The query ran and found nothing — a COMPLETED query over an empty population. */
const NO_CORRECTIONS = ["CORRECTION_APPENDED", "EMPTY_VERIFIED", "EMPTY_RESULT_VERIFIED"] as const;

/**
 * The six trades whose execution evidence exists.
 *
 *   demo-trade-sol-0006   a CLOSED LONG reduced twice and then closed by its remaining
 *                         balance. Four orders, each FULLY FILLED; two of them reduce the
 *                         position without closing it, which is what makes "a fully filled
 *                         order that partially exits a position" a different fact from "a
 *                         partially filled order". Protection placed, amended, then cancelled
 *                         when the last share left. An APPENDED CORRECTION restates the level
 *                         of one amendment without touching the event it corrects
 *   demo-trade-arb-0001   an OPEN LONG whose entry order was PARTIALLY FILLED and then filled
 *                         out. The second fill was OBSERVED THREE HOURS LATE
 *   demo-trade-nvl-0002   an OPEN LONG that pyramided. Two entry orders, two retained risk
 *                         records, two protective amendments -- and NO RECONCILIATION RECORD,
 *                         which is the missing stage this book demonstrates
 *   demo-trade-cir-0003   a PARTIALLY_EXITED LONG. Its exit order filled completely and
 *                         reduced the position; the trade did not close and no second trade
 *                         was created
 *   demo-trade-hlx-0004   an OPEN SHORT. Its entry is a SELL and its protection is a BUY stop
 *                         above the market, so the order side is visibly not the position's
 *                         direction
 *   the first closed short a COMPLETED SHORT lifecycle: SELL_TO_OPEN, protection placed above,
 *                         BUY_TO_COVER, protection cancelled, reconciled
 */
const DECLARED: readonly ExecutionSpec[] = [
  {
    tradeId: MULTI_EXIT_TRADE,
    reconciliation: { sessionOffset: 0, result: "RECONCILED" },
    /** A closed trade whose decomposition was finalized -- a recorded event. */
    attribution: {
      factorHundredths: 2_600,
      regimeHundredths: 900,
      executionHundredths: -400,
      costHundredths: -700,
      state: "FINAL",
    },
    orders: [
      {
        target: { kind: "STAGE", ordinal: 0 },
        side: "BUY_TO_OPEN",
        referenceOffsetCents: -6,
        signalToOrderSeconds: 8,
        acknowledgeSeconds: 2,
        fills: [{ shares: 115, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
      {
        target: { kind: "EXIT", ordinal: 0 },
        side: "SELL_TO_CLOSE",
        referenceOffsetCents: 4,
        signalToOrderSeconds: 11,
        acknowledgeSeconds: 2,
        fills: [{ shares: 40, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
      {
        target: { kind: "EXIT", ordinal: 1 },
        side: "SELL_TO_CLOSE",
        referenceOffsetCents: 7,
        signalToOrderSeconds: 9,
        acknowledgeSeconds: 3,
        fills: [{ shares: 30, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
      {
        target: { kind: "EXIT", ordinal: 2 },
        side: "SELL_TO_CLOSE",
        referenceOffsetCents: 9,
        signalToOrderSeconds: 6,
        acknowledgeSeconds: 2,
        fills: [{ shares: 45, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
    ],
    protection: [
      { kind: "PLACED", sessionOffset: 0, levelCents: 53_20, protectedShares: 115 },
      {
        kind: "AMENDED",
        sessionOffset: 18,
        levelCents: 55_40,
        protectedShares: 75,
        /** Recorded at 55.40 and corrected to 55.10. The first event is retained unchanged. */
        correctedByLevelCents: 55_10,
      },
      { kind: "AMENDED", sessionOffset: 35, levelCents: 56_80, protectedShares: 45 },
      { kind: "CANCELLED", sessionOffset: 52, levelCents: 56_80, protectedShares: 0 },
    ],
    absentKinds: [],
  },
  {
    tradeId: "demo-trade-arb-0001",
    reconciliation: { sessionOffset: 0, result: "RECONCILED" },
    attribution: {
      factorHundredths: 3_100,
      regimeHundredths: 1_200,
      executionHundredths: -600,
      costHundredths: -500,
      state: "PROVISIONAL",
    },
    orders: [
      {
        target: { kind: "STAGE", ordinal: 0 },
        side: "BUY_TO_OPEN",
        referenceOffsetCents: -5,
        signalToOrderSeconds: 8,
        acknowledgeSeconds: 2,
        /*
         * 100 x 41.76 + 45 x 42.05 = 606,825 = 145 x 41.85, EXACTLY.
         *
         * The ledger records one entry at 41.85; this order reached it in two fills at
         * different prices, and their quantity-weighted price is that number rather than
         * something near it. The builder refuses any declaration where it is not.
         */
        fills: [
          { shares: 100, priceOffsetCents: -9, beforeStageSeconds: 6 },
          { shares: 45, priceOffsetCents: 20, beforeStageSeconds: 0, observedLateSeconds: 10_800 },
        ],
      },
    ],
    protection: [
      { kind: "PLACED", sessionOffset: 0, levelCents: 39_10, protectedShares: 145 },
      { kind: "AMENDED", sessionOffset: 21, levelCents: 43_60, protectedShares: 145 },
    ],
    absentKinds: [],
  },
  {
    tradeId: "demo-trade-nvl-0002",
    /** NOBODY RECONCILED THIS TRADE. The absence is recorded, and no result is invented. */
    reconciliation: null,
    /** AND NOBODY ATTRIBUTED IT EITHER. A second absence, on the same trade. */
    attribution: null,
    orders: [
      {
        target: { kind: "STAGE", ordinal: 0 },
        side: "BUY_TO_OPEN",
        referenceOffsetCents: -7,
        signalToOrderSeconds: 10,
        acknowledgeSeconds: 3,
        fills: [{ shares: 60, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
      {
        target: { kind: "STAGE", ordinal: 1 },
        side: "BUY_TO_OPEN",
        referenceOffsetCents: -4,
        signalToOrderSeconds: 14,
        acknowledgeSeconds: 2,
        fills: [{ shares: 40, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
    ],
    protection: [
      { kind: "PLACED", sessionOffset: 0, levelCents: 59_30, protectedShares: 60 },
      { kind: "AMENDED", sessionOffset: 30, levelCents: 60_80, protectedShares: 100 },
    ],
    absentKinds: [NO_RECONCILIATION_RECORD],
  },
  {
    tradeId: "demo-trade-cir-0003",
    reconciliation: { sessionOffset: 0, result: "RECONCILED" },
    attribution: {
      factorHundredths: 2_200,
      regimeHundredths: 1_500,
      executionHundredths: -300,
      costHundredths: -600,
      state: "PROVISIONAL",
    },
    orders: [
      {
        target: { kind: "STAGE", ordinal: 0 },
        side: "BUY_TO_OPEN",
        referenceOffsetCents: -8,
        signalToOrderSeconds: 9,
        acknowledgeSeconds: 2,
        fills: [{ shares: 96, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
      {
        /** ONE ORDER, FULLY FILLED, WHICH REDUCED THE POSITION AND DID NOT CLOSE IT. */
        target: { kind: "EXIT", ordinal: 0 },
        side: "SELL_TO_CLOSE",
        referenceOffsetCents: 6,
        signalToOrderSeconds: 7,
        acknowledgeSeconds: 2,
        fills: [{ shares: 40, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
    ],
    protection: [
      { kind: "PLACED", sessionOffset: 0, levelCents: 84_10, protectedShares: 96 },
      { kind: "AMENDED", sessionOffset: 37, levelCents: 90_10, protectedShares: 56 },
    ],
    absentKinds: [],
  },
  {
    tradeId: "demo-trade-hlx-0004",
    reconciliation: { sessionOffset: 0, result: "RECONCILED" },
    attribution: {
      factorHundredths: 1_900,
      regimeHundredths: 2_400,
      executionHundredths: -200,
      costHundredths: -900,
      state: "PROVISIONAL",
    },
    orders: [
      {
        /** A SHORT OPENS WITH A SELL. The side is not the position's direction. */
        target: { kind: "STAGE", ordinal: 0 },
        side: "SELL_TO_OPEN",
        referenceOffsetCents: 12,
        signalToOrderSeconds: 12,
        acknowledgeSeconds: 3,
        fills: [{ shares: 32, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
    ],
    protection: [
      /** A short's protection is a BUY stop ABOVE the market. */
      { kind: "PLACED", sessionOffset: 0, levelCents: 124_60, protectedShares: 32 },
      { kind: "AMENDED", sessionOffset: 19, levelCents: 116_20, protectedShares: 32 },
    ],
    absentKinds: [],
  },
];

/**
 * The completed SHORT lifecycle, on the first closed short the deterministic book contains.
 *
 * Its identity is READ FROM THE BOOK rather than typed in, because the generated ledger owns
 * it; the record below is declared exactly like the five above, and the shape assertion refuses
 * to attach it to a trade that is not a single-stage, single-exit closed short.
 */
function shortLifecycleSpec(): ExecutionSpec | null {
  const trade = BOOK.closedTrades.find(
    (candidate) =>
      candidate.direction === "SHORT" &&
      candidate.stages.length === 1 &&
      candidate.exits.length === 1 &&
      candidate.dataCompleteness === "COMPLETE" &&
      /*
       * NOT ONE OF THE TRADES THAT ALREADY DEMONSTRATE SOMETHING ELSE.
       *
       * One generated trade's entry-time risk record was deliberately never written, and
       * another's price path is deliberately incomplete. Attaching a complete execution
       * record to either would put two demonstrations on one row, and a reader could no
       * longer tell which absence the row was showing them.
       */
      candidate.initialRiskRecorded &&
      candidate.tradeId !== MISSING_RISK_RECORD_TRADE &&
      candidate.tradeId !== PARTIAL_PATH_TRADE,
  );
  if (trade === undefined) {
    return null;
  }
  const entryShares = trade.stages[0].shares;
  return {
    tradeId: trade.tradeId,
    reconciliation: { sessionOffset: 0, result: "RECONCILED" },
    attribution: {
      factorHundredths: 2_800,
      regimeHundredths: 700,
      executionHundredths: -500,
      costHundredths: -1_100,
      state: "FINAL",
    },
    orders: [
      {
        target: { kind: "STAGE", ordinal: 0 },
        side: "SELL_TO_OPEN",
        referenceOffsetCents: 9,
        signalToOrderSeconds: 13,
        acknowledgeSeconds: 3,
        fills: [{ shares: entryShares, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
      {
        /** A SHORT CLOSES WITH A BUY. */
        target: { kind: "EXIT", ordinal: 0 },
        side: "BUY_TO_COVER",
        referenceOffsetCents: -7,
        signalToOrderSeconds: 8,
        acknowledgeSeconds: 2,
        fills: [{ shares: entryShares, priceOffsetCents: 0, beforeStageSeconds: 0 }],
      },
    ],
    protection: [
      {
        kind: "PLACED",
        sessionOffset: 0,
        levelCents: trade.stages[0].invalidationCents,
        protectedShares: entryShares,
      },
      {
        kind: "CANCELLED",
        sessionOffset: trade.holdingSessions,
        levelCents: trade.stages[0].invalidationCents,
        protectedShares: 0,
      },
    ],
    absentKinds: [],
  };
}

const SHORT_SPEC = shortLifecycleSpec();

export const EXECUTION_SPECS: readonly ExecutionSpec[] =
  SHORT_SPEC === null ? DECLARED : [...DECLARED, SHORT_SPEC];

/** The completed short lifecycle's trade identity, or `null` where the book contains none. */
export const SHORT_LIFECYCLE_TRADE: string | null = SHORT_SPEC?.tradeId ?? null;

const BY_TRADE = new Map(EXECUTION_SPECS.map((spec) => [spec.tradeId, spec]));

/** Whether a trade has declared execution evidence at all. */
export function hasExecutionRecord(tradeId: string): boolean {
  return BY_TRADE.has(tradeId);
}

/**
 * What a trade's ENTRY ORDER RECORD actually shows, or nothing where no record exists.
 *
 * **A trade reference is not order evidence.** A candidate that became a trade tells you a
 * position was opened; it tells you nothing about whether any order was submitted,
 * acknowledged, partially filled, filled, rejected or cancelled, and six trades in this book
 * carry an execution record while the rest do not. Anything that wants an order state reads it
 * here, from the recorded fills, and gets `undefined` when nobody wrote one down.
 *
 * `partiallyFilled` is a fact about THIS ORDER and never about the position: an order that
 * fills in two parts passed through a partially filled state, and an order that fills at once
 * while reducing a position did not.
 */
export interface EntryOrderEvidence {
  /** The order passed through a partially filled state on its way to being filled. */
  readonly partiallyFilled: boolean;
  /** The recorded fills account for the whole ordered quantity. */
  readonly filled: boolean;
}

export function entryOrderEvidence(tradeId: string): EntryOrderEvidence | undefined {
  const spec = BY_TRADE.get(tradeId);
  if (spec === undefined) {
    return undefined;
  }
  const entry = spec.orders.find(
    (order) => order.target.kind === "STAGE" && order.target.ordinal === 0,
  );
  if (entry === undefined || entry.fills.length === 0) {
    return undefined;
  }
  const total = entry.fills.reduce((running, fill) => running + fill.shares, 0);
  let running = 0;
  let partiallyFilled = false;
  for (const fill of entry.fills) {
    running += fill.shares;
    if (running < total) {
      partiallyFilled = true;
    }
  }
  return { partiallyFilled, filled: running === total };
}

export function executionSpecFor(tradeId: string): ExecutionSpec | undefined {
  return BY_TRADE.get(tradeId);
}

/* -------------------------------------------------------------------- resolution */

/** One fill, resolved to absolute instants and absolute prices. */
export interface ResolvedFill {
  readonly orderId: string;
  readonly fillId: string;
  readonly side: OrderSide;
  readonly shares: number;
  readonly priceCents: number;
  readonly referenceCents: number;
  readonly eventMs: number;
  readonly observedMs: number;
  /** `true` once this fill completed the order it belongs to. */
  readonly completesOrder: boolean;
  /** How much of the order had filled once this fill landed. */
  readonly cumulativeShares: number;
  readonly orderedShares: number;
  readonly submittedMs: number;
  readonly signalMs: number;
  readonly acknowledgedMs: number;
  readonly targetKind: "STAGE" | "EXIT";
  readonly targetOrdinal: number;
}

interface ResolvedOrder {
  readonly orderId: string;
  readonly side: OrderSide;
  readonly orderedShares: number;
  readonly referenceCents: number;
  readonly signalMs: number;
  readonly submittedMs: number;
  readonly acknowledgedMs: number;
  readonly fills: readonly ResolvedFill[];
  readonly targetKind: "STAGE" | "EXIT";
  readonly targetOrdinal: number;
}

function stageInstantMs(
  trade: BookTrade,
  days: readonly string[],
  target: OrderSpec["target"],
): number {
  const session =
    target.kind === "STAGE"
      ? trade.stages[target.ordinal].session
      : trade.exits[target.ordinal].session;
  return Date.parse(sessionInstant(days[session]));
}

function recordedPriceCents(trade: BookTrade, target: OrderSpec["target"]): number {
  return target.kind === "STAGE"
    ? trade.stages[target.ordinal].priceCents
    : trade.exits[target.ordinal].priceCents;
}

function recordedShares(trade: BookTrade, target: OrderSpec["target"]): number {
  return target.kind === "STAGE"
    ? trade.stages[target.ordinal].shares
    : trade.exits[target.ordinal].shares;
}

/**
 * Resolves one trade's declared orders against the ledger row they belong to.
 *
 * **This is where the fixture is checked rather than trusted.** A declared order whose fills do
 * not sum to the recorded quantity, or whose quantity-weighted price is not the recorded price,
 * is refused: a lifecycle that disagrees with its own ledger row is two trades wearing one
 * identity, and `cockpit-v1-specification.md` §5 calls that teaching the wrong thing.
 */
function resolveOrders(
  trade: BookTrade,
  spec: ExecutionSpec,
  days: readonly string[],
): readonly ResolvedOrder[] {
  return spec.orders.map((order, index) => {
    const base = stageInstantMs(trade, days, order.target);
    const price = recordedPriceCents(trade, order.target);
    const ordered = recordedShares(trade, order.target);
    const filled = order.fills.reduce((total, fill) => total + fill.shares, 0);
    if (filled !== ordered) {
      throw new RangeError(
        `${spec.tradeId} order ${index} fills ${filled} shares against a recorded ${ordered}`,
      );
    }
    const weighted = order.fills.reduce(
      (total, fill) => total + fill.shares * (price + fill.priceOffsetCents),
      0,
    );
    if (weighted !== ordered * price) {
      throw new RangeError(
        `${spec.tradeId} order ${index} has a weighted fill price the ledger does not record`,
      );
    }
    const firstFillMs = base - Math.max(...order.fills.map((fill) => fill.beforeStageSeconds)) * 1000;
    const acknowledgedMs = firstFillMs - order.acknowledgeSeconds * 1000;
    const submittedMs = acknowledgedMs - 1000;
    const signalMs = submittedMs - order.signalToOrderSeconds * 1000;
    const orderId = `${spec.tradeId}-order-${index}`;
    let running = 0;
    const fills = order.fills.map((fill, fillIndex) => {
      running += fill.shares;
      const eventMs = base - fill.beforeStageSeconds * 1000;
      return {
        orderId,
        fillId: `${orderId}-fill-${fillIndex}`,
        side: order.side,
        shares: fill.shares,
        priceCents: price + fill.priceOffsetCents,
        referenceCents: price + order.referenceOffsetCents,
        eventMs,
        observedMs: eventMs + (fill.observedLateSeconds ?? 0) * 1000,
        completesOrder: running === ordered,
        cumulativeShares: running,
        orderedShares: ordered,
        submittedMs,
        signalMs,
        acknowledgedMs,
        targetKind: order.target.kind,
        targetOrdinal: order.target.ordinal,
      };
    });
    return {
      orderId,
      side: order.side,
      orderedShares: ordered,
      referenceCents: price + order.referenceOffsetCents,
      signalMs,
      submittedMs,
      acknowledgedMs,
      fills,
      targetKind: order.target.kind,
      targetOrdinal: order.target.ordinal,
    };
  });
}

/** Every resolved fill of a trade, ordered by the instant it happened. */
export function resolvedFills(
  trade: BookTrade,
  days: readonly string[],
): readonly ResolvedFill[] {
  const spec = BY_TRADE.get(trade.tradeId);
  if (spec === undefined) {
    return [];
  }
  return resolveOrders(trade, spec, days)
    .flatMap((order) => order.fills)
    .sort((left, right) => left.eventMs - right.eventMs);
}

/* ------------------------------------------------------------------- the events */

/** The event kinds a complete lifecycle carries, in the order one trade produces them. */
const KIND_ORDER_SUBMITTED = "ORDER_SUBMITTED_RECORDED";
const KIND_ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED_RECORDED";
const KIND_FILL = "FILL_RECORDED";
const KIND_PARTIAL_FILL = "PARTIAL_FILL_RECORDED";
const KIND_PROTECTION_PLACED = "PROTECTIVE_ORDER_PLACED";
const KIND_PROTECTION_AMENDED = "PROTECTIVE_ORDER_AMENDED";
const KIND_PROTECTION_CANCELLED = "PROTECTIVE_ORDER_CANCELLED";
const KIND_RECONCILIATION = "BROKER_RECONCILIATION_RECORDED";
const KIND_CORRECTION = "PROTECTIVE_LEVEL_CORRECTED";

/**
 * The complete lifecycle of one trade, from its declared execution record.
 *
 * Ordering is by `event_time` and `observed_time` is retained, so a fill that arrived three
 * hours late sits at the instant it happened rather than at the instant it was seen.
 *
 * **A correction APPENDS.** The corrected event stays in the list, unchanged, and the
 * correction references it — never the other way round.
 */
export function executionEvents(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): readonly TradeLifecycleEvent[] {
  const spec = BY_TRADE.get(trade.tradeId);
  if (spec === undefined) {
    return [];
  }
  const orders = resolveOrders(trade, spec, days);
  const events: TradeLifecycleEvent[] = [];

  for (const order of orders) {
    const sourceRef = demoRef(`${order.orderId}-source`, "source_fact");
    events.push({
      event_id: `${order.orderId}-submitted`,
      event_kind: demoReason(KIND_ORDER_SUBMITTED),
      event_time: instantOf(order.submittedMs),
      observed_time: instantOf(order.submittedMs),
      quantity: order.orderedShares,
      /** An order carries no fill price; it carries the reference it will be measured against. */
      price: usd("execution.reference_price", order.referenceCents, asOf),
      downstream_stage: "ORDER_SUBMITTED",
      source_ref: sourceRef,
    });
    events.push({
      event_id: `${order.orderId}-acknowledged`,
      event_kind: demoReason(KIND_ORDER_ACKNOWLEDGED),
      event_time: instantOf(order.acknowledgedMs),
      observed_time: instantOf(order.acknowledgedMs),
      quantity: order.orderedShares,
      price: usd("execution.reference_price", order.referenceCents, asOf),
      downstream_stage: "ORDER_ACKNOWLEDGED",
      source_ref: sourceRef,
    });
    for (const fill of order.fills) {
      events.push({
        event_id: fill.fillId,
        /*
         * A PARTIALLY FILLED ORDER IS NOT A PARTIAL EXIT.
         *
         * This kind and this downstream stage describe how much of THIS ORDER filled. Whether
         * the position was reduced or closed is a different question, answered by the trade's
         * remaining balance on the exit events below -- and one of these trades has an order
         * that filled completely while reducing the position, which is the pair of facts a
         * single field cannot carry.
         */
        event_kind: demoReason(fill.completesOrder ? KIND_FILL : KIND_PARTIAL_FILL),
        event_time: instantOf(fill.eventMs),
        observed_time: instantOf(fill.observedMs),
        quantity: fill.shares,
        price: usd("execution.fill_price", fill.priceCents, asOf),
        downstream_stage: fill.completesOrder ? "ORDER_FILLED" : "ORDER_PARTIALLY_FILLED",
        source_ref: demoRef(`${fill.fillId}-source`, "source_fact"),
      });
    }
  }

  const firstSession = trade.stages[0].session;
  for (const [index, event] of spec.protection.entries()) {
    const session = Math.min(firstSession + event.sessionOffset, trade.lastSession);
    const eventMs = Date.parse(sessionInstant(days[session])) + 60_000;
    const eventId = `${trade.tradeId}-protection-${index}`;
    const kind =
      event.kind === "PLACED"
        ? KIND_PROTECTION_PLACED
        : event.kind === "AMENDED"
          ? KIND_PROTECTION_AMENDED
          : KIND_PROTECTION_CANCELLED;
    events.push({
      event_id: eventId,
      event_kind: demoReason(kind),
      event_time: instantOf(eventMs),
      observed_time: instantOf(eventMs),
      quantity: event.protectedShares,
      price: usd("trade.mark_price", event.levelCents, asOf),
      /*
       * A WORKING PROTECTIVE ORDER IS ACKNOWLEDGED, NOT FILLED.
       *
       * The downstream axis describes the order's own state. A stop that was placed or amended
       * is working; one that was cancelled is cancelled. None of these is a fill, and none of
       * them ever reports one.
       */
      downstream_stage: event.kind === "CANCELLED" ? "ORDER_CANCELLED" : "ORDER_ACKNOWLEDGED",
      source_ref: demoRef(`${eventId}-source`, "source_fact"),
    });
    if (event.correctedByLevelCents !== undefined) {
      /*
       * THE CORRECTION IS A NEW EVENT THAT REFERENCES THE OLD ONE.
       *
       * The event above is retained exactly as it was recorded. Nothing overwrites it, and the
       * timeline shows both -- which is what "a corrected value shows that it was corrected"
       * means in Area 36.4.
       */
      const correctedMs = eventMs + 4 * 3_600_000;
      events.push({
        event_id: `${eventId}-correction`,
        event_kind: demoReason(KIND_CORRECTION),
        event_time: instantOf(correctedMs),
        observed_time: instantOf(correctedMs),
        quantity: event.protectedShares,
        price: usd("trade.mark_price", event.correctedByLevelCents, asOf),
        downstream_stage: "ORDER_ACKNOWLEDGED",
        correction_of: demoRef(eventId, "protection", "ENDPOINT"),
        source_ref: demoRef(`${eventId}-correction-source`, "source_fact"),
      });
    }
  }

  if (spec.reconciliation !== null) {
    const session = Math.min(
      trade.lastSession + spec.reconciliation.sessionOffset,
      trade.lastSession,
    );
    const eventMs = Date.parse(sessionInstant(days[session])) + 3_600_000;
    events.push({
      event_id: `${trade.tradeId}-reconciliation`,
      event_kind: demoReason(KIND_RECONCILIATION),
      event_time: instantOf(eventMs),
      observed_time: instantOf(eventMs),
      /** A reconciliation confirms a position; it moves no shares of its own. */
      quantity: 0,
      price: unavailable(
        "execution.fill_price",
        "USD",
        "NOT_APPLICABLE",
        "NOT_DEFINED_FOR_SUBJECT",
      ),
      /** It reconciles the position produced by orders that filled. */
      downstream_stage: "ORDER_FILLED",
      source_ref: demoRef(`${trade.tradeId}-reconciliation-source`, "source_fact"),
    });
  }

  return events;
}

/** The kinds a trade with a declared record still does not carry. */
export function declaredAbsentKinds(
  tradeId: string,
): readonly (readonly [string, AvailabilityState, FieldReasonCode])[] {
  const spec = BY_TRADE.get(tradeId);
  if (spec === undefined) {
    return [];
  }
  const listed = [...spec.absentKinds];
  const hasCorrection = spec.protection.some(
    (event) => event.correctedByLevelCents !== undefined,
  );
  if (!hasCorrection) {
    listed.push(NO_CORRECTIONS);
  }
  if (spec.protection.length === 0) {
    listed.push(NO_PROTECTION_RECORD);
  }
  return listed;
}

/* -------------------------------------------------------------- execution quality */

/** §12.3's declared minimum observation counts, per metric. */
const MINIMUM_FILLS_PER_FILL_METRIC = 1;
const MINIMUM_FILLS_PER_AGGREGATE = 20;

const CLOCK_SOURCE = "FIXTURE_MONOTONIC_SESSION_CLOCK";
const CLOCK_ACCURACY_SECONDS = 1;
const REFERENCE_NAME = "DECISION_INSTANT_CONSOLIDATED_MARK";
const SIDE_CONVENTION = "BUY_POSITIVE_SELL_NEGATIVE_ADVERSE_IS_POSITIVE";
const AGGREGATION_METHOD = "QUANTITY_WEIGHTED_OVER_FILLS_WITH_A_RESOLVABLE_REFERENCE";

function qualityFor(
  fill: ResolvedFill,
  asOf: string,
): ExecutionQuality {
  const hundredths = slippageHundredthBps(fill.side, fill.priceCents, fill.referenceCents);
  return {
    scope: "FILL",
    subject_ref: demoRef(fill.fillId, "fill", "ENDPOINT"),
    side: fill.side,
    quantity: sharesMetric("execution.quantity", fill.shares, asOf),
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
     * filled has not filled, and a per-fill record that reported 100% for every fill could
     * never show the partially filled state at all.
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
    minimum_observations: count(
      "performance.minimum_observations",
      MINIMUM_FILLS_PER_FILL_METRIC,
      asOf,
    ),
    observation_count: count("performance.observation_count", 1, asOf),
  };
}

export function fillQuality(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): readonly ExecutionQuality[] {
  return resolvedFills(trade, days).map((fill) => qualityFor(fill, asOf));
}

/**
 * The trade-level aggregate.
 *
 * **It reports a state rather than a number**, because §12.3 declares a minimum of twenty
 * fills for `slippage.aggregate` and no single demonstration trade has twenty. That is the
 * rule working, not a gap: a quantity-weighted average over four fills is a number whose
 * declared rule says it is not meaningful, and `INSUFFICIENT_OBSERVATIONS` says exactly that
 * while the per-fill values beside it stay `AVAILABLE`.
 */
export function aggregateQuality(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): ExecutionQuality | undefined {
  const fills = resolvedFills(trade, days);
  if (fills.length === 0) {
    return undefined;
  }
  const orderedTotal = new Map<string, number>();
  for (const fill of fills) {
    orderedTotal.set(fill.orderId, fill.orderedShares);
  }
  const ordered = [...orderedTotal.values()].reduce((total, value) => total + value, 0);
  const filled = fills.reduce((total, fill) => total + fill.shares, 0);
  return {
    scope: "AGGREGATE",
    subject_ref: demoRef(`${trade.tradeId}-execution-quality`, "execution_quality", "EMBEDDED"),
    /** The aggregate names the side of the stage that opened the position. */
    side: fills[0].side,
    quantity: sharesMetric("execution.quantity", filled, asOf),
    fill_price: unavailable(
      "execution.fill_price",
      "USD",
      "NOT_APPLICABLE",
      "NOT_DEFINED_FOR_SUBJECT",
    ),
    reference_price: {
      name: demoReason(REFERENCE_NAME),
      at: instantOf(fills[0].signalMs),
      side_convention: demoReason(SIDE_CONVENTION),
      price: usd("execution.reference_price", fills[0].referenceCents, asOf),
    },
    slippage: unavailable(
      "slippage.aggregate",
      "BPS",
      "INSUFFICIENT_OBSERVATIONS",
      "BELOW_MINIMUM_OBSERVATIONS",
    ),
    fill_rate: percent("execution.fill_rate", halfEven(filled * 100 * 100, ordered), asOf),
    signal_to_order_latency: seconds(
      "latency.signal_to_order",
      (fills[0].submittedMs - fills[0].signalMs) / 1000,
      asOf,
    ),
    order_to_fill_latency: seconds(
      "latency.order_to_fill",
      (fills[0].eventMs - fills[0].submittedMs) / 1000,
      asOf,
    ),
    clock_source: demoReason(CLOCK_SOURCE),
    clock_accuracy: seconds("clock.accuracy", CLOCK_ACCURACY_SECONDS, asOf),
    aggregation_method: demoReason(AGGREGATION_METHOD),
    /** Every fill here has a resolvable reference, so none was excluded. A measured zero. */
    excluded_fills: count("execution.excluded_fills", 0, asOf),
    minimum_observations: count(
      "performance.minimum_observations",
      MINIMUM_FILLS_PER_AGGREGATE,
      asOf,
    ),
    observation_count: count("performance.observation_count", fills.length, asOf),
  };
}

/* ----------------------------------------------------------------- attribution */

/**
 * The five attribution components, in cents, summing EXACTLY to the trade's outcome.
 *
 * Four are the declared shares; the fifth -- strategy -- takes the remainder, so rounding
 * cannot make the decomposition disagree with the thing it decomposes.
 */
export function attributionCents(
  trade: BookTrade,
): {
  readonly strategy: number;
  readonly factor: number;
  readonly regime: number;
  readonly execution: number;
  readonly cost: number;
  readonly state: "PROVISIONAL" | "FINAL";
} | null {
  const spec = BY_TRADE.get(trade.tradeId);
  if (spec?.attribution == null) {
    return null;
  }
  const outcome = trade.realizedCents + trade.unrealizedCents;
  const share = (hundredths: number) => halfEven(outcome * hundredths, 10_000);
  const factor = share(spec.attribution.factorHundredths);
  const regime = share(spec.attribution.regimeHundredths);
  const execution = share(spec.attribution.executionHundredths);
  const cost = share(spec.attribution.costHundredths);
  return {
    strategy: outcome - factor - regime - execution - cost,
    factor,
    regime,
    execution,
    cost,
    state: spec.attribution.state,
  };
}

/* ------------------------------------------------------------------- references */

/** The reference lists a trade detail carries, built from what the record actually contains. */
export function executionRefs(trade: BookTrade, days: readonly string[], asOf: string) {
  const spec = BY_TRADE.get(trade.tradeId);
  const orders = spec === undefined ? [] : resolveOrders(trade, spec, days);
  const fills = orders.flatMap((order) => order.fills);
  const protectionEvents = spec?.protection ?? [];
  /*
   * ORDERS, FILLS AND PROTECTIVE EVENTS RESOLVE THROUGH THE LIFECYCLE ENDPOINT (4.3).
   *
   * That endpoint exists in this application, so these are ENDPOINT references rather than
   * UNRESOLVABLE_V1 ones -- a reader can follow them to the events on this very page.
   */
  const orderRefs: Ref[] = orders.map((order) => demoRef(order.orderId, "order", "ENDPOINT"));
  const fillRefs: Ref[] = fills.map((fill) => demoRef(fill.fillId, "fill", "ENDPOINT"));
  const protectionRefs: Ref[] = protectionEvents.map((_event, index) =>
    demoRef(`${trade.tradeId}-protection-${index}`, "protection", "ENDPOINT"),
  );
  /*
   * RECONCILIATION AND AUDIT RESOLVE NOWHERE, AND SAY SO.
   *
   * `ReconciliationStatus` and `AuditEvent` are separate read models on separate screens
   * (Area 36.3), and neither is implemented. The reference is carried so the join is
   * specified, and it resolves to an availability state rather than to a payload.
   */
  const reconciliationRefs: Ref[] =
    spec?.reconciliation == null
      ? []
      : [demoRef(`${trade.tradeId}-reconciliation`, "reconciliation")];
  return {
    order_refs: refListOf(orderRefs, "ZERO_OR_MORE", asOf),
    fill_refs: refListOf(fillRefs, "ZERO_OR_MORE", asOf),
    protection_refs: refListOf(protectionRefs, "ZERO_OR_MORE", asOf),
    reconciliation_refs: refListOf(reconciliationRefs, "ZERO_OR_MORE", asOf),
  };
}

/** The recorded reconciliation outcome, as a token, or an absence. */
export function reconciliationOutcome(tradeId: string, asOf: string) {
  const spec = BY_TRADE.get(tradeId);
  if (spec?.reconciliation == null) {
    return unavailable(
      "trade.exit_reason",
      "DIMENSIONLESS",
      "NOT_YET_AVAILABLE",
      "UPSTREAM_INPUT_MISSING",
    );
  }
  return token("trade.exit_reason", spec.reconciliation.result, asOf);
}
