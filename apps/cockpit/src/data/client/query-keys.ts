/**
 * Query keys.
 *
 * A cache key includes the API version, the schema version, the environment, the source
 * provenance and every query parameter (`read-model-contracts.md` §7). AN ENVIRONMENT OR
 * PROVENANCE OMITTED FROM A CACHE KEY IS A CROSS-ENVIRONMENT LEAK WAITING TO HAPPEN, so
 * every key below is built from the whole scope rather than from a bare read-model name.
 */
import { scenarioProvenance, type ViewScope } from "@/lib/scope";

export const API_VERSION = "v1";

export function scopeKey(scope: ViewScope): readonly string[] {
  return [
    API_VERSION,
    scope.environment,
    scenarioProvenance(scope.scenario),
    scope.scenario,
  ];
}

export function readModelKey(
  readModel: string,
  schemaVersion: string,
  scope: ViewScope,
): readonly string[] {
  return ["cockpit", readModel, schemaVersion, ...scopeKey(scope)];
}
