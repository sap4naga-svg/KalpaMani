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

const NOT_IMPLEMENTED = "the producing subsystem does not exist";

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
    status: "placeholder",
    purpose: "Equity, drawdown and return against the authoritative strategy capital.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C4",
  },
  {
    href: "/portfolio/positions",
    label: "Positions & Exposure",
    areas: [3],
    group: "portfolio",
    status: "placeholder",
    purpose: "Open positions with long, short, gross and net exposure.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C4",
  },
  {
    href: "/portfolio/trades",
    label: "Trade History",
    areas: [36],
    group: "portfolio",
    status: "placeholder",
    purpose: "Closed and open trades. A fill is never counted as a trade.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C6",
  },
  {
    href: "/strategy/performance",
    label: "Strategy Performance",
    areas: [4],
    group: "strategy",
    status: "placeholder",
    purpose: "Per-strategy results, pinned to the versions that produced them.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C5",
  },
  {
    href: "/strategy/health",
    label: "Strategy Health",
    areas: [5],
    group: "strategy",
    status: "placeholder",
    purpose: "Health states and transitions, consumed from the ADR-0026 vocabulary.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C5",
  },
  {
    href: "/strategy/champion-challenger",
    label: "Champion / Challenger",
    areas: [15],
    group: "strategy",
    status: "placeholder",
    purpose: "Shadow Challengers against the unchanged Champion.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C7",
  },
  {
    href: "/strategy/versions",
    label: "Strategy Version Registry",
    areas: [20],
    group: "strategy",
    status: "placeholder",
    purpose: "Immutable strategy versions and their governance records.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C7",
  },
  {
    href: "/signals/funnel",
    label: "Signal & Candidate Funnel",
    areas: [6],
    group: "signals",
    status: "placeholder",
    purpose: "Brain decisions and downstream stages, presented as two separate axes.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C5",
  },
  {
    href: "/signals/missed",
    label: "Missed Opportunities",
    areas: [8],
    group: "signals",
    status: "placeholder",
    purpose: "Candidates the system declined, and why.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C5",
  },
  {
    href: "/risk",
    label: "Risk Dashboard",
    areas: [12],
    group: "risk",
    status: "placeholder",
    purpose: "Initial and current planned risk, kept apart, with permitted risk.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C4",
  },
  {
    href: "/risk/short-side",
    label: "Short-Side Dashboard",
    areas: [13],
    group: "risk",
    status: "placeholder",
    purpose: "Gross short exposure and borrow state. Borrow is never inferred from price.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C6",
  },
  {
    href: "/market/regime",
    label: "Market & Regime",
    areas: [11],
    group: "risk",
    status: "placeholder",
    purpose: "Regime context the Brain resolved its decisions against.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C6",
  },
  {
    href: "/execution/quality",
    label: "Execution Quality",
    areas: [9],
    group: "execution",
    status: "placeholder",
    purpose: "Slippage in signed basis points, and latency with synchronized clocks.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C6",
  },
  {
    href: "/execution/reconciliation",
    label: "Broker & Reconciliation",
    areas: [10],
    group: "execution",
    status: "placeholder",
    purpose: "Broker state against internal state. No broker-native order id is displayed.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C6",
  },
  {
    href: "/research/runs",
    label: "Research & Backtesting",
    areas: [14],
    group: "research",
    status: "placeholder",
    purpose: "Authorized research runs and their pins. Backtesting has not started.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C7",
  },
  {
    href: "/research/queue",
    label: "Research Queue",
    areas: [17],
    group: "research",
    status: "placeholder",
    purpose: "Queued research triggers from health, drift and failure clusters.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C7",
  },
  {
    href: "/research/hypotheses",
    label: "Hypothesis Registry",
    areas: [18],
    group: "research",
    status: "placeholder",
    purpose: "Immutable preregistrations, amendments and trial budgets.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C7",
  },
  {
    href: "/research/feedback",
    label: "Feedback / Self-Maturation",
    areas: [16],
    group: "research",
    status: "placeholder",
    purpose: "The loop, read-only. The Cockpit reads it and does not drive it.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C7",
  },
  {
    href: "/research/ai-contribution",
    label: "AI Contribution Analytics",
    areas: [21],
    group: "research",
    status: "placeholder",
    purpose: "Where AI removed candidates. AI may remove and may never restore.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C9",
  },
  {
    href: "/governance/packets",
    label: "Governance Packets",
    areas: [19],
    group: "governance",
    status: "placeholder",
    purpose: "Assembled packets for human review. Ready for review is not an approval.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C8",
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
    status: "placeholder",
    purpose: "Append-only audit events carrying classified references, never payloads.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C8",
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
    status: "placeholder",
    purpose: "Point-in-time profile and coverage. A profile is declared, never inferred.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C6",
  },
  {
    href: "/system/operations",
    label: "System Operations",
    areas: [23],
    group: "system",
    status: "placeholder",
    purpose: "Runtime health of the deterministic core.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C6",
  },
  {
    href: "/system/alerts",
    label: "Alerts & Exceptions",
    areas: [27],
    group: "system",
    status: "placeholder",
    purpose: "The alert feed the attention list is deduplicated against.",
    dependency: NOT_IMPLEMENTED,
    cycle: "C4",
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
 * Deep destinations reserved as DISTINCT and not implemented in C3.
 *
 * Trade Detail, Candidate Detail, Execution History and the Audit Trail are separate
 * destinations with their own workflows, and C3 does not implement them.
 */
export const RESERVED_DESTINATIONS: readonly string[] = [
  "/portfolio/trades/[tradeId]",
  "/signals/candidates/[candidateId]",
];
