/**
 * Query keys.
 *
 * A cache key includes the API version, the schema version, the environment, the source
 * provenance, the ACCESS SCOPE, the CLASSIFICATION and every query parameter
 * (`read-model-contracts.md` §7). AN ENVIRONMENT OR PROVENANCE OMITTED FROM A CACHE KEY IS
 * A CROSS-ENVIRONMENT LEAK WAITING TO HAPPEN, so every key below is built from the read
 * model's own identity plus the whole scope, rather than from a bare read-model name.
 *
 * Provenance comes from the READ MODEL, never from the scenario selector. §7 asks where the
 * numbers came from, and the selector answers a different question: `QualificationStatus`
 * is `REPOSITORY_TRACKED` in the demo scenario too, and the operational read models are
 * `SYNTHETIC` in project scope too.
 *
 * A response whose classification or access scope differs is a DIFFERENT ENTRY and is never
 * served in place of another — no shared cache across classification (§7).
 */
import type { ViewScope } from "@/lib/scope";

import type { ReadModelIdentity } from "./read-model-identity";

export const API_VERSION = "v1";

/**
 * The query parameters of a read.
 *
 * Every scope field is included. `mode` is a presentation selector this adapter does not
 * read, and it is keyed anyway: a key that is a superset of what a request depends on can
 * only over-separate, while a key omitting a parameter a later transport DOES read serves
 * one scope's payload under another's badge.
 */
export function scopeKey(scope: ViewScope): readonly string[] {
  return [scope.environment, scope.scenario, scope.mode];
}

/**
 * `period` is NOT part of `scopeKey`, and that is deliberate.
 *
 * §7 asks for "every query parameter" of a read. A period is a parameter of exactly ONE read
 * model — the performance series — and folding it into the shared scope key would hand the
 * governance, attention and overview reads a fresh cache entry every time a reader changed
 * the chart's range. Over-separation is safe but is not free, so the one read model that
 * depends on a period passes it explicitly through `params`, and every key still describes
 * every parameter its own request depends on.
 */
export function readModelKey(
  identity: ReadModelIdentity,
  scope: ViewScope,
  params: readonly string[] = [],
): readonly string[] {
  return [
    "cockpit",
    identity.queryName,
    API_VERSION,
    identity.schemaVersion,
    identity.provenance,
    identity.classification,
    identity.accessScope,
    ...scopeKey(scope),
    ...params,
  ];
}
