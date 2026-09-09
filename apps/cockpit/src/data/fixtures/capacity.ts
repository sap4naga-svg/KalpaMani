/**
 * `strategy.capacity`, answered by the ADR-0032 §12.3.3 admission gate — Areas 4 and 14.
 *
 * **THE ANSWER IS PRODUCED BY THE RULE, NOT WRITTEN BY A SCREEN.** Before ADR-0032 the
 * strategy screen and the research screen each carried a hand-written
 * `NOT_YET_AVAILABLE` / `UPSTREAM_INPUT_MISSING` literal. The rendered state is the same
 * today — because the gate evaluates today's actual facts and reaches exactly that — but it
 * is now reached by evaluating producer existence, authorization and every applicable
 * required input in the declared order, and the declaration beside it names the stage that
 * decided and every dependency that is missing.
 *
 * **ONE DEFINITION, EVERY CONSUMER.** The strategy performance row, the research run and the
 * Area 5 health input all come through here, so `strategy.capacity` cannot mean one thing on
 * one screen and something else on another (§12.2).
 *
 * **NO CAPACITY IS COMPUTED, ESTIMATED, CALIBRATED OR QUALIFIED HERE.** No model exists, no
 * calibration exists, no qualification exists, and no required input exists: **G1 is OPEN**
 * and no provider is selected, **G5 is OPEN**, and there is no execution or strategy runtime.
 */
import type { CapacityDeclaration } from "@/contracts/capacity";
import {
  capacityGate,
  currentCapacityRequest,
  type CapacityGateResult,
  type CapacityInputFact,
  type CapacityRequest,
} from "@/contracts/capacity";
import type { MetricValue } from "@/contracts/values";

import { count, demoReason, qualified, unavailable, usd } from "./common";

/** The gate's own answer, rendered as the two fields a consumer carries. */
export interface CapacityProjection {
  readonly value: MetricValue;
  readonly declaration: CapacityDeclaration;
}

function inputRows(facts: readonly CapacityInputFact[]) {
  return facts.map((fact) => ({
    input: demoReason(fact.input),
    /*
     * AN ABSENCE ALWAYS NAMES ITSELF. A fact reaching here with no absence code is a
     * disposition nobody explained, and `UNEXPLAINED_ABSENCE` says that rather than inventing
     * a plausible reason for it.
     */
    absence: demoReason(fact.absence ?? "UNEXPLAINED_ABSENCE"),
  }));
}

/**
 * Renders one gate answer.
 *
 * **NO ABSENCE IS EVER FILLED WITH ZERO** — and never with strategy capital, buying power,
 * available cash, gross exposure or a limit either (§D2.4). Every refusal below carries no
 * value at all. The one zero this can render is a COMPUTED one, which arrives as
 * `AVAILABLE` because a producer that ran and measured zero has answered the question.
 */
export function renderCapacity(result: CapacityGateResult, asOf: string): CapacityProjection {
  const declaration: CapacityDeclaration = {
    stage: demoReason(result.stage),
    /*
     * THE MEANING, NAMED PLAINLY, IN EVERY STATE.
     *
     * The word *capacity* on its own invites every reading it is not, so the baseline travels
     * with the field: a cost-degradation tolerance measured against THIS VERSION'S OWN
     * observed execution cost (§D2.1).
     */
    baseline: demoReason("COST_DEGRADATION_TOLERANCE_VERSUS_THIS_VERSIONS_OWN_OBSERVED_EXECUTION"),
    missing_inputs: inputRows(result.missingInputs),
    not_applicable_inputs: inputRows(result.notApplicableInputs),
    synthetic_inputs: result.synthetic,
    computed_zero: result.computedZero,
    lower_bound_only: result.lowerBoundOnly,
  };

  if (result.valueCents === null) {
    return {
      value: unavailable(
        "strategy.capacity",
        "USD",
        result.availability as Exclude<
          CapacityGateResult["availability"],
          "AVAILABLE" | "STALE" | "PARTIAL" | "EMPTY_VERIFIED"
        >,
        result.reason,
      ),
      declaration,
    };
  }
  if (result.availability === "AVAILABLE") {
    return { value: usd("strategy.capacity", result.valueCents, asOf), declaration };
  }
  return {
    value: qualified(
      result.availability as "STALE" | "PARTIAL",
      result.reason,
      {
        metricId: "strategy.capacity",
        unit: "USD",
        value: (result.valueCents / 100).toFixed(2),
        asOf,
      },
    ),
    declaration,
  };
}

/**
 * The capacity answer for one exact strategy version, over today's actual facts.
 *
 * `shortExposurePresent` is a fact about the evaluated trade population rather than a
 * setting: §D2.7 requires borrow history **only** where the population carries short
 * exposure, so a long-only version reports that input `NOT_APPLICABLE` and is not blocked by
 * the absence of a record it never needed.
 */
export function capacityFor(args: {
  readonly strategyVersion: string;
  readonly windowScope: string;
  readonly evaluationMs: number;
  readonly shortExposurePresent: boolean;
  readonly asOf: string;
}): CapacityProjection {
  const request: CapacityRequest = currentCapacityRequest(args);
  return renderCapacity(capacityGate(request), args.asOf);
}

/** The count of applicable required inputs a screen may state without recounting the rule. */
export function missingInputCount(
  projection: CapacityProjection,
  asOf: string,
): MetricValue {
  return count("trade.count", projection.declaration.missing_inputs.length, asOf);
}
