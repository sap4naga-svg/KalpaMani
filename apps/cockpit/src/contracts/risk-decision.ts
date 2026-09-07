/**
 * `RiskDecision` — the downstream record that says WHY THIS SIZE, and never why the
 * opportunity exists.
 *
 * `read-model-contracts.md` §4.3 resolves a `risk_decision` reference to
 * `RiskSnapshot.decisions[]` under an `AUTHORIZED_READ` on `risk:read`, and §4.4 already
 * defines every quantity such a decision assigns — `InitialPlannedRisk` for the retained
 * entry-time record and `CurrentOpenPlannedRisk` for a later assessment. The accepted
 * `decisions[]` entry carries `{ decision_ref, at, outcome }`: enough to INDEX a decision and
 * not enough to EXPLAIN one. This record is the resolved target of that reference, assembled
 * from the accepted §4.4 vocabulary rather than from a new one, and it is **additive and
 * documented** under §12.6 in exactly the way `funnel.numerator`, `funnel.denominator`,
 * `referencePrice.price` and `funnelReasonCount.overlapping` already are.
 *
 * WHAT IT IS, AND WHAT IT IS NOT.
 *
 *   A FIXTURE OUTPUT, NOT AN ENGINE     nothing here computes a size, applies a policy,
 *                                       permits an exposure or grants an authority. The
 *                                       records are immutable repository-owned declarations,
 *                                       and the builder REFUSES an incoherent one rather than
 *                                       deriving a coherent one
 *   DOWNSTREAM, AND STRUCTURALLY SO     `COCKPIT_FEEDBACK_EXTENSION.md` §3 gives sizing to the
 *                                       portfolio and risk layer. A Trade Detail may JOIN this
 *                                       record by reference; `CandidateIntent` never acquires
 *                                       a field of it, and `CandidateDetail` resolves the
 *                                       reference to an OUTCOME CODE carrying no quantity
 *   NOT AN APPROVAL TO TRADE            an approved decision records that a size was assigned
 *                                       under a named policy version. It authorizes nothing,
 *                                       and no order was ever sent
 *
 * THE ARITHMETIC IS CHECKED, NOT ASSERTED. §4.4 defines a stage's retained risk as its own
 * shares against its own reference and invalidation prices, so an approved decision must
 * reproduce the retained record it points at, to the cent. `riskDecisionRecord` refuses a
 * declaration that does not — a declared number nobody checks is how a fixture starts
 * teaching a reader something untrue.
 */
import { z } from "zod";

import { isValueBearing } from "./validity";
import { instant, metricOf, policyRef, reasonCoded, ref, safeId } from "./values";

/** APPROVED assigns a size. REJECTED assigns none. There is no third outcome that sizes. */
export const RISK_DECISION_OUTCOMES = ["APPROVED", "REJECTED"] as const;
export const riskDecisionOutcome = z.enum(RISK_DECISION_OUTCOMES);
export type RiskDecisionOutcome = z.infer<typeof riskDecisionOutcome>;

/**
 * The size that was assigned, and the two prices it was assigned against.
 *
 * All three travel together because a share count on its own cannot be checked: the risk a
 * decision assigned is `shares x |reference - invalidation|`, and a reader shown only the
 * first number is shown a figure they cannot verify.
 */
export const riskSizing = z.object({
  shares: metricOf("risk_decision.shares"),
  reference_price: metricOf("risk_decision.reference_price"),
  invalidation_price: metricOf("risk_decision.invalidation_price"),
  notional: metricOf("risk_decision.notional"),
});
export type RiskSizing = z.infer<typeof riskSizing>;

export const riskDecision = z
  .object({
    decision_id: safeId,
    /** The candidate this decision was taken on. */
    candidate_ref: ref,
    /**
     * The trade it produced, where one exists.
     *
     * A REJECTED decision produced none, and its reference resolves to nothing rather than to
     * a fallback entity.
     */
    trade_ref: ref,
    decided_at: instant,
    outcome: riskDecisionOutcome,
    /** The closed code that says what was decided. Never free text. */
    outcome_reason: reasonCoded,
    /** Why it was declined. Empty on an approval, and never empty on a rejection. */
    rejection_reasons: z.array(reasonCoded),
    assigned_risk: metricOf("risk_decision.assigned_risk"),
    assigned_risk_pct: metricOf("risk_decision.assigned_risk_pct"),
    sizing: riskSizing,
    /** The policy version that produced the decision. A size never appears without one. */
    risk_policy_ref: policyRef,
    /**
     * The retained §4.4 initial-risk stage this decision is traceable to.
     *
     * An approval names the stage record whose risk it assigned; a rejection retained no
     * record, because nothing was ever entered.
     */
    initial_risk_ref: ref,
    source: z.literal("RISK_ENGINE_DECISION_RECORD"),
  })
  .superRefine((candidate, ctx) => {
    const sized =
      isValueBearing(candidate.sizing.shares.availability) &&
      isValueBearing(candidate.assigned_risk.availability);
    if (candidate.outcome === "APPROVED") {
      if (!sized) {
        ctx.addIssue({
          code: "custom",
          message: "an approved risk decision states the size and the risk it assigned",
        });
      }
      if (candidate.rejection_reasons.length > 0) {
        ctx.addIssue({
          code: "custom",
          message: "an approved risk decision carries no rejection reason",
        });
      }
      if (
        typeof candidate.sizing.shares.value === "number" &&
        candidate.sizing.shares.value <= 0
      ) {
        ctx.addIssue({
          code: "custom",
          message: "an approved risk decision assigns a positive number of shares",
        });
      }
    }
    /*
     * A REJECTION ASSIGNS NOTHING.
     *
     * A declined decision that still carried a share count would be recording a size nobody
     * was permitted to take, and a screen joining it would show the position that was refused
     * as though it existed.
     */
    if (candidate.outcome === "REJECTED") {
      if (isValueBearing(candidate.sizing.shares.availability)) {
        ctx.addIssue({
          code: "custom",
          message: "a declined risk decision assigns no size",
        });
      }
      if (isValueBearing(candidate.assigned_risk.availability)) {
        ctx.addIssue({
          code: "custom",
          message: "a declined risk decision assigns no risk",
        });
      }
      if (candidate.rejection_reasons.length === 0) {
        ctx.addIssue({
          code: "custom",
          message: "a declined risk decision names why it declined",
        });
      }
      if (candidate.initial_risk_ref.resolution !== "UNRESOLVABLE_V1") {
        ctx.addIssue({
          code: "custom",
          message: "a declined decision retained no initial-risk record to point at",
        });
      }
    }
  });
export type RiskDecision = z.infer<typeof riskDecision>;
