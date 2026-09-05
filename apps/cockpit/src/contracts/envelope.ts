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
import { instant, refList, safeId } from "./values";
import { validityFailure } from "./validity";

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
  maturity_stage: maturityStage,
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
    });
}

export type EnvelopeOf<T> = z.infer<typeof envelopeFields> & { payload?: T };
