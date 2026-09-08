/**
 * The C7 governance payload contracts — `read-model-contracts.md` §4.5, Area 19.
 *
 * **Read-only presentation in V1.** The Cockpit DISPLAYS a packet and a recorded decision; it
 * does not ORIGINATE an approval or a rejection, and **no field on either contract can carry
 * one**. There is no approve, reject, request-more-evidence or release value a producer could
 * set from this application, because this application produces nothing.
 *
 * FOUR THINGS THAT ARE NEVER ONE THING, and the contract keeps them apart:
 *
 *   RECOMMENDATION   what automation assembled. **Input to a human decision, never the
 *                    decision** (§2.9)
 *   READINESS        that the evidence a packet requires is present. `READY_FOR_HUMAN_REVIEW`
 *                    **is not an approval**, and the automation's authority ends exactly there
 *   DECISION         a recorded human act, with authority, time and reasoning, taken through
 *                    the separately governed path that owns approvals (§2.10)
 *   EXECUTION        the promotion a decision authorized, performed by the deterministic
 *                    mechanism that owns it. Nothing here performs, schedules or requests one
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { collectionPayload } from "./pagination";
import { refListFieldOf, refOf } from "./references";
import { instant, metricOf, metricValue, reasonCoded, safeId } from "./values";
import { availabilityState, fieldReasonCode } from "./vocabularies";

/** §4.5 `GovernancePacket.state` — and no further transition is automatic (§2.9). */
export const PACKET_STATES = ["ASSEMBLING", "READY_FOR_HUMAN_REVIEW"] as const;
export const packetState = z.enum(PACKET_STATES);
export type PacketState = z.infer<typeof packetState>;

/** §4.5 `DecisionRecord.outcome`. A human may refuse for any reason, and it is recorded. */
export const DECISION_OUTCOMES = ["APPROVED", "REJECTED", "MORE_EVIDENCE_REQUESTED"] as const;
export const decisionOutcome = z.enum(DECISION_OUTCOMES);
export type DecisionOutcome = z.infer<typeof decisionOutcome>;

export const governancePacket = z
  .object({
    packet_id: safeId,
    /** §4.5 kind `registration`. */
    registration_ref: refOf("GovernancePacket.registration_ref"),
    /** §4.5 kind `research_run` — the authorized runs. */
    run_refs: refListFieldOf("GovernancePacket.run_refs"),
    /** §4.5 kind `research_run` — the SHADOW evidence, kept in its own field. */
    shadow_refs: refListFieldOf("GovernancePacket.shadow_refs"),
    /** §4.5 kind `source_fact` — the Champion comparison this packet rests on. */
    comparison_ref: refOf("GovernancePacket.comparison_ref"),
    proposal: reasonCoded,
    cause: reasonCoded,
    /** §4.5 kind `evidence`. */
    evidence_refs: refListFieldOf("GovernancePacket.evidence_refs"),
    risk_impact: z.array(z.object({ axis: reasonCoded, value: metricValue })),
    operational_impact: z.array(z.object({ axis: reasonCoded, value: metricValue })),
    failure_modes: z.array(reasonCoded),
    /** **INPUT to a human decision, never the decision.** */
    recommendation: reasonCoded,
    /** Read from the registry, and never recounted by a view. */
    trial_count: metricOf("research.trial_count"),
    /** Every reuse the evidence rests on (§2.7.1). */
    exposure_disclosure: z.array(reasonCoded),
    state: packetState,
    /** Present once a human decision has been recorded ELSEWHERE. Kind `decision`. */
    decision_ref: refOf("GovernancePacket.decision_ref").optional(),
    /** ADDITIVE: §5.1 sorts `/governance/packets` by `assembled_at`. */
    assembled_at: metricOf("packet.assembled_at"),
    /** ADDITIVE: §5.1 declares a `module` filter, and a filter needs its field. */
    strategy_module: reasonCoded,
    /** ADDITIVE: the two exact versions the proposal concerns. */
    champion_version: safeId,
    challenger_version: safeId,
    /**
     * ADDITIVE: what the packet is MISSING, named as closed codes.
     *
     * §2.9 refuses to assemble a packet whose evidence is incomplete, whose trial count is
     * unrecorded, which has no baseline comparison or whose criteria are unevaluated. An
     * `ASSEMBLING` packet is one that has hit one of those, and the reader is told which
     * rather than left to compare two screens.
     */
    missing_evidence: z.array(reasonCoded),
    /**
     * ADDITIVE: the registration's own criteria, and whether each was evaluated.
     *
     * `CRITERIA_NOT_EVALUATED` is one of §2.9's refusals, so the evaluation state travels
     * with the packet rather than being inferred from the presence of a result.
     */
    criteria_evaluation: z.array(
      z.object({
        criterion: reasonCoded,
        kind: z.enum(["SUCCESS", "FAILURE"]),
        outcome: z.object({ availability: availabilityState, reason: fieldReasonCode }),
        /** The evaluated verdict, where one exists. Absent while unevaluated. */
        verdict: reasonCoded.optional(),
      }),
    ),
    /**
     * ADDITIVE: the authority a decision on this packet would require.
     *
     * Displayed so a reader knows who takes it. **Naming an authority is not holding one**,
     * and this application offers no way to exercise it.
     */
    decision_authority: reasonCoded,
  })
  .superRefine((candidate, ctx) => {
    if (candidate.champion_version === candidate.challenger_version) {
      ctx.addIssue({
        code: "custom",
        message: "a promotion proposal names two different versions",
      });
    }
    /*
     * A READY PACKET IS COMPLETE, AND AN ASSEMBLING ONE SAYS WHY IT IS NOT (§2.9).
     *
     * "A packet with incomplete evidence, an unrecorded trial count, no baseline comparison or
     * unevaluated criteria is REFUSED rather than assembled." `READY_FOR_HUMAN_REVIEW` with
     * something still missing is precisely the packet that rule refuses, and it would put an
     * incomplete case in front of a person under a label that says it is complete.
     */
    if (candidate.state === "READY_FOR_HUMAN_REVIEW" && candidate.missing_evidence.length > 0) {
      ctx.addIssue({
        code: "custom",
        message: "a packet ready for human review is missing nothing it requires",
      });
    }
    if (candidate.state === "ASSEMBLING" && candidate.missing_evidence.length === 0) {
      ctx.addIssue({
        code: "custom",
        message: "an assembling packet names what it is still waiting for",
      });
    }
    /*
     * A READY PACKET HAS ITS TRIAL COUNT (§2.9 `TRIAL_COUNT_UNRECORDED`).
     *
     * The count is READ FROM THE REGISTRY, and a packet that could not read it has not met
     * the precondition for review.
     */
    if (
      candidate.state === "READY_FOR_HUMAN_REVIEW" &&
      candidate.trial_count.value === undefined
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a packet ready for human review carries the trial count it read",
      });
    }
    /*
     * EVERY CRITERION OF A READY PACKET HAS BEEN EVALUATED (§2.9 `CRITERIA_NOT_EVALUATED`).
     */
    if (candidate.state === "READY_FOR_HUMAN_REVIEW") {
      for (const entry of candidate.criteria_evaluation) {
        const evaluated = ["AVAILABLE", "STALE", "PARTIAL", "EMPTY_VERIFIED"].includes(
          entry.outcome.availability,
        );
        if (!evaluated || entry.verdict === undefined) {
          ctx.addIssue({
            code: "custom",
            message: "a packet ready for human review has evaluated every stated criterion",
          });
          return;
        }
      }
      /* A hypothesis that cannot fail has not been stated, and neither has this packet. */
      if (!candidate.criteria_evaluation.some((entry) => entry.kind === "FAILURE")) {
        ctx.addIssue({
          code: "custom",
          message: "a packet ready for human review evaluates at least one failure criterion",
        });
      }
    }
  });
export type GovernancePacket = z.infer<typeof governancePacket>;

export const governancePacketPayload = collectionPayload(governancePacket, {
  packet_states: z.array(packetState),
});
export type GovernancePacketPayload = z.infer<typeof governancePacketPayload>;

export const GOVERNANCE_PACKET_SCHEMA = "cockpit.governance_packet.v1";
export const governancePacketEnvelope = envelope(
  governancePacketPayload,
  GOVERNANCE_PACKET_SCHEMA,
);

/**
 * `DecisionRecord` — §4.5, Area 19.
 *
 * **The Cockpit displays this decision and does not originate it in V1.** The authoritative
 * record stays with the separately governed decision path that owns approvals, and this
 * contract is a projection of it.
 */
export const decisionRecord = z.object({
  decision_id: safeId,
  /** §4.5 kind `packet`. */
  packet_ref: refOf("DecisionRecord.packet_ref"),
  outcome: decisionOutcome,
  authority: reasonCoded,
  decided_at: instant,
  /** §4.5 kind `evidence`. */
  reasoning_ref: refOf("DecisionRecord.reasoning_ref"),
  /** §4.5 kind `strategy_version`. */
  affected_versions: refListFieldOf("DecisionRecord.affected_versions"),
  /** Always true. A decision that could be edited is not a record of what was decided. */
  immutable: z.literal(true),
  /**
   * ADDITIVE: the reasoning, as closed codes.
   *
   * `reasoning_ref` names an evidence artefact §5 catalogues no endpoint for, so a screen
   * carrying only the reference can render nothing at all. These are the recorded reasons,
   * in the same closed-vocabulary shape every other reason on every other screen uses.
   */
  reasoning: z.array(reasonCoded),
  /**
   * ADDITIVE: what the decision authorized, where it authorized anything.
   *
   * **A recorded decision in this application is a displayed fact and authorizes nothing
   * here**: no promotion, activation, capital change or release follows from rendering one,
   * and no mechanism exists that could act on it.
   */
  authorized_action: reasonCoded,
});
export type DecisionRecord = z.infer<typeof decisionRecord>;

export const decisionRecordPayload = collectionPayload(decisionRecord, {
  decision_outcomes: z.array(decisionOutcome),
});
export type DecisionRecordPayload = z.infer<typeof decisionRecordPayload>;

export const DECISION_RECORD_SCHEMA = "cockpit.decision_record.v1";
export const decisionRecordEnvelope = envelope(
  decisionRecordPayload,
  DECISION_RECORD_SCHEMA,
);
