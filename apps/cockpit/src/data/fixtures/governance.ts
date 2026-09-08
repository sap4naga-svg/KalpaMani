/**
 * `GovernancePacket` and `DecisionRecord`, projected from the synthetic research lineage —
 * Area 19.
 *
 * **READ-ONLY, WITHOUT EXCEPTION.** These are shapes a recorded packet and a recorded human
 * decision would arrive in. Nothing here approves, rejects, requests evidence, promotes,
 * activates, releases or schedules anything, and **no mechanism exists in this application
 * that could act on a decision it renders.**
 *
 * **NO APPROVED DECISION APPEARS IN THIS DEMONSTRATION, AND THAT IS DELIBERATE.** The two
 * recorded decisions are `MORE_EVIDENCE_REQUESTED` and `REJECTED`. A synthetic `APPROVED`
 * decision — over fictional strategies, on the one screen whose subject is authorization —
 * is the one fixture most likely to be read as this project having approved something, and
 * **no promotion, capital change, parameter replacement or release has been approved
 * anywhere in this repository.** The outcome vocabulary is still delivered in full, so the
 * screen states that the third member is absent rather than implying the set has two.
 */
import type {
  DecisionRecord,
  DecisionRecordPayload,
  GovernancePacket,
  GovernancePacketPayload,
  PacketState,
} from "@/contracts/governance-models";
import { DECISION_OUTCOMES, PACKET_STATES } from "@/contracts/governance-models";

import {
  count,
  demoRef,
  demoReason,
  instantValue,
  percent,
  refListOf,
  sessionInstant,
  unavailable,
  usd,
} from "./common";
import {
  CHALLENGERS,
  CHAMPIONS,
  DECISIONS,
  LINEAGE_BUDGET,
  LINEAGE_SESSIONS,
  PACKETS,
  REGISTRATIONS,
  RUNS,
} from "./lineage";

function instantAt(days: readonly string[], session: number): string {
  return sessionInstant(days[Math.max(0, Math.min(session, days.length - 1))]);
}

interface PacketSpec {
  readonly packetId: string;
  readonly registration: string;
  readonly champion: string;
  readonly challenger: string;
  readonly module: string;
  readonly state: PacketState;
  readonly session: number;
  readonly proposal: string;
  readonly cause: string;
  readonly recommendation: string;
  readonly runs: readonly string[];
  readonly shadows: readonly string[];
  readonly evidence: readonly string[];
  readonly failureModes: readonly string[];
  readonly disclosure: readonly string[];
  readonly missing: readonly string[];
  /** `null` where the packet could not read the count from the registry. */
  readonly trialCount: number | null;
  readonly decision?: string;
  readonly criteria: readonly {
    readonly criterion: string;
    readonly kind: "SUCCESS" | "FAILURE";
    readonly verdict: string | null;
  }[];
}

const PACKET_SPECS: readonly PacketSpec[] = [
  {
    packetId: PACKETS.reviewed,
    registration: REGISTRATIONS.original,
    champion: CHAMPIONS.pullback,
    challenger: CHALLENGERS.pullback,
    module: "PULLBACK_LONG",
    state: "READY_FOR_HUMAN_REVIEW",
    session: LINEAGE_SESSIONS.packetReviewed,
    proposal: "PROMOTE_THE_CHALLENGER_INTO_SHADOW_OPERATION",
    cause: "ROLLING_EXPECTANCY_BELOW_RESEARCHED_BAND_ON_THE_CHAMPION",
    recommendation: "RECOMMEND_A_LONGER_SHADOW_PERIOD_BEFORE_ANY_FURTHER_STEP",
    runs: [RUNS.confirmatory],
    shadows: [],
    evidence: ["demo-evidence-packet-summary-0000"],
    failureModes: [
      "THE_VARIATION_MAY_BE_FITTED_TO_ONE_REGIME",
      "THE_SHADOW_PERIOD_MAY_BE_TOO_SHORT_TO_SEPARATE_THE_VERSIONS",
    ],
    disclosure: ["THE_EVIDENCE_RESTS_ON_ONE_CONFIRMATORY_EVALUATION_OF_AN_UNTOUCHED_HOLDOUT"],
    missing: [],
    trialCount: 2,
    decision: DECISIONS.moreEvidence,
    criteria: [
      {
        criterion: "EXPECTANCY_IMPROVES_BY_AT_LEAST_A_QUARTER_R_AGAINST_THE_NAMED_BASELINE",
        kind: "SUCCESS",
        verdict: "MET",
      },
      { criterion: "MAXIMUM_DRAWDOWN_DOES_NOT_WORSEN", kind: "SUCCESS", verdict: "MET" },
      {
        criterion: "TAIL_LOSS_WORSENS_BY_MORE_THAN_HALF_AN_R",
        kind: "FAILURE",
        verdict: "NOT_TRIGGERED",
      },
    ],
  },
  {
    packetId: PACKETS.rejected,
    registration: REGISTRATIONS.original,
    champion: CHAMPIONS.pullback,
    challenger: CHALLENGERS.pullback,
    module: "PULLBACK_LONG",
    state: "READY_FOR_HUMAN_REVIEW",
    session: LINEAGE_SESSIONS.packetRejected,
    proposal: "PROMOTE_THE_CHALLENGER_INTO_ORDER_PRODUCING_PAPER_OPERATION",
    cause: "THE_CHALLENGER_OUTPERFORMED_THE_CHAMPION_ON_THE_LOCKED_SET",
    recommendation: "RECOMMEND_DEFERRAL_UNTIL_SHADOW_EVIDENCE_EXISTS",
    runs: [RUNS.confirmatory, RUNS.failed],
    shadows: [],
    evidence: ["demo-evidence-packet-summary-0003"],
    failureModes: ["ONE_LOCKED_SET_IS_NOT_EVIDENCE_OF_FORWARD_BEHAVIOUR"],
    disclosure: ["ONE_RUN_OF_THE_TWO_CITED_FAILED_AND_STILL_SPENT_A_TRIAL"],
    missing: [],
    trialCount: 2,
    decision: DECISIONS.rejected,
    criteria: [
      {
        criterion: "EXPECTANCY_IMPROVES_BY_AT_LEAST_A_QUARTER_R_AGAINST_THE_NAMED_BASELINE",
        kind: "SUCCESS",
        verdict: "MET",
      },
      {
        criterion: "TAIL_LOSS_WORSENS_BY_MORE_THAN_HALF_AN_R",
        kind: "FAILURE",
        verdict: "NOT_TRIGGERED",
      },
    ],
  },
  {
    packetId: PACKETS.ready,
    registration: REGISTRATIONS.amendment,
    champion: CHAMPIONS.pullback,
    challenger: CHALLENGERS.pullback,
    module: "PULLBACK_LONG",
    state: "READY_FOR_HUMAN_REVIEW",
    session: LINEAGE_SESSIONS.packetReady,
    proposal: "EXTEND_THE_AUTHORIZED_SHADOW_PERIOD_FOR_THE_CHALLENGER",
    cause: "THE_AMENDED_VARIATION_IMPROVED_EXPECTANCY_UNDER_DISCLOSED_REUSE",
    recommendation: "RECOMMEND_EXTENDING_SHADOW_AND_TAKING_NO_PROMOTION_STEP",
    runs: [RUNS.reuse, RUNS.reproduction],
    shadows: [],
    evidence: [
      "demo-evidence-packet-summary-0001",
      "demo-evidence-exposure-disclosure-0001",
    ],
    failureModes: [
      "THE_EVIDENCE_RESTS_ON_AN_ALREADY_EXPOSED_LOCKED_SET",
      "NO_FORWARD_EVIDENCE_EXISTS_AT_ALL",
    ],
    disclosure: [
      "EXPLORATORY_REUSE_OF_AN_ALREADY_EXPOSED_LOCKED_SET",
      "NEVER_PRESENTED_AS_FRESH_OUT_OF_SAMPLE_EVIDENCE",
      "A_DETERMINISTIC_REPRODUCTION_CONFIRMS_REPRODUCIBILITY_AND_NOTHING_ELSE",
    ],
    missing: [],
    trialCount: LINEAGE_BUDGET.consumed,
    criteria: [
      {
        criterion: "EXPECTANCY_IMPROVES_AGAINST_THE_NAMED_BASELINE_UNDER_DISCLOSED_REUSE",
        kind: "SUCCESS",
        verdict: "MET",
      },
      {
        criterion: "THE_VOLUME_CONDITION_REMOVES_MORE_WINNERS_THAN_LOSERS",
        kind: "FAILURE",
        verdict: "NOT_TRIGGERED",
      },
      {
        criterion: "EXPECTANCY_DOES_NOT_IMPROVE_AGAINST_THE_NAMED_BASELINE",
        kind: "FAILURE",
        verdict: "NOT_TRIGGERED",
      },
    ],
  },
  {
    packetId: PACKETS.assembling,
    registration: REGISTRATIONS.unknownHistory,
    champion: CHAMPIONS.peadShort,
    challenger: CHALLENGERS.peadShort,
    module: "PEAD_SHORT",
    state: "ASSEMBLING",
    session: LINEAGE_SESSIONS.packetAssembling,
    proposal: "PROMOTE_THE_SHORT_CHALLENGER_INTO_SHADOW_OPERATION",
    cause: "REPEATED_BORROW_RECALL_BEFORE_TARGET_ON_THE_CHAMPION",
    recommendation: "NO_RECOMMENDATION_IS_MADE_WHILE_THE_EVIDENCE_IS_INCOMPLETE",
    runs: [],
    shadows: [],
    evidence: [],
    failureModes: ["THE_BORROW_FILTER_MAY_REMOVE_MORE_EDGE_THAN_RECALL_RISK"],
    disclosure: [],
    /*
     * §2.9's REFUSALS, NAMED RATHER THAN LEFT TO A READER TO INFER.
     *
     * A packet with incomplete evidence, an unrecorded trial count, no baseline comparison or
     * unevaluated criteria is REFUSED rather than assembled — so this one is `ASSEMBLING` and
     * says which of the four it hit.
     */
    missing: [
      "EVIDENCE_INCOMPLETE",
      "TRIAL_COUNT_UNRECORDED",
      "NO_BASELINE_COMPARISON",
      "CRITERIA_NOT_EVALUATED",
      "EXPOSURE_DISCLOSURE_INCOMPLETE",
    ],
    trialCount: null,
    criteria: [
      {
        criterion: "THE_RECALL_CLUSTER_DISAPPEARS_AND_EXPECTANCY_HOLDS",
        kind: "SUCCESS",
        verdict: null,
      },
      {
        criterion: "THE_FILTER_REMOVES_MORE_EDGE_THAN_RECALL_RISK",
        kind: "FAILURE",
        verdict: null,
      },
    ],
  },
];

export function syntheticGovernancePackets(
  asOf: string,
  days: readonly string[],
): GovernancePacketPayload {
  const items: GovernancePacket[] = PACKET_SPECS.map((spec) => ({
    packet_id: spec.packetId,
    registration_ref: demoRef(spec.registration, "registration", "ENDPOINT"),
    run_refs: refListOf(
      spec.runs.map((id) => demoRef(id, "research_run", "ENDPOINT")),
      "ZERO_OR_MORE",
      asOf,
    ),
    shadow_refs: refListOf(
      spec.shadows.map((id) => demoRef(id, "research_run", "ENDPOINT")),
      "ZERO_OR_MORE",
      asOf,
    ),
    comparison_ref: demoRef(
      `demo-fact-comparison-${spec.challenger}`,
      "source_fact",
      "AUTHORIZED_READ",
    ),
    proposal: demoReason(spec.proposal),
    cause: demoReason(spec.cause),
    evidence_refs: refListOf(
      spec.evidence.map((id) => demoRef(id, "evidence", "AUTHORIZED_READ")),
      "ZERO_OR_MORE",
      asOf,
    ),
    risk_impact: [
      {
        axis: demoReason("OPEN_PLANNED_RISK_IF_THE_PROPOSAL_WERE_TAKEN"),
        value: usd("packet.risk_impact_usd", 0, asOf),
      },
      {
        axis: demoReason("GROSS_SHORT_EXPOSURE_IF_THE_PROPOSAL_WERE_TAKEN"),
        value: percent("packet.risk_impact_pct", 0, asOf),
      },
    ],
    operational_impact: [
      {
        axis: demoReason("ADDITIONAL_CANDIDATES_PER_SESSION"),
        value: count("packet.operational_impact_count", 4, asOf),
      },
      {
        axis: demoReason("ADDITIONAL_REVIEW_LOAD"),
        value: percent("packet.operational_impact_pct", 250, asOf),
      },
    ],
    failure_modes: spec.failureModes.map(demoReason),
    recommendation: demoReason(spec.recommendation),
    trial_count:
      spec.trialCount === null
        ? unavailable(
            "research.trial_count",
            "COUNT",
            "NOT_YET_AVAILABLE",
            "UPSTREAM_INPUT_MISSING",
          )
        : count("research.trial_count", spec.trialCount, asOf),
    exposure_disclosure: spec.disclosure.map(demoReason),
    state: spec.state,
    ...(spec.decision === undefined
      ? {}
      : { decision_ref: demoRef(spec.decision, "decision", "ENDPOINT") }),
    assembled_at: instantValue("packet.assembled_at", instantAt(days, spec.session), asOf),
    strategy_module: demoReason(spec.module),
    champion_version: spec.champion,
    challenger_version: spec.challenger,
    missing_evidence: spec.missing.map(demoReason),
    criteria_evaluation: spec.criteria.map((entry) => ({
      criterion: demoReason(entry.criterion),
      kind: entry.kind,
      outcome:
        entry.verdict === null
          ? { availability: "UNEVALUATED" as const, reason: "NOT_YET_ASSESSED" as const }
          : { availability: "AVAILABLE" as const, reason: "NONE" as const },
      ...(entry.verdict === null ? {} : { verdict: demoReason(entry.verdict) }),
    })),
    decision_authority: demoReason("A_HUMAN_THROUGH_THE_SEPARATELY_GOVERNED_DECISION_PATH"),
  }));

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("ASSEMBLED_AT_DESCENDING"),
      tiebreak: demoReason("PACKET_ID_ASCENDING"),
    },
    packet_states: [...PACKET_STATES],
  };
}

export function syntheticDecisions(
  asOf: string,
  days: readonly string[],
): DecisionRecordPayload {
  const items: DecisionRecord[] = [
    {
      decision_id: DECISIONS.moreEvidence,
      packet_ref: demoRef(PACKETS.reviewed, "packet", "ENDPOINT"),
      outcome: "MORE_EVIDENCE_REQUESTED",
      authority: demoReason("THE_OWNER_AS_THE_GOVERNING_HUMAN"),
      decided_at: instantAt(days, LINEAGE_SESSIONS.decisionOne),
      reasoning_ref: demoRef(
        "demo-evidence-decision-reasoning-0001",
        "evidence",
        "AUTHORIZED_READ",
      ),
      affected_versions: refListOf(
        [
          demoRef(CHAMPIONS.pullback, "strategy_version", "ENDPOINT"),
          demoRef(CHALLENGERS.pullback, "strategy_version", "ENDPOINT"),
        ],
        "ZERO_OR_MORE",
        asOf,
      ),
      immutable: true as const,
      reasoning: [
        demoReason("ONE_LOCKED_SET_EVALUATION_IS_NOT_FORWARD_EVIDENCE"),
        demoReason("A_LONGER_SHADOW_PERIOD_IS_REQUIRED_BEFORE_ANY_FURTHER_STEP"),
      ],
      authorized_action: demoReason("NOTHING_WAS_AUTHORIZED_MORE_EVIDENCE_WAS_REQUESTED"),
    },
    {
      decision_id: DECISIONS.rejected,
      packet_ref: demoRef(PACKETS.rejected, "packet", "ENDPOINT"),
      outcome: "REJECTED",
      authority: demoReason("THE_OWNER_AS_THE_GOVERNING_HUMAN"),
      decided_at: instantAt(days, LINEAGE_SESSIONS.decisionTwo),
      reasoning_ref: demoRef(
        "demo-evidence-decision-reasoning-0002",
        "evidence",
        "AUTHORIZED_READ",
      ),
      affected_versions: refListOf(
        [demoRef(CHALLENGERS.pullback, "strategy_version", "ENDPOINT")],
        "ZERO_OR_MORE",
        asOf,
      ),
      immutable: true as const,
      reasoning: [
        demoReason("AN_ORDER_PRODUCING_STAGE_REQUIRES_SHADOW_EVIDENCE_THAT_DOES_NOT_EXIST"),
        demoReason("A_CHALLENGER_THAT_OUTPERFORMS_IS_A_CHALLENGER_THAT_OUTPERFORMS"),
      ],
      authorized_action: demoReason("NOTHING_WAS_AUTHORIZED_THE_PROPOSAL_WAS_REJECTED"),
    },
  ];

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("DECIDED_AT_DESCENDING"),
      tiebreak: demoReason("DECISION_ID_ASCENDING"),
    },
    /**
     * The full outcome vocabulary, delivered.
     *
     * `APPROVED` is a member and **no record in this demonstration carries it**. The screen
     * states the absence rather than leaving a reader to infer that approvals are impossible
     * — and rather than manufacturing one, which on this screen would read as an approval
     * this project has never given.
     */
    decision_outcomes: [...DECISION_OUTCOMES],
  };
}
