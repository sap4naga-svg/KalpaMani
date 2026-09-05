/**
 * View scope — mode, runtime environment and data scenario.
 *
 * Scoping travels with everything (`ui-ux-specification.md` §5): cache keys, filters, URLs
 * and deep links all carry environment and source, so a shared link cannot open under a
 * different environment than the one it was captured in.
 *
 * FIVE THINGS ARE KEPT SEPARATE (ADR-0027 §5), and this module keeps them separate:
 * deployment identity, runtime environment, strategy maturity, source provenance and data
 * availability. SYNTHETIC/DEMO is PROVENANCE, not a runtime environment, so `scenario`
 * below is a provenance selector and never an environment value.
 */
import { ENVIRONMENTS, type Environment } from "@/contracts/vocabularies";

export const VIEW_MODES = ["executive", "operator"] as const;
export type ViewMode = (typeof VIEW_MODES)[number];

/**
 * The data scenario. This selects PROVENANCE, and advances no maturity and no authority.
 *
 *   project  the honest project-readiness presentation, from REPOSITORY_TRACKED facts
 *   demo     a clearly labelled SYNTHETIC scenario that populates the visual states
 */
export const DATA_SCENARIOS = ["project", "demo"] as const;
export type DataScenario = (typeof DATA_SCENARIOS)[number];

export interface ViewScope {
  readonly mode: ViewMode;
  readonly environment: Environment;
  readonly scenario: DataScenario;
}

/** Selecting Paper or Live as a VIEWING SCOPE advances no maturity and no authority. */
export const DEFAULT_SCOPE: ViewScope = {
  mode: "executive",
  environment: "RESEARCH",
  scenario: "project",
};

function oneOf<T extends string>(
  candidates: readonly T[],
  raw: string | null | undefined,
  fallback: T,
): T {
  return candidates.includes(raw as T) ? (raw as T) : fallback;
}

export function parseScope(params: URLSearchParams | ReadonlyMap<string, string>): ViewScope {
  const read = (key: string): string | null =>
    params instanceof URLSearchParams ? params.get(key) : (params.get(key) ?? null);
  return {
    mode: oneOf(VIEW_MODES, read("mode"), DEFAULT_SCOPE.mode),
    environment: oneOf(ENVIRONMENTS, read("env"), DEFAULT_SCOPE.environment),
    scenario: oneOf(DATA_SCENARIOS, read("scenario"), DEFAULT_SCOPE.scenario),
  };
}

/** The URL encoding. Every scope field is present, so a link reproduces the whole view. */
export function scopeToSearchParams(scope: ViewScope): URLSearchParams {
  const params = new URLSearchParams();
  params.set("mode", scope.mode);
  params.set("env", scope.environment);
  params.set("scenario", scope.scenario);
  return params;
}

/** Preserves scope across a navigation, so a drill-down never silently changes environment. */
export function withScope(href: string, scope: ViewScope): string {
  const [path, existing] = href.split("?");
  const params = new URLSearchParams(existing ?? "");
  for (const [key, value] of scopeToSearchParams(scope)) {
    params.set(key, value);
  }
  return `${path}?${params.toString()}`;
}

/** The provenance a scenario produces. `demo` is SYNTHETIC; `project` is REPOSITORY_TRACKED. */
export function scenarioProvenance(scenario: DataScenario): "SYNTHETIC" | "REPOSITORY_TRACKED" {
  return scenario === "demo" ? "SYNTHETIC" : "REPOSITORY_TRACKED";
}
