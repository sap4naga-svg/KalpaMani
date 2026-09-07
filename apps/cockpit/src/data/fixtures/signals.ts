/**
 * THE JOURNALED CANDIDATE BOOK, and the three signals projections read from it.
 *
 * `CandidateFunnel`, `CandidateSummary`, `CandidateDetail` and `MissedOpportunity`, all
 * projected from **one** declared set of sixteen fictional candidate decisions, so the funnel's
 * counts, the candidate list, one candidate's explanation and the missed-opportunity ledger
 * cannot disagree with each other.
 *
 * WHAT IT IS NOT.
 *
 *   NOT A BRAIN            no Brain runtime exists, nothing has ever scanned, ranked, blocked
 *                          or consolidated anything, and no candidate here was produced by a
 *                          decision compiler. These are records that were typed in
 *   NOT AI OUTPUT          no model was called. The AI evidence records below carry model and
 *                          prompt versions because §14.3 requires them ON evidence, and the
 *                          versions are fictional strings identifying nothing
 *   NOT A RESULT           no favourable movement here is profit that was available, and no
 *                          counterfactual is an outcome. They are arithmetic over a fixed step
 *                          function between endpoints that were chosen by hand
 *
 * THE FIVE THINGS THIS FILE REFUSES TO DO.
 *
 *   NO SIZING              nothing here carries a share count, a dollar amount or a position
 *                          size, and the contract refuses one structurally rather than by
 *                          convention
 *   NO AI RESTORATION      AI evidence removes candidates and never restores one
 *   NO HINDSIGHT EXIT      a counterfactual is the close-to-close movement over the window that
 *                          was REGISTERED AT THE DECISION, never the best point in the path
 *   NO DOLLAR COUNTERFACTUAL  price movement is not a position. The money limb is refused for
 *                          want of an approved sizing basis
 *   NO RATE WITHOUT A POPULATION  the false-negative rate is refused, because a candidate that
 *                          was never detected cannot be counted from the ledger of detected
 *                          candidates
 */
import type {
  CandidateDetailPayload,
  CandidateFunnelPayload,
  CandidateSummary,
  CandidateSummaryPayload,
  MissedOpportunity,
  MissedOpportunityPayload,
} from "@/contracts/signal-models";
import type { BrainDecisionState } from "@/contracts/signal-models";
import type { Series } from "@/contracts/values";
import { BRAIN_DECISION_STATES, DOWNSTREAM_STAGES } from "@/contracts/vocabularies";

import type { BookSecurity, BookTrade } from "./book";
import { BOOK, SESSION_COUNT, buildPath, securityOf, strategyVersionOf } from "./book";
import {
  CALENDAR,
  count,
  demoRef,
  demoReason,
  instantValue,
  notApplicable,
  ordinal,
  percent,
  qualified,
  refListOf,
  scaled,
  seconds,
  sessionInstant,
  token,
  tradingDays,
  unavailable,
  usd,
} from "./common";
import { demoPins } from "./positions";

/* ------------------------------------------------------------------ declarations */

/** How AI evidence stands on one candidate. Three genuinely different situations. */
type AiPosture =
  /** Evidence was produced, and none of it removed the candidate. */
  | "SUPPORTING"
  /** Evidence was produced, and one piece of it REMOVED the candidate. */
  | "REMOVING"
  /** The producer answered nothing at all. An absence, never an empty list. */
  | "UNAVAILABLE"
  /** Evidence exists and is past its contract. Value-bearing, and qualified. */
  | "STALE";

interface CandidateRecord {
  readonly candidateId: string;
  readonly symbol: string;
  readonly versionId: string;
  /** The session the decision was journaled on. */
  readonly session: number;
  readonly state: BrainDecisionState;
  readonly primaryReason: string;
  readonly blockingReasons: readonly string[];
  readonly contradictions: readonly string[];
  readonly convictionBand: string;
  readonly setupQuality: string;
  readonly rank: number;
  readonly rankPopulation: number;
  readonly thesis: string;
  readonly whyNow: string;
  readonly entryCondition: string;
  readonly horizonDays: number;
  readonly ai: AiPosture;
  readonly challengerFindings: readonly string[];
  /**
   * How many module decisions consolidated into this one candidate.
   *
   * Brain specification §8: a security qualifying through several modules is **one economic
   * opportunity with several pieces of evidence**, not several trades. The generated stage
   * counts those decisions and the consolidated stage counts these candidates, which is why
   * the two stages count different subjects and never subtract.
   */
  readonly contributingDecisions: number;
  /** The trade this candidate became, where one exists. */
  readonly tradeId?: string;
  /** Why it was not entered, for a candidate that never became a trade. */
  readonly missCause?: string;
  /** The session a watchlist candidate's window closes on. */
  readonly expirySession?: number;
  /** Seconds between detection and the recorded decision. */
  readonly decisionDelaySeconds: number;
  /** Whether the follow-up path this book can observe is complete. */
  readonly followUpComplete: boolean;
}

/** The window every counterfactual on this page was registered against, in trading days. */
const REGISTERED_HORIZON_DAYS = 10;

/** How far back the candidate journal reaches, in sessions before the snapshot. */
const JOURNAL_SESSIONS = 90;

/**
 * The sixteen journaled decisions.
 *
 * **Every one of the eight Brain states appears**, because the funnel renders them as a closed
 * set and a demonstration that populated only the interesting ones would teach a reader that
 * the others do not exist.
 *
 * Five candidates became the five demonstration trades that have execution evidence; a sixth
 * became the closed multi-exit trade. The other ten were not entered, and each of them names a
 * different recorded cause.
 */
const CANDIDATES: readonly CandidateRecord[] = [
  {
    candidateId: "demo-candidate-0001",
    symbol: "DEMO.SOL",
    versionId: "breakout-long-v3",
    session: SESSION_COUNT - 97,
    state: "READY_FOR_RISK_REVIEW",
    primaryReason: "EVERY_DETERMINISTIC_REQUIREMENT_SATISFIED",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_B",
    setupQuality: "CLEAN_BASE_BREAK",
    rank: 4,
    rankPopulation: 41,
    thesis: "RANGE_EXPANSION_WITH_CONFIRMED_RELATIVE_STRENGTH",
    whyNow: "CLOSE_ABOVE_THE_CONSOLIDATION_HIGH",
    entryCondition: "CLOSE_ABOVE_THE_CONSOLIDATION_HIGH_ON_EXPANDING_RANGE",
    horizonDays: 18,
    ai: "SUPPORTING",
    challengerFindings: ["NO_FALSIFYING_EVIDENCE_FOUND"],
    contributingDecisions: 2,
    tradeId: "demo-trade-sol-0006",
    decisionDelaySeconds: 46,
    followUpComplete: true,
  },
  {
    candidateId: "demo-candidate-0002",
    symbol: "DEMO.ARB",
    versionId: "breakout-long-v3",
    session: SESSION_COUNT - 40,
    state: "READY_FOR_RISK_REVIEW",
    primaryReason: "EVERY_DETERMINISTIC_REQUIREMENT_SATISFIED",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_A",
    setupQuality: "CLEAN_BASE_BREAK",
    rank: 1,
    rankPopulation: 41,
    thesis: "RANGE_EXPANSION_WITH_CONFIRMED_RELATIVE_STRENGTH",
    whyNow: "CLOSE_ABOVE_THE_CONSOLIDATION_HIGH",
    entryCondition: "CLOSE_ABOVE_THE_CONSOLIDATION_HIGH_ON_EXPANDING_RANGE",
    horizonDays: 22,
    ai: "SUPPORTING",
    challengerFindings: ["VALUATION_RISK_NOTED_AND_NOT_DISQUALIFYING"],
    contributingDecisions: 1,
    tradeId: "demo-trade-arb-0001",
    decisionDelaySeconds: 38,
    followUpComplete: true,
  },
  {
    candidateId: "demo-candidate-0003",
    symbol: "DEMO.NVL",
    versionId: "pullback-long-v2",
    session: SESSION_COUNT - 54,
    state: "READY_FOR_RISK_REVIEW",
    primaryReason: "EVERY_DETERMINISTIC_REQUIREMENT_SATISFIED",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_B",
    setupQuality: "ORDERLY_PULLBACK_TO_SUPPORT",
    rank: 6,
    rankPopulation: 41,
    thesis: "TREND_PULLBACK_INTO_RISING_SUPPORT",
    whyNow: "REVERSAL_BAR_AT_THE_TESTED_LEVEL",
    entryCondition: "RECLAIM_OF_THE_PRIOR_SESSION_HIGH",
    horizonDays: 15,
    ai: "SUPPORTING",
    challengerFindings: ["CROWDING_ASSESSED_AS_MODERATE"],
    contributingDecisions: 1,
    tradeId: "demo-trade-nvl-0002",
    decisionDelaySeconds: 52,
    followUpComplete: true,
  },
  {
    candidateId: "demo-candidate-0004",
    symbol: "DEMO.CIR",
    versionId: "pead-long-v1",
    session: SESSION_COUNT - 48,
    state: "READY_FOR_RISK_REVIEW",
    primaryReason: "EVERY_DETERMINISTIC_REQUIREMENT_SATISFIED",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_A",
    setupQuality: "POSITIVE_SURPRISE_WITH_ORDERLY_DRIFT",
    rank: 2,
    rankPopulation: 41,
    thesis: "POST_EARNINGS_DRIFT_AFTER_A_POSITIVE_SURPRISE",
    whyNow: "DRIFT_WINDOW_OPENED_ON_THE_CONFIRMED_REPORT",
    entryCondition: "HOLD_ABOVE_THE_REPORT_SESSION_MIDPOINT",
    horizonDays: 20,
    ai: "SUPPORTING",
    challengerFindings: ["ALTERNATIVE_EXPLANATION_CONSIDERED_AND_REJECTED"],
    contributingDecisions: 2,
    tradeId: "demo-trade-cir-0003",
    decisionDelaySeconds: 41,
    followUpComplete: true,
  },
  {
    candidateId: "demo-candidate-0005",
    symbol: "DEMO.HLX",
    versionId: "deterioration-short-v1",
    session: SESSION_COUNT - 29,
    state: "READY_FOR_RISK_REVIEW",
    primaryReason: "EVERY_DETERMINISTIC_REQUIREMENT_SATISFIED",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_B",
    setupQuality: "CONFIRMED_FUNDAMENTAL_DETERIORATION",
    rank: 3,
    rankPopulation: 41,
    thesis: "FUNDAMENTAL_DETERIORATION_WITH_DISTRIBUTION",
    whyNow: "LOSS_OF_THE_LAST_DEFENDED_LEVEL",
    entryCondition: "CLOSE_BELOW_THE_DEFENDED_LEVEL",
    horizonDays: 16,
    ai: "SUPPORTING",
    challengerFindings: ["SQUEEZE_RISK_ASSESSED_AS_LOW"],
    contributingDecisions: 1,
    tradeId: "demo-trade-hlx-0004",
    decisionDelaySeconds: 63,
    followUpComplete: true,
  },
  {
    /** READY, and then declined DOWNSTREAM. The Brain had no objection; risk did. */
    candidateId: "demo-candidate-0006",
    symbol: "DEMO.KTN",
    versionId: "breakout-long-v3",
    session: SESSION_COUNT - 34,
    state: "READY_FOR_RISK_REVIEW",
    primaryReason: "EVERY_DETERMINISTIC_REQUIREMENT_SATISFIED",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_C",
    setupQuality: "CLEAN_BASE_BREAK",
    rank: 9,
    rankPopulation: 41,
    thesis: "RANGE_EXPANSION_WITH_CONFIRMED_RELATIVE_STRENGTH",
    whyNow: "CLOSE_ABOVE_THE_CONSOLIDATION_HIGH",
    entryCondition: "CLOSE_ABOVE_THE_CONSOLIDATION_HIGH_ON_EXPANDING_RANGE",
    horizonDays: 18,
    ai: "SUPPORTING",
    challengerFindings: ["NO_FALSIFYING_EVIDENCE_FOUND"],
    contributingDecisions: 1,
    missCause: "DOWNSTREAM_RISK_DECISION_DECLINED",
    decisionDelaySeconds: 55,
    followUpComplete: true,
  },
  {
    /** The thesis stood, the entry never fired, and the window closed. */
    candidateId: "demo-candidate-0007",
    symbol: "DEMO.MRD",
    versionId: "pullback-long-v2",
    session: SESSION_COUNT - 44,
    state: "WATCHLIST",
    primaryReason: "ENTRY_CONDITION_NOT_MET_AT_THIS_DECISION",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_C",
    setupQuality: "ORDERLY_PULLBACK_TO_SUPPORT",
    rank: 14,
    rankPopulation: 41,
    thesis: "TREND_PULLBACK_INTO_RISING_SUPPORT",
    whyNow: "SUPPORT_TESTED_WITHOUT_A_REVERSAL_BAR",
    entryCondition: "RECLAIM_OF_THE_PRIOR_SESSION_HIGH",
    horizonDays: 12,
    ai: "SUPPORTING",
    challengerFindings: ["NO_FALSIFYING_EVIDENCE_FOUND"],
    contributingDecisions: 1,
    missCause: "WATCHLIST_WINDOW_EXPIRED_UNTRIGGERED",
    expirySession: SESSION_COUNT - 32,
    decisionDelaySeconds: 44,
    followUpComplete: true,
  },
  {
    candidateId: "demo-candidate-0008",
    symbol: "DEMO.PLM",
    versionId: "pead-long-v1",
    session: SESSION_COUNT - 52,
    state: "REJECTED",
    primaryReason: "LIQUIDITY_BELOW_THE_MODULE_MINIMUM",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_D",
    setupQuality: "SURPRISE_WITHOUT_ORDERLY_DRIFT",
    rank: 31,
    rankPopulation: 41,
    thesis: "POST_EARNINGS_DRIFT_AFTER_A_POSITIVE_SURPRISE",
    whyNow: "DRIFT_WINDOW_OPENED_ON_THE_CONFIRMED_REPORT",
    entryCondition: "HOLD_ABOVE_THE_REPORT_SESSION_MIDPOINT",
    horizonDays: 20,
    ai: "SUPPORTING",
    challengerFindings: ["EVIDENCE_QUALITY_SCORED_LOW"],
    contributingDecisions: 1,
    missCause: "REJECTED_BY_A_DETERMINISTIC_ELIGIBILITY_RULE",
    decisionDelaySeconds: 31,
    followUpComplete: true,
  },
  {
    /** The one whose follow-up path this book cannot complete. */
    candidateId: "demo-candidate-0009",
    symbol: "DEMO.SOL",
    versionId: "pead-long-v1",
    session: SESSION_COUNT - 25,
    state: "BLOCKED_DATA",
    primaryReason: "POINT_IN_TIME_COVERAGE_REQUIREMENT_UNMET",
    blockingReasons: [
      "POINT_IN_TIME_COVERAGE_REQUIREMENT_UNMET",
      "FUNDAMENTAL_AS_OF_DATE_UNRESOLVED",
    ],
    contradictions: [],
    convictionBand: "BAND_C",
    setupQuality: "POSITIVE_SURPRISE_WITH_ORDERLY_DRIFT",
    rank: 11,
    rankPopulation: 41,
    thesis: "POST_EARNINGS_DRIFT_AFTER_A_POSITIVE_SURPRISE",
    whyNow: "DRIFT_WINDOW_OPENED_ON_THE_CONFIRMED_REPORT",
    entryCondition: "HOLD_ABOVE_THE_REPORT_SESSION_MIDPOINT",
    horizonDays: 20,
    ai: "SUPPORTING",
    challengerFindings: ["NO_FALSIFYING_EVIDENCE_FOUND"],
    contributingDecisions: 1,
    missCause: "POINT_IN_TIME_DATA_COVERAGE_UNMET",
    decisionDelaySeconds: 37,
    followUpComplete: false,
  },
  {
    candidateId: "demo-candidate-0010",
    symbol: "DEMO.NVL",
    versionId: "pead-long-v1",
    session: SESSION_COUNT - 38,
    state: "BLOCKED_EVENT",
    primaryReason: "BINARY_EVENT_INSIDE_THE_EXPECTED_HOLDING_PERIOD",
    blockingReasons: ["BINARY_EVENT_INSIDE_THE_EXPECTED_HOLDING_PERIOD"],
    contradictions: [],
    convictionBand: "BAND_B",
    setupQuality: "POSITIVE_SURPRISE_WITH_ORDERLY_DRIFT",
    rank: 7,
    rankPopulation: 41,
    thesis: "POST_EARNINGS_DRIFT_AFTER_A_POSITIVE_SURPRISE",
    whyNow: "DRIFT_WINDOW_OPENED_ON_THE_CONFIRMED_REPORT",
    entryCondition: "HOLD_ABOVE_THE_REPORT_SESSION_MIDPOINT",
    horizonDays: 20,
    ai: "SUPPORTING",
    challengerFindings: ["EVENT_RISK_IDENTIFIED"],
    contributingDecisions: 1,
    missCause: "EVENT_CONSTRAINT_REFUSED_THE_ENTRY",
    decisionDelaySeconds: 29,
    followUpComplete: true,
  },
  {
    candidateId: "demo-candidate-0011",
    symbol: "DEMO.PLM",
    versionId: "pead-short-v1",
    session: SESSION_COUNT - 21,
    state: "BLOCKED_BORROW",
    primaryReason: "BORROW_AVAILABILITY_UNKNOWN_AT_DECISION",
    blockingReasons: ["BORROW_AVAILABILITY_UNKNOWN_AT_DECISION", "FEE_STATE_UNRESOLVED"],
    contradictions: [],
    convictionBand: "BAND_B",
    setupQuality: "NEGATIVE_SURPRISE_WITH_ORDERLY_FADE",
    rank: 5,
    rankPopulation: 41,
    thesis: "POST_EARNINGS_FADE_AFTER_A_NEGATIVE_SURPRISE",
    whyNow: "FAILURE_TO_RECLAIM_THE_REPORT_SESSION_LOW",
    entryCondition: "CLOSE_BELOW_THE_REPORT_SESSION_LOW",
    horizonDays: 14,
    ai: "SUPPORTING",
    challengerFindings: ["SQUEEZE_RISK_IDENTIFIED"],
    contributingDecisions: 1,
    missCause: "BORROW_PREREQUISITES_UNSATISFIED",
    decisionDelaySeconds: 71,
    followUpComplete: true,
  },
  {
    /** AI evidence REMOVED this candidate. It removed one; it restored none. */
    candidateId: "demo-candidate-0012",
    symbol: "DEMO.CIR",
    versionId: "pullback-long-v2",
    session: SESSION_COUNT - 30,
    state: "BLOCKED_CONTRADICTION",
    primaryReason: "EVIDENCE_SOURCES_DISAGREE_ON_THE_CATALYST",
    blockingReasons: ["EVIDENCE_SOURCES_DISAGREE_ON_THE_CATALYST"],
    contradictions: [
      "DETERMINISTIC_TREND_EVIDENCE_CONTRADICTS_THE_RESEARCHED_CATALYST",
      "TWO_MODULES_DISAGREE_ON_DIRECTION_IN_ONE_DECISION_WINDOW",
    ],
    convictionBand: "BAND_C",
    setupQuality: "ORDERLY_PULLBACK_TO_SUPPORT",
    rank: 12,
    rankPopulation: 41,
    thesis: "TREND_PULLBACK_INTO_RISING_SUPPORT",
    whyNow: "REVERSAL_BAR_AT_THE_TESTED_LEVEL",
    entryCondition: "RECLAIM_OF_THE_PRIOR_SESSION_HIGH",
    horizonDays: 15,
    ai: "REMOVING",
    challengerFindings: ["THESIS_FALSIFIED_BY_A_CONTRADICTING_SOURCE"],
    contributingDecisions: 2,
    missCause: "UNRESOLVED_EVIDENCE_CONTRADICTION",
    decisionDelaySeconds: 58,
    followUpComplete: true,
  },
  {
    /** The AI producer answered nothing at all. An absence, never an empty list. */
    candidateId: "demo-candidate-0013",
    symbol: "DEMO.MRD",
    versionId: "breakout-long-v3",
    session: SESSION_COUNT - 18,
    state: "BLOCKED_AI",
    primaryReason: "REQUIRED_AI_EVIDENCE_MISSING",
    blockingReasons: ["REQUIRED_AI_EVIDENCE_MISSING"],
    contradictions: [],
    convictionBand: "BAND_C",
    setupQuality: "CLEAN_BASE_BREAK",
    rank: 10,
    rankPopulation: 41,
    thesis: "RANGE_EXPANSION_WITH_CONFIRMED_RELATIVE_STRENGTH",
    whyNow: "CLOSE_ABOVE_THE_CONSOLIDATION_HIGH",
    entryCondition: "CLOSE_ABOVE_THE_CONSOLIDATION_HIGH_ON_EXPANDING_RANGE",
    horizonDays: 18,
    ai: "UNAVAILABLE",
    challengerFindings: [],
    contributingDecisions: 1,
    missCause: "REQUIRED_AI_EVIDENCE_UNAVAILABLE",
    decisionDelaySeconds: 33,
    followUpComplete: true,
  },
  {
    /** Still watching, and its window has not closed. NOT a missed opportunity. */
    candidateId: "demo-candidate-0014",
    symbol: "DEMO.KTN",
    versionId: "pullback-long-v2",
    session: SESSION_COUNT - 6,
    state: "WATCHLIST",
    primaryReason: "ENTRY_CONDITION_NOT_MET_AT_THIS_DECISION",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_B",
    setupQuality: "ORDERLY_PULLBACK_TO_SUPPORT",
    rank: 8,
    rankPopulation: 41,
    thesis: "TREND_PULLBACK_INTO_RISING_SUPPORT",
    whyNow: "SUPPORT_TESTED_WITHOUT_A_REVERSAL_BAR",
    entryCondition: "RECLAIM_OF_THE_PRIOR_SESSION_HIGH",
    horizonDays: 12,
    ai: "SUPPORTING",
    challengerFindings: ["NO_FALSIFYING_EVIDENCE_FOUND"],
    contributingDecisions: 1,
    expirySession: SESSION_COUNT + 6,
    decisionDelaySeconds: 40,
    followUpComplete: true,
  },
  {
    /** The AI evidence exists and is past its contract. Value-bearing, and qualified. */
    candidateId: "demo-candidate-0015",
    symbol: "DEMO.HLX",
    versionId: "pead-short-v1",
    session: SESSION_COUNT - 15,
    state: "BLOCKED_AI",
    primaryReason: "REQUIRED_AI_EVIDENCE_STALE",
    blockingReasons: ["REQUIRED_AI_EVIDENCE_STALE"],
    contradictions: [],
    convictionBand: "BAND_C",
    setupQuality: "NEGATIVE_SURPRISE_WITH_ORDERLY_FADE",
    rank: 13,
    rankPopulation: 41,
    thesis: "POST_EARNINGS_FADE_AFTER_A_NEGATIVE_SURPRISE",
    whyNow: "FAILURE_TO_RECLAIM_THE_REPORT_SESSION_LOW",
    entryCondition: "CLOSE_BELOW_THE_REPORT_SESSION_LOW",
    horizonDays: 14,
    ai: "STALE",
    challengerFindings: ["EVIDENCE_QUALITY_SCORED_LOW"],
    contributingDecisions: 1,
    missCause: "REQUIRED_AI_EVIDENCE_STALE",
    decisionDelaySeconds: 49,
    followUpComplete: true,
  },
  {
    /** The entry window closed while the decision was still being made. */
    candidateId: "demo-candidate-0016",
    symbol: "DEMO.ARB",
    versionId: "pead-long-v1",
    session: SESSION_COUNT - 12,
    state: "READY_FOR_RISK_REVIEW",
    primaryReason: "EVERY_DETERMINISTIC_REQUIREMENT_SATISFIED",
    blockingReasons: [],
    contradictions: [],
    convictionBand: "BAND_B",
    setupQuality: "POSITIVE_SURPRISE_WITH_ORDERLY_DRIFT",
    rank: 15,
    rankPopulation: 41,
    thesis: "POST_EARNINGS_DRIFT_AFTER_A_POSITIVE_SURPRISE",
    whyNow: "DRIFT_WINDOW_OPENED_ON_THE_CONFIRMED_REPORT",
    entryCondition: "HOLD_ABOVE_THE_REPORT_SESSION_MIDPOINT",
    horizonDays: 20,
    ai: "SUPPORTING",
    challengerFindings: ["NO_FALSIFYING_EVIDENCE_FOUND"],
    contributingDecisions: 1,
    missCause: "DECISION_DELAY_EXCEEDED_THE_ENTRY_WINDOW",
    decisionDelaySeconds: 9_180,
    followUpComplete: true,
  },
];

/** Every journaled candidate, in the order they were decided. */
export const CANDIDATE_RECORDS: readonly CandidateRecord[] = [...CANDIDATES].sort(
  (left, right) =>
    right.session - left.session || left.candidateId.localeCompare(right.candidateId),
);

const BY_ID = new Map(CANDIDATES.map((entry) => [entry.candidateId, entry]));
const BY_TRADE = new Map(
  CANDIDATES.filter((entry) => entry.tradeId !== undefined).map((entry) => [
    entry.tradeId as string,
    entry,
  ]),
);

export function candidateRecord(candidateId: string): CandidateRecord | undefined {
  return BY_ID.get(candidateId);
}

/** The candidate a trade came from, where one was journaled. Most trades have none. */
export function candidateForTrade(tradeId: string): CandidateRecord | undefined {
  return BY_TRADE.get(tradeId);
}

/* ------------------------------------------------------------- declared stage counts */

/**
 * The two stage counts that are DECLARED rather than derived.
 *
 * The journal below records the candidates a decision produced. It records nothing about the
 * securities that produced none, so the universe and eligible counts cannot be derived from it
 * — a real funnel producer would journal them as stage counts, and here they are declared as
 * exactly that. **They are fictional stage counts, and the definition code on each stage says
 * what it counted.**
 */
const UNIVERSE_SECURITIES = 512;
const ELIGIBLE_SECURITIES = 41;

/* -------------------------------------------------------------------- projections */

function securityFor(record: CandidateRecord): BookSecurity {
  return securityOf(record.symbol);
}

function decisionInstant(record: CandidateRecord, days: readonly string[]): string {
  return sessionInstant(days[Math.min(record.session, days.length - 1)]);
}

/** The direction a candidate's strategy version trades. Never inferred from anything else. */
function directionOf(record: CandidateRecord): "LONG" | "SHORT" {
  return strategyVersionOf(record.versionId).direction;
}

/**
 * The downstream stage a candidate reached.
 *
 * **A SEPARATE AXIS (§2.7), and almost always an absence.** No risk engine, order router or
 * execution runtime exists, so the honest answer for every candidate is that no downstream
 * record was produced — with one exception the journal itself records: the candidate whose
 * recorded miss cause IS a downstream risk decision. That cause is a fact the missed-
 * opportunity producer journaled; the risk decision record it refers to does not exist here,
 * and its reference resolves to an availability state rather than to a payload.
 */
function downstreamStageOf(record: CandidateRecord, asOf: string) {
  if (record.missCause === "DOWNSTREAM_RISK_DECISION_DECLINED") {
    return token("candidate.downstream_stage", "RISK_REJECTED", asOf);
  }
  if (record.tradeId !== undefined) {
    return token("candidate.downstream_stage", "ORDER_FILLED", asOf);
  }
  return unavailable(
    "candidate.downstream_stage",
    "DIMENSIONLESS",
    "NOT_IMPLEMENTED",
    "PRODUCER_NOT_IMPLEMENTED",
  );
}

export function buildCandidateSummary(
  record: CandidateRecord,
  days: readonly string[],
  asOf: string,
): CandidateSummary {
  const security = securityFor(record);
  const version = strategyVersionOf(record.versionId);
  return {
    candidate_id: record.candidateId,
    security_ref: demoRef(`security-${record.symbol.toLowerCase()}`, "evidence", "EMBEDDED"),
    security: { symbol: record.symbol, display_name: security.displayName },
    direction: directionOf(record),
    decided_at: decisionInstant(record, days),
    brain_state: record.state,
    primary_reason: demoReason(record.primaryReason),
    conviction_band: demoReason(record.convictionBand),
    strategy_module: demoReason(version.module),
    downstream_stage: downstreamStageOf(record, asOf),
    detail_ref: demoRef(record.candidateId, "candidate", "ENDPOINT"),
    pins: demoPins(record.versionId),
  };
}

const CANDIDATE_PAGE_SIZE = 200;
const CANDIDATE_POPULATION = "EVERY_JOURNALED_CANDIDATE_DECISION_IN_THE_RETAINED_WINDOW";

function journalWindow(days: readonly string[]) {
  const first = Math.max(0, days.length - 1 - JOURNAL_SESSIONS);
  return {
    from: `${days[first]}T00:00:00.000Z`,
    to: sessionInstant(days[days.length - 1]),
    calendar: CALENDAR,
    timezone: "UTC" as const,
  };
}

export function syntheticCandidates(
  asOf: string,
  days: readonly string[],
): CandidateSummaryPayload {
  const items = CANDIDATE_RECORDS.map((record) =>
    buildCandidateSummary(record, days, asOf),
  );
  return {
    items,
    page: {
      page_size: CANDIDATE_PAGE_SIZE,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("DECIDED_AT_DESCENDING"),
      tiebreak: demoReason("CANDIDATE_ID_ASCENDING"),
    },
    window: journalWindow(days),
    population: demoReason(CANDIDATE_POPULATION),
  };
}

/* ------------------------------------------------------------------ CandidateDetail */

const RESEARCH_MODEL_VERSION = "research-agent-demo-v1";
const RESEARCH_PROMPT_VERSION = "research-prompt-demo-v1";
const CHALLENGER_MODEL_VERSION = "challenger-agent-demo-v1";
const CHALLENGER_PROMPT_VERSION = "challenger-prompt-demo-v1";
const EVIDENCE_SCHEMA_VERSION = "ai-evidence-demo-v1";

/** How far before the decision a piece of research evidence was published, in hours. */
const RESEARCH_PUBLISH_LEAD_HOURS = 26;
const STALE_PUBLISH_LEAD_HOURS = 26 * 30;

function aiRecord(
  record: CandidateRecord,
  days: readonly string[],
  asOf: string,
  options: {
    readonly index: number;
    readonly finding: string;
    readonly source: string;
    readonly removes: boolean;
    readonly challenger: boolean;
    readonly stale: boolean;
  },
) {
  const decidedMs = Date.parse(decisionInstant(record, days));
  const lead = options.stale ? STALE_PUBLISH_LEAD_HOURS : RESEARCH_PUBLISH_LEAD_HOURS;
  const publishedMs = decidedMs - lead * 3_600_000;
  const observedMs = publishedMs + 45 * 60_000;
  const kind = options.challenger ? "challenger" : "research";
  return {
    reference: demoRef(
      `${record.candidateId}-${kind}-${options.index}`,
      "evidence",
      "AUTHORIZED_READ",
    ),
    source: demoReason(options.source),
    published_at: instantValue("evidence.published_at", new Date(publishedMs).toISOString(), asOf),
    observed_at: instantValue("evidence.observed_at", new Date(observedMs).toISOString(), asOf),
    model_version: options.challenger ? CHALLENGER_MODEL_VERSION : RESEARCH_MODEL_VERSION,
    prompt_version: options.challenger ? CHALLENGER_PROMPT_VERSION : RESEARCH_PROMPT_VERSION,
    schema_version: EVIDENCE_SCHEMA_VERSION,
    confidence: scaled("evidence.confidence", "DIMENSIONLESS", options.stale ? 41 : 72, asOf),
    quality: token("evidence.quality", options.stale ? "STALE_SOURCE" : "STRUCTURED_AND_CITED", asOf),
    finding: demoReason(options.finding),
    removes_candidate: options.removes,
  };
}

/** The deterministic factor evidence a candidate carries. Dimensionless scores, never prices. */
const FACTOR_AXES = [
  "RESIDUAL_MOMENTUM_126D",
  "RELATIVE_STRENGTH_VS_SECTOR",
  "REALIZED_VOLATILITY_20D",
  "LIQUIDITY_PARTICIPATION",
] as const;

const FACTOR_DEFINITION_PIN = "factor-definition-demo-v2";

function factorEvidence(record: CandidateRecord, asOf: string) {
  const security = securityFor(record);
  return FACTOR_AXES.map((axis, index) => {
    /*
     * A fixed step function over the security's own constants. It is arithmetic over a table
     * and it MEANS NOTHING -- no factor was computed, and no factor definition exists.
     */
    const score =
      ((security.basePriceCents + security.stopDistanceCents * (index + 1) + record.rank * 7) %
        401) -
      200;
    return {
      factor: demoReason(axis),
      value: scaled("candidate.factor_score", "DIMENSIONLESS", score, asOf),
      pin: FACTOR_DEFINITION_PIN,
    };
  });
}

/** The evidence a decision wanted and did not have, per posture. */
function evidenceGaps(record: CandidateRecord) {
  const gaps: {
    expected: ReturnType<typeof demoReason>;
    availability: "NOT_IMPLEMENTED" | "NOT_YET_AVAILABLE" | "NOT_AUTHORIZED";
    reason: "PRODUCER_NOT_IMPLEMENTED" | "UPSTREAM_INPUT_MISSING";
  }[] = [
    {
      expected: demoReason("HISTORICAL_BORROW_EVIDENCE"),
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
    },
    {
      expected: demoReason("ANALYST_ESTIMATE_REVISIONS"),
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
    },
  ];
  if (record.ai === "UNAVAILABLE") {
    gaps.unshift({
      expected: demoReason("AI_RESEARCH_EVIDENCE"),
      availability: "NOT_YET_AVAILABLE",
      reason: "UPSTREAM_INPUT_MISSING",
    });
  }
  if (record.state === "BLOCKED_DATA") {
    gaps.unshift({
      expected: demoReason("POINT_IN_TIME_FUNDAMENTAL_COVERAGE"),
      availability: "NOT_YET_AVAILABLE",
      reason: "UPSTREAM_INPUT_MISSING",
    });
  }
  return gaps;
}

export function syntheticCandidateDetail(
  record: CandidateRecord,
  days: readonly string[],
  asOf: string,
): CandidateDetailPayload {
  const security = securityFor(record);
  const version = strategyVersionOf(record.versionId);
  const direction = directionOf(record);
  const stale = record.ai === "STALE";
  const research =
    record.ai === "UNAVAILABLE"
      ? []
      : [
          aiRecord(record, days, asOf, {
            index: 0,
            finding: "CATALYST_CLASSIFIED_AND_SOURCED",
            source: "APPROVED_FILING_SUMMARY",
            removes: false,
            challenger: false,
            stale,
          }),
        ];
  const challenger = record.challengerFindings.map((finding, index) =>
    aiRecord(record, days, asOf, {
      index,
      finding,
      source: "CHALLENGER_FALSIFICATION_ATTEMPT",
      /** Only a REMOVING posture produces evidence that removed the candidate. */
      removes: record.ai === "REMOVING" && index === 0,
      challenger: true,
      stale,
    }),
  );
  const aiEvidence = [...research, ...challenger];
  /*
   * THE INVALIDATION DISTANCE, AS A PERCENTAGE OF THE ENTRY REFERENCE.
   *
   * The Brain specification's 6.2 forbids a dollar amount, a share count and a position size
   * anywhere in a candidate, so the risk BASIS a later decision would size against is carried
   * as a distance rather than as an amount. Nothing here can be multiplied into capital.
   */
  const distanceHundredths = Math.round(
    (security.stopDistanceCents * 10_000) / security.basePriceCents,
  );

  return {
    candidate_id: record.candidateId,
    security_ref: demoRef(`security-${record.symbol.toLowerCase()}`, "evidence", "EMBEDDED"),
    security: { symbol: record.symbol, display_name: security.displayName },
    direction,
    alpha_family: demoReason(version.family),
    strategy_module: demoReason(version.module),
    trade_template: demoReason(version.template),
    decided_at: decisionInstant(record, days),
    thesis: demoReason(record.thesis),
    why_now: demoReason(record.whyNow),
    entry_condition: demoReason(record.entryCondition),
    expected_horizon: tradingDays("candidate.expected_horizon", record.horizonDays, asOf),
    rank: ordinal("candidate.rank", record.rank, asOf),
    rank_population: count("candidate.rank_population", record.rankPopulation, asOf),
    ranking_basis: demoReason("CROSS_SECTIONAL_WITHIN_THE_ELIGIBLE_UNIVERSE"),
    setup_quality: token("candidate.setup_quality", record.setupQuality, asOf),
    conviction_band: demoReason(record.convictionBand),
    deterministic_evidence: factorEvidence(record, asOf),
    regime_ref: demoRef("market-regime-current", "regime_context", "ENDPOINT"),
    regime_context: demoReason("REGIME_PERMITTED_THIS_MODULE_AT_THE_DECISION"),
    ai_evidence_refs: refListOf(
      aiEvidence.map((entry) => entry.reference),
      "ZERO_OR_MORE",
      asOf,
    ),
    ai_evidence: aiEvidence,
    ai_availability:
      record.ai === "UNAVAILABLE" ? "NOT_YET_AVAILABLE" : stale ? "STALE" : "AVAILABLE",
    ai_reason:
      record.ai === "UNAVAILABLE"
        ? "UPSTREAM_INPUT_MISSING"
        : stale
          ? "UPSTREAM_INPUT_STALE"
          : "NONE",
    challenger_objections: refListOf(
      challenger.map((entry) => entry.reference),
      "ZERO_OR_MORE",
      asOf,
    ),
    challenger_findings: challenger,
    brain_state: record.state,
    blocking_reasons: record.blockingReasons.map((code) => demoReason(code)),
    contradictions: record.contradictions.map((code) => demoReason(code)),
    evidence_gaps: evidenceGaps(record),
    /** A LEVEL, CARRIED AS A REFERENCE. It is not an order and it never becomes one here. */
    invalidation_ref: demoRef(
      `${record.candidateId}-invalidation`,
      "evidence",
      "AUTHORIZED_READ",
    ),
    risk_context: {
      initial_planned_risk_basis: percent(
        "candidate.invalidation_distance",
        distanceHundredths,
        asOf,
      ),
      event_flags: security.eventInWindow
        ? [demoReason("SCHEDULED_BINARY_EVENT_INSIDE_THE_EXPECTED_HOLDING_PERIOD")]
        : [demoReason("NO_SCHEDULED_BINARY_EVENT_IN_THE_EXPECTED_HOLDING_PERIOD")],
      gap_risk: scaled(
        "candidate.gap_risk",
        "DIMENSIONLESS",
        security.eventInWindow ? 180 : 60,
        asOf,
      ),
      liquidity_state: token(
        "candidate.liquidity_state",
        record.state === "REJECTED" ? "BELOW_MODULE_MINIMUM" : "ABOVE_MODULE_MINIMUM",
        asOf,
      ),
      earnings_carry: demoReason(
        security.eventInWindow ? "EARNINGS_CARRY_NOT_PERMITTED" : "NO_EARNINGS_INSIDE_THE_HORIZON",
      ),
      sector: demoReason(security.sector),
      correlation_cluster: demoReason(security.correlationCluster),
    },
    short_context:
      direction === "SHORT"
        ? {
            borrow_required: true,
            borrow_state: demoReason(
              record.state === "BLOCKED_BORROW" ? "BORROW_UNKNOWN" : "BORROW_LOCATED",
            ),
            borrow_evidence_ref: demoRef(
              `${record.candidateId}-borrow`,
              "evidence",
              "AUTHORIZED_READ",
            ),
            fee_state: demoReason(
              record.state === "BLOCKED_BORROW" ? "FEE_UNRESOLVED" : "FEE_WITHIN_THE_MODULE_BAND",
            ),
            squeeze_state: demoReason("SQUEEZE_RISK_ASSESSED_FROM_A_RECORD"),
            ssr_state: demoReason("SHORT_SALE_RESTRICTION_NOT_IN_FORCE"),
            recall_risk: demoReason("RECALL_RISK_ASSESSED_FROM_A_RECORD"),
          }
        : undefined,
    expires_at:
      record.expirySession === undefined
        ? undefined
        : instantValue(
            "candidate.decided_at",
            sessionInstant(days[Math.min(record.expirySession, days.length - 1)]),
            asOf,
          ),
    downstream_refs: {
      /*
       * THE RISK DECISION AND THE TRADE ARE SEPARATELY OWNED.
       *
       * No risk engine exists, so the risk decision resolves to an availability state. The
       * trade does exist for a taken candidate, and its detail is one authorized read away.
       */
      risk_decision: demoRef(`${record.candidateId}-risk-decision`, "risk_decision"),
      trade:
        record.tradeId === undefined
          ? demoRef(`${record.candidateId}-trade`, "source_fact")
          : demoRef(record.tradeId, "source_fact", "ENDPOINT"),
    },
    pins: demoPins(record.versionId),
  };
}

/* ------------------------------------------------------------------ CandidateFunnel */

const UNIVERSE_DEFINITION = "LIQUID_US_COMMON_STOCKS_IN_THE_DECLARED_DEMONSTRATION_UNIVERSE";
const ELIGIBLE_DEFINITION = "SECURITIES_PASSING_EVERY_DETERMINISTIC_ELIGIBILITY_RULE";
const GENERATED_DEFINITION = "MODULE_DECISIONS_PRODUCED_BEFORE_CONSOLIDATION";
const CONSOLIDATED_DEFINITION = "ECONOMIC_OPPORTUNITIES_AFTER_CONSOLIDATION";

function generatedDecisions(records: readonly CandidateRecord[]): number {
  return records.reduce((total, record) => total + record.contributingDecisions, 0);
}

function stageEntry(
  stage: "UNIVERSE" | "ELIGIBLE" | "GENERATED" | "CONSOLIDATED",
  subject: "SECURITIES" | "CANDIDATE_DECISIONS" | "CANDIDATES",
  definition: string,
  value: number,
  asOf: string,
) {
  return {
    stage,
    subject,
    count: count("funnel.stage_count", value, asOf),
    definition: demoReason(definition),
  } as const;
}

/** The reason distribution of one state, and whether one candidate can contribute twice. */
function reasonsFor(records: readonly CandidateRecord[], asOf: string) {
  const overlapping = records.some(
    (record) => record.blockingReasons.length + 1 > 1 && record.blockingReasons.length > 0,
  );
  const tally = new Map<string, number>();
  for (const record of records) {
    const codes = new Set<string>([record.primaryReason, ...record.blockingReasons]);
    for (const code of codes) {
      tally.set(code, (tally.get(code) ?? 0) + 1);
    }
  }
  return [...tally.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([code, value]) => ({
      code: demoReason(code),
      count: count("funnel.reason_count", value, asOf),
      overlapping,
    }));
}

function brainAxis(records: readonly CandidateRecord[], asOf: string) {
  return BRAIN_DECISION_STATES.map((state) => {
    const inState = records.filter((record) => record.state === state);
    return {
      state,
      /** A state nothing reached carries a MEASURED ZERO, which is a result (ADR-0029 §2.1). */
      count: count("funnel.state_count", inState.length, asOf),
      reasons: reasonsFor(inState, asOf),
    };
  });
}

function conversion(
  from: string,
  to: string,
  fromSubject: "SECURITIES" | "CANDIDATE_DECISIONS" | "CANDIDATES",
  toSubject: "SECURITIES" | "CANDIDATE_DECISIONS" | "CANDIDATES",
  numerator: number,
  denominator: number,
  asOf: string,
) {
  const comparable = fromSubject === toSubject && denominator > 0;
  return {
    from: demoReason(from),
    to: demoReason(to),
    rate: comparable
      ? scaled(
          "funnel.conversion_rate",
          "RATIO",
          Math.round((numerator * 10_000) / denominator),
          asOf,
        )
      : denominator === 0
        ? unavailable("funnel.conversion_rate", "RATIO", "NOT_APPLICABLE", "DENOMINATOR_ZERO")
        : /*
           * TWO STAGES COUNTING DIFFERENT SUBJECTS DO NOT DIVIDE.
           *
           * Eligible SECURITIES into generated DECISIONS is not a conversion rate; it is a
           * ratio between two different populations, and reporting it as a percentage would
           * tell a reader that consolidation lost opportunities that never existed.
           */
          unavailable(
            "funnel.conversion_rate",
            "RATIO",
            "NOT_APPLICABLE",
            "NOT_DEFINED_FOR_SUBJECT",
          ),
    numerator: count("funnel.stage_count", numerator, asOf),
    denominator: count("funnel.stage_count", denominator, asOf),
    from_subject: fromSubject,
    to_subject: toSubject,
    comparable,
  };
}

export function syntheticCandidateFunnel(
  asOf: string,
  days: readonly string[],
): CandidateFunnelPayload {
  const records = CANDIDATE_RECORDS;
  const generated = generatedDecisions(records);
  const consolidated = records.length;
  const securitiesWithCandidates = new Set(records.map((record) => record.symbol)).size;
  const ready = records.filter((record) => record.state === "READY_FOR_RISK_REVIEW").length;

  const modules = [...new Set(records.map((record) => strategyVersionOf(record.versionId).module))]
    .sort()
    .map((module) => {
      const inModule = records.filter(
        (record) => strategyVersionOf(record.versionId).module === module,
      );
      const version = strategyVersionOf(inModule[0].versionId);
      return {
        strategy_module: demoReason(module),
        strategy_version: version.versionId,
        /*
         * A PER-MODULE VIEW CARRIES THE TWO STAGES ITS RECORDS CAN ANSWER FOR.
         *
         * The universe and eligible stages are properties of the whole scan, not of one
         * module, and splitting a declared universe count across modules would invent a
         * per-module eligibility nobody journaled.
         */
        stages: [
          stageEntry(
            "GENERATED",
            "CANDIDATE_DECISIONS",
            GENERATED_DEFINITION,
            generatedDecisions(inModule),
            asOf,
          ),
          stageEntry(
            "CONSOLIDATED",
            "CANDIDATES",
            CONSOLIDATED_DEFINITION,
            inModule.length,
            asOf,
          ),
        ],
        brain_axis: brainAxis(inModule, asOf),
      };
    });

  return {
    window: journalWindow(days),
    scope: demoReason(UNIVERSE_DEFINITION),
    population: demoReason(CANDIDATE_POPULATION),
    stages: [
      stageEntry("UNIVERSE", "SECURITIES", UNIVERSE_DEFINITION, UNIVERSE_SECURITIES, asOf),
      stageEntry("ELIGIBLE", "SECURITIES", ELIGIBLE_DEFINITION, ELIGIBLE_SECURITIES, asOf),
      stageEntry("GENERATED", "CANDIDATE_DECISIONS", GENERATED_DEFINITION, generated, asOf),
      stageEntry("CONSOLIDATED", "CANDIDATES", CONSOLIDATED_DEFINITION, consolidated, asOf),
    ],
    brain_axis: brainAxis(records, asOf),
    /*
     * EVERY DOWNSTREAM MEMBER IS NOT_IMPLEMENTED IN V1 (§4.5).
     *
     * The axis is rendered in full and carries no count anywhere. That is what keeps it beside
     * the Brain axis rather than merged into it: a reader sees nine stages that exist as a
     * vocabulary and a producer that does not exist at all.
     */
    downstream_axis: DOWNSTREAM_STAGES.map((stage) => ({
      stage,
      count: unavailable(
        "funnel.state_count",
        "COUNT",
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
      ),
      availability: "NOT_IMPLEMENTED" as const,
      reason: "PRODUCER_NOT_IMPLEMENTED" as const,
    })),
    conversion: [
      conversion(
        "UNIVERSE",
        "ELIGIBLE",
        "SECURITIES",
        "SECURITIES",
        ELIGIBLE_SECURITIES,
        UNIVERSE_SECURITIES,
        asOf,
      ),
      conversion(
        "ELIGIBLE",
        "SECURITIES_WITH_A_CONSOLIDATED_CANDIDATE",
        "SECURITIES",
        "SECURITIES",
        securitiesWithCandidates,
        ELIGIBLE_SECURITIES,
        asOf,
      ),
      conversion(
        "ELIGIBLE",
        "GENERATED",
        "SECURITIES",
        "CANDIDATE_DECISIONS",
        generated,
        ELIGIBLE_SECURITIES,
        asOf,
      ),
      conversion(
        "GENERATED",
        "CONSOLIDATED",
        "CANDIDATE_DECISIONS",
        "CANDIDATES",
        consolidated,
        generated,
        asOf,
      ),
      conversion(
        "CONSOLIDATED",
        "READY_FOR_RISK_REVIEW",
        "CANDIDATES",
        "CANDIDATES",
        ready,
        consolidated,
        asOf,
      ),
    ],
    strategy_views: modules,
    decision_count: count("funnel.stage_count", generated, asOf),
  };
}

/* --------------------------------------------------------------- MissedOpportunity */

/**
 * The follow-up path a missed candidate was observed over.
 *
 * A fixed step function between two endpoints, exactly like the trade paths: the first point is
 * the security's base price and the last is a deterministic function of the candidate's own
 * identity. **It models nothing.**
 */
function followUpPath(record: CandidateRecord, sessions: number): number[] {
  const security = securityFor(record);
  const seed = record.candidateId.length * 104_729 + record.session * 7_919 + record.rank;
  /* A bounded drift of at most eight stop distances, up or down, from the base price. */
  const drift = ((seed % 17) - 8) * security.stopDistanceCents;
  const target = Math.max(security.stopDistanceCents * 3, security.basePriceCents + drift);
  return buildPath(
    security.basePriceCents,
    target,
    sessions,
    security.stopDistanceCents,
    seed,
  );
}

/** How many sessions of the registered window this book can actually observe. */
function observedSessions(record: CandidateRecord, days: readonly string[]): number {
  const available = Math.max(0, days.length - 1 - record.session);
  const requested = REGISTERED_HORIZON_DAYS;
  if (!record.followUpComplete) {
    /* The one candidate whose follow-up coverage is genuinely short. */
    return Math.min(available, Math.floor(requested / 2));
  }
  return Math.min(available, requested);
}

function followUpSeries(
  record: CandidateRecord,
  days: readonly string[],
  asOf: string,
): { series: Series; path: number[]; complete: boolean } {
  const present = observedSessions(record, days);
  const path = followUpPath(record, present);
  const points = path.map((price, offset) => ({
    t: days[Math.min(record.session + offset, days.length - 1)],
    v: usd("miss.follow_up_price", price, asOf),
  }));
  const complete = present >= REGISTERED_HORIZON_DAYS;
  return {
    series: {
      points,
      granularity: "DAILY",
      calendar: CALENDAR,
      timezone: "UTC",
      coverage: { present: points.length, requested: REGISTERED_HORIZON_DAYS + 1 },
      completeness: complete ? "COMPLETE" : "PARTIAL",
    },
    path,
    complete,
  };
}

/** The evaluable population every rate on this page is computed over. */
const EVALUABLE_POPULATION =
  "JOURNALED_CANDIDATES_NOT_ENTERED_WITH_A_COMPLETE_REGISTERED_FOLLOW_UP_PATH";

const COUNTERFACTUAL_METHOD =
  "CLOSE_TO_CLOSE_MOVEMENT_OVER_THE_WINDOW_REGISTERED_AT_THE_DECISION";

const COUNTERFACTUAL_ASSUMPTIONS = [
  "NO_POSITION_SIZE_ASSUMED",
  "NO_COMMISSION_OR_FEE_MODELLED",
  "NO_SPREAD_OR_SLIPPAGE_MODELLED",
  "NO_BORROW_COST_OR_AVAILABILITY_MODELLED",
  "NO_PROTECTIVE_STOP_MODELLED",
  "WINDOW_REGISTERED_BEFORE_THE_PATH_WAS_READ",
] as const;

function missFor(
  record: CandidateRecord,
  days: readonly string[],
  asOf: string,
): MissedOpportunity {
  const security = securityFor(record);
  const version = strategyVersionOf(record.versionId);
  const direction = directionOf(record);
  const sign = direction === "LONG" ? 1 : -1;
  const { series, path, complete } = followUpSeries(record, days, asOf);
  const entry = path[0];
  const last = path[path.length - 1];
  /*
   * THE COUNTERFACTUAL IS THE CLOSE-TO-CLOSE MOVEMENT OVER THE REGISTERED WINDOW.
   *
   * NOT the best point in the path. Choosing the most favourable exit in hindsight and
   * presenting it as an achievable outcome is the single most misleading thing this screen
   * could do, so the window is registered at the decision and the endpoint is whatever the
   * path reached at its close.
   */
  const movementHundredths = Math.round((sign * (last - entry) * 10_000) / entry);
  const best = path.reduce((peak, price) => Math.max(peak, sign * (price - entry)), 0);
  const worst = path.reduce((trough, price) => Math.min(trough, sign * (price - entry)), 0);
  const favourableHundredths = Math.round((best * 10_000) / entry);
  const adverseHundredths = Math.round((worst * 10_000) / entry);

  const decidedAt = decisionInstant(record, days);
  const decidedMs = Date.parse(decidedAt);
  const detectedMs = decidedMs - record.decisionDelaySeconds * 1000;
  const closeSession = Math.min(record.session + REGISTERED_HORIZON_DAYS, days.length - 1);
  const expirySession = record.expirySession ?? closeSession;

  /** A path-dependent value over an incomplete path is PARTIAL, never an optimistic value. */
  const pathValue = (metricId: string, hundredths: number) =>
    complete
      ? percent(metricId, hundredths, asOf)
      : qualified("PARTIAL", "PRICE_PATH_INCOMPLETE", {
          metricId,
          unit: "PERCENT",
          value: (hundredths / 100).toFixed(2),
          asOf,
        });

  return {
    miss_id: `${record.candidateId}-miss`,
    candidate_ref: demoRef(record.candidateId, "candidate", "ENDPOINT"),
    security: { symbol: record.symbol, display_name: security.displayName },
    strategy_module: demoReason(version.module),
    brain_state: record.state,
    cause: demoReason(record.missCause as string),
    window: {
      from: decidedAt,
      to: sessionInstant(days[closeSession]),
      horizon: tradingDays("candidate.expected_horizon", REGISTERED_HORIZON_DAYS, asOf),
      /** REGISTERED AT THE DECISION, before any of the path below was observed. */
      registered_at: instantValue("miss.decided_at", decidedAt, asOf),
      calendar: CALENDAR,
      timezone: "UTC",
    },
    detected_at: instantValue("miss.detected_at", new Date(detectedMs).toISOString(), asOf),
    decided_at: instantValue("miss.decided_at", decidedAt, asOf),
    expired_at:
      record.state === "WATCHLIST"
        ? instantValue(
            "miss.expired_at",
            sessionInstant(days[Math.min(expirySession, days.length - 1)]),
            asOf,
          )
        : notApplicable("miss.expired_at", "DIMENSIONLESS"),
    decision_delay: seconds("miss.decision_delay", record.decisionDelaySeconds, asOf),
    favourable_movement: pathValue("miss.favourable_movement", favourableHundredths),
    adverse_movement: pathValue("miss.adverse_movement", adverseHundredths),
    counterfactual: pathValue("miss.counterfactual", movementHundredths),
    /*
     * THE MONEY LIMB IS STRUCTURALLY PRESENT AND IS NEVER SERVED.
     *
     * Converting a price movement into an amount needs a position size, and a position size is
     * a risk decision under a governed policy. No such policy value exists here, so this is
     * `POLICY_REFERENCE_MISSING` rather than a number nobody approved.
     */
    counterfactual_money: unavailable(
      "miss.counterfactual_money",
      "USD",
      "NOT_YET_AVAILABLE",
      "POLICY_REFERENCE_MISSING",
    ),
    assumptions: COUNTERFACTUAL_ASSUMPTIONS.map((code) => demoReason(code)),
    cost_treatment: "GROSS",
    /** Absent where the path is incomplete: an unevaluable row is in no rate's population. */
    population: complete ? demoReason(EVALUABLE_POPULATION) : undefined,
    price_path_completeness: complete ? "COMPLETE" : "PARTIAL",
    follow_up_series: series,
    trade_ref: undefined,
  };
}

/** Every journaled candidate that records a cause for not being entered. */
export function missedRecords(): readonly CandidateRecord[] {
  return CANDIDATE_RECORDS.filter((record) => record.missCause !== undefined);
}

/* ---------------------------------------------------------- taken versus missed */

const MISS_PAGE_SIZE = 100;

/**
 * One arm's measured outcome, on the ONE basis both arms share.
 *
 * The taken arm is measured as the close-to-close price movement over the same registered
 * window as the missed arm — **not** as its realized profit and loss. A realized result and a
 * counterfactual are different kinds of claim, and §12.4 forbids putting them in one series;
 * measuring both arms the same way is what makes the comparison a comparison.
 */
function takenArmOutcomeHundredths(days: readonly string[]): number {
  const taken = CANDIDATE_RECORDS.filter(
    (record) => record.tradeId !== undefined,
  );
  const values = taken.map((record) => {
    const trade = BOOK.trades.find((entry) => entry.tradeId === record.tradeId) as BookTrade;
    const first = trade.path[0];
    const offset = Math.min(REGISTERED_HORIZON_DAYS, trade.path.length - 1);
    const later = trade.path[offset];
    const sign = trade.direction === "LONG" ? 1 : -1;
    return Math.round((sign * (later - first) * 10_000) / first);
  });
  void days;
  return values.length === 0
    ? 0
    : Math.round(values.reduce((total, value) => total + value, 0) / values.length);
}

function missedArmOutcomeHundredths(days: readonly string[], asOf: string): number {
  const evaluable = missedRecords()
    .map((record) => missFor(record, days, asOf))
    .filter((miss) => miss.price_path_completeness === "COMPLETE");
  const values = evaluable.map((miss) =>
    typeof miss.counterfactual.value === "string" ? Number(miss.counterfactual.value) * 100 : 0,
  );
  return values.length === 0
    ? 0
    : Math.round(values.reduce((total, value) => total + value, 0) / values.length);
}

export function syntheticMissedOpportunities(
  asOf: string,
  days: readonly string[],
): MissedOpportunityPayload {
  const records = missedRecords();
  const items = records.map((record) => missFor(record, days, asOf));
  const evaluable = items.filter((miss) => miss.price_path_completeness === "COMPLETE");

  const tally = new Map<string, number>();
  for (const record of records) {
    const cause = record.missCause as string;
    tally.set(cause, (tally.get(cause) ?? 0) + 1);
  }
  const causePatterns = [...tally.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([cause, value]) => ({
      cause: demoReason(cause),
      count: count("miss.count", value, asOf),
      share: scaled(
        "miss.rate",
        "RATIO",
        Math.round((value * 10_000) / records.length),
        asOf,
      ),
    }));

  const takenCount = CANDIDATE_RECORDS.filter((record) => record.tradeId !== undefined).length;
  const window = {
    from: sessionInstant(days[Math.max(0, days.length - 1 - JOURNAL_SESSIONS)]),
    to: sessionInstant(days[days.length - 1]),
    horizon: tradingDays("candidate.expected_horizon", REGISTERED_HORIZON_DAYS, asOf),
    registered_at: instantValue(
      "miss.decided_at",
      sessionInstant(days[Math.max(0, days.length - 1 - JOURNAL_SESSIONS)]),
      asOf,
    ),
    calendar: CALENDAR,
    timezone: "UTC" as const,
  };
  const takenOutcome = takenArmOutcomeHundredths(days);
  const missedOutcome = missedArmOutcomeHundredths(days, asOf);

  const compatibleArms = [
    {
      arm: "TAKEN" as const,
      population: demoReason("JOURNALED_CANDIDATES_THAT_BECAME_A_RECORDED_TRADE"),
      observation_count: count("performance.observation_count", takenCount, asOf),
      window,
      cost_treatment: "GROSS" as const,
      information_profile: demoReason("PROVIDER_REALISTIC_PIT"),
      outcome_basis: demoReason(COUNTERFACTUAL_METHOD),
      outcome: percent("miss.counterfactual", takenOutcome, asOf),
    },
    {
      arm: "MISSED" as const,
      population: demoReason(EVALUABLE_POPULATION),
      observation_count: count("performance.observation_count", evaluable.length, asOf),
      window,
      cost_treatment: "GROSS" as const,
      information_profile: demoReason("PROVIDER_REALISTIC_PIT"),
      outcome_basis: demoReason(COUNTERFACTUAL_METHOD),
      outcome: percent("miss.counterfactual", missedOutcome, asOf),
    },
  ] as const;

  /**
   * THE SECOND COMPARISON IS REFUSED, ON PURPOSE.
   *
   * Its arms differ in cost treatment and in window length. Nothing about the arithmetic
   * prevents subtracting one from the other; what prevents it is that the difference would
   * mean nothing, and a screen that shows it teaches a reader that it does.
   */
  const incompatibleWindow = {
    ...window,
    to: sessionInstant(days[days.length - 1]),
    horizon: tradingDays("candidate.expected_horizon", REGISTERED_HORIZON_DAYS * 2, asOf),
  };
  const incompatibleArms = [
    {
      ...compatibleArms[0],
      cost_treatment: "NET_ALL_COSTS" as const,
      outcome_basis: demoReason("REALIZED_RESULT_NET_OF_EVERY_RECORDED_COST"),
    },
    {
      ...compatibleArms[1],
      window: incompatibleWindow,
    },
  ] as const;

  return {
    items,
    page: {
      page_size: MISS_PAGE_SIZE,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("WINDOW_START_DESCENDING"),
      tiebreak: demoReason("MISS_ID_ASCENDING"),
    },
    window: journalWindow(days),
    population: demoReason("JOURNALED_CANDIDATES_WITH_A_RECORDED_CAUSE_FOR_NOT_ENTERING"),
    cause_patterns: causePatterns,
    comparisons: [
      {
        comparison_id: "demo-comparison-compatible",
        arms: [compatibleArms[0], compatibleArms[1]],
        comparable: true,
        difference: percent("miss.counterfactual", takenOutcome - missedOutcome, asOf),
      },
      {
        comparison_id: "demo-comparison-refused",
        arms: [incompatibleArms[0], incompatibleArms[1]],
        comparable: false,
        refusal: demoReason("ARMS_DIFFER_IN_COST_TREATMENT_WINDOW_LENGTH_AND_OUTCOME_BASIS"),
        difference: unavailable(
          "miss.counterfactual",
          "PERCENT",
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
        ),
      },
    ],
    rates: [
      {
        kind: "FALSE_POSITIVE",
        population: demoReason(EVALUABLE_POPULATION),
        numerator: count(
          "miss.count",
          evaluable.filter((miss) => {
            const value = miss.counterfactual.value;
            return typeof value === "string" && Number(value) <= 0;
          }).length,
          asOf,
        ),
        denominator: count("miss.count", evaluable.length, asOf),
        rate:
          evaluable.length === 0
            ? unavailable("miss.rate", "RATIO", "NOT_APPLICABLE", "DENOMINATOR_ZERO")
            : scaled(
                "miss.rate",
                "RATIO",
                Math.round(
                  (evaluable.filter((miss) => {
                    const value = miss.counterfactual.value;
                    return typeof value === "string" && Number(value) <= 0;
                  }).length *
                    10_000) /
                    evaluable.length,
                ),
                asOf,
              ),
      },
      {
        /*
         * NO FALSE-NEGATIVE RATE, BECAUSE NO POPULATION IS DEFINED.
         *
         * A false negative is an opportunity the system never detected, and a ledger of
         * detected candidates contains none of them by construction. The count is reported --
         * it is zero, and it is a measurement of THIS ledger rather than of the world -- and
         * the RATE is refused.
         */
        kind: "FALSE_NEGATIVE",
        population: undefined,
        numerator: unavailable(
          "miss.count",
          "COUNT",
          "NOT_YET_AVAILABLE",
          "UPSTREAM_INPUT_MISSING",
        ),
        denominator: unavailable(
          "miss.count",
          "COUNT",
          "NOT_YET_AVAILABLE",
          "UPSTREAM_INPUT_MISSING",
        ),
        rate: unavailable("miss.rate", "RATIO", "NOT_APPLICABLE", "NOT_DEFINED_FOR_SUBJECT"),
        note: demoReason("AN_UNDETECTED_CANDIDATE_IS_NOT_IN_THE_DETECTED_CANDIDATE_LEDGER"),
      },
    ],
    counterfactual_method: demoReason(COUNTERFACTUAL_METHOD),
  };
}
