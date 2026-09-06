/**
 * `RiskSnapshot` and `ShortSideSnapshot`, projected from the demonstration book.
 *
 * **READ-ONLY, WITHOUT EXCEPTION.** Nothing here changes a threshold, trips a breaker or
 * reduces an exposure, and no permitted exposure is computed anywhere.
 *
 * **EVERY PERMITTED LIMIT IS ABSENT, AND THAT IS THE HONEST ANSWER.** A permitted value is a
 * separately governed policy value carried with its `PolicyRef`, and **no risk-limit policy
 * version exists in this project** — so each limit is reported as `POLICY_REFERENCE_MISSING`,
 * naming which limit is missing rather than serving a number nobody approved. The governed
 * research values of `CLAUDE.md` §6 are a **different thing**: they are research parameters,
 * they are read from tracked repository authority, and they are carried by the tracked
 * `QualificationStatus` read model so a real fact is never badged synthetic.
 *
 * **BORROW IS READ FROM A RECORD.** One short has one and one does not, and the one that does
 * not renders unknown — never available, and never inferred from price behaviour. **G5,
 * historical borrow qualification, is OPEN**, and every borrow figure here inherits that.
 */
import type {
  RiskSnapshotPayload,
  ShortSideSnapshotPayload,
} from "@/contracts/risk-market-models";

import { BOOK, centsToDecimal, pctOfCapitalHundredths, positionValueCents, securityOf } from "./book";
import { EXPOSURE_AXES, initialRiskRecord } from "./positions";
import {
  count,
  demoPolicyRef,
  demoRef,
  demoReason,
  percent,
  refListOf,
  scaled,
  sessionInstant,
  shares,
  unavailable,
  usd,
} from "./common";
import { equityWindow } from "./equity";

/** The thresholds a risk engine would carry, named while every value stays unavailable. */
const LOSS_THRESHOLDS = [
  "DAILY_LOSS_HALT",
  "WEEKLY_LOSS_HALT",
  "PORTFOLIO_DRAWDOWN_HALT",
  "CONSECUTIVE_LOSS_HALT",
] as const;

/** The permitted limits §4.4 names, each reported as the specific missing limit it is. */
const PERMITTED_SCOPES = [
  "OPEN_PORTFOLIO",
  "PER_TRADE_LONG",
  "PER_TRADE_SHORT",
  "INDIVIDUAL_POSITION",
  "GROSS_SHORT",
] as const;

export function syntheticRiskSnapshot(
  asOf: string,
  days: readonly string[],
  originMs: number,
): RiskSnapshotPayload {
  const snapshotAt = sessionInstant(days[days.length - 1]);
  const open = BOOK.openTrades;
  const totals = BOOK.totals;
  /** One position's assessment is stale, so the AGGREGATE containing it is PARTIAL. */
  const stale = open.some((trade) => trade.tradeId === "demo-trade-plm-0005");

  const largestPosition = open.reduce(
    (worst, trade) => Math.max(worst, positionValueCents(trade)),
    0,
  );

  /**
   * Annualized portfolio volatility, from the book's own daily return series.
   *
   * The sample convention, the frequency and the annualization factor are stated: sample
   * standard deviation of daily index returns on the named calendar, times the square root of
   * 252. It is a **measurement of the demonstration equity path** and nothing more.
   */
  const window = equityWindow(originMs, "ALL");
  const returns = window.periodReturns;
  const mean = returns.reduce((total, value) => total + value, 0) / returns.length;
  const variance =
    returns.reduce((total, value) => total + (value - mean) ** 2, 0) / (returns.length - 1);
  const annualizedVolatility = Math.sqrt(variance) * Math.sqrt(252);

  return {
    as_of: snapshotAt,
    open_planned_risk: {
      record: {
        risk_money: usd("risk.open_planned", totals.openPlannedRiskCents, snapshotAt),
        risk_pct_of_capital: percent(
          "risk.open_planned_pct",
          pctOfCapitalHundredths(totals.openPlannedRiskCents),
          snapshotAt,
        ),
        as_of: snapshotAt,
        assessment_ref: demoRef("portfolio-risk-assessment", "risk_decision"),
        risk_policy_ref: demoPolicyRef(snapshotAt),
        protection_state: demoReason("PROTECTIVE_ORDERS_WORKING"),
        source: "RISK_ENGINE_ASSESSMENT",
        staleness: stale ? "STALE" : "FRESH",
      },
      /*
       * §4.4: "an aggregate containing any STALE or missing component is PARTIAL with the
       * components named". One of five assessments is stale, so the sum is PARTIAL — it is
       * not rounded up to AVAILABLE, and it is not discarded as missing.
       */
      availability: stale ? "PARTIAL" : "AVAILABLE",
      reason: stale ? "UPSTREAM_INPUT_STALE" : "NONE",
      as_of: snapshotAt,
    },
    /** Listed per trade rather than summed away: each is an immutable entry-time record. */
    initial_planned_risk_open: open.map((trade) => ({
      trade_ref: demoRef(trade.tradeId, "source_fact", "ENDPOINT"),
      value: {
        record: initialRiskRecord(trade, days),
        availability: "AVAILABLE" as const,
        reason: "NONE" as const,
        as_of: sessionInstant(days[trade.stages[0].session]),
      },
    })),
    permitted: PERMITTED_SCOPES.map((scope) => ({
      scope,
      value: {
        availability: "NOT_YET_AVAILABLE" as const,
        reason: "POLICY_REFERENCE_MISSING" as const,
      },
    })),
    concentration:
      totals.grossValueCents === 0
        ? unavailable("risk.concentration", "PERCENT", "NOT_APPLICABLE", "DENOMINATOR_ZERO")
        : percent(
            "risk.concentration",
            Math.round((largestPosition * 10_000) / totals.grossValueCents),
            snapshotAt,
          ),
    exposure_refs: refListOf(
      EXPOSURE_AXES.map((axis) =>
        demoRef(`exposure-${axis.toLowerCase()}`, "source_fact", "ENDPOINT"),
      ),
      "ONE_OR_MORE",
      asOf,
    ),
    portfolio_volatility: percent(
      "risk.portfolio_volatility",
      Math.round(annualizedVolatility * 100 * 100),
      snapshotAt,
    ),
    gap_event_risk: {
      record: {
        modelled_loss: usd("gap_event.modelled_loss", 96_00, snapshotAt),
        scenario_ref: demoRef("gap-event-scenario-demo", "evidence", "AUTHORIZED_READ"),
        model_version: "gap-event-model-demo-v1",
        as_of: snapshotAt,
      },
      availability: "AVAILABLE",
      reason: "NONE",
      as_of: snapshotAt,
    },
    loss_thresholds: LOSS_THRESHOLDS.map((threshold) => ({
      threshold: demoReason(threshold),
      /** Named, and unapproved. A limit with no versioned reference is not served. */
      value: unavailable(
        "risk.loss_threshold",
        "USD",
        "NOT_YET_AVAILABLE",
        "POLICY_REFERENCE_MISSING",
      ),
    })),
    risk_tier: demoReason("RISK_TIER_RECORDED_AS_NORMAL"),
    circuit_breaker_state: demoReason("CIRCUIT_BREAKER_NOT_TRIPPED_BY_RECORD"),
    new_entry_state: demoReason("NEW_ENTRIES_PERMITTED_BY_RECORD"),
    decisions: open.slice(0, 3).map((trade) => ({
      decision_ref: demoRef(`${trade.tradeId}-risk-decision`, "risk_decision"),
      at: sessionInstant(days[trade.stages[0].session]),
      outcome: demoReason("RISK_APPROVED_AT_RECORDED_SIZE"),
    })),
  };
}

/* -------------------------------------------------------------------- short side */

/** The one short with a recorded borrow, and the one without. */
const BORROW_RECORDED_TRADE = "demo-trade-hlx-0004";

export function syntheticShortSide(
  asOf: string,
  days: readonly string[],
): ShortSideSnapshotPayload {
  const snapshotAt = sessionInstant(days[days.length - 1]);
  const shorts = BOOK.openTrades.filter((trade) => trade.direction === "SHORT");
  const grossShortCents = shorts.reduce(
    (total, trade) => total + positionValueCents(trade),
    0,
  );

  return {
    as_of: snapshotAt,
    short_positions: refListOf(
      shorts.map((trade) => demoRef(trade.tradeId, "source_fact", "ENDPOINT")),
      "ZERO_OR_MORE",
      asOf,
    ),
    borrow: shorts.map((trade) => {
      const recorded = trade.tradeId === BORROW_RECORDED_TRADE;
      const security = securityOf(trade.symbol);
      return {
        security_ref: demoRef(`security-${trade.symbol.toLowerCase()}`, "evidence", "EMBEDDED"),
        security_label: `${security.displayName} (${trade.symbol})`,
        /*
         * THE BORROW AVAILABILITY, FROM THE RECORD.
         *
         * One security has a borrow record and one has none. The one with none is
         * `BORROW_STATE_UNKNOWN` — **never `BORROW_AVAILABLE`** — and nothing looked at a
         * price to decide either.
         */
        availability: demoReason(
          recorded ? "BORROW_AVAILABLE_FROM_RECORD" : "BORROW_STATE_UNKNOWN",
        ),
        /** Each figure has its OWN source and as-of. A fee is not a quantity. */
        fee: recorded
          ? percent("borrow.fee", 3_25, snapshotAt)
          : unavailable("borrow.fee", "PERCENT", "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING"),
        quantity: recorded
          ? shares("borrow.quantity", 25_000, snapshotAt)
          : unavailable(
              "borrow.quantity",
              "SHARES",
              "NOT_YET_AVAILABLE",
              "UPSTREAM_INPUT_MISSING",
            ),
        deterioration: recorded
          ? scaled("borrow.deterioration", "BPS", 40, snapshotAt)
          : unavailable(
              "borrow.deterioration",
              "BPS",
              "NOT_YET_AVAILABLE",
              "UPSTREAM_INPUT_MISSING",
            ),
        record_ref: demoRef(
          `borrow-record-${trade.symbol.toLowerCase()}`,
          "evidence",
          recorded ? "AUTHORIZED_READ" : "UNRESOLVABLE_V1",
        ),
      };
    }),
    /**
     * Crowding needs cross-market short-interest data. **No provider is selected, G1 is OPEN
     * and G5 is OPEN**, so it is unavailable rather than estimated from this book.
     */
    crowding: unavailable(
      "short.crowding",
      "PERCENT",
      "NOT_YET_AVAILABLE",
      "UPSTREAM_INPUT_MISSING",
    ),
    /**
     * Utilization is measured against the ONE recorded borrow quantity this book holds, so it
     * covers part of the short book rather than all of it.
     */
    utilization: percent("short.utilization", 12_80, snapshotAt),
    squeeze_state: demoReason("SQUEEZE_STATE_NOT_ASSESSED"),
    ssr_state: demoReason("SSR_STATE_NOT_RECORDED"),
    recall_risk: demoReason("RECALL_RISK_NOT_ASSESSED"),
    gross_short: {
      amount: centsToDecimal(grossShortCents),
      currency: "USD",
      direction: "SHORT",
    },
    permitted_gross_short: {
      availability: "NOT_YET_AVAILABLE",
      reason: "POLICY_REFERENCE_MISSING",
    },
    permitted_gross_short_scope: "GROSS_SHORT",
    /**
     * Two candidates the book records as declined for a borrow reason.
     *
     * **`BLOCKED_BORROW` is a first-class Brain state** (ADR-0026), and an unknown borrow is
     * a block rather than an assumption of availability.
     */
    blocked_shorts: [
      {
        candidate_ref: demoRef("demo-candidate-blocked-0001", "candidate"),
        reason: demoReason("BLOCKED_BORROW_NO_RECORD"),
      },
      {
        candidate_ref: demoRef("demo-candidate-blocked-0002", "candidate"),
        reason: demoReason("BLOCKED_BORROW_FEE_ABOVE_RECORDED_THRESHOLD"),
      },
    ],
    missed_opportunity_ref: demoRef("borrow-related-misses", "source_fact"),
  };
}

export { count };
