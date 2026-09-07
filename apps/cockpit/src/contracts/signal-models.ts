/**
 * The signals read models — `read-model-contracts.md` §4.5 *Signals*.
 *
 * `CandidateFunnel`, `CandidateSummary`, `CandidateDetail` and `MissedOpportunity`, transcribed
 * from their payload contracts and given the cross-field rules their invariants require.
 *
 * FOUR INVARIANTS ARE ENFORCED HERE RATHER THAN TRUSTED TO A VIEW, because a view that forgets
 * one is a screen that states something nobody computed:
 *
 *   THE TWO AXES NEVER MERGE         the eight Brain states and the nine downstream stages are
 *                                    two closed vocabularies on two fields, and no value of one
 *                                    is admitted into the other
 *   NO SIZING REACHES A CANDIDATE    `CandidateIntent` carries no share count, dollar amount,
 *                                    position size, order type, route or broker identifier, and
 *                                    the exclusion is STRUCTURAL — the refinement below refuses
 *                                    a USD or SHARES unit anywhere in a candidate payload
 *   AI NEVER RESTORES A CANDIDATE    AI evidence may remove a candidate and may never restore
 *                                    one, so a `BLOCKED_*` state is never explained away by an
 *                                    AI reference and `READY_FOR_RISK_REVIEW` never cites one
 *                                    as the reason a block was cleared
 *   NO RATE WITHOUT A POPULATION     a false-positive or false-negative rate requires a defined
 *                                    evaluable population, and is refused without one
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { collectionPayload } from "./pagination";
import {
  instant,
  metricOf,
  reasonCoded,
  ref,
  refList,
  safeId,
  series,
  versionPins,
} from "./values";
import { isValueBearing } from "./validity";
import {
  BRAIN_DECISION_STATES,
  DOWNSTREAM_STAGES,
  availabilityState,
  fieldReasonCode,
} from "./vocabularies";
import { analysisWindow, securityIdentity } from "./portfolio-models";

/* ================================================================ the two axes */

/**
 * ADR-0026's eight Brain decision states — **consumed, never extended** (§2.6).
 *
 * The array lives in `vocabularies.ts` beside every other closed vocabulary; the enum is built
 * here so exactly one spelling of the eight exists in the application.
 */
export const brainDecisionState = z.enum(BRAIN_DECISION_STATES);
export type BrainDecisionState = z.infer<typeof brainDecisionState>;

/** §2.7 — a SEPARATE axis, owned by the portfolio, risk and execution layers. */
export const downstreamStageValue = z.enum(DOWNSTREAM_STAGES);
export type DownstreamStageValue = z.infer<typeof downstreamStageValue>;

/** The five states that are a BLOCK. A block is never cleared by AI evidence (§14.3). */
export const BLOCKED_STATES = [
  "BLOCKED_DATA",
  "BLOCKED_EVENT",
  "BLOCKED_AI",
  "BLOCKED_CONTRADICTION",
  "BLOCKED_BORROW",
] as const satisfies readonly BrainDecisionState[];

export function isBlockedState(state: BrainDecisionState): boolean {
  return (BLOCKED_STATES as readonly BrainDecisionState[]).includes(state);
}

/**
 * The units a candidate payload may never carry.
 *
 * The Brain specification's §6.2 forbids `CandidateIntent` from carrying a share count, a dollar
 * amount or a final position size, and requires the exclusion to be a property of the type. A
 * closed list of field names would only forbid the spellings somebody thought of; forbidding the
 * UNITS refuses the quantity itself, whatever a later author decides to call it.
 */
const FORBIDDEN_CANDIDATE_UNITS = ["USD", "SHARES"] as const;

/** Walks a parsed payload and reports the first forbidden unit it carries, or `null`. */
export function forbiddenCandidateUnit(value: unknown): string | null {
  if (Array.isArray(value)) {
    for (const entry of value) {
      const found = forbiddenCandidateUnit(entry);
      if (found !== null) {
        return found;
      }
    }
    return null;
  }
  if (value === null || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const unit = record.unit;
  if (
    typeof unit === "string" &&
    (FORBIDDEN_CANDIDATE_UNITS as readonly string[]).includes(unit)
  ) {
    return unit;
  }
  // A `Money` object carries no `unit` key at all, and is refused on its own shape.
  if (typeof record.amount === "string" && record.currency === "USD") {
    return "USD";
  }
  for (const entry of Object.values(record)) {
    const found = forbiddenCandidateUnit(entry);
    if (found !== null) {
      return found;
    }
  }
  return null;
}

/* ============================================================== CandidateFunnel */

/**
 * What one funnel stage COUNTS.
 *
 * §4.5 names four stages and does not say what each one counts, and the difference is
 * load-bearing: a security that qualifies through four modules is **one economic opportunity
 * with four pieces of evidence** (Brain specification §8), so the generated stage counts
 * DECISIONS while the eligible stage counts SECURITIES. A funnel that reports both under one
 * word tells a reader that consolidation lost opportunities it never had.
 *
 * ADDITIVE, and documented: without it, the four counts read as one decreasing population.
 */
export const FUNNEL_SUBJECTS = ["SECURITIES", "CANDIDATE_DECISIONS", "CANDIDATES"] as const;
export const funnelSubject = z.enum(FUNNEL_SUBJECTS);
export type FunnelSubject = z.infer<typeof funnelSubject>;

export const FUNNEL_STAGES = ["UNIVERSE", "ELIGIBLE", "GENERATED", "CONSOLIDATED"] as const;
export const funnelStageName = z.enum(FUNNEL_STAGES);

export const funnelStage = z.object({
  stage: funnelStageName,
  /** What this count counts. Two stages counting different subjects never subtract. */
  subject: funnelSubject,
  count: metricOf("funnel.stage_count"),
  /** How the stage's population was defined, as a closed code rather than as free text. */
  definition: reasonCoded,
});

/**
 * One reason and how many times it OCCURRED.
 *
 * `overlapping` is additive and load-bearing: a candidate may carry several blocking reasons, so
 * the reason counts of one state can sum past that state's candidate count. A distribution that
 * does not say so is read as a partition.
 */
export const funnelReasonCount = z.object({
  code: reasonCoded,
  count: metricOf("funnel.reason_count"),
  overlapping: z.boolean(),
});

export const funnelBrainEntry = z.object({
  state: brainDecisionState,
  /** CANDIDATES, never decisions and never reason occurrences. */
  count: metricOf("funnel.state_count"),
  reasons: z.array(funnelReasonCount),
});

/**
 * §4.5: "every downstream member is `NOT_IMPLEMENTED` in V1".
 *
 * The count is carried and is an absence, so the axis is visibly present and visibly empty
 * rather than omitted — which is what keeps the two axes side by side without merging them.
 */
export const funnelDownstreamEntry = z.object({
  stage: downstreamStageValue,
  count: metricOf("funnel.state_count"),
  availability: availabilityState,
  reason: fieldReasonCode,
});

/**
 * One conversion, with BOTH of its counts and BOTH of their subjects.
 *
 * §4.5 declares `{ from, to, rate }`. A rate whose denominator a reader cannot see is a number
 * they cannot check, and a rate between two stages counting DIFFERENT subjects is not a
 * conversion at all — so the numerator, the denominator, their subjects and whether the two are
 * comparable travel with the rate. ADDITIVE, and documented.
 */
export const funnelConversion = z
  .object({
    from: reasonCoded,
    to: reasonCoded,
    rate: metricOf("funnel.conversion_rate"),
    numerator: metricOf("funnel.stage_count"),
    denominator: metricOf("funnel.stage_count"),
    from_subject: funnelSubject,
    to_subject: funnelSubject,
    /** `false` where the two stages count different subjects. The rate is then refused. */
    comparable: z.boolean(),
  })
  .superRefine((candidate, ctx) => {
    if (candidate.from_subject !== candidate.to_subject && candidate.comparable) {
      ctx.addIssue({
        code: "custom",
        message: "two stages counting different subjects are not comparable",
      });
    }
    if (!candidate.comparable && isValueBearing(candidate.rate.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "an incomparable conversion carries no rate",
      });
    }
    const denominator = candidate.denominator.value;
    if (denominator === 0 && isValueBearing(candidate.rate.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "a zero denominator yields no rate, and never a sentinel",
      });
    }
  });

/** One strategy module's own funnel, so a per-strategy view is a projection and not a filter. */
export const funnelStrategyView = z.object({
  strategy_module: reasonCoded,
  strategy_version: safeId,
  stages: z.array(funnelStage),
  brain_axis: z.array(funnelBrainEntry),
});

export const candidateFunnelPayload = z
  .object({
    window: analysisWindow,
    /** The universe definition this funnel was computed over. Stated, never assumed. */
    scope: reasonCoded,
    population: reasonCoded,
    stages: z.array(funnelStage),
    brain_axis: z.array(funnelBrainEntry),
    downstream_axis: z.array(funnelDownstreamEntry),
    conversion: z.array(funnelConversion),
    strategy_views: z.array(funnelStrategyView),
    /** How many candidate decisions the reason distribution was drawn over. */
    decision_count: metricOf("funnel.stage_count"),
  })
  .superRefine((candidate, ctx) => {
    const states = candidate.brain_axis.map((entry) => entry.state);
    if (new Set(states).size !== states.length) {
      ctx.addIssue({ code: "custom", message: "each Brain state appears once on the axis" });
    }
    /*
     * THE EIGHT RENDER AS A CLOSED SET.
     *
     * A funnel that lists only the states something landed in teaches a reader that the other
     * states do not exist. Every one of the eight is present, and a state nothing reached
     * carries a measured zero -- which ADR-0029 2.1 makes a RESULT rather than an absence.
     */
    if (states.length !== BRAIN_DECISION_STATES.length) {
      ctx.addIssue({
        code: "custom",
        message: "the eight Brain states render as a closed set, including the empty ones",
      });
    }
    const stages = candidate.downstream_axis.map((entry) => entry.stage);
    if (stages.length !== DOWNSTREAM_STAGES.length) {
      ctx.addIssue({
        code: "custom",
        message: "the downstream axis renders every stage it declares a vocabulary for",
      });
    }
    /*
     * 4.5: "every downstream member is NOT_IMPLEMENTED in V1". The two axes are presented side
     * by side and are NEVER MERGED, and a downstream count that appeared would be the first
     * step of merging them.
     */
    for (const entry of candidate.downstream_axis) {
      if (isValueBearing(entry.availability)) {
        ctx.addIssue({
          code: "custom",
          message: "no downstream stage carries a count while its producer does not exist",
        });
      }
    }
    const seenStages = candidate.stages.map((stage) => stage.stage);
    if (seenStages.length !== FUNNEL_STAGES.length) {
      ctx.addIssue({ code: "custom", message: "every funnel stage is reported" });
    }
    /*
     * THE BRAIN AXIS PARTITIONS THE CONSOLIDATED STAGE.
     *
     * Every consolidated candidate has exactly one Brain state, so the axis sums to that
     * stage's count. A funnel whose axis does not add up is a funnel whose reader cannot use
     * either number.
     */
    const consolidated = candidate.stages.find((stage) => stage.stage === "CONSOLIDATED");
    const axisTotal = candidate.brain_axis.reduce(
      (total, entry) => total + (typeof entry.count.value === "number" ? entry.count.value : 0),
      0,
    );
    if (
      consolidated !== undefined &&
      typeof consolidated.count.value === "number" &&
      consolidated.count.value !== axisTotal
    ) {
      ctx.addIssue({
        code: "custom",
        message: "the Brain axis partitions the consolidated candidates exactly",
      });
    }
  });
export type CandidateFunnelPayload = z.infer<typeof candidateFunnelPayload>;

export const CANDIDATE_FUNNEL_SCHEMA = "cockpit.candidate_funnel.v1";
export const candidateFunnelEnvelope = envelope(
  candidateFunnelPayload,
  CANDIDATE_FUNNEL_SCHEMA,
);

/* ============================================================= CandidateSummary */

export const candidateSummary = z
  .object({
    candidate_id: safeId,
    security_ref: ref,
    /** EMBEDDED, so a table of reference identifiers is readable (the C5 precedent). */
    security: securityIdentity,
    direction: z.enum(["LONG", "SHORT"]),
    decided_at: instant,
    brain_state: brainDecisionState,
    primary_reason: reasonCoded,
    conviction_band: reasonCoded,
    strategy_module: reasonCoded,
    /** §4.5: "a DownstreamStage or its availability". A token, never a second Brain state. */
    downstream_stage: metricOf("candidate.downstream_stage"),
    detail_ref: ref,
    pins: versionPins,
  })
  .superRefine((candidate, ctx) => {
    const stage = candidate.downstream_stage.value;
    if (
      typeof stage === "string" &&
      !(DOWNSTREAM_STAGES as readonly string[]).includes(stage)
    ) {
      ctx.addIssue({
        code: "custom",
        message: `${stage} is not a downstream stage, and the two axes never merge`,
      });
    }
    const forbidden = forbiddenCandidateUnit(candidate);
    if (forbidden !== null) {
      ctx.addIssue({
        code: "custom",
        message: `a candidate carries no ${forbidden} quantity: sizing is downstream of it`,
      });
    }
  });
export type CandidateSummary = z.infer<typeof candidateSummary>;

export const candidateSummaryPayload = collectionPayload(candidateSummary, {
  window: analysisWindow,
  /** The population these rows were drawn from, so a filtered page is not read as the whole. */
  population: reasonCoded,
});
export type CandidateSummaryPayload = z.infer<typeof candidateSummaryPayload>;

export const CANDIDATE_SUMMARY_SCHEMA = "cockpit.candidate_summary.v1";
export const candidateSummaryEnvelope = envelope(
  candidateSummaryPayload,
  CANDIDATE_SUMMARY_SCHEMA,
);

/* ============================================================== CandidateDetail */

/**
 * One AI evidence reference, with the provenance §4.5 requires ON EACH REFERENCE.
 *
 * "`ai_evidence_refs` RefList required, kind evidence — **with model, prompt and source
 * provenance on each reference**". A `Ref` carries none of that, so the provenance travels
 * beside it in a parallel structure and the `RefList` stays exactly what §4.2 defines.
 *
 * The Brain specification's §14.3 fixes the required set: source provenance, source publish
 * time, model version, prompt version, schema version, confidence and evidence quality.
 */
export const aiEvidenceRecord = z.object({
  reference: ref,
  source: reasonCoded,
  published_at: metricOf("evidence.published_at"),
  observed_at: metricOf("evidence.observed_at"),
  model_version: safeId,
  prompt_version: safeId,
  schema_version: safeId,
  confidence: metricOf("evidence.confidence"),
  quality: metricOf("evidence.quality"),
  /** What the evidence says, as a closed code. **There is no free text in this payload.** */
  finding: reasonCoded,
  /**
   * Whether this evidence REMOVED the candidate.
   *
   * §14.3: AI may remove a candidate and may never restore one. A reference that contributed to
   * a block says so; nothing anywhere says an AI reference cleared one.
   */
  removes_candidate: z.boolean(),
});
export type AiEvidenceRecord = z.infer<typeof aiEvidenceRecord>;

/**
 * The Brain specification's §6.1 risk context, and nothing downstream of it.
 *
 * §4.5 declares `risk_context { initial_planned_risk_basis }`. §6.1 also requires upcoming event
 * flags, a gap-risk estimate, liquidity, and — for a short — the borrow, fee, squeeze and SSR
 * context. Those are ADDITIVE here and are what Area 7 asks the screen to show.
 *
 * **The basis is a PERCENTAGE of the entry reference, not a dollar figure.** It is the distance
 * to invalidation the thesis rests on; turning it into an amount of capital is a risk decision
 * this payload structurally cannot express.
 */
export const candidateRiskContext = z.object({
  initial_planned_risk_basis: metricOf("candidate.invalidation_distance"),
  event_flags: z.array(reasonCoded),
  gap_risk: metricOf("candidate.gap_risk"),
  liquidity_state: metricOf("candidate.liquidity_state"),
  earnings_carry: reasonCoded,
  sector: reasonCoded,
  correlation_cluster: reasonCoded,
});

/** §6.1's short context — required when the direction is SHORT, and absent otherwise. */
export const candidateShortContext = z.object({
  borrow_required: z.boolean(),
  borrow_state: reasonCoded,
  borrow_evidence_ref: ref,
  fee_state: reasonCoded,
  squeeze_state: reasonCoded,
  ssr_state: reasonCoded,
  recall_risk: reasonCoded,
});

export const deterministicEvidence = z.object({
  factor: reasonCoded,
  value: metricOf("candidate.factor_score"),
  pin: safeId,
});

export const candidateDetailPayload = z
  .object({
    candidate_id: safeId,
    security_ref: ref,
    security: securityIdentity,
    direction: z.enum(["LONG", "SHORT"]),
    /** Area 7's identity fields. Additive here; `CandidateSummary` already carries the module. */
    alpha_family: reasonCoded,
    strategy_module: reasonCoded,
    trade_template: reasonCoded,
    decided_at: instant,
    thesis: reasonCoded,
    why_now: reasonCoded,
    /** Area 7 names the entry condition separately from the trigger that fired now. */
    entry_condition: reasonCoded,
    expected_horizon: metricOf("candidate.expected_horizon"),
    rank: metricOf("candidate.rank"),
    rank_population: metricOf("candidate.rank_population"),
    ranking_basis: reasonCoded,
    setup_quality: metricOf("candidate.setup_quality"),
    conviction_band: reasonCoded,
    deterministic_evidence: z.array(deterministicEvidence),
    regime_ref: ref,
    regime_context: reasonCoded,
    ai_evidence_refs: refList,
    /** The provenance §4.5 requires on each AI reference, one record per reference. */
    ai_evidence: z.array(aiEvidenceRecord),
    /** Stated when the AI producer answered nothing at all — an absence, never an empty list. */
    ai_availability: availabilityState,
    ai_reason: fieldReasonCode,
    challenger_objections: refList,
    challenger_findings: z.array(aiEvidenceRecord),
    brain_state: brainDecisionState,
    blocking_reasons: z.array(reasonCoded),
    /** Unresolved disagreements between evidence sources (§8.2). */
    contradictions: z.array(reasonCoded),
    /** Evidence the decision wanted and did not have, each with the state that explains it. */
    evidence_gaps: z.array(
      z.object({
        expected: reasonCoded,
        availability: availabilityState,
        reason: fieldReasonCode,
      }),
    ),
    /** §4.5: the technical stop is a REFERENCE to an invalidation level, and never an order. */
    invalidation_ref: ref,
    risk_context: candidateRiskContext,
    short_context: candidateShortContext.optional(),
    /** Watchlist expiry, where the thesis stands and the entry condition has not fired. */
    expires_at: metricOf("candidate.decided_at").optional(),
    downstream_refs: z.object({ risk_decision: ref, trade: ref }),
    pins: versionPins,
  })
  .superRefine((candidate, ctx) => {
    const forbidden = forbiddenCandidateUnit(candidate);
    if (forbidden !== null) {
      ctx.addIssue({
        code: "custom",
        message: `a candidate carries no ${forbidden} quantity: sizing is downstream of it`,
      });
    }
    if ((candidate.direction === "SHORT") !== (candidate.short_context !== undefined)) {
      ctx.addIssue({
        code: "custom",
        message: "a short candidate carries its short context, and a long candidate carries none",
      });
    }
    /*
     * A DETERMINISTIC FAILURE CANNOT BE RESCUED BY AI (14.3).
     *
     * A blocked candidate has at least one blocking reason, and a candidate the Brain has no
     * deterministic objection to has none. Without this, a screen could show
     * READY_FOR_RISK_REVIEW beside a blocking reason and leave a reader to guess which won.
     */
    if (isBlockedState(candidate.brain_state) && candidate.blocking_reasons.length === 0) {
      ctx.addIssue({
        code: "custom",
        message: "a blocked candidate states the deterministic reason that blocked it",
      });
    }
    if (candidate.brain_state === "READY_FOR_RISK_REVIEW") {
      if (candidate.blocking_reasons.length > 0) {
        ctx.addIssue({
          code: "custom",
          message:
            "READY_FOR_RISK_REVIEW means no deterministic objection stands, so it carries none",
        });
      }
      /*
       * AI MAY REMOVE A CANDIDATE AND MAY NEVER RESTORE ONE.
       *
       * A ready candidate carrying AI evidence that REMOVED it is the exact contradiction 14.3
       * forbids: it would say a block existed and something cleared it.
       */
      for (const record of candidate.ai_evidence) {
        if (record.removes_candidate) {
          ctx.addIssue({
            code: "custom",
            message: "AI evidence never explains a candidate that is no longer blocked",
          });
        }
      }
    }
    /*
     * A BLOCKED_AI CANDIDATE HAS AN AI STORY, AND IT IS NEVER A CLEAN ONE.
     *
     * 7 defines BLOCKED_AI as "required AI evidence is missing, malformed, stale or
     * unschematized", so an AI availability of AVAILABLE under that state describes a producer
     * that answered and a block that has no cause.
     */
    if (candidate.brain_state === "BLOCKED_AI" && candidate.ai_availability === "AVAILABLE") {
      const removing = candidate.ai_evidence.some((record) => record.removes_candidate);
      if (!removing) {
        ctx.addIssue({
          code: "custom",
          message: "BLOCKED_AI names either missing AI evidence or evidence that removed it",
        });
      }
    }
    if (candidate.brain_state === "WATCHLIST" && candidate.expires_at === undefined) {
      ctx.addIssue({
        code: "custom",
        message: "a watchlist candidate states when it expires",
      });
    }
    if (candidate.brain_state === "BLOCKED_CONTRADICTION" && candidate.contradictions.length === 0) {
      ctx.addIssue({
        code: "custom",
        message: "a contradiction block names the contradiction",
      });
    }
    for (const gap of candidate.evidence_gaps) {
      if (isValueBearing(gap.availability)) {
        ctx.addIssue({
          code: "custom",
          message: "an evidence gap is an absence; a value-bearing state is not a gap",
        });
      }
    }
  });
export type CandidateDetailPayload = z.infer<typeof candidateDetailPayload>;

export const CANDIDATE_DETAIL_SCHEMA = "cockpit.candidate_detail.v1";
export const candidateDetailEnvelope = envelope(
  candidateDetailPayload,
  CANDIDATE_DETAIL_SCHEMA,
);

/* ============================================================ MissedOpportunity */

export const COST_TREATMENT_VALUES = ["GROSS", "NET_COMMISSIONS", "NET_ALL_COSTS"] as const;
export const costTreatment = z.enum(COST_TREATMENT_VALUES);

export const PATH_COMPLETENESS = ["COMPLETE", "PARTIAL", "UNKNOWN"] as const;
export const pathCompleteness = z.enum(PATH_COMPLETENESS);

/**
 * The measurement window a counterfactual was registered against.
 *
 * §4.5 requires a window on every counterfactual, and Area 8 makes it contractual: "two
 * counterfactuals with different windows are never compared". The window is REGISTERED — it is
 * declared before the follow-up path is read, so a best-in-hindsight exit cannot be chosen after
 * the fact and presented as a rule.
 */
export const registeredWindow = z.object({
  from: instant,
  to: instant,
  /** Horizon in trading days, so two windows are comparable by their length as well as dates. */
  horizon: metricOf("candidate.expected_horizon"),
  registered_at: metricOf("miss.decided_at"),
  calendar: reasonCoded,
  timezone: z.literal("UTC"),
});

export const missedOpportunity = z
  .object({
    miss_id: safeId,
    candidate_ref: ref,
    security: securityIdentity,
    strategy_module: reasonCoded,
    brain_state: brainDecisionState,
    cause: reasonCoded,
    window: registeredWindow,
    /** Timing, so a delay is a fact rather than a difference a reader computes. */
    detected_at: metricOf("miss.detected_at"),
    decided_at: metricOf("miss.decided_at"),
    expired_at: metricOf("miss.expired_at"),
    decision_delay: metricOf("miss.decision_delay"),
    /**
     * OBSERVED MOVEMENT AFTER THE DECISION. **NOT PROFIT THAT WAS AVAILABLE.**
     *
     * Both excursions are reported. One signed number would hide whichever of them a reader
     * most needs to see.
     */
    favourable_movement: metricOf("miss.favourable_movement"),
    adverse_movement: metricOf("miss.adverse_movement"),
    /** §4.5 `counterfactual` — HYPOTHETICAL, and never in a series with a realized result. */
    counterfactual: metricOf("miss.counterfactual"),
    /**
     * The money limb, which is structurally present and is never served.
     *
     * A dollar counterfactual needs a permitted SIZING BASIS, and sizing is a risk decision no
     * producer here makes. The field exists so the refusal is visible rather than the question
     * being quietly dropped.
     */
    counterfactual_money: metricOf("miss.counterfactual_money"),
    assumptions: z.array(reasonCoded),
    cost_treatment: costTreatment,
    /** Required before any rate is shown. Absent where no evaluable population is defined. */
    population: reasonCoded.optional(),
    price_path_completeness: pathCompleteness,
    /** The observed follow-up path, drawn as marks. Gaps are shown and never interpolated. */
    follow_up_series: series.optional(),
    /** The trade a taken candidate became, where one exists. */
    trade_ref: ref.optional(),
  })
  .superRefine((candidate, ctx) => {
    /*
     * A DOLLAR COUNTERFACTUAL IS NEVER SERVED.
     *
     * Price movement alone is not a position: converting it needs a sizing basis somebody
     * approved, and none exists. The refusal is enforced here so a later fixture cannot fill it
     * in from a share count it happens to have.
     */
    if (isValueBearing(candidate.counterfactual_money.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "a money counterfactual requires an approved sizing basis, and none exists",
      });
    }
    /*
     * AN INCOMPLETE PATH YIELDS `PARTIAL`, NEVER AN OPTIMISTIC COMPLETION (Area 8).
     *
     * Every path-dependent value on this record is derived from the follow-up path, so an
     * incomplete path qualifies all of them.
     */
    const pathDependent = [
      candidate.favourable_movement,
      candidate.adverse_movement,
      candidate.counterfactual,
    ];
    if (candidate.price_path_completeness !== "COMPLETE") {
      for (const metric of pathDependent) {
        if (metric.availability === "AVAILABLE") {
          ctx.addIssue({
            code: "custom",
            message:
              "a path-dependent value over an incomplete path is PARTIAL, never AVAILABLE",
          });
        }
      }
    }
    if (
      candidate.follow_up_series !== undefined &&
      candidate.follow_up_series.completeness === "PARTIAL" &&
      candidate.price_path_completeness === "COMPLETE"
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a partial follow-up series is not reported as a complete price path",
      });
    }
  });
export type MissedOpportunity = z.infer<typeof missedOpportunity>;

/**
 * One arm of a taken-versus-missed comparison.
 *
 * Every dimension that would make two arms incomparable is carried ON the arm: the window, the
 * horizon, the cost treatment, the information profile and the population. A comparison that
 * states only two numbers is a comparison a reader cannot check.
 */
export const comparisonArm = z.object({
  arm: z.enum(["TAKEN", "MISSED"]),
  population: reasonCoded,
  observation_count: metricOf("performance.observation_count"),
  window: registeredWindow,
  cost_treatment: costTreatment,
  information_profile: reasonCoded,
  outcome_basis: reasonCoded,
  /** The arm's own measured value, on the basis it names. */
  outcome: metricOf("miss.counterfactual"),
});

export const takenMissedComparison = z
  .object({
    comparison_id: safeId,
    arms: z.tuple([comparisonArm, comparisonArm]),
    comparable: z.boolean(),
    /** Why not, when not. A refused comparison names its incompatibility. */
    refusal: reasonCoded.optional(),
    /** The difference, present only where the two arms are compatible. */
    difference: metricOf("miss.counterfactual"),
  })
  .superRefine((candidate, ctx) => {
    if (!candidate.comparable) {
      if (candidate.refusal === undefined) {
        ctx.addIssue({
          code: "custom",
          message: "a refused comparison names the incompatibility that refused it",
        });
      }
      if (isValueBearing(candidate.difference.availability)) {
        ctx.addIssue({
          code: "custom",
          message: "two incomparable arms produce no difference",
        });
      }
    }
    const [left, right] = candidate.arms;
    const identical =
      left.cost_treatment === right.cost_treatment &&
      left.window.from === right.window.from &&
      left.window.to === right.window.to &&
      left.information_profile.code === right.information_profile.code &&
      left.outcome_basis.code === right.outcome_basis.code;
    if (candidate.comparable && !identical) {
      ctx.addIssue({
        code: "custom",
        message:
          "arms differing in window, cost treatment, information profile or basis are not " +
          "comparable, whatever the comparison claims",
      });
    }
    if (left.arm === right.arm) {
      ctx.addIssue({ code: "custom", message: "a comparison has one taken and one missed arm" });
    }
  });
export type TakenMissedComparison = z.infer<typeof takenMissedComparison>;

/**
 * A rate over a DEFINED evaluable population, or a refusal.
 *
 * Area 8: "no false-negative rate without a population — a rate requires a defined evaluable
 * population; where none is defined, the view reports the count and refuses the rate."
 */
export const missRate = z
  .object({
    kind: z.enum(["FALSE_POSITIVE", "FALSE_NEGATIVE"]),
    population: reasonCoded.optional(),
    numerator: metricOf("miss.count"),
    denominator: metricOf("miss.count"),
    rate: metricOf("miss.rate"),
    /** Why the population is undefined, when it is. */
    note: reasonCoded.optional(),
  })
  .superRefine((candidate, ctx) => {
    if (candidate.population === undefined && isValueBearing(candidate.rate.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "a rate requires a defined evaluable population",
      });
    }
    if (candidate.population === undefined && candidate.note === undefined) {
      ctx.addIssue({
        code: "custom",
        message: "an undefined population says why it is undefined",
      });
    }
  });

export const missedOpportunityPayload = collectionPayload(missedOpportunity, {
  window: analysisWindow,
  population: reasonCoded,
  /** Recurring causes, as counts of occurrences over the delivered population. */
  cause_patterns: z.array(
    z.object({ cause: reasonCoded, count: metricOf("miss.count"), share: metricOf("miss.rate") }),
  ),
  comparisons: z.array(takenMissedComparison),
  rates: z.array(missRate),
  /** How the counterfactual method was registered, once, for every row on the page. */
  counterfactual_method: reasonCoded,
});
export type MissedOpportunityPayload = z.infer<typeof missedOpportunityPayload>;

export const MISSED_OPPORTUNITY_SCHEMA = "cockpit.missed_opportunity.v1";
export const missedOpportunityEnvelope = envelope(
  missedOpportunityPayload,
  MISSED_OPPORTUNITY_SCHEMA,
);
