/**
 * Admission — `read-model-contracts.md` §2.4 and §7.1.
 *
 * Classification is a SENSITIVITY LABEL; publication is a SEPARATE recorded authorization.
 * A `PUBLIC_SAFE` label does not authorize publication, and uncertain classification FAILS
 * CLOSED.
 *
 * The C3 foundation runs at `PUBLIC_EDGE` and admits exactly what §7.1 permits:
 * `PUBLIC_SAFE` payloads with `SYNTHETIC` or `REPOSITORY_TRACKED` provenance, and
 * `REPOSITORY_TRACKED` only from the enumerated governance read models.
 */
import type { DataClassification, DataProvenance, HostingBoundary } from "./vocabularies";

/**
 * §7.1: the read models whose `REPOSITORY_TRACKED` facts resolve to tracked sources already
 * published in this public repository. Nothing else, and no other provenance.
 */
export const REPOSITORY_TRACKED_READ_MODELS = [
  "QualificationStatus",
  "AttentionItem",
  "WhatChangedEntry",
  "SearchResultPage",
  "MaturityStatus",
] as const;
export type RepositoryTrackedReadModel = (typeof REPOSITORY_TRACKED_READ_MODELS)[number];

export interface AdmissionRequest {
  readonly readModel: string;
  readonly classification: DataClassification;
  readonly provenance: DataProvenance;
  readonly boundary: HostingBoundary;
}

/** Returns `null` when the payload is admitted, and the refusal reason otherwise. */
export function admissionFailure(request: AdmissionRequest): string | null {
  // CONTROL is refused at admission regardless of host, label, authorization or scope.
  if (request.classification === "CONTROL") {
    return "CONTROL is refused at admission; CONTROL publication remains DEFERRED";
  }
  // UNCLASSIFIED goes nowhere -- it fails closed.
  if (request.classification === "UNCLASSIFIED") {
    return "UNCLASSIFIED fails closed and is refused rather than downgraded";
  }
  if (request.boundary === "PRIVATE_BOUNDARY") {
    return null;
  }
  if (request.classification !== "PUBLIC_SAFE") {
    return `PUBLIC_EDGE admits PUBLIC_SAFE payloads only, not ${request.classification}`;
  }
  if (request.provenance === "SYNTHETIC") {
    return null;
  }
  if (request.provenance === "REPOSITORY_TRACKED") {
    const enumerated = (REPOSITORY_TRACKED_READ_MODELS as readonly string[]).includes(
      request.readModel,
    );
    return enumerated
      ? null
      : `REPOSITORY_TRACKED is admitted to PUBLIC_EDGE only from the enumerated governance ` +
          `read models, not from ${request.readModel}`;
  }
  // SYSTEM_RECORDED, BACKTEST_SIMULATED and BROKER_REPORTED are NEVER admitted to an
  // externally hosted deployment, whatever their classification.
  return `${request.provenance} is never admitted to PUBLIC_EDGE`;
}
