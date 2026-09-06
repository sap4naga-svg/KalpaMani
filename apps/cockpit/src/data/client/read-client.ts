/**
 * The read-client boundary.
 *
 * This is the ONE seam the presentation layer talks to. In C3 it is satisfied by a local,
 * deterministic FIXTURE ADAPTER; a later authorized cycle satisfies it with the versioned
 * read API of ADR-0027 §4.
 *
 * IT IS A LOCAL SUBSTITUTE FOR A FUTURE TRANSPORT, AND NOT A CLAIM THAT THE FASTAPI
 * SERVICE OR ANY PRODUCTION PROJECTION EXISTS. Neither exists, and neither is authorized.
 *
 * The Cockpit has NO direct access to a provider API, provider credentials, AWS secrets,
 * IBKR trading APIs, brokerage credentials, mutable Brain internals or private
 * qualification artifacts (ADR-0027 §4). Nothing in this boundary opens a network
 * connection of any kind.
 */
import type { z } from "zod";

import { admissionFailure } from "@/contracts/admission";
import type { EnvelopeOf } from "@/contracts/envelope";
import type {
  AttentionItemPayload,
  ExecutiveOverviewPayload,
  QualificationStatusPayload,
  WhatChangedEntryPayload,
} from "@/contracts/read-models";
import type { HostingBoundary } from "@/contracts/vocabularies";
import type { ViewScope } from "@/lib/scope";

export interface WhatChangedPayload {
  readonly baseline_label: string;
  readonly baseline_as_of?: string;
  readonly comparison_as_of?: string;
  readonly entries: WhatChangedEntryPayload[];
}

export interface AttentionListPayload {
  readonly items: AttentionItemPayload[];
}

export interface ReadClient {
  executiveOverview(scope: ViewScope): Promise<EnvelopeOf<ExecutiveOverviewPayload>>;
  attention(scope: ViewScope): Promise<EnvelopeOf<AttentionListPayload>>;
  whatChanged(scope: ViewScope): Promise<EnvelopeOf<WhatChangedPayload>>;
  qualificationStatus(scope: ViewScope): Promise<EnvelopeOf<QualificationStatusPayload>>;
}

export class ContractViolationError extends Error {
  constructor(readModel: string, detail: string) {
    super(`read model ${readModel} refused at the boundary: ${detail}`);
    this.name = "ContractViolationError";
  }
}

/**
 * Validate a response against its schema and the admission rules, or refuse it.
 *
 * An unknown `schema_version` is REJECTED, never coerced (§3), and a payload that fails
 * §7.1 admission is REFUSED rather than downgraded.
 */
export function admit<S extends z.ZodTypeAny>(
  readModel: string,
  schema: S,
  candidate: unknown,
  boundary: HostingBoundary,
): z.infer<S> {
  const parsed = schema.safeParse(candidate);
  if (!parsed.success) {
    throw new ContractViolationError(readModel, parsed.error.issues[0]?.message ?? "invalid");
  }
  const envelopeLike = parsed.data as { classification: never; provenance: never };
  const failure = admissionFailure({
    readModel,
    classification: envelopeLike.classification,
    provenance: envelopeLike.provenance,
    boundary,
  });
  if (failure !== null) {
    throw new ContractViolationError(readModel, failure);
  }
  return parsed.data;
}
