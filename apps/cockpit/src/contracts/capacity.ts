/**
 * `strategy.capacity` — the qualified-model interface and its admission gate, as ADR-0032
 * §D2 accepted it and `read-model-contracts.md` §12.3.3 carries it.
 *
 * **THIS MODULE ADMITS OR REFUSES A CAPACITY VALUE. IT NEVER COMPUTES ONE.** There is no
 * market-impact model here, no calibration, no search executor, no participation assumption
 * and no schedule builder. Evidence a caller supplies is VALIDATED; the model that would
 * produce it does not exist in this repository and is not created by this file.
 *
 * **THE STATE TODAY IS `NOT_YET_AVAILABLE` WITH `UPSTREAM_INPUT_MISSING`**, and it is that
 * because the gate below evaluates today's actual facts and reaches it — not because a
 * screen says so. **G1 is OPEN** and no provider is selected, so no traded-volume history
 * and no price history exists; no impact function and no calibration exists; **G5 is OPEN**,
 * so no borrow history exists; and no strategy runtime exists to determine an overlap set.
 *
 * WHAT CAPACITY IS, AND THE FIVE QUANTITIES IT IS NOT. It is a **cost-degradation-tolerance
 * capacity relative to this version's own observed execution** — how much more capital the
 * version could have pushed before its MODELLED execution cost degraded past its OWN
 * realized baseline by more than the declared tolerance. **Poor observed execution
 * mechanically raises the reported number**, so it is **not comparable across versions of
 * differing execution quality**, and it is **not a profitability capacity, not the capital at
 * which the strategy stops making money, not a liquidity ceiling and not a risk or allocation
 * limit**. It is never filled from strategy capital, buying power, available cash, gross
 * exposure or any limit (§D2.4), and **per-version capacities are never summed into a
 * portfolio capacity** (§D2.9).
 */
import { z } from "zod";

import { reasonCoded } from "./values";
import type {
  AvailabilityState,
  DataProvenance,
  FieldReasonCode,
  InformationProfile,
} from "./vocabularies";

/**
 * The nine required inputs of §D2.7, as closed codes.
 *
 * They are a closed list because "every applicable input" has to be checkable: a gate that
 * accepted an open-ended bag could admit a value while something nobody named was missing.
 */
export const CAPACITY_REQUIRED_INPUTS = [
  "PER_SECURITY_TRADED_VOLUME_HISTORY",
  "PER_SECURITY_PRICE_HISTORY",
  "RECORDED_ORDER_AND_FILL_HISTORY",
  "DECLARED_PARTICIPATION_LIMIT",
  "DECLARED_EXECUTION_HORIZON",
  "MARKET_IMPACT_FUNCTION",
  "DECLARED_COST_TOLERANCE",
  "BORROW_AVAILABILITY_HISTORY",
  "PORTFOLIO_OVERLAP_SET",
] as const;
export type CapacityRequiredInput = (typeof CAPACITY_REQUIRED_INPUTS)[number];

/**
 * What is true of one required input.
 *
 * `DETERMINED_EMPTY` and `UNDETERMINED` exist because §D2.7 separates them and the
 * separation is the point: *no other version held these securities over this window* is an
 * ANSWER, and it is not the same fact as *nobody looked*. An undetermined overlap set is a
 * missing input; an empty determined one is not.
 */
export type CapacityInputDisposition =
  | "PRESENT"
  | "DETERMINED_EMPTY"
  | "ABSENT"
  | "UNDETERMINED"
  | "NOT_APPLICABLE";

/** Why an input is not satisfied, for the disclosure carried beside the refusal. */
export const CAPACITY_ABSENCE_CODES = [
  "NO_QUALIFIED_PROVIDER_G1_OPEN",
  "NO_BORROW_HISTORY_G5_OPEN",
  "NO_EXECUTION_RUNTIME",
  "NO_STRATEGY_RUNTIME",
  "NO_CAPACITY_MODEL",
  "NO_CALIBRATION",
  "NOT_DECLARED_BY_A_MODEL",
  "OBSERVED_COST_BASIS_INCOMPARABLE",
  "CAPITAL_TO_SCHEDULE_MAPPING_NOT_DECLARED",
  "SEARCH_RULE_NOT_DECLARED",
  /*
   * NOT AN ABSENCE AT ALL, AND NAMED SO IT IS NOT READ AS ONE.
   *
   * A long-only population has no short-side limb, so borrow history is inapplicable to the
   * request rather than a requirement it fails. Leaving this unexplained would show a reader a
   * blank beside an input and invite them to read it as a gap.
   */
  "NO_SHORT_EXPOSURE_IN_POPULATION",
] as const;
export type CapacityAbsenceCode = (typeof CAPACITY_ABSENCE_CODES)[number];

export interface CapacityInputFact {
  readonly input: CapacityRequiredInput;
  readonly disposition: CapacityInputDisposition;
  /** Named for every absent, undetermined or inapplicable input. Never invented. */
  readonly absence?: CapacityAbsenceCode;
  /** §D2.8: provenance is CARRIED, never assumed. Required of a present input. */
  readonly provenance?: DataProvenance;
  /** The input's own effective instant, in epoch milliseconds. */
  readonly asOfMs?: number;
  /** The input's OWN freshness contract, in seconds. §3.1 governs, per input. */
  readonly maxAgeSeconds?: number;
}

/**
 * A recorded model qualification — §D2.8.
 *
 * **No model qualifies itself, and nothing is qualified by having been looked at.** A
 * qualification is a recorded POSITIVE decision, so `decision` is checked rather than the
 * mere existence of the record.
 */
export interface CapacityQualificationRecord {
  readonly modelIdentity: string;
  readonly calibrationIdentity: string;
  /** The LOCKED evaluation set the model was assessed on. */
  readonly evaluationSet: string;
  /** The window scope the assessment was granted for. */
  readonly windowScope: string;
  readonly assessedOnMs: number;
  /** When the qualification stops being one under its own stated validity. */
  readonly validUntilMs: number;
  /** The human governance decision. Only `ADMITTED` is a qualification. */
  readonly decision: "ADMITTED" | "REFUSED";
}

/** How the model's declared search resolved. §D2.11's search outcomes. */
export type CapacitySearchOutcome =
  | "INTERIOR_MAXIMUM"
  | "ZERO_ONLY_FEASIBLE"
  | "UPPER_ENDPOINT_FEASIBLE"
  | "EMPTY_FEASIBLE_SET";

/**
 * The model's declared search domain — §D2.6.
 *
 * `C*` is **the greatest feasible point the model actually evaluated**, resolved no more
 * finely than the granularity and bounded by the endpoints. **No interpolation between
 * evaluated points and no extrapolation beyond the upper endpoint is evaluated evidence.**
 */
export interface CapacitySearchDeclaration {
  /** The declared grid's lower endpoint, in USD cents. §D2.6 requires it to include zero. */
  readonly lowerEndpointCents: number;
  readonly upperEndpointCents: number;
  /** The declared granularity, in USD cents. The value's real resolution. */
  readonly granularityCents: number;
  /**
   * Monotone non-decreasing, or a declared rule that sweeps the WHOLE declared domain.
   *
   * Stopping at the first infeasible point on a non-monotone function returns a different,
   * smaller answer than a full sweep, so the two are NOT interchangeable and the model says
   * which it used. Without one of the two, *the greatest `C`* is ambiguous.
   */
  readonly costFunction: "MONOTONE_NON_DECREASING" | "NON_MONOTONE";
  readonly stoppingRule: "FIRST_INFEASIBLE_POINT" | "FULL_DOMAIN_SWEEP";
  /** Whether the declared domain was actually swept to completion. */
  readonly searchCompleted: boolean;
  /** Declared, or the modelled leg is not a function of `C` at all (§D2.6). */
  readonly capitalToScheduleMapping?: string;
}

/** The BPS basis both cost legs must share, or the comparison is not one. */
export interface CapacityCostBasis {
  readonly referencePrice: string;
  readonly sideConvention: string;
  readonly aggregationMethod: string;
  readonly weighting: string;
}

export interface CapacityEvidence {
  readonly modelIdentity: string;
  readonly calibrationIdentity: string;
  readonly qualification?: CapacityQualificationRecord;
  readonly search: CapacitySearchDeclaration;
  readonly outcome: CapacitySearchOutcome;
  /** The greatest feasible evaluated point, in USD cents. Absent for an empty feasible set. */
  readonly greatestFeasibleCents?: number;
  /** Both legs in BPS hundredths, on ONE basis. §D2.6: BPS against BPS. */
  readonly observedExecutionCostBasis: CapacityCostBasis;
  readonly modelledExecutionCostBasis: CapacityCostBasis;
  readonly costToleranceBpsHundredths: number;
  readonly observedExecutionCostBpsHundredths: number;
  readonly participationLimitHundredths: number;
  readonly executionHorizonSessions: number;
  /** Declared, never inferred. `PUBLIC_PIT` is refused over provider-derived prices. */
  readonly informationProfile: InformationProfile;
}

export interface CapacityRequest {
  /** ONE EXACT strategy version. Area 4 is keyed by it and so is this. */
  readonly strategyVersion: string;
  /** The evaluated window scope, matched against a qualification's own scope. */
  readonly windowScope: string;
  readonly evaluationMs: number;
  /** A capacity producer exists at all. Absent, the answer is `NOT_IMPLEMENTED`. */
  readonly producer: "IMPLEMENTED" | "NOT_IMPLEMENTED";
  readonly authorization: "AUTHORIZED" | "NOT_AUTHORIZED";
  /** §D2.7: input 8 is required ONLY where the evaluated population carries short exposure. */
  readonly shortExposurePresent: boolean;
  readonly inputs: readonly CapacityInputFact[];
  /** Whether volume history covers the window for EVERY security (§D2.12). */
  readonly volumeCoversEverySecurity: boolean;
  /** Whether the evaluated window is fully covered. */
  readonly windowCoverage: "COMPLETE" | "PARTIAL";
  /** Supplied only where a qualified model actually produced one. Never fabricated here. */
  readonly evidence?: CapacityEvidence;
}

/** Why the gate answered as it did — a closed code, for the disclosure beside the value. */
export const CAPACITY_GATE_STAGES = [
  "PRODUCER_EXISTENCE",
  "AUTHORIZATION",
  "REQUIRED_INPUTS",
  "MODEL_QUALIFICATION",
  "FRESHNESS",
  "EXTENT",
  "SEARCH_OUTCOME",
] as const;
export type CapacityGateStage = (typeof CAPACITY_GATE_STAGES)[number];

export interface CapacityGateResult {
  readonly availability: AvailabilityState;
  readonly reason: FieldReasonCode;
  /** The stage that decided the answer. The FIRST unmet condition, never a later one. */
  readonly stage: CapacityGateStage;
  /** The greatest feasible evaluated point in USD cents, or `null` for every absence. */
  readonly valueCents: number | null;
  /** Every required input that is not satisfied, in declared order. */
  readonly missingInputs: readonly CapacityInputFact[];
  /** Inputs the request declared inapplicable, so an absence is not read as a gap. */
  readonly notApplicableInputs: readonly CapacityInputFact[];
  /** `true` where any contributing input is `SYNTHETIC` (§D2.8, criterion 11). */
  readonly synthetic: boolean;
  /** `true` only for a computed zero — a MEASUREMENT, never a substituted absence. */
  readonly computedZero: boolean;
  /** `true` where the value means *at least this much* rather than a resolved maximum. */
  readonly lowerBoundOnly: boolean;
}

/** The declared applicability of one input for one request. */
function isApplicable(input: CapacityRequiredInput, request: CapacityRequest): boolean {
  if (input === "BORROW_AVAILABILITY_HISTORY") {
    return request.shortExposurePresent;
  }
  return true;
}

/** An input is satisfied when it is present, or determined-empty where that is an answer. */
function isSatisfied(fact: CapacityInputFact): boolean {
  return fact.disposition === "PRESENT" || fact.disposition === "DETERMINED_EMPTY";
}

function factFor(
  input: CapacityRequiredInput,
  request: CapacityRequest,
): CapacityInputFact {
  const found = request.inputs.find((fact) => fact.input === input);
  /*
   * AN INPUT NOBODY STATED IS MISSING, NOT ASSUMED PRESENT.
   *
   * A gate that treated silence as satisfaction would admit a value whenever a caller forgot
   * to mention a dependency, which is the failure mode the whole gate exists to prevent.
   */
  return found ?? { input, disposition: "ABSENT" };
}

/**
 * The two cost legs share a basis, or the comparison is not dimensionally one.
 *
 * §D2.6: two legs computed on different reference prices, side conventions, aggregation
 * methods or weightings are NOT comparable, and the value is **refused rather than computed
 * across an incomparable basis**.
 */
function basesAgree(left: CapacityCostBasis, right: CapacityCostBasis): boolean {
  return (
    left.referencePrice === right.referencePrice &&
    left.sideConvention === right.sideConvention &&
    left.aggregationMethod === right.aggregationMethod &&
    left.weighting === right.weighting
  );
}

/**
 * Whether a recorded qualification is a qualification FOR THIS REQUEST.
 *
 * §D2.8: a record that REFUSED the model, one that has EXPIRED under its own stated
 * validity, and one granted for a DIFFERENT model identity, calibration identity, evaluation
 * set or window scope are each **not a qualification for this request**.
 */
function qualificationVerdict(
  record: CapacityQualificationRecord | undefined,
  evidence: CapacityEvidence,
  request: CapacityRequest,
): "QUALIFIED" | "REFUSED" | "NOT_QUALIFIED_HERE" {
  if (record === undefined) {
    return "NOT_QUALIFIED_HERE";
  }
  // A refused model is not an unassessed one, and it is checked before anything else.
  if (record.decision === "REFUSED") {
    return "REFUSED";
  }
  if (record.validUntilMs < request.evaluationMs) {
    return "NOT_QUALIFIED_HERE";
  }
  if (
    record.modelIdentity !== evidence.modelIdentity ||
    record.calibrationIdentity !== evidence.calibrationIdentity ||
    record.windowScope !== request.windowScope
  ) {
    return "NOT_QUALIFIED_HERE";
  }
  return "QUALIFIED";
}

/**
 * The admission gate, evaluated in the DECLARED ORDER, first unmet condition answering.
 *
 * ```text
 * producer existence -> authorization -> every APPLICABLE input -> model qualification
 *   -> freshness -> extent -> the search outcome
 * ```
 *
 * **A missing producer is never reported as a missing input, and a stale input is never
 * reported over an unqualified model** (§D2.11). This is one metric's own admission order
 * and it is not a precedence rule over availability states generally.
 *
 * **NO ABSENCE IS EVER RENDERED AS ZERO.** Every refusal below returns `valueCents: null`.
 * The one zero this function can return is a COMPUTED one — `ZERO_ONLY_FEASIBLE`, meaning no
 * positive evaluated capital level stayed within tolerance — and it is `AVAILABLE`, because
 * a producer that ran and measured zero has answered the question (§D2.11, §4.1.2).
 */
export function capacityGate(request: CapacityRequest): CapacityGateResult {
  const applicable = CAPACITY_REQUIRED_INPUTS.filter((input) => isApplicable(input, request));
  const facts = applicable.map((input) => factFor(input, request));
  const missingInputs = facts.filter((fact) => !isSatisfied(fact));
  const notApplicableInputs = CAPACITY_REQUIRED_INPUTS.filter(
    (input) => !isApplicable(input, request),
  ).map((input) => factFor(input, request));
  /*
   * A SYNTHETIC CONTRIBUTING INPUT MAKES THE RESULT A SYNTHETIC ILLUSTRATION (§D2.8).
   *
   * It is computed over the inputs that were actually satisfied, so the label follows the
   * evidence rather than a caller's assertion about it.
   */
  const synthetic = facts.some(
    (fact) => isSatisfied(fact) && fact.provenance === "SYNTHETIC",
  );

  const refuse = (
    availability: AvailabilityState,
    reason: FieldReasonCode,
    stage: CapacityGateStage,
  ): CapacityGateResult => ({
    availability,
    reason,
    stage,
    valueCents: null,
    missingInputs,
    notApplicableInputs,
    synthetic,
    computedZero: false,
    lowerBoundOnly: false,
  });

  if (request.producer === "NOT_IMPLEMENTED") {
    return refuse("NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED", "PRODUCER_EXISTENCE");
  }
  if (request.authorization === "NOT_AUTHORIZED") {
    return refuse("NOT_AUTHORIZED", "PRODUCER_NOT_AUTHORIZED", "AUTHORIZATION");
  }
  if (missingInputs.length > 0) {
    return refuse("NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING", "REQUIRED_INPUTS");
  }
  /*
   * EVERY APPLICABLE INPUT IS SATISFIED, SO EVIDENCE MUST EXIST TO QUALIFY.
   *
   * Reaching here with no evidence means the model that the inputs describe produced
   * nothing; that is an unassessed model rather than a missing input, and §D2.11 gives it
   * `UNEVALUATED`.
   */
  const evidence = request.evidence;
  if (evidence === undefined) {
    return refuse("UNEVALUATED", "NOT_YET_ASSESSED", "MODEL_QUALIFICATION");
  }
  /*
   * THE DECLARATIONS THE VALUE'S MEANING DEPENDS ON, CHECKED RATHER THAN TRUSTED.
   *
   * Without the capital-to-schedule mapping `modelled_execution_cost(C)` is not a function
   * of `C` at all; a non-monotone cost function stopped at the first infeasible point returns
   * a different, smaller answer than a sweep; an incomplete search resolved no maximum; and
   * two cost legs on different bases are not comparable. Each is refused rather than
   * reported, and each is refused as the required declaration it is (§D2.6).
   */
  const declarationFailure =
    evidence.search.capitalToScheduleMapping === undefined ||
    evidence.search.capitalToScheduleMapping.length === 0 ||
    evidence.search.lowerEndpointCents !== 0 ||
    evidence.search.granularityCents <= 0 ||
    evidence.search.upperEndpointCents < evidence.search.lowerEndpointCents ||
    !evidence.search.searchCompleted ||
    (evidence.search.costFunction === "NON_MONOTONE" &&
      evidence.search.stoppingRule !== "FULL_DOMAIN_SWEEP") ||
    !basesAgree(evidence.observedExecutionCostBasis, evidence.modelledExecutionCostBasis);
  if (declarationFailure) {
    return refuse("NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING", "REQUIRED_INPUTS");
  }

  /*
   * `PUBLIC_PIT` IS NOT REACHABLE FROM PROVIDER-DERIVED PRICE DATA (§D2.8).
   *
   * The profile is declared rather than inferred, and a declaration the contract forbids is
   * refused rather than quietly downgraded to the profile it should have carried.
   *
   * IT IS CHECKED WITH THE OTHER DECLARATIONS, AND NOT AFTER THE QUALIFICATION STAGE. This
   * refusal is a `REQUIRED_INPUTS` one, and §D2.11's declared order puts every applicable
   * input BEFORE model qualification -- so evaluating it later reported an unqualified model
   * over an input-stage refusal that the same order says answers first, and contradicted both
   * `CAPACITY_GATE_STAGES` and this function's own documented order.
   */
  if (evidence.informationProfile === "PUBLIC_PIT") {
    return refuse("NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING", "REQUIRED_INPUTS");
  }

  const verdict = qualificationVerdict(evidence.qualification, evidence, request);
  if (verdict === "REFUSED") {
    return refuse("NOT_AUTHORIZED", "PRODUCER_NOT_AUTHORIZED", "MODEL_QUALIFICATION");
  }
  if (verdict === "NOT_QUALIFIED_HERE") {
    return refuse("UNEVALUATED", "NOT_YET_ASSESSED", "MODEL_QUALIFICATION");
  }

  /*
   * FRESHNESS, per input, against THAT INPUT'S OWN contract, reported for the OLDEST (§3.1).
   *
   * `STALE` carries the value, so it is evaluated after qualification and before extent,
   * exactly where the declared order puts it.
   */
  const stale = facts.some((fact) => {
    if (fact.asOfMs === undefined || fact.maxAgeSeconds === undefined) {
      return false;
    }
    return request.evaluationMs - fact.asOfMs > fact.maxAgeSeconds * 1000;
  });

  /*
   * THE EMPTY FEASIBLE SET IS DECIDED BEFORE EXTENT, because it is not an extent question.
   *
   * It arises only where `observed_execution_cost + cost_tolerance < 0` — the version's own
   * fills beat the reference by more than the tolerance allows, so no non-negative modelled
   * cost can meet the ceiling. The greatest admissible `C` NAMES NOTHING, the value is
   * ABSENT, and it is **never rendered as zero** (§D2.11).
   */
  if (evidence.outcome === "EMPTY_FEASIBLE_SET") {
    return refuse("NOT_APPLICABLE", "NOT_DEFINED_FOR_SUBJECT", "SEARCH_OUTCOME");
  }

  if (!request.volumeCoversEverySecurity) {
    return refuse("INSUFFICIENT_OBSERVATIONS", "BELOW_MINIMUM_OBSERVATIONS", "EXTENT");
  }

  const value = evidence.greatestFeasibleCents;
  if (value === undefined) {
    /*
     * A FEASIBLE OUTCOME WITH NO EVALUATED POINT IS NOT A ZERO.
     *
     * The evidence contradicts itself, so it is refused rather than resolved by substituting
     * the one number §4.1.2 forbids substituting.
     */
    return refuse("NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING", "REQUIRED_INPUTS");
  }

  const computedZero = evidence.outcome === "ZERO_ONLY_FEASIBLE";
  /*
   * A STILL-FEASIBLE UPPER ENDPOINT IS A LOWER BOUND, NOT A MAXIMUM (§D2.11).
   *
   * The search did not resolve an upper boundary, so the value means *at least this much* and
   * is never reported as the greatest capital the version could deploy. A partly covered
   * window is the other route to the same qualification.
   */
  const lowerBoundOnly = evidence.outcome === "UPPER_ENDPOINT_FEASIBLE";
  const partial = lowerBoundOnly || request.windowCoverage === "PARTIAL";

  if (stale) {
    return {
      availability: "STALE",
      reason: "UPSTREAM_INPUT_STALE",
      stage: "FRESHNESS",
      valueCents: value,
      missingInputs,
      notApplicableInputs,
      synthetic,
      computedZero,
      lowerBoundOnly,
    };
  }
  return {
    availability: partial ? "PARTIAL" : "AVAILABLE",
    reason: partial ? "EXTENT_PARTIALLY_COVERED" : "NONE",
    stage: partial ? "EXTENT" : "SEARCH_OUTCOME",
    valueCents: value,
    missingInputs,
    notApplicableInputs,
    synthetic,
    computedZero,
    lowerBoundOnly,
  };
}

/**
 * Today's actual capacity facts for one exact strategy version, in this repository.
 *
 * **THIS IS A STATEMENT OF WHAT IS ABSENT, NOT A CONFIGURATION CHOICE.** Every disposition
 * below is a fact a reader can check against tracked authority: **G1 is OPEN** and no
 * provider is selected, so there is no traded-volume and no price history; there is no
 * execution runtime, so there are no recorded order and fill records; there is no capacity
 * model, so nothing declares a participation limit, an execution horizon, an impact function
 * or a cost tolerance; **G5 is OPEN**, so there is no borrow history; and there is no
 * strategy runtime to determine a portfolio-overlap set.
 *
 * A PRODUCER EXISTS AND IS AUTHORIZED. The producer is this gate — the component asked to
 * produce the field — and it runs, evaluates and answers. `NOT_IMPLEMENTED` on this row
 * asserts that **no producer exists at all**, which is the honest state of `slippage.aggregate`
 * and is not the state of this one: the impact model is required **input 6** and is reported
 * as the missing input it is (§12.3.3's input table, row 6).
 */
export function currentCapacityRequest(args: {
  readonly strategyVersion: string;
  readonly windowScope: string;
  readonly evaluationMs: number;
  readonly shortExposurePresent: boolean;
}): CapacityRequest {
  return {
    strategyVersion: args.strategyVersion,
    windowScope: args.windowScope,
    evaluationMs: args.evaluationMs,
    producer: "IMPLEMENTED",
    authorization: "AUTHORIZED",
    shortExposurePresent: args.shortExposurePresent,
    inputs: [
      {
        input: "PER_SECURITY_TRADED_VOLUME_HISTORY",
        disposition: "ABSENT",
        absence: "NO_QUALIFIED_PROVIDER_G1_OPEN",
      },
      {
        input: "PER_SECURITY_PRICE_HISTORY",
        disposition: "ABSENT",
        absence: "NO_QUALIFIED_PROVIDER_G1_OPEN",
      },
      {
        input: "RECORDED_ORDER_AND_FILL_HISTORY",
        disposition: "ABSENT",
        absence: "NO_EXECUTION_RUNTIME",
      },
      {
        input: "DECLARED_PARTICIPATION_LIMIT",
        disposition: "ABSENT",
        absence: "NOT_DECLARED_BY_A_MODEL",
      },
      {
        input: "DECLARED_EXECUTION_HORIZON",
        disposition: "ABSENT",
        absence: "NOT_DECLARED_BY_A_MODEL",
      },
      {
        input: "MARKET_IMPACT_FUNCTION",
        disposition: "ABSENT",
        absence: "NO_CAPACITY_MODEL",
      },
      {
        input: "DECLARED_COST_TOLERANCE",
        disposition: "ABSENT",
        absence: "NOT_DECLARED_BY_A_MODEL",
      },
      {
        input: "BORROW_AVAILABILITY_HISTORY",
        disposition: args.shortExposurePresent ? "ABSENT" : "NOT_APPLICABLE",
        absence: args.shortExposurePresent
          ? "NO_BORROW_HISTORY_G5_OPEN"
          : "NO_SHORT_EXPOSURE_IN_POPULATION",
      },
      {
        input: "PORTFOLIO_OVERLAP_SET",
        disposition: "UNDETERMINED",
        absence: "NO_STRATEGY_RUNTIME",
      },
    ],
    volumeCoversEverySecurity: false,
    windowCoverage: "PARTIAL",
  };
}

/* ------------------------------------------------- the payload the gate's answer renders as */

/**
 * What a capacity field carries beside its value, whatever the gate answered — ADR-0032 §D2.
 *
 * **IT IS CARRIED IN EVERY STATE, INCLUDING TODAY'S REFUSAL.** "Unavailable" on its own sends
 * a reader to look for a broken producer rather than at a dependency that does not exist, so
 * the stage that decided the answer and every unsatisfied input travel with the field.
 *
 * **THE MEANING TRAVELS WITH IT, BECAUSE THE WORD *CAPACITY* INVITES EVERY READING IT IS
 * NOT.** `baseline` names the quantity plainly — a cost-degradation tolerance against this
 * version's OWN observed execution — and it is carried so a value can never be read as a
 * profitability capacity, a liquidity ceiling, a permitted position size or a scaling
 * permission (§D2.1, §D2.3).
 */
export const capacityDeclaration = z
  .object({
    /** The first unmet gate condition, or the search outcome where every condition held. */
    stage: reasonCoded,
    /** The accepted meaning, named plainly and never abbreviated to "capacity". */
    baseline: reasonCoded,
    /** Every applicable required input that is not satisfied, in declared order. */
    missing_inputs: z.array(z.object({ input: reasonCoded, absence: reasonCoded })),
    /** Inputs this request declared inapplicable, so an absence is not read as a gap. */
    not_applicable_inputs: z.array(z.object({ input: reasonCoded, absence: reasonCoded })),
    /** `true` where a contributing input is `SYNTHETIC` — a synthetic illustration. */
    synthetic_inputs: z.boolean(),
    /** `true` only for a COMPUTED zero. Never set by an absence. */
    computed_zero: z.boolean(),
    /** `true` where the value means *at least this much* rather than a resolved maximum. */
    lower_bound_only: z.boolean(),
    /**
     * The model's own declarations, present only where a qualified model produced a value.
     *
     * ABSENT TODAY, and absent honestly: no model, calibration, qualification, participation
     * limit, execution horizon, cost tolerance or search grid exists to declare.
     */
    model: z
      .object({
        model_identity: z.string().min(1),
        calibration_identity: z.string().min(1),
        qualification_identity: z.string().min(1),
        /*
         * THE MODEL'S DECLARED PARAMETERS ARE DECLARATIONS, NOT MEASUREMENTS.
         *
         * They are carried as declared scalars rather than as `MetricValue`s on purpose: a
         * `MetricValue` asserts a dictionary `metric_id` that was measured under a stated
         * definition, and none of these was measured at all. Registering a dictionary row for
         * each would invent §12.3 entries ADR-0032 did not accept.
         */
        participation_limit_hundredths: z.number().int().nonnegative(),
        execution_horizon_sessions: z.number().int().positive(),
        /** BPS hundredths, on the §12.3.1 reference and side convention. */
        cost_tolerance_bps_hundredths: z.number().int(),
        observed_execution_cost_bps_hundredths: z.number().int(),
        /** USD cents. The grid's real resolution, whatever scale the value renders at. */
        search_lower_endpoint_cents: z.number().int().nonnegative(),
        search_upper_endpoint_cents: z.number().int().nonnegative(),
        search_granularity_cents: z.number().int().positive(),
        stopping_rule: reasonCoded,
        capital_to_schedule_mapping: reasonCoded,
        information_profile: reasonCoded,
      })
      .optional(),
  })
  .superRefine((candidate, ctx) => {
    /*
     * A COMPUTED ZERO AND A LOWER BOUND ARE PROPERTIES OF A VALUE THAT EXISTS.
     *
     * Neither is reachable while a required input is missing, so a payload asserting one
     * beside an unsatisfied input is describing a search that never ran.
     */
    if (candidate.missing_inputs.length > 0 && (candidate.computed_zero || candidate.lower_bound_only)) {
      ctx.addIssue({
        code: "custom",
        message: "a refused capacity reports no search outcome",
      });
    }
    if (candidate.model !== undefined && candidate.missing_inputs.length > 0) {
      ctx.addIssue({
        code: "custom",
        message: "model declarations are carried only where every applicable input is present",
      });
    }
  });
export type CapacityDeclaration = z.infer<typeof capacityDeclaration>;
