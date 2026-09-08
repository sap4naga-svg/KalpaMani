/**
 * The Ask KalpaMani question catalogue — Area 31.
 *
 * **This is the whole vocabulary.** Every question the assistant can answer is one of the
 * entries below, each bound to exactly one closed `AskQuestionClass` and to the read model
 * that owns its answer. A question outside this catalogue is not answered, not approximated
 * and not routed to the nearest entry — it is reported as unsupported, by name.
 *
 * **The catalogue is data, and the resolver is arithmetic over it.** There is no model, no
 * embedding, no index of free text and no network call: `resolve.ts` matches an entry's
 * declared terms against a normalized question and reports what it found. That is the whole
 * of the "natural language" in Area 31, and the interface says so rather than implying a
 * running model.
 *
 * **No entry is an instruction, and none is a verb.** The catalogue navigates nothing,
 * changes nothing and submits nothing; ADR-0027's read-only boundary holds because the
 * `ReadClient` has no method that writes, and this file adds none.
 */
import type { AskQuestionClass, AskSubjectKind } from "@/contracts/ask-models";
import { PERFORMANCE_PERIODS, type PerformancePeriod } from "@/lib/scope";

/** The area of the Cockpit an answer is drawn from, for the reader who wants the screen. */
export interface AskSourceArea {
  readonly area: number;
  readonly label: string;
  readonly href: string;
}

export interface AskIntent {
  readonly questionClass: AskQuestionClass;
  /** The one-line statement of what this class answers. Product copy, not a rationale. */
  readonly label: string;
  /** What the reader gets, in one sentence, shown beside the suggestion. */
  readonly summary: string;
  /**
   * The subject this class is ABOUT, or `undefined` where it is about the portfolio.
   *
   * A class that takes a subject NEVER defaults one. Asking without one is answered by
   * asking which, because "silently choose a different trade" is precisely the failure a
   * default produces.
   */
  readonly subjectKind?: AskSubjectKind;
  /** Whether the class takes an analysis window. A window is never assumed either. */
  readonly takesWindow: boolean;
  /**
   * Terms that must ALL appear, each satisfied by any one of its alternatives.
   *
   * Written as groups rather than as a bag of keywords so that "return" alone does not
   * resolve a question about a trade's return to the portfolio class: the portfolio entry
   * requires a portfolio term as well.
   */
  readonly requires: readonly (readonly string[])[];
  /** Terms that, where present, add confidence without being required. */
  readonly prefers: readonly string[];
  readonly sourceArea: AskSourceArea;
  /** Ready-made questions. Each one RESOLVES — none is decorative copy. */
  readonly examples: readonly string[];
}

/** The demonstration identifiers the ready-made questions name. */
export const EXAMPLE_SUBJECTS = {
  trade: "demo-trade-arb-0001",
  candidate: "demo-candidate-0003",
  strategyVersion: "breakout-long-v3",
  registration: "demo-reg-0003",
} as const;

const PORTFOLIO_TERMS = ["portfolio", "book", "account", "overall", "total"] as const;

export const ASK_INTENTS: readonly AskIntent[] = [
  {
    questionClass: "PORTFOLIO_RETURN",
    label: "Portfolio return over a window",
    summary:
      "The time-weighted return of the whole book over one trailing window, with the " +
      "population it was measured over.",
    takesWindow: true,
    requires: [[...PORTFOLIO_TERMS], ["return", "perform", "made", "gain"]],
    prefers: ["time", "weighted", "twr"],
    sourceArea: { area: 1, label: "Portfolio performance", href: "/portfolio/performance" },
    examples: [
      "How did the portfolio perform over 3 months?",
      "What is the total portfolio return over 1 year?",
    ],
  },
  {
    questionClass: "PORTFOLIO_DRAWDOWN",
    label: "Portfolio drawdown over a window",
    summary: "The maximum drawdown recorded over one trailing window.",
    takesWindow: true,
    requires: [["drawdown", "peak", "worst"]],
    prefers: ["max", "maximum", "deepest", "portfolio"],
    sourceArea: { area: 1, label: "Portfolio performance", href: "/portfolio/performance" },
    examples: [
      "What was the maximum drawdown over 6 months?",
      "How deep was the portfolio drawdown over 1 month?",
    ],
  },
  {
    questionClass: "STRATEGY_HEALTH",
    label: "A strategy version's recorded health",
    summary:
      "The health state a strategy version is recorded in, since when, and the safety " +
      "action and human authorization the record names.",
    subjectKind: "STRATEGY_VERSION",
    takesWindow: false,
    requires: [["strategy", "module", "version"], ["health", "healthy", "degraded", "state"]],
    prefers: ["transition", "recovery", "disabled", "reduced"],
    sourceArea: { area: 5, label: "Strategy health", href: "/strategy/health" },
    examples: [
      `What is the health of strategy version ${EXAMPLE_SUBJECTS.strategyVersion}?`,
      `Is strategy version ${EXAMPLE_SUBJECTS.strategyVersion} degraded?`,
    ],
  },
  {
    questionClass: "TRADE_OUTCOME",
    label: "A trade's recorded outcome",
    summary:
      "One trade's R multiple, realized result, business status and the exit reason the " +
      "record carries — never an inferred cause.",
    subjectKind: "TRADE",
    takesWindow: false,
    requires: [["trade"], ["happened", "outcome", "result", "went", "do", "did", "perform"]],
    prefers: ["exit", "closed", "r", "multiple", "pnl"],
    sourceArea: { area: 36, label: "Trade history", href: "/portfolio/trades" },
    examples: [
      `What happened to trade ${EXAMPLE_SUBJECTS.trade}?`,
      `What was the outcome of trade ${EXAMPLE_SUBJECTS.trade}?`,
    ],
  },
  {
    questionClass: "CANDIDATE_PROGRESSION",
    label: "A candidate's recorded progression",
    summary:
      "The Brain decision state a candidate is journaled in, its rank in the population " +
      "it was ranked against, and the blocking reasons the record names.",
    subjectKind: "CANDIDATE",
    takesWindow: false,
    requires: [["candidate"], ["happened", "state", "decision", "progression", "went", "did"]],
    prefers: ["brain", "blocked", "rejected", "watchlist"],
    sourceArea: { area: 7, label: "Candidate detail", href: "/signals/candidates" },
    examples: [
      `What happened to candidate ${EXAMPLE_SUBJECTS.candidate}?`,
      `What decision state is candidate ${EXAMPLE_SUBJECTS.candidate} in?`,
    ],
  },
  {
    questionClass: "ATTENTION_SUMMARY",
    label: "What needs attention",
    summary:
      "How many executive attention items are open, and the impact the highest-ranked " +
      "one carries.",
    takesWindow: false,
    requires: [["attention", "attend", "urgent", "wrong", "watch"]],
    prefers: ["need", "needs", "requires", "executive", "today"],
    sourceArea: { area: 28, label: "Attention required", href: "/attention" },
    examples: ["What needs attention?", "How many attention items are open?"],
  },
  {
    questionClass: "RECORDED_CHANGES",
    label: "What changed since the baseline",
    summary:
      "How many verified changes the comparison found, and both endpoints it compared — " +
      "never a delta against a missing baseline.",
    takesWindow: false,
    requires: [["changed", "change", "changes", "different", "moved", "new"]],
    prefers: ["since", "yesterday", "baseline", "recently"],
    sourceArea: { area: 3, label: "Executive overview", href: "/" },
    examples: ["What changed since the baseline?", "What is different today?"],
  },
  {
    questionClass: "DATA_QUALITY_CONDITION",
    label: "Data quality and point-in-time conditions",
    summary:
      "How many data-quality subjects are recorded in a degraded state, and the coverage " +
      "and information profile of the affected one.",
    takesWindow: false,
    requires: [["data"], ["quality", "coverage", "stale", "point", "pit", "problem", "issue"]],
    prefers: ["feed", "profile", "missing", "degraded"],
    sourceArea: { area: 22, label: "Data quality and PIT", href: "/system/data-quality" },
    examples: [
      "Is there a data quality problem?",
      "How is data coverage looking?",
    ],
  },
  {
    questionClass: "RECONCILIATION_RESULT",
    label: "The last reconciliation result",
    summary:
      "The result the latest reconciliation run recorded, how long ago it ran, and the " +
      "inputs it did not have — a past run is never present health.",
    takesWindow: false,
    requires: [["reconciliation", "reconcile", "reconciled", "broker"], ["match", "result", "run", "last", "latest", "differ", "state"]],
    prefers: ["orphan", "position", "sweep"],
    sourceArea: { area: 10, label: "Broker and reconciliation", href: "/execution/reconciliation" },
    examples: [
      "Did the last reconciliation match?",
      "What was the latest broker reconciliation result?",
    ],
  },
  {
    questionClass: "OPEN_ALERTS",
    label: "Open alerts and exceptions",
    summary:
      "How many deduplicated alert rows are recorded open, and how many duplicate " +
      "observations were folded into them.",
    takesWindow: false,
    requires: [["alert", "alerts", "exception", "exceptions"]],
    prefers: ["open", "firing", "severity", "how", "many"],
    sourceArea: { area: 27, label: "Alerts and exceptions", href: "/system/alerts" },
    examples: ["How many alerts are open?", "What exceptions are recorded?"],
  },
  {
    questionClass: "RESEARCH_LINEAGE",
    label: "A registration's research lineage",
    summary:
      "The trial budget remaining across a registration's whole research lineage, its " +
      "evaluation class, and the registrations it descends from.",
    subjectKind: "REGISTRATION",
    takesWindow: false,
    requires: [["registration", "hypothesis", "research"], ["lineage", "budget", "trial", "trials", "history", "descends", "produced"]],
    prefers: ["exposure", "amendment", "parent", "reuse"],
    sourceArea: { area: 18, label: "Hypothesis registry", href: "/research/hypotheses" },
    examples: [
      `What is the research lineage of registration ${EXAMPLE_SUBJECTS.registration}?`,
      `How much trial budget remains for hypothesis ${EXAMPLE_SUBJECTS.registration}?`,
    ],
  },
];

export const ASK_INTENT_BY_CLASS: ReadonlyMap<AskQuestionClass, AskIntent> = new Map(
  ASK_INTENTS.map((intent) => [intent.questionClass, intent]),
);

/**
 * Questions this assistant deliberately does not answer, and the area that records them.
 *
 * A REFERRAL IS NAVIGATION, AND IT IS NEVER AN ANSWER. Nothing here reads a read model,
 * produces a figure, cites a record or claims a fact; it names the screen that owns the
 * subject and says so. That distinction is the whole point of the list: "the assistant does
 * not answer this" and "the Cockpit does not know this" are different statements, and a bare
 * *unsupported* would have made the first sound like the second.
 *
 * **The governance referral is a CONTRACT CONSEQUENCE, not a shortcut.** §2.6 catalogues
 * `AskAnswer` as `SYNTHETIC`, and §7.1 does not admit `REPOSITORY_TRACKED` to `PUBLIC_EDGE`
 * from it — so an `AskAnswer` over tracked governance facts would have to mislabel them or be
 * refused at admission. The facts stay where the catalogue puts them, on the area that owns
 * them, and the assistant sends the reader there rather than restating them under the wrong
 * provenance.
 */
export interface AskReferral {
  readonly code: string;
  readonly terms: readonly string[];
  readonly area: AskSourceArea;
  /** Why the assistant does not answer it, as product copy the reader can act on. */
  readonly because: string;
}

export const ASK_REFERRALS: readonly AskReferral[] = [
  {
    code: "PROJECT_QUALIFICATION",
    terms: [
      "qualification",
      "qualified",
      "gate",
      "gates",
      "g1",
      "g2",
      "run a",
      "run b",
      "provider",
      "phase 3",
      "adr",
      "p1",
      "p9",
      "sharadar",
      "licence",
      "license",
    ],
    area: {
      area: 24,
      label: "Project and qualification governance",
      href: "/governance/qualification",
    },
    because:
      "Qualification and gate status are tracked repository facts. The assistant answers " +
      "over synthetic read models only, so it sends you to the area that records them " +
      "rather than restating a real fact under a synthetic label.",
  },
  {
    code: "MATURITY_AND_ENVIRONMENT",
    terms: ["maturity", "shadow", "micro live", "scaled live", "promotion stage", "lifecycle"],
    area: { area: 25, label: "Environment and deployment maturity", href: "/governance/maturity" },
    because:
      "Maturity stage is a governance property of a strategy version, and the area that " +
      "owns it shows the stage-to-environment mapping in full.",
  },
  {
    code: "RISK_LIMITS",
    terms: ["risk limit", "limits", "planned risk", "capital", "leverage", "position limit"],
    area: { area: 12, label: "Risk dashboard", href: "/risk" },
    because:
      "The governed research parameters are displayed unchanged on the risk area, beside " +
      "the policy reference each permitted limit would need and does not have.",
  },
  {
    code: "SHORT_SIDE",
    terms: ["borrow", "borrowable", "locate", "squeeze", "short side", "shortable"],
    area: { area: 13, label: "Short-side dashboard", href: "/risk/short-side" },
    because:
      "Borrow availability is never inferred from price, so it is shown only where a record " +
      "exists — on the short-side area, with unknown borrow rendered as unknown.",
  },
  {
    code: "AUDIT_HISTORY",
    terms: ["audit", "event log", "who changed", "history of changes", "tombstone"],
    area: { area: 26, label: "Audit trail", href: "/governance/audit" },
    because:
      "The audit projection is browsed on its own area, where each event keeps its own " +
      "identity and a correction appends rather than overwrites.",
  },
  {
    code: "CONTROLS",
    terms: ["kill switch", "control plane", "controls", "button", "override switch"],
    area: { area: 35, label: "Future control plane (inert)", href: "/governance/controls" },
    because:
      "No control exists anywhere in this Cockpit. The control-plane area is an inert " +
      "specification of controls a governed human will eventually need.",
  },
];

/**
 * The window terms a question may name, and the period each resolves to.
 *
 * A window is a REQUEST PARAMETER of the read it drives (`lib/scope.ts`), so naming one
 * changes the answer's extent rather than its presentation. Nothing here invents a default:
 * a windowed class asked without a window is reported as needing one.
 */
export const WINDOW_TERMS: ReadonlyMap<string, PerformancePeriod> = new Map([
  ["1m", "1M"],
  ["1 month", "1M"],
  ["one month", "1M"],
  ["month", "1M"],
  ["3m", "3M"],
  ["3 months", "3M"],
  ["three months", "3M"],
  ["quarter", "3M"],
  ["6m", "6M"],
  ["6 months", "6M"],
  ["six months", "6M"],
  ["half year", "6M"],
  ["1y", "1Y"],
  ["1 year", "1Y"],
  ["one year", "1Y"],
  ["year", "1Y"],
  ["all", "ALL"],
  ["all time", "ALL"],
  ["everything", "ALL"],
  ["full history", "ALL"],
]);

export const ASK_WINDOWS: readonly PerformancePeriod[] = PERFORMANCE_PERIODS;
