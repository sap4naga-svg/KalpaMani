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

/**
 * The performance overview's comparison period.
 *
 * A period is a REQUEST PARAMETER, not a presentation preference: it changes the extent a
 * series is requested over, so it changes the answer. It lives in the URL with the rest of
 * the scope, so a link reproduces the view (`ui-ux-specification.md` §8, U13).
 */
export const PERFORMANCE_PERIODS = ["1M", "3M", "6M", "1Y", "ALL"] as const;
export type PerformancePeriod = (typeof PERFORMANCE_PERIODS)[number];

/** The trading days each period requests. `ALL` is the whole retained extent. */
export const PERIOD_TRADING_DAYS: Readonly<Record<PerformancePeriod, number>> = {
  "1M": 21,
  "3M": 63,
  "6M": 126,
  "1Y": 252,
  ALL: 504,
};

export const PERIOD_LABEL: Readonly<Record<PerformancePeriod, string>> = {
  "1M": "1 month",
  "3M": "3 months",
  "6M": "6 months",
  "1Y": "1 year",
  ALL: "Full retained extent",
};

/**
 * The What Changed demonstration variant.
 *
 * §7 and U17 require four distinct behaviours from a comparison, and three of them are only
 * reachable when something is WRONG with an endpoint. A reviewer cannot break a fixture from
 * the interface, so the variants are selectable — deterministically, from the URL, and ONLY
 * inside the already-labelled synthetic scenario.
 *
 *   auto         the honest default for the scenario: no baseline in project, valid in demo
 *   valid        two sound endpoints, and real deltas between them
 *   none         both endpoints sound, and NOTHING changed -- EMPTY_VERIFIED, not "no data"
 *   no-baseline  no prior endpoint at all -- reported as a state, never as a zero baseline
 *   degraded     endpoints exist and are STALE or PARTIAL -- reported instead of a delta
 */
export const CHANGE_VARIANTS = ["auto", "valid", "none", "no-baseline", "degraded"] as const;
export type ChangeVariant = (typeof CHANGE_VARIANTS)[number];

export const CHANGE_VARIANT_LABEL: Readonly<Record<ChangeVariant, string>> = {
  auto: "Scenario default",
  valid: "Verified changes",
  none: "No verified changes",
  "no-baseline": "Missing baseline",
  degraded: "Degraded endpoints",
};

/**
 * The granularity a performance series is requested at.
 *
 * Like `period`, it is a REQUEST PARAMETER of the performance read and not a presentation
 * preference: daily, weekly and monthly returns are three different chain-linked series over
 * the same window, not one series drawn three ways. It lives in the URL so a link reproduces
 * the view (U13), and it joins that read model's cache key so one granularity's points can
 * never be drawn under another's label.
 */
export const SERIES_GRANULARITIES = ["DAILY", "WEEKLY", "MONTHLY"] as const;
export type ScopeGranularity = (typeof SERIES_GRANULARITIES)[number];

export const GRANULARITY_LABEL: Readonly<Record<ScopeGranularity, string>> = {
  DAILY: "Daily",
  WEEKLY: "Weekly",
  MONTHLY: "Monthly",
};

export interface ViewScope {
  readonly mode: ViewMode;
  readonly environment: Environment;
  readonly scenario: DataScenario;
  readonly period: PerformancePeriod;
  readonly granularity: ScopeGranularity;
  readonly changes: ChangeVariant;
}

/** Selecting Paper or Live as a VIEWING SCOPE advances no maturity and no authority. */
export const DEFAULT_SCOPE: ViewScope = {
  mode: "executive",
  environment: "RESEARCH",
  scenario: "project",
  period: "3M",
  granularity: "DAILY",
  changes: "auto",
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
    period: oneOf(PERFORMANCE_PERIODS, read("period"), DEFAULT_SCOPE.period),
    granularity: oneOf(SERIES_GRANULARITIES, read("gran"), DEFAULT_SCOPE.granularity),
    changes: oneOf(CHANGE_VARIANTS, read("changes"), DEFAULT_SCOPE.changes),
  };
}

/** The URL encoding. Every scope field is present, so a link reproduces the whole view. */
export function scopeToSearchParams(scope: ViewScope): URLSearchParams {
  const params = new URLSearchParams();
  params.set("mode", scope.mode);
  params.set("env", scope.environment);
  params.set("scenario", scope.scenario);
  params.set("period", scope.period);
  params.set("gran", scope.granularity);
  params.set("changes", scope.changes);
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

/*
 * There is deliberately no `scenarioProvenance` here.
 *
 * A scenario does not determine a provenance. `QualificationStatus` reads REAL tracked
 * governance facts in the demo scenario too, and the operational read models are fixture
 * output in project scope too, so a scenario-to-provenance function states the wrong source
 * in both directions. Provenance belongs to the read model and lives in
 * `data/client/read-model-identity.ts`.
 */
