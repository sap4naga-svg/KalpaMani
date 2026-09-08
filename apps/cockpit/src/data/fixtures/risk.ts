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
import { EXPOSURE_AXES, stageRiskRecord } from "./positions";
import { CANDIDATE_RECORDS, riskDecisionFor } from "./signals";
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
        assessment_ref: demoRef(
          "portfolio-risk-assessment",
          "risk_decision",
          "AUTHORIZED_READ",
        ),
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
    /*
     * Listed per RETAINED STAGE RECORD rather than summed away: each is immutable, each has
     * its own reference price and as-of, and a pyramided trade retains one per stage (§12.4).
     * Listing one per trade would report a pyramid's planned risk as its entry stage's alone.
     */
    initial_planned_risk_open: open.flatMap((trade) =>
      trade.stages.map((stage, ordinal) => ({
        /*
         * KIND `trade`, AND IT USED TO SAY `source_fact`.
         *
         * This is the trade a planned-risk row BELONGS TO, and not a provenance
         * record the projection was built out of. §4.3 had no `trade` row to assign
         * until ADR-0030 R1 added one, so the implementation guessed `source_fact`
         * here and in `CandidateDetail.downstream_refs.trade` the same way twice.
         * Its ENDPOINT is conformant now: the `trade` row lists it, and
         * `source_fact`'s row never did.
         */
        trade_ref: demoRef(trade.tradeId, "trade", "ENDPOINT"),
        ...(trade.stages.length > 1 ? { stage_ordinal: ordinal } : {}),
        value: {
          record: stageRiskRecord(trade, ordinal, days),
          availability: "AVAILABLE" as const,
          reason: "NONE" as const,
          as_of: sessionInstant(days[stage.session]),
        },
      })),
    ),
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
        demoRef(`exposure-${axis.toLowerCase()}`, "source_fact", "AUTHORIZED_READ"),
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
    /*
     * THE DECISIONS THE BOOK ACTUALLY RECORDS -- APPROVALS AND THE ONE DECLINE.
     *
     * An earlier revision listed three approvals synthesised from the first three open
     * trades, under reference ids that resolved to nothing, while Trade Detail declared the
     * risk-decision producer NOT_IMPLEMENTED for those same trades. **One fixture said a
     * decision had been recorded and another said none could exist.** The index now comes
     * from the decision records themselves, so the two screens cannot disagree, and a
     * DECLINED decision appears here rather than only approvals.
     */
    decisions: CANDIDATE_RECORDS.flatMap((record) => {
      const decision = riskDecisionFor(record, days, asOf);
      return decision === undefined
        ? []
        : [
            {
              decision_ref: demoRef(decision.decision_id, "risk_decision", "AUTHORIZED_READ"),
              at: decision.decided_at,
              outcome: decision.outcome_reason,
            },
          ];
    }),
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
      shorts.map((trade) => demoRef(trade.tradeId, "source_fact", "AUTHORIZED_READ")),
      "ZERO_OR_MORE",
      asOf,
    ),
    borrow: shorts.map((trade) => {
      const recorded = trade.tradeId === BORROW_RECORDED_TRADE;
      const security = securityOf(trade.symbol);
      return {
        /*
         * AUTHORIZED_READ, AND IT USED TO SAY EMBEDDED.
         *
         * The only thing beside it here is `security_label`, a human-readable display
         * string: there is no `symbol`, no identifier and nothing to canonicalize, so
         * no identity correspondence can be stated for it. An embed whose identity
         * rests on a display name is exactly the ambiguity R4 refuses, so the
         * catalogue authorizes no carrier on this field and the reference resolves
         * by authorized read instead.
         */
        security_ref: demoRef(
          `security-${trade.symbol.toLowerCase()}`,
          "evidence",
          "AUTHORIZED_READ",
        ),
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
        /*
         * ONE RESOLUTION, WHETHER OR NOT A RECORD WAS WRITTEN.
         *
         * `evidence` resolves by AUTHORIZED_READ alone, and the security with no
         * borrow record used to declare `UNRESOLVABLE_V1` — a claim about the
         * PRODUCER, made where only the RECORD is missing. The distinction is
         * already carried honestly by `availability` beside it.
         */
        record_ref: demoRef(
          `borrow-record-${trade.symbol.toLowerCase()}`,
          "evidence",
          "AUTHORIZED_READ",
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
        candidate_ref: demoRef("demo-candidate-blocked-0001", "candidate", "ENDPOINT"),
        reason: demoReason("BLOCKED_BORROW_NO_RECORD"),
      },
      {
        candidate_ref: demoRef("demo-candidate-blocked-0002", "candidate", "ENDPOINT"),
        reason: demoReason("BLOCKED_BORROW_FEE_ABOVE_RECORDED_THRESHOLD"),
      },
    ],
    missed_opportunity_ref: demoRef(
      "borrow-related-misses",
      "source_fact",
      "AUTHORIZED_READ",
    ),
  };
}

export { count };
