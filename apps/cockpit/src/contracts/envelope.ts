/**
 * The shared envelope — `read-model-contracts.md` §3.
 *
 * Every read-model response carries the same envelope. It is not optional and is not
 * stripped for convenience: a response without provenance and availability is a number
 * with no provenance and no availability, which is how a synthetic figure becomes a
 * reported result.
 *
 * SCOPE: the envelope fields the C3 foundation consumes. `schema_version` rejection is
 * load-bearing — an unknown version is REJECTED, never coerced.
 */
import { z } from "zod";

import { freshnessReport } from "./freshness";
import {
  availabilityState,
  completeness,
  dataClassification,
  dataProvenance,
  environment,
  fieldReasonCode,
  maturityStage,
} from "./vocabularies";
import type { Environment, MaturityStage } from "./vocabularies";
import { instant, refList, safeId } from "./values";
import { validityFailure } from "./validity";

/**
 * The accepted maturity-to-environment mapping (COCKPIT_FEEDBACK_EXTENSION.md 4.1).
 *
 * Transcribed, not invented: `SHADOW` has no order authority and runs in `RESEARCH`;
 * `AUTOMATED_PAPER` is the first order-producing stage and runs in `PAPER`.
 */
export const MATURITY_ENVIRONMENTS: Readonly<Record<MaturityStage, Environment>> = {
  RESEARCH: "RESEARCH",
  SHADOW: "RESEARCH",
  AUTOMATED_PAPER: "PAPER",
  MICRO_LIVE: "LIVE",
  SCALED_LIVE: "LIVE",
};

export const coverage = z.object({
  present: z.number().int().nonnegative(),
  requested: z.number().int().nonnegative(),
});

export const envelopeFields = z.object({
  schema_version: z.string().min(1),
  api_version: z.string().min(1),
  entity_id: safeId,
  correlation_id: safeId,
  source_refs: refList,
  event_time: instant,
  observed_time: instant,
  as_of_time: instant,
  projected_time: instant,
  environment,
  /**
   * "the governance stage of the strategy version involved, WHERE APPLICABLE" (3).
   *
   * Optional because C3 has no strategy version: asserting a stage for a scope that carries
   * no facts would state a governance position nothing has reached. A payload-bearing
   * response must carry one, and the refinement below requires it.
   */
  maturity_stage: maturityStage.optional(),
  provenance: dataProvenance,
  availability: availabilityState,
  availability_reason: fieldReasonCode,
  freshness: freshnessReport,
  coverage,
  completeness,
  snapshot_version: z.string().min(1),
  classification: dataClassification,
  access_scope: z.string().min(1),
  metric_definition_version: z.string().min(1),
});

/**
 * Builds the envelope schema for one payload type. A payload never repeats an envelope field.
 *
 * The §4.1.1 matrix governs the envelope's own axes exactly as it governs a field's: a
 * value-bearing `availability` CARRIES its payload, and every other state carries NONE. A
 * read model whose producing subsystem does not exist is present, `NOT_IMPLEMENTED`, and
 * PAYLOADLESS -- never a skeleton payload of zeros standing in for a producer that has
 * never run.
 */
export function envelope<T extends z.ZodTypeAny>(payload: T, schemaVersion: string) {
  return envelopeFields
    .extend({ payload: payload.optional() })
    .superRefine((candidate, ctx) => {
      if (candidate.schema_version !== schemaVersion) {
        ctx.addIssue({
          code: "custom",
          message: `unknown schema_version ${candidate.schema_version}: expected ${schemaVersion}`,
        });
      }
      const failure = validityFailure(
        candidate.availability,
        candidate.availability_reason,
        candidate.payload !== undefined,
      );
      if (failure !== null) {
        ctx.addIssue({ code: "custom", message: failure });
      }
      if (candidate.payload !== undefined && candidate.maturity_stage === undefined) {
        ctx.addIssue({
          code: "custom",
          message: "a payload-bearing response states the maturity stage it was produced at",
        });
      }
      /*
       * THE FIVE AXES STAY SEPARATE (ADR-0027 5), and two of them are checked against the
       * accepted mapping here: COCKPIT_FEEDBACK_EXTENSION.md 4.1 maps RESEARCH and SHADOW
       * onto the RESEARCH runtime environment, AUTOMATED_PAPER onto PAPER, and MICRO_LIVE
       * and SCALED_LIVE onto LIVE. A record carrying `maturity_stage: RESEARCH` under a
       * PAPER or LIVE environment is a combination the mapping does not admit -- which is
       * exactly what a scope selector produces when it relabels one record's badge.
       */
      const permitted = MATURITY_ENVIRONMENTS[candidate.maturity_stage ?? "RESEARCH"];
      if (candidate.maturity_stage !== undefined && permitted !== candidate.environment) {
        ctx.addIssue({
          code: "custom",
          message:
            `maturity stage ${candidate.maturity_stage} is produced in the ` +
            `${permitted} environment, not in ${candidate.environment}`,
        });
      }
    });
}

export type EnvelopeOf<T> = z.infer<typeof envelopeFields> & { payload?: T };
