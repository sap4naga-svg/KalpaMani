/**
 * The typed navigation registry.
 *
 * The route map is transcribed from `docs/cockpit/ui-ux-specification.md` section 3 and
 * SETTLED ROUTES ARE NOT RENAMED. Thirty-six areas are not thirty-six equal-weight sidebar
 * links, so the grouping below is part of the specification rather than a layout choice.
 *
 * Every registered route resolves to a real page. A registered route that 404s is the
 * defect this registry exists to prevent, and a test walks the whole registry.
 */

export type NavGroupId =
  | "overview"
  | "portfolio"
  | "strategy"
  | "signals"
  | "risk"
  | "execution"
  | "research"
  | "governance"
  | "system"
  | "foundation";

export type RouteStatus = "implemented" | "placeholder" | "inert";

export interface NavRoute {
  readonly href: string;
  readonly label: string;
  /** The Cockpit V1 product areas this route presents. */
  readonly areas: readonly number[];
  readonly group: NavGroupId;
  readonly status: RouteStatus;
  /** What the area is for -- shown on a placeholder so it explains itself. */
  readonly purpose: string;
  /** The producing subsystem or dependency this route waits on. */
  readonly dependency: string;
  /** The delivery cycle that implements it, from the traceability matrix. */
  readonly cycle: string;
  /** Extra search terms for the command palette. */
  readonly keywords?: readonly string[];
}

export interface NavGroup {
  readonly id: NavGroupId;
  readonly label: string;
}

export const NAV_GROUPS: readonly NavGroup[] = [
  { id: "overview", label: "Overview" },
  { id: "portfolio", label: "Portfolio" },
  { id: "strategy", label: "Strategy" },
  { id: "signals", label: "Signals" },
  { id: "risk", label: "Risk & Market" },
  { id: "execution", label: "Execution" },
  { id: "research", label: "Research" },
  { id: "governance", label: "Governance" },
  { id: "system", label: "System" },
  { id: "foundation", label: "Foundation" },
];

export const NAV_ROUTES: readonly NavRoute[] = [
  {
    href: "/",
    label: "Executive Overview",
    areas: [1, 28, 29],
    group: "overview",
    status: "implemented",
    purpose: "The five ten-second answers, attention and what changed.",
    dependency: "read-model projections",
    cycle: "C4",
    keywords: ["home", "dashboard", "executive", "operator"],
  },
  {
    href: "/attention",
    label: "Attention Required",
    areas: [28],
    group: "overview",
    status: "implemented",
    purpose: "The ranked, deduplicated list of what needs a human, with evidence.",
    dependency: "the attention projection and the alert feed",
    cycle: "C4",
    keywords: ["alerts", "severity", "evidence", "ranked", "deduplicated"],
  },
  {
    href: "/portfolio/performance",
    label: "Portfolio Performance",
    areas: [2],
    group: "portfolio",
    status: "implemented",
    purpose: "Equity, drawdown and return against the authoritative strategy capital.",
    dependency: "the portfolio valuation projection and its recorded cash flows",
    cycle: "C5",
    keywords: ["equity", "drawdown", "return", "expectancy", "sharpe", "heatmap", "benchmark"],
  },
  {
    href: "/portfolio/positions",
    label: "Positions & Exposure",
    areas: [3],
    group: "portfolio",
    status: "implemented",
    purpose: "Open positions with long, short, gross and net exposure.",
    dependency: "the portfolio runtime and its recorded positions and lots",
    cycle: "C5",
    keywords: ["positions", "exposure", "gross", "net", "sector", "borrow", "concentration"],
  },
  {
    href: "/portfolio/trades",
    label: "Trade History",
    areas: [36],
    group: "portfolio",
    status: "implemented",
    purpose: "Closed and open trades. A fill is never counted as a trade.",
    dependency: "the portfolio and execution runtimes and their recorded trades",
    /*
     * The matrix splits area 36: C5 owns the history and a BASIC detail, and C6 owns the
     * complete lifecycle and the chart drill-down. The cycle recorded here is the one that
     * implemented what is reachable now.
     */
    cycle: "C5 history and basic detail, C6 full lifecycle",
    keywords: ["trades", "ledger", "r multiple", "winners", "losers", "partial exit"],
  },
  {
    href: "/strategy/performance",
    label: "Strategy Performance",
    areas: [4],
    group: "strategy",
    status: "implemented",
    purpose: "Per-strategy results, pinned to the versions that produced them.",
    dependency: "the strategy runtime — no strategy module exists",
    cycle: "C5",
    keywords: ["breakout", "pullback", "pead", "deterioration", "expectancy", "family", "G7"],
  },
  {
    href: "/strategy/health",
    label: "Strategy Health",
    areas: [5],
    group: "strategy",
    status: "implemented",
    purpose: "Health states and transitions, consumed from the ADR-0026 vocabulary.",
    dependency: "the strategy runtime and its health monitor — neither exists",
    cycle: "C7",
    keywords: [
      "health",
      "degraded",
      "watch",
      "suspended",
      "retired",
      "drift",
      "failure cluster",
      "recovery",
    ],
  },
  {
    href: "/strategy/champion-challenger",
    label: "Champion / Challenger",
    areas: [15],
    group: "strategy",
    status: "implemented",
    purpose: "Shadow Challengers against the unchanged Champion.",
    dependency: "the research runtime and the shadow runner — neither exists",
    cycle: "C7",
    keywords: [
      "champion",
      "challenger",
      "overlap",
      "divergence",
      "readiness",
      "shadow",
      "exposure",
    ],
  },
  {
    href: "/strategy/versions",
    label: "Strategy Version Registry",
    areas: [20],
    group: "strategy",
    status: "implemented",
    purpose: "Immutable strategy versions and their governance records.",
    dependency: "the strategy runtime — no strategy module exists",
    cycle: "C7",
    keywords: [
      "version",
      "lineage",
      "pins",
      "immutable",
      "open position",
      "rollback",
      "champion",
      "challenger",
    ],
  },
  {
    href: "/signals/funnel",
    label: "Signal & Candidate Funnel",
    areas: [6],
    group: "signals",
    status: "implemented",
    purpose: "Brain decisions and downstream stages, presented as two separate axes.",
    dependency: "the Brain runtime and its journaled decisions — no Brain runtime exists",
    cycle: "C6",
    keywords: [
      "funnel",
      "candidates",
      "brain",
      "watchlist",
      "blocked",
      "conversion",
      "reasons",
    ],
  },
  {
    href: "/signals/missed",
    label: "Missed Opportunities",
    areas: [8],
    group: "signals",
    status: "implemented",
    purpose: "Candidates the system declined, and why. Hindsight is never achievable profit.",
    dependency:
      "the Brain runtime and a qualified price history — no Brain runtime exists and G1 is OPEN",
    cycle: "C6",
    keywords: [
      "missed",
      "counterfactual",
      "hindsight",
      "expiry",
      "delay",
      "borrow",
      "false positive",
    ],
  },
  {
    href: "/risk",
    label: "Risk Dashboard",
    areas: [12],
    group: "risk",
    status: "implemented",
    purpose: "Initial and current planned risk, kept apart, with permitted risk.",
    dependency: "the risk engine — no risk engine exists",
    cycle: "C5",
    keywords: ["risk", "planned risk", "permitted", "breaker", "threshold", "research values"],
  },
  {
    href: "/risk/short-side",
    label: "Short-Side Dashboard",
    areas: [13],
    group: "risk",
    status: "implemented",
    purpose: "Gross short exposure and borrow state. Borrow is never inferred from price.",
    dependency: "a borrow data feed — G5 historical borrow qualification is OPEN",
    cycle: "C5",
    keywords: ["short", "borrow", "squeeze", "SSR", "recall", "blocked", "G5"],
  },
  {
    href: "/market/regime",
    label: "Market & Regime",
    areas: [11],
    group: "risk",
    status: "implemented",
    purpose: "Regime context the Brain resolved its decisions against.",
    dependency: "a regime engine and qualified provider data — neither exists",
    cycle: "C5",
    keywords: ["regime", "trend", "breadth", "volatility", "stress", "sector leadership"],
  },
  {
    href: "/execution/quality",
    label: "Execution Quality",
    areas: [9],
    group: "execution",
    status: "implemented",
    purpose: "Slippage in signed basis points, and latency with synchronized clocks.",
    dependency:
      "the execution runtime — no automated execution runtime exists beyond the certified Phase 2 scope",
    cycle: "C8",
    keywords: [
      "slippage",
      "latency",
      "fill",
      "reject",
      "cancel",
      "partial fill",
      "duplicate",
      "protection",
      "cost",
    ],
  },
  {
    href: "/execution/reconciliation",
    label: "Broker & Reconciliation",
    areas: [10],
    group: "execution",
    status: "implemented",
    purpose: "Broker state against internal state. No broker-native order id is displayed.",
    dependency: "a broker session — none exists in any Cockpit path, and none is authorized",
    cycle: "C8",
    keywords: [
      "reconciliation",
      "broker",
      "orphan",
      "mismatch",
      "session",
      "reconnect",
      "as of",
      "equity",
    ],
  },
  {
    href: "/research/runs",
    label: "Research & Backtesting",
    areas: [14],
    group: "research",
    status: "implemented",
    purpose: "Authorized research runs and their pins. Backtesting has not started.",
    dependency:
      "the research runner and a qualified point-in-time provider — neither exists and G1 is OPEN",
    cycle: "C7",
    keywords: [
      "run",
      "backtest",
      "manifest",
      "baseline",
      "trial",
      "evaluation class",
      "stress",
      "decomposition",
    ],
  },
  {
    href: "/research/queue",
    label: "Research Queue",
    areas: [17],
    group: "research",
    status: "implemented",
    purpose: "Queued research triggers from health, drift and failure clusters.",
    dependency: "the learning engine — no learning engine exists",
    cycle: "C7",
    keywords: ["queue", "trigger", "priority", "baseline", "authorization", "withdrawn"],
  },
  {
    href: "/research/hypotheses",
    label: "Hypothesis Registry",
    areas: [18],
    group: "research",
    status: "implemented",
    purpose: "Immutable preregistrations, amendments and trial budgets.",
    dependency: "the hypothesis registry — no learning engine exists",
    cycle: "C7",
    keywords: [
      "hypothesis",
      "preregistration",
      "amendment",
      "budget",
      "exposure ledger",
      "locked set",
      "confirmatory",
      "reuse",
    ],
  },
  {
    href: "/research/feedback",
    label: "Feedback / Self-Maturation",
    areas: [16],
    group: "research",
    status: "implemented",
    purpose: "The loop, read-only. The Cockpit reads it and does not drive it.",
    dependency: "the learning engine — no learning engine exists",
    cycle: "C7",
    keywords: ["feedback", "loop", "pipeline", "stage", "blocked", "shadow", "release"],
  },
  {
    href: "/research/ai-contribution",
    label: "AI Contribution Analytics",
    areas: [21],
    group: "research",
    status: "implemented",
    purpose: "Where AI removed candidates. AI may remove and may never restore.",
    dependency:
      "the AI Research and Challenger agents — neither exists, and experiment E has not been run",
    cycle: "C7",
    keywords: ["AI", "arm", "matched", "uncertainty", "outage", "experiment E", "provenance"],
  },
  {
    href: "/governance/packets",
    label: "Governance Packets",
    areas: [19],
    group: "governance",
    status: "implemented",
    purpose: "Assembled packets for human review. Ready for review is not an approval.",
    dependency: "the governance packet assembler — no governance runtime exists",
    cycle: "C7",
    keywords: [
      "packet",
      "decision",
      "recommendation",
      "readiness",
      "criteria",
      "approve",
      "reject",
    ],
  },
  {
    href: "/governance/qualification",
    label: "Project & Qualification",
    areas: [24],
    group: "governance",
    status: "implemented",
    purpose: "Real tracked governance and qualification facts, each with its source.",
    dependency: "tracked repository authority",
    cycle: "C4",
    keywords: ["gates", "G1", "G2", "G3", "ADR", "run b", "P1", "readiness"],
  },
  {
    href: "/governance/maturity",
    label: "Environment & Maturity",
    areas: [25],
    group: "governance",
    status: "implemented",
    /*
     * The traceability matrix places area 25 in C4; the C3 registry recorded C8, which
     * disagreed with it. The matrix governs, and this row now matches it.
     */
    purpose: "The five maturity stages against the unchanged runtime environment enum.",
    dependency: "the accepted stage-to-environment mapping",
    cycle: "C4",
    keywords: ["shadow", "paper", "live", "promotion", "stage"],
  },
  {
    href: "/governance/audit",
    label: "Audit Trail",
    areas: [26],
    group: "governance",
    status: "implemented",
    purpose: "Append-only audit events carrying classified references, never payloads.",
    dependency: "the platform audit event stream — no authoritative audit store exists",
    cycle: "C8",
    keywords: [
      "audit",
      "event",
      "timeline",
      "correction",
      "tombstone",
      "projection",
      "lineage",
      "digest",
    ],
  },
  {
    href: "/governance/controls",
    label: "Future Control Plane",
    areas: [35],
    group: "governance",
    status: "inert",
    purpose: "An INERT specification of a future control plane. Nothing here acts.",
    dependency: "a separate control architecture, NOT AUTHORIZED",
    cycle: "C3 inert page, later cycle for design",
    keywords: ["controls", "inert", "kill switch"],
  },
  {
    href: "/system/data-quality",
    label: "Data Quality & PIT",
    areas: [22],
    group: "system",
    status: "implemented",
    purpose: "Point-in-time profile and coverage. A profile is declared, never inferred.",
    dependency:
      "a qualified point-in-time provider — none is selected, G1 and G2 are OPEN and P1-P9 are UNEVALUATED",
    cycle: "C8",
    keywords: [
      "coverage",
      "freshness",
      "point in time",
      "PIT",
      "profile",
      "lineage",
      "revision",
      "corporate action",
      "borrow",
    ],
  },
  {
    href: "/system/operations",
    label: "System Operations",
    areas: [23],
    group: "system",
    status: "implemented",
    purpose: "Runtime health of the deterministic core.",
    dependency: "a scheduler and service runtime — neither exists, and nothing observes one",
    cycle: "C8",
    keywords: [
      "jobs",
      "incidents",
      "queue depth",
      "last success",
      "restart",
      "scheduler",
      "timeline",
    ],
  },
  {
    href: "/system/alerts",
    label: "Alerts & Exceptions",
    areas: [27],
    group: "system",
    status: "implemented",
    purpose: "The alert feed the attention list is deduplicated against.",
    dependency:
      "a platform alert pipeline — none exists, and no notification integration is built or authorized",
    cycle: "C8",
    keywords: [
      "alerts",
      "severity",
      "deduplication",
      "occurrence",
      "resolved",
      "exception",
      "condition",
    ],
  },
  {
    href: "/foundation/states",
    label: "Contract & State Reference",
    areas: [33],
    group: "foundation",
    status: "implemented",
    purpose: "Every availability state and freshness rule, rendered for repeatable review.",
    dependency: "none -- a local foundation review surface",
    cycle: "C3",
    keywords: ["states", "availability", "freshness", "stale", "empty", "reference"],
  },
];

export const ROUTES_BY_HREF: ReadonlyMap<string, NavRoute> = new Map(
  NAV_ROUTES.map((route) => [route.href, route]),
);

export function routesInGroup(group: NavGroupId): readonly NavRoute[] {
  return NAV_ROUTES.filter((route) => route.group === group);
}

/**
 * Deep destinations that are DISTINCT screens with their own workflows.
 *
 * Trade Detail, Candidate Detail, Execution History and the Audit Trail share identifiers and
 * **never share a screen** (Area 36.3). They are not sidebar entries: each is reached from
 * the row it belongs to.
 *
 * `/portfolio/trades/[tradeId]` carries the **complete** lifecycle: C5 owned the history and a
 * basic detail, and C6 added the orders, fills, protective-order events, reconciliation,
 * execution quality, attribution and benchmark. `/signals/candidates/[candidateId]` is
 * implemented by C6 and is reached from the funnel row and from the trade it produced.
 */
export const DEEP_DESTINATIONS: readonly {
  readonly route: string;
  readonly status: RouteStatus;
  readonly cycle: string;
  /** The screen's own name — a trade's detail is not the ledger it was opened from. */
  readonly label: string;
  /** The registered sidebar route this screen is reached from, and belongs to. */
  readonly owner: string;
}[] = [
  {
    route: "/portfolio/trades/[tradeId]",
    status: "implemented",
    cycle: "C5 basic, C6 full",
    label: "Trade Detail",
    owner: "/portfolio/trades",
  },
  {
    route: "/signals/candidates/[candidateId]",
    status: "implemented",
    cycle: "C6",
    label: "Candidate Detail",
    owner: "/signals/funnel",
  },
];

/**
 * The path prefix a deep destination's template describes.
 *
 * `/portfolio/trades/[tradeId]` is reached at `/portfolio/trades/<id>`, so the prefix is
 * everything before the first dynamic segment. It is DERIVED from the template rather than
 * written out a second time, because a prefix copied beside a route is a second route.
 */
function deepPrefix(route: string): string {
  const dynamic = route.indexOf("/[");
  return dynamic === -1 ? route : route.slice(0, dynamic);
}

/**
 * The registered destination a pathname belongs to, and what to call it.
 *
 * MATCHING A PATHNAME AGAINST `href` ALONE MARKED NO SIDEBAR ENTRY CURRENT ON A DETAIL SCREEN.
 * A reader who had drilled into `/portfolio/trades/<id>` or `/signals/candidates/<id>` saw a
 * sidebar with no position in it at all, so the navigation stopped saying where they were at
 * exactly the point they had gone somewhere.
 *
 * A deep destination resolves to the SIDEBAR ROUTE THAT OWNS IT — Trade Detail belongs to Trade
 * History — and carries its OWN name, because a detail screen is a different screen from the
 * ledger it was opened from. An unregistered path resolves to `null`: **nothing is guessed**, and
 * a caller marks nothing rather than marking a nearest match.
 */
export interface ResolvedRoute {
  /** The sidebar entry that should read as current, or `null` for an unregistered path. */
  readonly owner: NavRoute | null;
  /** The screen's own name. */
  readonly label: string;
}

export function resolveRoute(pathname: string): ResolvedRoute | null {
  const exact = ROUTES_BY_HREF.get(pathname);
  if (exact !== undefined) {
    return { owner: exact, label: exact.label };
  }
  for (const destination of DEEP_DESTINATIONS) {
    const prefix = deepPrefix(destination.route);
    if (pathname.startsWith(`${prefix}/`)) {
      return {
        owner: ROUTES_BY_HREF.get(destination.owner) ?? null,
        label: destination.label,
      };
    }
  }
  return null;
}

/** The routes with no page of their own, kept for the tests that assert their absence. */
export const RESERVED_DESTINATIONS: readonly string[] = DEEP_DESTINATIONS.filter(
  (destination) => destination.status !== "implemented",
).map((destination) => destination.route);
