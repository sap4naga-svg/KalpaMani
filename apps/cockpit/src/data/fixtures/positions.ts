/**
 * `PositionSnapshot` and `ExposureAggregate`, projected from the demonstration book.
 *
 * **THE TWO RISK QUANTITIES ARE SEPARATE FIELDS AND NEITHER IS DERIVED FROM THE OTHER.**
 * Initial planned risk is the immutable entry record, read from each stage's own recorded
 * invalidation level; current open planned risk is an assessment of the REMAINING exposure
 * against the CURRENT protective level. Two positions in this book have had their stop
 * moved, and only the second figure moved with it.
 *
 * **BORROW STATE COMES FROM A RECORD.** One short carries a recorded availability and one
 * carries none at all — and the one with none renders unknown, never available. Nothing here
 * looks at a price to decide it.
 *
 * **A POSITION CONTRIBUTES TO EACH AXIS EXACTLY ONCE.** The exposure aggregates are seven
 * views of one set of positions, and every one of them reconciles to the same portfolio
 * totals.
 */
import type {
  ExposureAggregate,
  ExposureAggregatePayload,
  PositionSnapshot,
  PositionSnapshotPayload,
} from "@/contracts/portfolio-models";
import type { CurrentOpenPlannedRisk, InitialPlannedRisk } from "@/contracts/risk-records";
import { pinsOf } from "@/contracts/factories";
import type { Magnitude } from "@/contracts/values";

import type { BookTrade } from "./book";
import {
  BOOK,
  GAP_EVENT_TRADE,
  STALE_ASSESSMENT_TRADE,
  centsToDecimal,
  pctOfCapitalHundredths,
  positionValueCents,
  securityOf,
  strategyVersionOf,
} from "./book";
import {
  CALENDAR,
  STRATEGY_CAPITAL_MONEY,
  count,
  demoPolicyRef,
  demoRef,
  demoReason,
  percent,
  scaled,
  sessionInstant,
  tradingDays,
  unavailable,
  usd,
} from "./common";

/** The demonstration factor-definition version every grouping is stated under. */
const FACTOR_DEFINITION_VERSION = "factor-definitions-v1";

/**
 * The pins a position or trade carries.
 *
 * The strategy, factor, risk, entry and exit identities are the demonstration book's own.
 * **The model and prompt pins state that they do not apply**, because no AI agent exists and
 * none contributed to any record here — which §4.2 asks to be SAID rather than omitted.
 */
export function demoPins(versionId: string) {
  return pinsOf({
    strategy_version: versionId,
    factor_definition_version: FACTOR_DEFINITION_VERSION,
    risk_policy_version: "risk-policy-demo",
    entry_policy_version: "entry-policy-demo",
    exit_policy_version: "exit-policy-demo",
    code_identity: "cockpit-fixture-c5",
    config_identity: "fixture-research",
  });
}

/** The invalidation level of a stage, as a reference. **A level, never an order.** */
function invalidationRef(trade: BookTrade, stageOrdinal: number) {
  return demoRef(
    `${trade.tradeId}-invalidation-${stageOrdinal}`,
    "evidence",
    "AUTHORIZED_READ",
  );
}

/**
 * The retained initial planned risk record of a whole trade.
 *
 * §12.4: "the trade-level denominator is the **sum of the retained per-stage initial planned
 * risks**", and "no stop movement, protection change or size change alters any retained
 * record". The reference price is the position-weighted entry basis the stages actually
 * produced, and `recorded_at` is the FIRST stage's session — the instant the trade's risk was
 * first written, never the response's own time.
 */
export function initialRiskRecord(trade: BookTrade, days: readonly string[]): InitialPlannedRisk {
  return {
    risk_money: { amount: centsToDecimal(trade.initialRiskCents), currency: "USD" },
    risk_pct_of_capital: {
      value: centsToDecimal(pctOfCapitalHundredths(trade.initialRiskCents)),
      denominator: "STRATEGY_CAPITAL_AT_ENTRY",
    },
    reference_price: { amount: centsToDecimal(trade.basisCents), currency: "USD" },
    invalidation_ref: invalidationRef(trade, 0),
    recorded_at: sessionInstant(days[trade.stages[0].session]),
    risk_policy_ref: demoPolicyRef(sessionInstant(days[trade.stages[0].session])),
    source: "RISK_RECORD_AT_ENTRY",
  };
}

/**
 * The risk engine's assessment of a trade's REMAINING exposure.
 *
 * It is an assessment and it carries its own `as_of`. One position's assessment is
 * deliberately STALE: the record is **present**, its staleness says so, and the value is
 * shown with the instant it was true at — **never presented as current, and never discarded
 * as missing**.
 */
export function openRiskRecord(
  trade: BookTrade,
  days: readonly string[],
  asOf: string,
): {
  record?: CurrentOpenPlannedRisk;
  availability: "AVAILABLE" | "STALE" | "NOT_APPLICABLE";
  reason: "NONE" | "UPSTREAM_INPUT_STALE" | "NOT_DEFINED_FOR_SUBJECT";
  as_of?: string;
} {
  if (trade.openPlannedRiskCents === null || trade.sharesOpen === 0) {
    /*
     * A fully closed trade carries no remaining exposure for the question to be about, so the
     * record is ABSENT and `NOT_APPLICABLE` — the one case where that state is correct here.
     */
    return { availability: "NOT_APPLICABLE", reason: "NOT_DEFINED_FOR_SUBJECT" };
  }
  const stale = trade.tradeId === STALE_ASSESSMENT_TRADE;
  /** A stale assessment is shown with the instant it was true at, two sessions ago. */
  const assessedAt = sessionInstant(days[trade.lastSession - (stale ? 2 : 0)]);
  return {
    record: {
      risk_money: usd("risk.open_planned", trade.openPlannedRiskCents, assessedAt),
      risk_pct_of_capital: percent(
        "risk.open_planned_pct",
        pctOfCapitalHundredths(trade.openPlannedRiskCents),
        assessedAt,
      ),
      as_of: assessedAt,
      assessment_ref: demoRef(`${trade.tradeId}-risk-assessment`, "risk_decision"),
      risk_policy_ref: demoPolicyRef(assessedAt),
      protection_state: demoReason(
        trade.currentStopCents === trade.stages[0].invalidationCents
          ? "PROTECTIVE_ORDER_AT_ENTRY_LEVEL"
          : "PROTECTIVE_ORDER_TRAILED",
      ),
      source: "RISK_ENGINE_ASSESSMENT",
      staleness: stale ? "STALE" : "FRESH",
    },
    availability: stale ? "STALE" : "AVAILABLE",
    reason: stale ? "UPSTREAM_INPUT_STALE" : "NONE",
    as_of: stale ? assessedAt : asOf,
  };
}

/** The borrow state of a short position, read from a record and never from a price. */
function borrowState(trade: BookTrade) {
  if (trade.direction !== "SHORT") {
    return undefined;
  }
  /*
   * ONE SHORT HAS NO BORROW RECORD, and it renders unknown.
   *
   * "Hard-to-borrow conditions and price action correlate; a correlation is not a borrow
   * record" (Area 13). The position exists and the record does not, so the state is
   * `BORROW_STATE_UNKNOWN` — **never `BORROW_AVAILABLE`, and never inferred**.
   */
  return demoReason(
    trade.tradeId === "demo-trade-plm-0005"
      ? "BORROW_STATE_UNKNOWN"
      : "BORROW_AVAILABLE_FROM_RECORD",
  );
}

export function syntheticPositions(
  asOf: string,
  days: readonly string[],
): PositionSnapshotPayload {
  const snapshotAt = sessionInstant(days[days.length - 1]);
  const items: PositionSnapshot[] = BOOK.openTrades.map((trade) => {
    const security = securityOf(trade.symbol);
    const version = strategyVersionOf(trade.versionId);
    return {
      position_id: `demo-position-${trade.symbol.toLowerCase().replace(".", "-")}`,
      security_ref: demoRef(`security-${trade.symbol.toLowerCase()}`, "evidence", "EMBEDDED"),
      security: { symbol: trade.symbol, display_name: security.displayName },
      direction: trade.direction,
      quantity: trade.sharesOpen,
      entry_price: usd("position.entry_price", trade.basisCents, snapshotAt),
      /** The mark carries its OWN as-of — the session close it was observed at. */
      current_price: usd("position.current_price", trade.markCents ?? 0, snapshotAt),
      unrealized: {
        amount: centsToDecimal(trade.unrealizedCents),
        currency: "USD",
        sign_convention: "INFLOW_POSITIVE_OUTFLOW_NEGATIVE",
      },
      initial_planned_risk: {
        record: initialRiskRecord(trade, days),
        availability: "AVAILABLE",
        reason: "NONE",
        as_of: sessionInstant(days[trade.stages[0].session]),
      },
      open_planned_risk: openRiskRecord(trade, days, asOf),
      gap_event_risk:
        trade.tradeId === GAP_EVENT_TRADE
          ? {
              record: {
                /** A SEPARATE model. It is never added into either planned-risk figure. */
                modelled_loss: usd("gap_event.modelled_loss", 96_00, snapshotAt),
                scenario_ref: demoRef(
                  `${trade.tradeId}-gap-scenario`,
                  "evidence",
                  "AUTHORIZED_READ",
                ),
                model_version: "gap-event-model-demo-v1",
                as_of: snapshotAt,
              },
              availability: "AVAILABLE",
              reason: "NONE",
              as_of: snapshotAt,
            }
          : {
              /** The model does not apply to this subject, and says so. */
              availability: "NOT_APPLICABLE",
              reason: "NOT_DEFINED_FOR_SUBJECT",
            },
      invalidation_ref: invalidationRef(trade, 0),
      holding_duration: tradingDays("holding_period", trade.holdingSessions, snapshotAt),
      borrow_state: borrowState(trade),
      groupings: {
        sector: demoReason(security.sector),
        industry: demoReason(security.industry),
        strategy_module: demoReason(version.module),
        alpha_family: demoReason(version.family),
        factor_bucket: demoReason(security.factorBucket),
        correlation_cluster: demoReason(security.correlationCluster),
      },
      trade_ref: demoRef(trade.tradeId, "source_fact", "ENDPOINT"),
      pins: demoPins(trade.versionId),
    };
  });

  return {
    items,
    page: {
      page_size: 50,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("UNREALIZED_RESULT_DESCENDING"),
      tiebreak: demoReason("POSITION_ID_ASCENDING"),
    },
    as_of: snapshotAt,
    strategy_capital: STRATEGY_CAPITAL_MONEY,
  };
}

/* ------------------------------------------------------------------- exposure */

type AxisKey =
  | "DIRECTION"
  | "SECTOR"
  | "INDUSTRY"
  | "STRATEGY_MODULE"
  | "ALPHA_FAMILY"
  | "FACTOR_BUCKET"
  | "CORRELATION_CLUSTER";

/** The seven grouping axes. Each is a VIEW of the same positions, never a new population. */
export const EXPOSURE_AXES: readonly AxisKey[] = [
  "DIRECTION",
  "SECTOR",
  "INDUSTRY",
  "STRATEGY_MODULE",
  "ALPHA_FAMILY",
  "FACTOR_BUCKET",
  "CORRELATION_CLUSTER",
];

function bucketKey(trade: BookTrade, axis: AxisKey): string {
  const security = securityOf(trade.symbol);
  const version = strategyVersionOf(trade.versionId);
  switch (axis) {
    case "DIRECTION":
      return trade.direction;
    case "SECTOR":
      return security.sector;
    case "INDUSTRY":
      return security.industry;
    case "STRATEGY_MODULE":
      return version.module;
    case "ALPHA_FAMILY":
      return version.family;
    case "FACTOR_BUCKET":
      return security.factorBucket;
    case "CORRELATION_CLUSTER":
      return security.correlationCluster;
  }
}

function magnitude(cents: number, direction: "LONG" | "SHORT"): Magnitude {
  return { amount: centsToDecimal(cents), currency: "USD", direction };
}

/**
 * The four magnitudes of one bucket.
 *
 * Gross is long plus short and net is their difference, carried as a **positive magnitude
 * whose direction states which side it leans**. No exposure carries a profit sign.
 */
function magnitudesOf(trades: readonly BookTrade[]) {
  const longCents = trades
    .filter((trade) => trade.direction === "LONG")
    .reduce((total, trade) => total + positionValueCents(trade), 0);
  const shortCents = trades
    .filter((trade) => trade.direction === "SHORT")
    .reduce((total, trade) => total + positionValueCents(trade), 0);
  return {
    long: magnitude(longCents, "LONG"),
    short: magnitude(shortCents, "SHORT"),
    gross: magnitude(longCents + shortCents, "LONG"),
    net: magnitude(
      Math.abs(longCents - shortCents),
      longCents >= shortCents ? "LONG" : "SHORT",
    ),
  };
}

/**
 * A bucket's open planned risk.
 *
 * §4.4: "an aggregate containing any `STALE` or missing component is `PARTIAL` with the
 * components named". One position's assessment is stale, so every bucket containing it is
 * `PARTIAL` — and the bucket that does not contain it is not.
 */
function bucketRisk(
  trades: readonly BookTrade[],
  days: readonly string[],
): ExposureAggregate["buckets"][number]["open_planned_risk"] {
  const cents = trades.reduce((total, trade) => total + (trade.openPlannedRiskCents ?? 0), 0);
  const stale = trades.some((trade) => trade.tradeId === STALE_ASSESSMENT_TRADE);
  const anchor = trades[0];
  const assessedAt = sessionInstant(days[days.length - 1]);
  return {
    record: {
      risk_money: usd("risk.open_planned", cents, assessedAt),
      risk_pct_of_capital: percent(
        "risk.open_planned_pct",
        pctOfCapitalHundredths(cents),
        assessedAt,
      ),
      as_of: assessedAt,
      assessment_ref: demoRef(`aggregate-${anchor.tradeId}-risk`, "risk_decision"),
      risk_policy_ref: demoPolicyRef(assessedAt),
      protection_state: demoReason("PROTECTIVE_ORDERS_WORKING"),
      source: "RISK_ENGINE_ASSESSMENT",
      staleness: stale ? "STALE" : "FRESH",
    },
    availability: stale ? ("PARTIAL" as const) : ("AVAILABLE" as const),
    reason: stale ? ("UPSTREAM_INPUT_STALE" as const) : ("NONE" as const),
    as_of: assessedAt,
  };
}

/**
 * The permitted limits for an exposure axis.
 *
 * **They are absent, and that is the honest answer.** A permitted value is a separately
 * governed policy value and is "never served under a default nobody approved" (§4.4). No
 * risk-limit policy version exists in this project, so every limit is carried as an ABSENT
 * record with `POLICY_REFERENCE_MISSING`. The governed research values of `CLAUDE.md` §6 are
 * a different thing — research parameters, read from tracked authority, and shown separately
 * and labelled as such rather than dressed as approved limits.
 */
function permittedForAxis(axis: AxisKey): ExposureAggregate["permitted"] {
  const scopes =
    axis === "DIRECTION"
      ? (["OPEN_PORTFOLIO", "GROSS_SHORT"] as const)
      : (["OPEN_PORTFOLIO", "INDIVIDUAL_POSITION"] as const);
  return scopes.map((scope) => ({
    scope,
    value: { availability: "NOT_YET_AVAILABLE" as const, reason: "POLICY_REFERENCE_MISSING" as const },
  }));
}

export function syntheticExposure(
  asOf: string,
  days: readonly string[],
): ExposureAggregatePayload {
  const open = BOOK.openTrades;
  const snapshotAt = sessionInstant(days[days.length - 1]);

  const aggregates: ExposureAggregate[] = EXPOSURE_AXES.map((axis) => {
    const keys = [...new Set(open.map((trade) => bucketKey(trade, axis)))].sort();
    const buckets = keys.map((key) => {
      const inBucket = open.filter((trade) => bucketKey(trade, axis) === key);
      return {
        bucket: demoReason(key),
        ...magnitudesOf(inBucket),
        open_planned_risk: bucketRisk(inBucket, days),
        position_count: count("position.count", inBucket.length, snapshotAt),
      };
    });
    /*
     * Concentration is the largest bucket's gross exposure as a percentage of the portfolio's
     * gross. It is a MEASUREMENT of the displayed grouping, and it is not a permitted
     * exposure: **a grouping is displayed, never computed as a permitted exposure**.
     */
    const grossTotal = BOOK.totals.grossValueCents;
    const largest = buckets.reduce((worst, bucket) => {
      const value = Number(bucket.gross.amount.replace(".", ""));
      return value > worst ? value : worst;
    }, 0);
    return {
      grouping: demoReason(axis),
      buckets,
      base: demoReason("PORTFOLIO_GROSS_EXPOSURE"),
      permitted: permittedForAxis(axis),
      concentration:
        grossTotal === 0
          ? unavailable("risk.concentration", "PERCENT", "NOT_APPLICABLE", "DENOMINATOR_ZERO")
          : percent(
              "risk.concentration",
              Math.round((largest * 10_000) / grossTotal),
              snapshotAt,
            ),
      correlation_ref:
        axis === "CORRELATION_CLUSTER"
          ? demoRef("correlation-matrix-demo", "evidence", "UNRESOLVABLE_V1")
          : undefined,
    };
  });

  const totals = magnitudesOf(open);
  return {
    items: aggregates,
    page: {
      page_size: 50,
      total: count("reference.total", aggregates.length, asOf),
      truncated: false,
      sort: demoReason("GROUPING_AXIS_ASCENDING"),
      tiebreak: demoReason("BUCKET_CODE_ASCENDING"),
    },
    as_of: snapshotAt,
    totals: {
      ...totals,
      position_count: count("position.count", open.length, snapshotAt),
    },
  };
}

export { CALENDAR, scaled };
