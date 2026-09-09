/**
 * The research and feedback projections — Areas 14, 15, 16, 17, 18 and 21.
 *
 * Every row is read from the one synthetic lineage in `lineage.ts`, so the health degradation,
 * the queue entry it created, the registrations that followed, the runs against them, the
 * exposure those runs spent, the comparisons they support and the packets assembled from them
 * are one story rather than six unrelated tables.
 *
 * **BACKTESTING IS NOT STARTED.** No research engine, learning engine, shadow runner or AI
 * agent exists, none has ever run, and **no figure below is the outcome of an experiment**.
 * **No synthetic figure closes a gate, qualifies a provider, validates a strategy or
 * establishes a threshold**, and **no numerical value here becomes a production rule.**
 */
import type {
  AiContribution,
  AiContributionPayload,
  ChampionChallengerComparison,
  ChampionChallengerPayload,
  EvaluationClass,
  FeedbackPipelinePayload,
  FeedbackStage,
  HypothesisRegistration,
  HypothesisRegistrationPayload,
  ResearchQueueItem,
  ResearchQueuePayload,
  ResearchRun,
  ResearchRunPayload,
  ResearchRunState,
} from "@/contracts/research-models";
import { EVALUATION_CLASSES, RESEARCH_QUEUE_STATES, RESEARCH_RUN_STATES } from "@/contracts/research-models";
import type { MetricValue, ReasonCoded } from "@/contracts/values";

import { capacityFor } from "./capacity";
import {
  count,
  demoRef,
  demoReason,
  insufficient,
  instantValue,
  notApplicable,
  percent,
  refListOf,
  scaled,
  sessionInstant,
  token,
  unavailable,
  windowOf,
} from "./common";
import {
  AI_BUDGET,
  CHALLENGERS,
  CHAMPIONS,
  LINEAGE_BUDGET,
  LINEAGE_SESSIONS,
  LOCKED_SET_A,
  LOCKED_SET_B,
  LOCKED_SET_C,
  OWN_TRIALS,
  QUEUE_ITEMS,
  REGISTRATIONS,
  RUNS,
  SET_B_OVERLAP_HUNDREDTHS,
} from "./lineage";

/** The reproducibility identities every run in this lineage records. */
const REPRODUCIBILITY = {
  manifest: "demo-research-manifest-0001",
  revision_view: "demo-revision-view-0001",
  code_identity: "research-code-demo-0001",
  config_identity: "research-config-demo-0001",
} as const;

function instantAt(days: readonly string[], session: number): string {
  return sessionInstant(days[Math.max(0, Math.min(session, days.length - 1))]);
}

/** A run's declared window: a fixed slice of the retained extent, with its calendar. */
function runWindow(days: readonly string[], fromSession: number, toSession: number) {
  return windowOf(days.slice(Math.max(0, fromSession), Math.min(toSession, days.length)));
}

/** A result set every completed run in this lineage reports, in the same six measures. */
function completedResults(
  asOf: string,
  seed: { expectancy: number; profitFactor: number; winRate: number; sharpe: number; drawdown: number; trades: number },
): { measure: ReasonCoded; value: MetricValue }[] {
  return [
    { measure: demoReason("EXPECTANCY_R"), value: scaled("expectancy.r", "R_MULTIPLE", seed.expectancy, asOf) },
    { measure: demoReason("PROFIT_FACTOR"), value: scaled("profit_factor", "RATIO", seed.profitFactor, asOf) },
    { measure: demoReason("WIN_RATE"), value: scaled("win_rate", "RATIO", seed.winRate, asOf) },
    { measure: demoReason("SHARPE"), value: scaled("sharpe", "DIMENSIONLESS", seed.sharpe, asOf) },
    { measure: demoReason("MAXIMUM_DRAWDOWN"), value: percent("drawdown.max", seed.drawdown, asOf) },
    { measure: demoReason("CLOSED_TRADE_POPULATION"), value: count("trade.count", seed.trades, asOf) },
  ];
}

/** The same six measures, as absences. A run that did not finish reports no result. */
function absentResults(): { measure: ReasonCoded; value: MetricValue }[] {
  const missing = (metricId: string, unit: Parameters<typeof unavailable>[1]) =>
    unavailable(metricId, unit, "NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING");
  return [
    { measure: demoReason("EXPECTANCY_R"), value: missing("expectancy.r", "R_MULTIPLE") },
    { measure: demoReason("PROFIT_FACTOR"), value: missing("profit_factor", "RATIO") },
    { measure: demoReason("WIN_RATE"), value: missing("win_rate", "RATIO") },
    { measure: demoReason("SHARPE"), value: missing("sharpe", "DIMENSIONLESS") },
    { measure: demoReason("MAXIMUM_DRAWDOWN"), value: missing("drawdown.max", "PERCENT") },
    { measure: demoReason("CLOSED_TRADE_POPULATION"), value: missing("trade.count", "COUNT") },
  ];
}

interface RunSpec {
  readonly runId: string;
  readonly registration: string;
  readonly challenger: string;
  /** The baseline version. `null` where the record names one that does not resolve. */
  readonly baseline: string | null;
  readonly state: ResearchRunState;
  readonly evaluationClass: EvaluationClass;
  readonly lockedSet: string;
  readonly ordinal: number;
  readonly startedSession: number;
  readonly completedSession: number;
  readonly stateReason: string;
  readonly disclosure: readonly string[];
  readonly limitations: readonly string[];
  readonly results:
    | { expectancy: number; profitFactor: number; winRate: number; sharpe: number; drawdown: number; trades: number }
    | null;
}

const RUN_SPECS: readonly RunSpec[] = [
  {
    runId: RUNS.confirmatory,
    registration: REGISTRATIONS.original,
    challenger: CHALLENGERS.pullback,
    baseline: CHAMPIONS.pullback,
    state: "COMPLETED",
    evaluationClass: "CONFIRMATORY",
    lockedSet: LOCKED_SET_A,
    ordinal: 1,
    startedSession: LINEAGE_SESSIONS.runOne,
    completedSession: LINEAGE_SESSIONS.runOne + 1,
    stateReason: "COMPLETED_WITHIN_THE_DECLARED_BOUNDS",
    /** The first touch of an untouched holdout rests on no reuse at all. */
    disclosure: [],
    limitations: [
      "A_SYNTHETIC_DEMONSTRATION_IS_NOT_QUALIFICATION_EVIDENCE",
      "NO_PROVIDER_IS_SELECTED_AND_G1_IS_OPEN",
    ],
    results: { expectancy: 34, profitFactor: 152, winRate: 47, sharpe: 71, drawdown: -820, trades: 64 },
  },
  {
    runId: RUNS.failed,
    registration: REGISTRATIONS.original,
    challenger: CHALLENGERS.pullback,
    baseline: CHAMPIONS.pullback,
    state: "FAILED",
    evaluationClass: "EXPLORATORY_REUSE",
    lockedSet: LOCKED_SET_A,
    ordinal: 2,
    startedSession: LINEAGE_SESSIONS.runTwo,
    completedSession: LINEAGE_SESSIONS.runTwo,
    stateReason: "MANIFEST_UNAVAILABLE",
    disclosure: ["EXPLORATORY_REUSE_OF_AN_ALREADY_EXPOSED_LOCKED_SET"],
    limitations: ["THE_RUN_PRODUCED_NO_RESULT_AND_STILL_SPENT_A_TRIAL"],
    results: null,
  },
  {
    runId: RUNS.reuse,
    registration: REGISTRATIONS.amendment,
    challenger: CHALLENGERS.pullback,
    baseline: CHAMPIONS.pullback,
    state: "COMPLETED",
    evaluationClass: "EXPLORATORY_REUSE",
    lockedSet: LOCKED_SET_A,
    ordinal: 3,
    startedSession: LINEAGE_SESSIONS.runThree,
    completedSession: LINEAGE_SESSIONS.runThree + 1,
    stateReason: "COMPLETED_WITHIN_THE_DECLARED_BOUNDS",
    disclosure: [
      "EXPLORATORY_REUSE_OF_AN_ALREADY_EXPOSED_LOCKED_SET",
      "NEVER_PRESENTED_AS_FRESH_OUT_OF_SAMPLE_EVIDENCE",
    ],
    limitations: [
      "A_SYNTHETIC_DEMONSTRATION_IS_NOT_QUALIFICATION_EVIDENCE",
      "THE_EVIDENCE_RESTS_ON_DATA_THE_LEDGER_RECORDS_AS_EXPOSED",
    ],
    results: { expectancy: 41, profitFactor: 168, winRate: 49, sharpe: 78, drawdown: -760, trades: 64 },
  },
  {
    runId: RUNS.abandonedLineage,
    registration: REGISTRATIONS.amendment,
    challenger: CHALLENGERS.pullback,
    baseline: CHAMPIONS.pullback,
    state: "ABANDONED",
    evaluationClass: "EXPLORATORY_REUSE",
    lockedSet: LOCKED_SET_A,
    ordinal: 4,
    startedSession: LINEAGE_SESSIONS.runFour,
    completedSession: LINEAGE_SESSIONS.runFour,
    stateReason: "RELATED_LINEAGE_EXPOSED",
    disclosure: ["A_RELATED_REGISTRATION_HAD_ALREADY_EXPOSED_THIS_SET"],
    limitations: ["AN_ABANDONED_RUN_STILL_COUNTS_AGAINST_THE_TRIAL_BUDGET"],
    results: null,
  },
  {
    runId: RUNS.abandonedReuse,
    registration: REGISTRATIONS.renamedReuse,
    challenger: CHALLENGERS.peadShort,
    /*
     * THE NAMED BASELINE DOES NOT RESOLVE.
     *
     * The record names one, the registry holds no such version, and **a run without a named
     * baseline renders incomplete** rather than as a result. The reference stays visible; the
     * comparison it would have supported carries the state.
     */
    baseline: null,
    state: "ABANDONED",
    evaluationClass: "CONFIRMATORY",
    lockedSet: LOCKED_SET_B,
    ordinal: 5,
    startedSession: LINEAGE_SESSIONS.runFive,
    completedSession: LINEAGE_SESSIONS.runFive,
    stateReason: "OUT_OF_SAMPLE_ALREADY_CONSUMED",
    disclosure: [
      "THE_LOCKED_SET_OVERLAPS_ONE_ALREADY_EVALUATED_UNDER_ANOTHER_REGISTRATION",
      "A_NEW_REGISTRATION_IDENTITY_DOES_NOT_MAKE_EXPOSED_DATA_UNTOUCHED",
    ],
    limitations: [
      "THE_DECLARED_CONFIRMATORY_CLASS_WAS_REFUSED_AND_NOT_DOWNGRADED",
      "NO_RESULT_MAY_BE_READ_FROM_A_REFUSED_RUN",
    ],
    results: null,
  },
  {
    runId: RUNS.reproduction,
    registration: REGISTRATIONS.amendment,
    challenger: CHALLENGERS.pullback,
    baseline: CHAMPIONS.pullback,
    state: "COMPLETED",
    evaluationClass: "DETERMINISTIC_REPRODUCTION",
    lockedSet: LOCKED_SET_A,
    ordinal: 6,
    startedSession: LINEAGE_SESSIONS.runSix,
    completedSession: LINEAGE_SESSIONS.runSix,
    stateReason: "REPRODUCED_THE_RECORDED_RESULT_EXACTLY",
    disclosure: ["A_REPRODUCTION_NOTE_ONLY_AND_NO_NEW_EXPOSURE_ENTRY"],
    limitations: ["A_REPRODUCTION_CONFIRMS_REPRODUCIBILITY_AND_NOTHING_ELSE"],
    /** Byte for byte the reused run's figures: that is what a reproduction reproduces. */
    results: { expectancy: 41, profitFactor: 168, winRate: 49, sharpe: 78, drawdown: -760, trades: 64 },
  },
];

/** A run that ends counts a trial — **except a deterministic reproduction, which spends none.** */
function countsAgainstBudget(spec: RunSpec): boolean {
  if (spec.evaluationClass === "DETERMINISTIC_REPRODUCTION") {
    return false;
  }
  return (["COMPLETED", "FAILED", "ABANDONED"] as readonly ResearchRunState[]).includes(
    spec.state,
  );
}

export function syntheticResearchRuns(
  asOf: string,
  days: readonly string[],
): ResearchRunPayload {
  const items: ResearchRun[] = RUN_SPECS.map((spec) => {
    const resolvedBaseline = spec.baseline !== null;
    const baselineId = spec.baseline ?? "pullback-long-v4-baseline";
    /*
     * THE SAME ADMISSION GATE THE STRATEGY SCREEN READS — one definition, two consumers.
     *
     * §D2.7 would let an authorized research run satisfy required input 3 from its own
     * `BACKTEST_SIMULATED` fills. **No run has produced any**: backtesting is NOT STARTED, no
     * research engine exists and no result in this fixture is an outcome of anything, so the
     * fill history is absent here exactly as it is on the strategy screen.
     */
    const capacity = capacityFor({
      strategyVersion: spec.challenger,
      windowScope: `${days[0]}/${days[days.length - 1]}`,
      evaluationMs: Date.parse(asOf),
      /*
       * A CHALLENGER'S SHORT EXPOSURE IS NOT DETERMINED, so borrow history is not declared
       * inapplicable. Declaring an input `NOT_APPLICABLE` is a positive claim about the
       * evaluated population, and no research run has one to make it about.
       */
      shortExposurePresent: true,
      asOf,
    });
    return {
      run_id: spec.runId,
      registration_ref: demoRef(spec.registration, "registration", "ENDPOINT"),
      challenger_version: spec.challenger,
      baseline_ref: demoRef(baselineId, "strategy_version", "ENDPOINT"),
      state: spec.state,
      evaluation_class: spec.evaluationClass,
      dataset_ref: demoRef(spec.lockedSet, "evidence", "AUTHORIZED_READ"),
      counts_against_budget: countsAgainstBudget(spec),
      trial_ordinal: count("research.trial_ordinal", spec.ordinal, asOf),
      results: spec.results === null ? absentResults() : completedResults(asOf, spec.results),
      decomposition:
        spec.results === null
          ? []
          : [
              {
                axis: demoReason("REGIME"),
                bucket: demoReason("TRENDING_UP"),
                value: scaled("expectancy.r", "R_MULTIPLE", spec.results.expectancy + 18, asOf),
              },
              {
                axis: demoReason("REGIME"),
                bucket: demoReason("RANGE_BOUND"),
                value: scaled("expectancy.r", "R_MULTIPLE", spec.results.expectancy - 26, asOf),
              },
              {
                axis: demoReason("REGIME"),
                bucket: demoReason("HIGH_VOLATILITY_STRESS"),
                value: scaled("expectancy.r", "R_MULTIPLE", spec.results.expectancy - 44, asOf),
              },
              {
                axis: demoReason("SECTOR"),
                bucket: demoReason("INFORMATION_TECHNOLOGY"),
                value: scaled("expectancy.r", "R_MULTIPLE", spec.results.expectancy + 9, asOf),
              },
              {
                axis: demoReason("SECTOR"),
                bucket: demoReason("CONSUMER_DISCRETIONARY"),
                value: scaled("expectancy.r", "R_MULTIPLE", spec.results.expectancy - 12, asOf),
              },
              {
                axis: demoReason("FACTOR_BUCKET"),
                bucket: demoReason("HIGH_MOMENTUM"),
                value: scaled("expectancy.r", "R_MULTIPLE", spec.results.expectancy + 14, asOf),
              },
            ],
      /**
       * THE ADMISSION GATE'S OWN ANSWER — ADR-0032 §12.3.3, the same gate Area 4 reads.
       *
       * The first unmet condition is the required-input stage, and the declaration beside it
       * names every dependency: **G1 is OPEN** and no provider is selected, no model declares
       * a participation limit, an execution horizon, an impact function or a cost tolerance,
       * **G5 is OPEN**, and no overlap set has been determined. **No capacity is estimated.**
       */
      capacity: capacity.value,
      capacity_declaration: capacity.declaration,
      stress:
        spec.results === null
          ? []
          : [
              {
                scenario: demoReason("GAP_DOWN_FIVE_PERCENT_AT_THE_OPEN"),
                value: percent("research.stress_impact", -1140, asOf),
              },
              {
                scenario: demoReason("LIQUIDITY_HALVED_FOR_ONE_SESSION"),
                value: percent("research.stress_impact", -430, asOf),
              },
              {
                scenario: demoReason("BORROW_UNAVAILABLE_FOR_THE_SHORT_LEG"),
                value: notApplicable("research.stress_impact", "PERCENT"),
              },
            ],
      reproducibility: {
        manifest: REPRODUCIBILITY.manifest,
        /** Sharadar price data never renders as `PUBLIC_PIT`, and no provider is selected. */
        profile: demoReason("PROVIDER_REALISTIC_PIT"),
        revision_view: REPRODUCIBILITY.revision_view,
        code_identity: REPRODUCIBILITY.code_identity,
        config_identity: REPRODUCIBILITY.config_identity,
        seeds: [1013904223, 1664525],
        environment: "RESEARCH",
      },
      baseline_comparison: resolvedBaseline
        ? spec.results === null
          ? [
              {
                measure: demoReason("BASELINE_EXPECTANCY_R"),
                value: unavailable(
                  "expectancy.r",
                  "R_MULTIPLE",
                  "NOT_YET_AVAILABLE",
                  "UPSTREAM_INPUT_MISSING",
                ),
              },
            ]
          : [
              {
                measure: demoReason("BASELINE_EXPECTANCY_R"),
                value: scaled("expectancy.r", "R_MULTIPLE", 22, asOf),
              },
              {
                measure: demoReason("BASELINE_WIN_RATE"),
                value: scaled("win_rate", "RATIO", 44, asOf),
              },
            ]
        : [
            {
              measure: demoReason("BASELINE_EXPECTANCY_R"),
              value: unavailable(
                "expectancy.r",
                "R_MULTIPLE",
                "NOT_YET_AVAILABLE",
                "REFERENT_NOT_FOUND",
              ),
            },
            {
              measure: demoReason("BASELINE_WIN_RATE"),
              value: unavailable("win_rate", "RATIO", "NOT_YET_AVAILABLE", "REFERENT_NOT_FOUND"),
            },
          ],
      baseline_state: resolvedBaseline
        ? { availability: "AVAILABLE", reason: "NONE" }
        : { availability: "NOT_YET_AVAILABLE", reason: "REFERENT_NOT_FOUND" },
      started_at: instantValue(
        "research.run_started_at",
        instantAt(days, spec.startedSession),
        asOf,
      ),
      completed_at:
        spec.state === "PLANNED" || spec.state === "RUNNING"
          ? unavailable(
              "research.run_completed_at",
              "DIMENSIONLESS",
              "NOT_YET_AVAILABLE",
              "UPSTREAM_INPUT_MISSING",
            )
          : instantValue(
              "research.run_completed_at",
              instantAt(days, spec.completedSession),
              asOf,
            ),
      window: runWindow(days, 0, 380),
      state_reason: demoReason(spec.stateReason),
      exposure_disclosure: spec.disclosure.map(demoReason),
      limitations: spec.limitations.map(demoReason),
    };
  });

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("STARTED_AT_DESCENDING"),
      tiebreak: demoReason("RUN_ID_ASCENDING"),
    },
    evaluation_classes: [...EVALUATION_CLASSES],
    run_states: [...RESEARCH_RUN_STATES],
  };
}

/* ==================================================================== Area 17 — queue */

interface QueueSpec {
  readonly itemId: string;
  readonly triggerId: string;
  readonly triggerArea?: "STRATEGY_HEALTH" | "SHORT_SIDE" | "DATA_QUALITY";
  readonly issue: string;
  readonly experiment: string;
  readonly baseline: string;
  readonly state: (typeof RESEARCH_QUEUE_STATES)[number];
  readonly priority: string;
  readonly module: string;
  readonly session: number;
  readonly awaiting: readonly string[];
  readonly dependencies: readonly string[];
  readonly evidence: readonly string[];
  readonly challenger?: string;
  readonly registration?: string;
  readonly withdrawal?: string;
}

const QUEUE_SPECS: readonly QueueSpec[] = [
  {
    itemId: QUEUE_ITEMS.pullback,
    triggerId: "demo-fact-rolling-expectancy-pullback-long-v2",
    triggerArea: "STRATEGY_HEALTH",
    issue: "ROLLING_EXPECTANCY_BELOW_RESEARCHED_BAND",
    experiment: "PULLBACK_ENTRY_TIMING_VARIATION_AGAINST_THE_UNCHANGED_CHAMPION",
    baseline: CHAMPIONS.pullback,
    state: "REGISTERED",
    priority: "HIGH",
    module: "PULLBACK_LONG",
    session: LINEAGE_SESSIONS.queued,
    awaiting: [
      "A_WRITTEN_AUTHORIZATION_TO_RUN_RESEARCH_AGAINST_REAL_DATA",
      "A_QUALIFIED_POINT_IN_TIME_PROVIDER_G1_IS_OPEN",
    ],
    dependencies: ["A_SELECTED_PROVIDER", "AN_IMMUTABLE_RESEARCH_MANIFEST"],
    evidence: ["demo-evidence-cluster-fading-trend-0001"],
    challenger: CHALLENGERS.pullback,
    registration: REGISTRATIONS.original,
  },
  {
    itemId: QUEUE_ITEMS.borrow,
    triggerId: "demo-fact-borrow-incident-0004",
    triggerArea: "STRATEGY_HEALTH",
    issue: "REPEATED_BORROW_RECALL_BEFORE_TARGET",
    experiment: "SHORT_ENTRY_WITH_AND_WITHOUT_A_BORROW_AND_SQUEEZE_FILTER",
    baseline: CHAMPIONS.peadShort,
    state: "PREREGISTRATION_DRAFTED",
    priority: "HIGH",
    module: "PEAD_SHORT",
    session: LINEAGE_SESSIONS.healthReduced,
    awaiting: [
      "HISTORICAL_BORROW_QUALIFICATION_G5_IS_OPEN",
      "A_WRITTEN_AUTHORIZATION_FOR_SHORT_RESEARCH",
    ],
    dependencies: ["A_QUALIFIED_HISTORICAL_BORROW_FEED"],
    evidence: ["demo-evidence-borrow-recall-0001"],
  },
  {
    itemId: QUEUE_ITEMS.missed,
    triggerId: "demo-fact-missed-pattern-0001",
    issue: "REPEATED_MISSES_IN_ONE_TRADE_TEMPLATE",
    experiment: "RANKED_ENTRY_BASELINE_AGAINST_THE_CURRENT_SHORTLIST_RULE",
    baseline: "breakout-long-v3",
    state: "QUEUED",
    priority: "MEDIUM",
    module: "BREAKOUT_LONG",
    session: 450,
    awaiting: ["A_BRAIN_RUNTIME_THAT_JOURNALS_DECISIONS"],
    dependencies: ["A_BRAIN_RUNTIME", "A_QUALIFIED_PRICE_HISTORY"],
    evidence: [],
  },
  {
    itemId: QUEUE_ITEMS.duplicate,
    triggerId: "demo-fact-rolling-expectancy-pullback-long-v2",
    triggerArea: "STRATEGY_HEALTH",
    issue: "ROLLING_EXPECTANCY_BELOW_RESEARCHED_BAND",
    experiment: "PULLBACK_ENTRY_TIMING_VARIATION_AGAINST_THE_UNCHANGED_CHAMPION",
    baseline: CHAMPIONS.pullback,
    state: "WITHDRAWN",
    priority: "LOW",
    module: "PULLBACK_LONG",
    session: LINEAGE_SESSIONS.queued + 2,
    awaiting: [],
    dependencies: [],
    evidence: [],
    withdrawal: "DUPLICATE_OF_OPEN_ITEM",
  },
  {
    itemId: QUEUE_ITEMS.aiExperiment,
    triggerId: "demo-fact-ai-experiment-request-0001",
    issue: "AI_CONTRIBUTION_HAS_NEVER_BEEN_MEASURED",
    experiment: "DETERMINISTIC_ONLY_VERSUS_STRUCTURED_EVIDENCE_VERSUS_STRUCTURED_EVIDENCE_PLUS_LLM",
    baseline: "breakout-long-v3",
    state: "REGISTERED",
    priority: "MEDIUM",
    module: "CROSS_MODULE_AI_EVIDENCE",
    session: 458,
    awaiting: [
      "AN_AI_RESEARCH_AGENT_THAT_DOES_NOT_EXIST",
      "A_WRITTEN_AUTHORIZATION_TO_RUN_EXPERIMENT_E",
    ],
    dependencies: ["A_BRAIN_RUNTIME", "AN_APPROVED_SOURCE_DOCUMENT_SET"],
    evidence: [],
    registration: REGISTRATIONS.aiExperiment,
  },
];

export function syntheticResearchQueue(
  asOf: string,
  days: readonly string[],
): ResearchQueuePayload {
  const items: ResearchQueueItem[] = QUEUE_SPECS.map((spec) => ({
    item_id: spec.itemId,
    trigger_ref: demoRef(spec.triggerId, "source_fact", "AUTHORIZED_READ", spec.triggerArea),
    issue: demoReason(spec.issue),
    proposed_experiment: demoReason(spec.experiment),
    baseline_ref: demoRef(spec.baseline, "strategy_version", "ENDPOINT"),
    state: spec.state,
    ...(spec.withdrawal === undefined
      ? {}
      : {
          withdrawal_reason: token("research.withdrawal_reason", spec.withdrawal, asOf),
        }),
    awaiting_authorizations: spec.awaiting.map(demoReason),
    priority: demoReason(spec.priority),
    queued_at: instantValue("research.queued_at", instantAt(days, spec.session), asOf),
    strategy_module: demoReason(spec.module),
    evidence_refs: refListOf(
      spec.evidence.map((id) => demoRef(id, "evidence", "AUTHORIZED_READ")),
      "ZERO_OR_MORE",
      asOf,
    ),
    dependencies: spec.dependencies.map(demoReason),
    ...(spec.challenger === undefined
      ? {}
      : { challenger_ref: demoRef(spec.challenger, "strategy_version", "ENDPOINT") }),
    ...(spec.registration === undefined
      ? {}
      : { registration_ref: demoRef(spec.registration, "registration", "ENDPOINT") }),
    history: [
      {
        state: "QUEUED" as const,
        at: instantAt(days, spec.session),
        note: demoReason("RAISED_BY_THE_RECORDED_TRIGGER"),
      },
      ...(spec.state === "QUEUED"
        ? []
        : [
            {
              state:
                spec.state === "WITHDRAWN"
                  ? ("WITHDRAWN" as const)
                  : ("PREREGISTRATION_DRAFTED" as const),
              at: instantAt(days, spec.session + 1),
              note: demoReason(
                spec.state === "WITHDRAWN"
                  ? "WITHDRAWN_AS_A_DUPLICATE_OF_AN_OPEN_ITEM"
                  : "A_PREREGISTRATION_WAS_DRAFTED",
              ),
            },
          ]),
      ...(spec.state === "REGISTERED"
        ? [
            {
              state: "REGISTERED" as const,
              at: instantAt(days, spec.session + 2),
              note: demoReason("THE_PREREGISTRATION_WAS_RECORDED_IMMUTABLY"),
            },
          ]
        : []),
    ],
  }));

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("PRIORITY_DESCENDING"),
      tiebreak: demoReason("ITEM_ID_ASCENDING"),
    },
    queue_states: [...RESEARCH_QUEUE_STATES],
  };
}

/* =============================================================== Area 18 — hypotheses */

interface LedgerEntrySpec {
  readonly entryId: string;
  readonly registration: string;
  readonly challenger: string;
  readonly evaluationClass: EvaluationClass;
  readonly session: number;
  readonly extent: string;
  /** Hundredths, or `null` where the extents cannot be compared at all. */
  readonly overlapHundredths: number | null;
}

const SET_A_LEDGER: readonly LedgerEntrySpec[] = [
  {
    entryId: "demo-exposure-0001",
    registration: REGISTRATIONS.original,
    challenger: CHALLENGERS.pullback,
    evaluationClass: "CONFIRMATORY",
    session: LINEAGE_SESSIONS.runOne,
    extent: "THE_WHOLE_LOCKED_SET",
    /** A MEASURED ZERO: the set was untouched, and that is a result rather than an absence. */
    overlapHundredths: 0,
  },
  {
    entryId: "demo-exposure-0002",
    registration: REGISTRATIONS.original,
    challenger: CHALLENGERS.pullback,
    evaluationClass: "EXPLORATORY_REUSE",
    session: LINEAGE_SESSIONS.runTwo,
    extent: "THE_WHOLE_LOCKED_SET",
    overlapHundredths: 100,
  },
  {
    entryId: "demo-exposure-0003",
    registration: REGISTRATIONS.amendment,
    challenger: CHALLENGERS.pullback,
    evaluationClass: "EXPLORATORY_REUSE",
    session: LINEAGE_SESSIONS.runThree,
    extent: "THE_WHOLE_LOCKED_SET",
    overlapHundredths: 100,
  },
  {
    entryId: "demo-exposure-0004",
    registration: REGISTRATIONS.renamedReuse,
    challenger: CHALLENGERS.peadShort,
    evaluationClass: "CONFIRMATORY",
    session: LINEAGE_SESSIONS.runFive,
    extent: "A_RE_CUT_WITH_ONE_ADDITIONAL_YEAR",
    /** The re-cut is a new identity over four-fifths of the same data. */
    overlapHundredths: SET_B_OVERLAP_HUNDREDTHS,
  },
];

const SET_C_LEDGER: readonly LedgerEntrySpec[] = [
  {
    entryId: "demo-exposure-0005",
    registration: REGISTRATIONS.original,
    challenger: CHALLENGERS.pullback,
    evaluationClass: "EXPLORATORY_REUSE",
    session: LINEAGE_SESSIONS.runTwo,
    extent: "A_ROLLING_RE_CUT_WHOSE_BOUNDARY_WAS_NOT_RECORDED",
    /** INCOMPARABLE IS NOT DISJOINT. An unmeasurable overlap fails closed. */
    overlapHundredths: null,
  },
];

interface RegistrationSpec {
  readonly registrationId: string;
  readonly queueItem: string;
  readonly module: string;
  readonly thesis: string;
  readonly baseline: string;
  readonly variation: string;
  readonly session: number;
  readonly declared: EvaluationClass;
  readonly lockedSet: string;
  readonly ledger: readonly LedgerEntrySpec[];
  readonly ledgerCompleteness: "COMPLETE" | "PARTIAL" | "UNKNOWN";
  readonly refusal?: string;
  readonly state: string;
  readonly parent?: string;
  readonly amendments: readonly string[];
  readonly related: readonly string[];
  readonly supersededBy?: string;
  readonly linkedRuns: readonly string[];
  readonly budget: { granted: number; consumed: number; remaining: number };
  readonly ownTrials: number;
  readonly success: readonly string[];
  readonly failure: readonly string[];
  readonly dataRequirements: readonly string[];
}

const REGISTRATION_SPECS: readonly RegistrationSpec[] = [
  {
    registrationId: REGISTRATIONS.original,
    queueItem: QUEUE_ITEMS.pullback,
    module: "PULLBACK_LONG",
    thesis: "A_LATER_PULLBACK_ENTRY_IMPROVES_EXPECTANCY_WITHOUT_RAISING_TAIL_LOSS",
    baseline: CHAMPIONS.pullback,
    variation: "ENTRY_DELAYED_UNTIL_A_CONFIRMED_REVERSAL_BAR",
    session: LINEAGE_SESSIONS.registered,
    declared: "CONFIRMATORY",
    lockedSet: LOCKED_SET_A,
    ledger: SET_A_LEDGER,
    ledgerCompleteness: "COMPLETE",
    state: "AMENDED",
    amendments: [REGISTRATIONS.amendment],
    related: [REGISTRATIONS.renamedReuse],
    supersededBy: undefined,
    linkedRuns: [RUNS.confirmatory, RUNS.failed],
    budget: LINEAGE_BUDGET,
    ownTrials: OWN_TRIALS[REGISTRATIONS.original],
    success: [
      "EXPECTANCY_IMPROVES_BY_AT_LEAST_A_QUARTER_R_AGAINST_THE_NAMED_BASELINE",
      "MAXIMUM_DRAWDOWN_DOES_NOT_WORSEN",
    ],
    failure: [
      "EXPECTANCY_DOES_NOT_IMPROVE_AGAINST_THE_NAMED_BASELINE",
      "TAIL_LOSS_WORSENS_BY_MORE_THAN_HALF_AN_R",
    ],
    dataRequirements: ["A_SURVIVORSHIP_AWARE_UNIVERSE", "A_REVISION_AWARE_PRICE_HISTORY"],
  },
  {
    registrationId: REGISTRATIONS.amendment,
    queueItem: QUEUE_ITEMS.pullback,
    module: "PULLBACK_LONG",
    thesis: "A_LATER_PULLBACK_ENTRY_IMPROVES_EXPECTANCY_WITHOUT_RAISING_TAIL_LOSS",
    baseline: CHAMPIONS.pullback,
    variation: "ENTRY_DELAYED_UNTIL_A_CONFIRMED_REVERSAL_BAR_WITH_A_VOLUME_CONDITION",
    session: LINEAGE_SESSIONS.amended,
    declared: "EXPLORATORY_REUSE",
    lockedSet: LOCKED_SET_A,
    ledger: SET_A_LEDGER,
    ledgerCompleteness: "COMPLETE",
    state: "REGISTERED",
    parent: REGISTRATIONS.original,
    amendments: [],
    related: [REGISTRATIONS.original],
    linkedRuns: [RUNS.reuse, RUNS.abandonedLineage, RUNS.reproduction],
    budget: LINEAGE_BUDGET,
    ownTrials: OWN_TRIALS[REGISTRATIONS.amendment],
    success: ["EXPECTANCY_IMPROVES_AGAINST_THE_NAMED_BASELINE_UNDER_DISCLOSED_REUSE"],
    failure: [
      "EXPECTANCY_DOES_NOT_IMPROVE_AGAINST_THE_NAMED_BASELINE",
      "THE_VOLUME_CONDITION_REMOVES_MORE_WINNERS_THAN_LOSERS",
    ],
    dataRequirements: ["THE_SAME_LOCKED_SET_AS_THE_PARENT_REGISTRATION"],
  },
  {
    registrationId: REGISTRATIONS.renamedReuse,
    queueItem: QUEUE_ITEMS.pullback,
    module: "PEAD_SHORT",
    thesis: "A_FRESH_HOLDOUT_CONFIRMS_THE_SHORT_ENTRY_VARIATION",
    baseline: CHAMPIONS.peadShort,
    variation: "SHORT_ENTRY_WITH_A_BORROW_AND_SQUEEZE_FILTER",
    session: LINEAGE_SESSIONS.runFive - 2,
    declared: "CONFIRMATORY",
    lockedSet: LOCKED_SET_B,
    ledger: SET_A_LEDGER,
    ledgerCompleteness: "COMPLETE",
    /**
     * THE NEGATIVE CONTROL §2.7.1 EXISTS FOR.
     *
     * A new registration identity, a new Challenger identity and a new research question,
     * evaluated against a holdout the ledger already records as exposed, is **refused** — and
     * is not admitted as fresh out-of-sample evidence under any name.
     */
    refusal: "OUT_OF_SAMPLE_ALREADY_CONSUMED",
    state: "REGISTERED",
    amendments: [],
    related: [REGISTRATIONS.original, REGISTRATIONS.amendment],
    linkedRuns: [RUNS.abandonedReuse],
    budget: LINEAGE_BUDGET,
    ownTrials: OWN_TRIALS[REGISTRATIONS.renamedReuse],
    success: ["THE_SHORT_VARIATION_CONFIRMS_ON_AN_UNTOUCHED_HOLDOUT"],
    failure: ["THE_SHORT_VARIATION_DOES_NOT_CONFIRM_ON_AN_UNTOUCHED_HOLDOUT"],
    dataRequirements: ["AN_UNTOUCHED_HOLDOUT", "A_QUALIFIED_HISTORICAL_BORROW_FEED"],
  },
  {
    registrationId: REGISTRATIONS.unknownHistory,
    queueItem: QUEUE_ITEMS.borrow,
    module: "PEAD_SHORT",
    thesis: "THE_BORROW_FILTER_REMOVES_THE_RECALL_CLUSTER_WITHOUT_REMOVING_THE_EDGE",
    baseline: CHAMPIONS.peadShort,
    variation: "SHORT_ENTRY_GATED_ON_A_RECORDED_BORROW_STATE",
    session: LINEAGE_SESSIONS.runFive - 1,
    declared: "CONFIRMATORY",
    lockedSet: LOCKED_SET_C,
    ledger: SET_C_LEDGER,
    /** The ledger cannot be shown to cover every prior evaluation of the set. */
    ledgerCompleteness: "UNKNOWN",
    refusal: "EXPOSURE_HISTORY_UNKNOWN",
    state: "REGISTERED",
    amendments: [],
    related: [REGISTRATIONS.renamedReuse],
    linkedRuns: [],
    budget: LINEAGE_BUDGET,
    ownTrials: OWN_TRIALS[REGISTRATIONS.unknownHistory],
    success: ["THE_RECALL_CLUSTER_DISAPPEARS_AND_EXPECTANCY_HOLDS"],
    failure: ["THE_FILTER_REMOVES_MORE_EDGE_THAN_RECALL_RISK"],
    dataRequirements: ["A_QUALIFIED_HISTORICAL_BORROW_FEED_G5_IS_OPEN"],
  },
  {
    registrationId: REGISTRATIONS.aiExperiment,
    queueItem: QUEUE_ITEMS.aiExperiment,
    module: "CROSS_MODULE_AI_EVIDENCE",
    thesis: "STRUCTURED_EVIDENCE_PLUS_LLM_INTERPRETATION_REMOVES_MORE_BAD_CANDIDATES",
    baseline: "breakout-long-v3",
    variation: "THREE_MATCHED_ARMS_OVER_ONE_SHORTLIST",
    session: 460,
    declared: "EXPLORATORY_REUSE",
    lockedSet: "demo-locked-set-ai-arms",
    ledger: [],
    ledgerCompleteness: "COMPLETE",
    state: "REGISTERED",
    amendments: [],
    related: [],
    linkedRuns: [],
    budget: AI_BUDGET,
    ownTrials: 0,
    success: ["A_MATCHED_ARM_DIFFERENCE_EXCEEDS_ITS_STATED_UNCERTAINTY"],
    failure: ["THE_ARMS_DO_NOT_SEPARATE_BEYOND_THEIR_STATED_UNCERTAINTY"],
    dataRequirements: ["AN_APPROVED_SOURCE_DOCUMENT_SET", "A_MATCHED_CANDIDATE_POPULATION"],
  },
];

function ledgerEntries(
  specs: readonly LedgerEntrySpec[],
  asOf: string,
  days: readonly string[],
) {
  return specs.map((entry) => ({
    entry_id: entry.entryId,
    registration_ref: demoRef(entry.registration, "registration", "ENDPOINT"),
    challenger_version: entry.challenger,
    research_code_identity: REPRODUCIBILITY.code_identity,
    evaluation_class: entry.evaluationClass,
    at: instantAt(days, entry.session),
    requested_extent: demoReason(entry.extent),
    measured_overlap:
      entry.overlapHundredths === null
        ? unavailable(
            "research.overlap_fraction",
            "RATIO",
            "NOT_YET_AVAILABLE",
            "EXTENT_NOT_DETERMINABLE",
          )
        : scaled("research.overlap_fraction", "RATIO", entry.overlapHundredths, asOf),
  }));
}

export function syntheticHypotheses(
  asOf: string,
  days: readonly string[],
): HypothesisRegistrationPayload {
  const items: HypothesisRegistration[] = REGISTRATION_SPECS.map((spec) => ({
    registration_id: spec.registrationId,
    registered_at: instantAt(days, spec.session),
    immutable: true as const,
    trigger_ref: demoRef(spec.queueItem, "queue_item", "ENDPOINT"),
    strategy_module: demoReason(spec.module),
    thesis: demoReason(spec.thesis),
    baseline_ref: demoRef(spec.baseline, "strategy_version", "ENDPOINT"),
    variation: demoReason(spec.variation),
    trial_budget: {
      granted: count("research.trial_budget_granted", spec.budget.granted, asOf),
      consumed: count("research.trial_budget_consumed", spec.budget.consumed, asOf),
      remaining: count("research.trial_budget_remaining", spec.budget.remaining, asOf),
    },
    own_trial_count: count("research.trials_own", spec.ownTrials, asOf),
    success_criteria: spec.success.map(demoReason),
    failure_criteria: spec.failure.map(demoReason),
    data_requirements: spec.dataRequirements.map(demoReason),
    pins: {
      manifest: REPRODUCIBILITY.manifest,
      profile: demoReason("PROVIDER_REALISTIC_PIT"),
      revision_view: REPRODUCIBILITY.revision_view,
      factor_definition_version: "factor-definitions-demo-v2",
      research_code_identity: REPRODUCIBILITY.code_identity,
    },
    lineage: {
      ...(spec.parent === undefined
        ? {}
        : { parent_registration: demoRef(spec.parent, "registration", "ENDPOINT") }),
      related_registrations: refListOf(
        spec.related.map((id) => demoRef(id, "registration", "ENDPOINT")),
        "ZERO_OR_MORE",
        asOf,
      ),
      amendment_chain: refListOf(
        spec.amendments.map((id) => demoRef(id, "registration", "ENDPOINT")),
        "ZERO_OR_MORE",
        asOf,
      ),
      ...(spec.supersededBy === undefined
        ? {}
        : { superseded_by: demoRef(spec.supersededBy, "registration", "ENDPOINT") }),
    },
    exposure_ledger_ref: demoRef(spec.lockedSet, "evidence", "AUTHORIZED_READ"),
    exposure_ledger: {
      locked_set: spec.lockedSet,
      entry_count: count("research.exposure_entries", spec.ledger.length, asOf),
      entries: ledgerEntries(spec.ledger, asOf, days),
      completeness: spec.ledgerCompleteness,
      ...(spec.refusal === undefined ? {} : { refusal: demoReason(spec.refusal) }),
    },
    declared_evaluation_class: spec.declared,
    state: demoReason(spec.state),
    linked_results: refListOf(
      spec.linkedRuns.map((id) => demoRef(id, "research_run", "ENDPOINT")),
      "ZERO_OR_MORE",
      asOf,
    ),
  }));

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("REGISTERED_AT_DESCENDING"),
      tiebreak: demoReason("REGISTRATION_ID_ASCENDING"),
    },
    evaluation_classes: [...EVALUATION_CLASSES],
  };
}

/* ================================================== Area 15 — Champion / Challenger */

export function syntheticChampionChallenger(
  asOf: string,
  days: readonly string[],
): ChampionChallengerPayload {
  const noRealizedOutcome = {
    availability: "NOT_APPLICABLE" as const,
    reason: "NOT_DEFINED_FOR_SUBJECT" as const,
  };

  const items: ChampionChallengerComparison[] = [
    {
      champion_version: CHAMPIONS.pullback,
      challenger_version: CHALLENGERS.pullback,
      registration_ref: demoRef(REGISTRATIONS.amendment, "registration", "ENDPOINT"),
      overlap: [
        {
          measure: demoReason("SHARED_CANDIDATE_POPULATION"),
          value: scaled("comparison.overlap", "RATIO", 81, asOf),
        },
        {
          measure: demoReason("SHARED_ENTRY_DECISIONS"),
          value: scaled("comparison.overlap", "RATIO", 64, asOf),
        },
      ],
      divergence: [
        {
          measure: demoReason("ENTRY_DECISIONS_TAKEN_BY_ONE_VERSION_ONLY"),
          value: count("comparison.divergence_count", 23, asOf),
        },
        {
          measure: demoReason("EXPECTANCY_DIFFERENCE_AS_A_RATIO_OF_THE_CHAMPION"),
          value: scaled("comparison.divergence_ratio", "RATIO", 19, asOf),
        },
      ],
      exposure_difference: [
        {
          axis: demoReason("HIGH_MOMENTUM_FACTOR_BUCKET"),
          value: percent("comparison.exposure_difference", 640, asOf),
        },
        {
          axis: demoReason("CYCLICAL_INDUSTRIAL_CLUSTER"),
          value: percent("comparison.exposure_difference", -310, asOf),
        },
      ],
      evidence_completeness: "PARTIAL",
      /** DISPLAYED, never conferred. "Ready" would mean the packet's evidence is present. */
      readiness: demoReason("NOT_READY_SHADOW_EVIDENCE_IS_INCOMPLETE"),
      data_exposure_disclosure: [
        demoReason("EXPLORATORY_REUSE_OF_AN_ALREADY_EXPOSED_LOCKED_SET"),
        demoReason("NEVER_PRESENTED_AS_FRESH_OUT_OF_SAMPLE_EVIDENCE"),
      ],
      comparable_population: demoReason("CANDIDATES_BOTH_VERSIONS_OBSERVED_IN_THE_SAME_WINDOW"),
      window: runWindow(days, 380, 504),
      evaluation_class: "EXPLORATORY_REUSE",
      shadow_economics: [
        {
          measure: demoReason("HYPOTHETICAL_RETURN_UNDER_STATED_ASSUMPTIONS"),
          value: percent("comparison.shadow_hypothetical_return", 340, asOf),
        },
      ],
      shadow_assumptions: [
        demoReason("A_FIXED_SLIPPAGE_ASSUMPTION_OF_EIGHT_BASIS_POINTS"),
        demoReason("NO_MARKET_IMPACT_AND_NO_CAPACITY_CONSTRAINT_IS_MODELLED"),
        demoReason("HYPOTHETICAL_ECONOMICS_ARE_NEVER_PLACED_BESIDE_A_REALIZED_RESULT"),
      ],
      realized_outcomes: noRealizedOutcome,
      evidence_refs: refListOf(
        [
          demoRef(RUNS.reuse, "research_run", "ENDPOINT"),
          demoRef(RUNS.reproduction, "research_run", "ENDPOINT"),
        ],
        "ZERO_OR_MORE",
        asOf,
      ),
      shadow_refs: refListOf([], "ZERO_OR_MORE", asOf),
    },
    {
      champion_version: CHAMPIONS.peadShort,
      challenger_version: CHALLENGERS.peadShort,
      registration_ref: demoRef(REGISTRATIONS.unknownHistory, "registration", "ENDPOINT"),
      /*
       * AN INCOMPARABLE POPULATION PRODUCES NO OVERLAP FIGURE.
       *
       * The two versions did not observe one opportunity set, so every ratio over "the shared
       * population" would be a ratio over a population nobody defined.
       */
      overlap: [
        {
          measure: demoReason("SHARED_CANDIDATE_POPULATION"),
          value: insufficient("comparison.overlap", "RATIO"),
        },
      ],
      divergence: [
        {
          measure: demoReason("ENTRY_DECISIONS_TAKEN_BY_ONE_VERSION_ONLY"),
          value: insufficient("comparison.divergence_count", "COUNT"),
        },
      ],
      exposure_difference: [
        {
          axis: demoReason("SHORT_BORROW_CONSTRAINED_UNIVERSE"),
          value: unavailable(
            "comparison.exposure_difference",
            "PERCENT",
            "NOT_YET_AVAILABLE",
            "UPSTREAM_INPUT_MISSING",
          ),
        },
      ],
      evidence_completeness: "UNKNOWN",
      readiness: demoReason("NOT_READY_EXPOSURE_HISTORY_IS_UNKNOWN"),
      data_exposure_disclosure: [
        demoReason("THE_LEDGER_CANNOT_BE_SHOWN_TO_COVER_EVERY_PRIOR_EVALUATION"),
      ],
      comparable_population: demoReason("NO_COMPARABLE_POPULATION_HAS_BEEN_ESTABLISHED"),
      window: runWindow(days, 380, 504),
      evaluation_class: "EXPLORATORY_REUSE",
      shadow_economics: [],
      shadow_assumptions: [demoReason("NO_SHADOW_RUN_HAS_BEEN_AUTHORIZED_OR_PERFORMED")],
      realized_outcomes: noRealizedOutcome,
      evidence_refs: refListOf([], "ZERO_OR_MORE", asOf),
      shadow_refs: refListOf([], "ZERO_OR_MORE", asOf),
    },
  ];

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("CHALLENGER_VERSION_ASCENDING"),
      tiebreak: demoReason("CHAMPION_VERSION_ASCENDING"),
    },
  };
}

/* ============================================================ Area 21 — AI contribution */

const AI_MINIMUM_OBSERVATIONS = 120;

interface ArmSpec {
  readonly arm: string;
  readonly population: number;
  /** Hundredths of an R, or `null` where no outcome may be reported. */
  readonly outcomeHundredths: number | null;
  readonly uncertaintyHundredths: number | null;
}

export function syntheticAiContribution(
  asOf: string,
  days: readonly string[],
): AiContributionPayload {
  const arms = (specs: readonly ArmSpec[]) =>
    specs.map((spec) => ({
      arm: demoReason(spec.arm),
      population: count("ai.arm_population", spec.population, asOf),
      outcome:
        spec.outcomeHundredths === null
          ? insufficient("expectancy.r", "R_MULTIPLE")
          : scaled("expectancy.r", "R_MULTIPLE", spec.outcomeHundredths, asOf),
      uncertainty:
        spec.uncertaintyHundredths === null
          ? insufficient("ai.outcome_uncertainty", "R_MULTIPLE")
          : scaled("ai.outcome_uncertainty", "R_MULTIPLE", spec.uncertaintyHundredths, asOf),
    }));

  const provenance = (sourceIds: readonly string[]) => ({
    model_version: "demo-model-version-0001",
    prompt_version: "demo-prompt-version-0001",
    source_refs: refListOf(
      sourceIds.map((id) => demoRef(id, "source_fact", "AUTHORIZED_READ")),
      "ZERO_OR_MORE",
      asOf,
    ),
  });

  const causalAttribution = {
    availability: "UNEVALUATED" as const,
    reason: "NOT_YET_ASSESSED" as const,
    gate: demoReason("EXPERIMENT_E_HAS_NOT_BEEN_RUN"),
  };

  const items: AiContribution[] = [
    {
      experiment_ref: demoRef(REGISTRATIONS.aiExperiment, "registration", "ENDPOINT"),
      arms: arms([
        { arm: "DETERMINISTIC_ONLY", population: 412, outcomeHundredths: 28, uncertaintyHundredths: 11 },
        { arm: "STRUCTURED_EVIDENCE", population: 412, outcomeHundredths: 33, uncertaintyHundredths: 12 },
        {
          arm: "STRUCTURED_EVIDENCE_PLUS_LLM",
          population: 412,
          outcomeHundredths: 36,
          uncertaintyHundredths: 14,
        },
      ]),
      matched: true,
      ai_provenance: provenance([
        "demo-fact-ai-arm-assignment-0001",
        "demo-fact-ai-source-document-0001",
      ]),
      outages: [
        {
          from: instantAt(days, 470),
          to: instantAt(days, 472),
          handling: demoReason("CANDIDATES_IN_THE_OUTAGE_WINDOW_WERE_EXCLUDED_FROM_EVERY_ARM"),
        },
      ],
      minimum_observations_met: true,
      experiment: demoReason("EXPERIMENT_E_DETERMINISTIC_VERSUS_EVIDENCE_VERSUS_LLM"),
      minimum_observations: count(
        "performance.minimum_observations",
        AI_MINIMUM_OBSERVATIONS,
        asOf,
      ),
      matching_basis: demoReason("ONE_SHORTLIST_ONE_WINDOW_AND_ONE_REGIME_PARTITION"),
      assumptions: [
        demoReason("EVERY_ARM_SAW_THE_SAME_SHORTLIST_AT_THE_SAME_INSTANT"),
        demoReason("AI_MAY_REMOVE_A_CANDIDATE_AND_MAY_NEVER_RESTORE_ONE"),
        demoReason("THE_DIFFERENCE_IS_DESCRIPTIVE_AND_IS_NOT_AN_ATTRIBUTION"),
      ],
      causal_attribution: causalAttribution,
      coverage_note: demoReason("TWO_SESSIONS_OF_THE_WINDOW_ARE_EXCLUDED_BY_A_RECORDED_OUTAGE"),
    },
    {
      experiment_ref: demoRef(REGISTRATIONS.aiExperiment, "registration", "ENDPOINT"),
      arms: arms([
        { arm: "DETERMINISTIC_ONLY", population: 38, outcomeHundredths: null, uncertaintyHundredths: null },
        { arm: "STRUCTURED_EVIDENCE", population: 38, outcomeHundredths: null, uncertaintyHundredths: null },
        {
          arm: "STRUCTURED_EVIDENCE_PLUS_LLM",
          population: 38,
          outcomeHundredths: null,
          uncertaintyHundredths: null,
        },
      ]),
      matched: true,
      ai_provenance: provenance(["demo-fact-ai-arm-assignment-0002"]),
      outages: [],
      /** Below the declared minimum: the view reports the rule and NO difference. */
      minimum_observations_met: false,
      experiment: demoReason("EXPERIMENT_E_RESTRICTED_TO_THE_SHORT_SIDE"),
      minimum_observations: count(
        "performance.minimum_observations",
        AI_MINIMUM_OBSERVATIONS,
        asOf,
      ),
      matching_basis: demoReason("ONE_SHORTLIST_ONE_WINDOW_AND_ONE_REGIME_PARTITION"),
      assumptions: [demoReason("THE_SHORT_SIDE_POPULATION_IS_TOO_SMALL_TO_SEPARATE_ARMS")],
      causal_attribution: causalAttribution,
      coverage_note: demoReason("THE_WINDOW_IS_COVERED_AND_THE_POPULATION_IS_NOT_SUFFICIENT"),
    },
    {
      experiment_ref: demoRef(REGISTRATIONS.aiExperiment, "registration", "ENDPOINT"),
      arms: arms([
        { arm: "DETERMINISTIC_ONLY", population: 306, outcomeHundredths: null, uncertaintyHundredths: null },
        { arm: "STRUCTURED_EVIDENCE_PLUS_LLM", population: 118, outcomeHundredths: null, uncertaintyHundredths: null },
      ]),
      /** The arms were drawn from different populations, so the difference measures those. */
      matched: false,
      ai_provenance: provenance([]),
      outages: [
        {
          from: instantAt(days, 440),
          to: instantAt(days, 452),
          handling: demoReason("THE_LLM_ARM_WAS_UNAVAILABLE_AND_ITS_CANDIDATES_WERE_NOT_REPLACED"),
        },
      ],
      minimum_observations_met: true,
      experiment: demoReason("EXPERIMENT_E_OVER_AN_OUTAGE_AFFECTED_WINDOW"),
      minimum_observations: count(
        "performance.minimum_observations",
        AI_MINIMUM_OBSERVATIONS,
        asOf,
      ),
      matching_basis: demoReason("NO_MATCHING_WAS_POSSIBLE_ACROSS_THE_OUTAGE"),
      assumptions: [demoReason("AN_UNMATCHED_DIFFERENCE_MEASURES_THE_POPULATIONS_NOT_THE_ARMS")],
      causal_attribution: causalAttribution,
      coverage_note: demoReason("TWELVE_SESSIONS_ARE_MISSING_FROM_ONE_ARM_ONLY"),
    },
  ];

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("EXPERIMENT_ASCENDING"),
      tiebreak: demoReason("ARM_SET_ASCENDING"),
    },
  };
}

/* ================================================================== Area 16 — the loop */

interface StageSpec {
  readonly stage: string;
  readonly owner: string;
  readonly items: number;
  readonly blocked: number;
  readonly awaiting: readonly string[];
  readonly inputs: readonly string[];
  readonly outputs: readonly string[];
  readonly refusals: readonly string[];
  readonly pins: readonly string[];
  readonly queueItems: readonly string[];
  readonly automatable: boolean;
}

const HUMAN_ONLY_STAGE = "HUMAN_AUTHORIZED_RELEASE";

const STAGE_SPECS: readonly StageSpec[] = [
  {
    stage: "JOURNAL",
    owner: "EACH_PRODUCING_SUBSYSTEM_WRITES_ITS_OWN_RECORDS",
    items: 240,
    blocked: 0,
    awaiting: ["A_BRAIN_RUNTIME_THAT_JOURNALS_DECISIONS"],
    inputs: ["CANDIDATE_DECISIONS", "TRADE_EVENTS", "RISK_DECISIONS", "SAFETY_ACTIONS"],
    outputs: ["AN_IMMUTABLE_APPEND_ONLY_JOURNAL"],
    refusals: ["UNPINNED_VERSION", "SCHEMA_MISMATCH", "MISSING_LINEAGE"],
    pins: ["EVERY_VERSION_IDENTITY_ON_EVERY_RECORD"],
    queueItems: [],
    automatable: true,
  },
  {
    stage: "OUTCOME_AND_ATTRIBUTION",
    owner: "THE_ATTRIBUTION_COMPONENT_OF_THE_FUTURE_RESEARCH_ENGINE",
    items: 41,
    blocked: 3,
    awaiting: ["A_COMPLETE_ENOUGH_PRICE_PATH"],
    inputs: ["JOURNALED_TRADES", "REALIZED_ECONOMICS", "BENCHMARK_AND_REGIME_SERIES"],
    outputs: ["PER_TRADE_AND_PER_MODULE_ATTRIBUTION"],
    refusals: [
      "INCOMPLETE_PRICE_PATH",
      "INSUFFICIENT_OBSERVATIONS",
      "UNRESOLVED_CORPORATE_ACTION",
      "COST_TREATMENT_UNKNOWN",
    ],
    pins: ["THE_METRIC_DICTIONARY_VERSION"],
    queueItems: [],
    automatable: true,
  },
  {
    stage: "STRATEGY_HEALTH_DRIFT_AND_FAILURE_CLUSTERS",
    owner: "THE_HEALTH_MONITOR",
    items: 6,
    blocked: 1,
    awaiting: ["AN_ATTRIBUTION_COMPONENT_THAT_DOES_NOT_EXIST"],
    inputs: ["ATTRIBUTION", "EXECUTION_QUALITY", "CAPACITY", "REGIME", "INCIDENT_RECORDS"],
    outputs: ["HEALTH_TRANSITIONS", "DRIFT_MEASURES", "FAILURE_CLUSTERS"],
    refusals: ["INSUFFICIENT_OBSERVATIONS", "MISSING_ATTRIBUTION", "STALE_INPUT"],
    pins: ["STRATEGY_VERSION", "FACTOR_DEFINITION_VERSION"],
    queueItems: [],
    automatable: true,
  },
  {
    stage: "RESEARCH_QUEUE",
    owner: "THE_RESEARCH_QUEUE",
    items: 5,
    blocked: 4,
    awaiting: ["A_WRITTEN_AUTHORIZATION_TO_RUN_RESEARCH_AGAINST_REAL_DATA"],
    inputs: ["HEALTH_TRANSITIONS", "DRIFT", "FAILURE_CLUSTERS", "MISSED_OPPORTUNITY_PATTERNS"],
    outputs: ["PRIORITIZED_QUEUE_ITEMS"],
    refusals: [
      "NO_NAMED_BASELINE",
      "DUPLICATE_OF_OPEN_ITEM",
      "DEPENDENCY_UNAUTHORIZED",
      "DATA_UNAVAILABLE",
    ],
    pins: ["THE_TRIGGERING_EVIDENCE_IDENTITIES"],
    queueItems: [
      QUEUE_ITEMS.pullback,
      QUEUE_ITEMS.borrow,
      QUEUE_ITEMS.missed,
      QUEUE_ITEMS.duplicate,
      QUEUE_ITEMS.aiExperiment,
    ],
    automatable: true,
  },
  {
    stage: "PREREGISTERED_HYPOTHESIS",
    owner: "THE_HYPOTHESIS_REGISTRY",
    items: 5,
    blocked: 2,
    awaiting: ["AN_UNTOUCHED_HOLDOUT_OR_A_GOVERNED_REUSE_METHODOLOGY"],
    inputs: ["A_QUEUE_ITEM_AND_ITS_EVIDENCE"],
    outputs: ["AN_IMMUTABLE_PREREGISTRATION"],
    refusals: [
      "CRITERIA_INCOMPLETE",
      "NO_FAILURE_CRITERION",
      "BUDGET_EXHAUSTED",
      "BUDGET_EXHAUSTED_ACROSS_LINEAGE",
      "DATA_REQUIREMENT_UNAVAILABLE",
    ],
    pins: ["MANIFEST", "PROFILE", "REVISION_VIEW", "RESEARCH_CODE_IDENTITY"],
    queueItems: [QUEUE_ITEMS.pullback, QUEUE_ITEMS.borrow, QUEUE_ITEMS.aiExperiment],
    automatable: true,
  },
  {
    stage: "IMMUTABLE_CHALLENGER",
    owner: "THE_STRATEGY_VERSION_REGISTRY",
    items: 2,
    blocked: 0,
    awaiting: ["AN_AUTHORIZED_ENVIRONMENT_SET_THAT_EXCLUDES_ORDER_PRODUCING_STAGES"],
    inputs: ["A_REGISTRATION", "A_CHAMPION_VERSION", "A_VARIATION_DEFINITION"],
    outputs: ["AN_IMMUTABLE_CHALLENGER_STRATEGY_VERSION"],
    refusals: ["UNPINNED_VERSION", "NO_REGISTRATION", "UNAUTHORIZED_ENVIRONMENT"],
    pins: ["EVERY_VERSION_IDENTITY_THE_BRAIN_SPECIFICATION_REQUIRES"],
    queueItems: [QUEUE_ITEMS.pullback, QUEUE_ITEMS.borrow],
    automatable: true,
  },
  {
    stage: "AUTHORIZED_BACKTEST_LOCKED_OUT_OF_SAMPLE_AND_STRESS",
    owner: "THE_RESEARCH_RUNNER",
    items: 6,
    blocked: 2,
    awaiting: ["A_WRITTEN_AUTHORIZATION", "A_QUALIFIED_POINT_IN_TIME_PROVIDER_G1_IS_OPEN"],
    inputs: ["A_CHALLENGER", "A_REGISTRATION", "AN_IMMUTABLE_RESEARCH_MANIFEST"],
    outputs: ["RUN_RESULTS", "TRIAL_COUNT_INCREMENTS", "DECOMPOSITION", "STRESS_RESULTS"],
    refusals: [
      "BUDGET_EXHAUSTED",
      "OUT_OF_SAMPLE_ALREADY_CONSUMED",
      "EXPOSURE_HISTORY_UNKNOWN",
      "RELATED_LINEAGE_EXPOSED",
      "REPRODUCTION_MISMATCH",
      "AUTHORIZATION_MISSING",
    ],
    pins: ["MANIFEST", "PROFILE", "CODE_IDENTITY", "CONFIGURATION_IDENTITY", "SEEDS"],
    queueItems: [QUEUE_ITEMS.pullback],
    automatable: true,
  },
  {
    stage: "SHADOW",
    owner: "THE_SHADOW_RUNNER",
    items: 1,
    blocked: 1,
    awaiting: ["AN_AUTHORIZATION_FOR_SHADOW_OPERATION"],
    inputs: ["AN_IMMUTABLE_CHALLENGER", "THE_LIVE_POINT_IN_TIME_OPPORTUNITY_SET"],
    outputs: ["SHADOW_DECISIONS", "OVERLAP_AND_DIVERGENCE", "HYPOTHETICAL_ECONOMICS"],
    refusals: ["NO_OUT_OF_SAMPLE_EVIDENCE", "AUTHORIZATION_MISSING", "DATA_UNAVAILABLE"],
    pins: ["THE_CHALLENGER_VERSION_AND_EVERY_PIN_IT_CARRIES"],
    queueItems: [QUEUE_ITEMS.pullback],
    automatable: true,
  },
  {
    stage: "GOVERNANCE_PACKET",
    owner: "THE_GOVERNANCE_PACKET_ASSEMBLER",
    items: 4,
    blocked: 1,
    awaiting: ["COMPLETE_EVIDENCE_FOR_EVERY_CLAIM_THE_PACKET_MAKES"],
    inputs: ["EVERY_RUN", "THE_EXPOSURE_LEDGER", "SHADOW_EVIDENCE", "THE_CHAMPION_COMPARISON"],
    outputs: ["AN_ASSEMBLED_PACKET_AND_A_PLACE_FOR_THE_HUMAN_DECISION"],
    refusals: [
      "EVIDENCE_INCOMPLETE",
      "TRIAL_COUNT_UNRECORDED",
      "NO_BASELINE_COMPARISON",
      "CRITERIA_NOT_EVALUATED",
      "EXPOSURE_DISCLOSURE_INCOMPLETE",
    ],
    pins: ["EVERY_VERSION_AND_MANIFEST_IDENTITY_REFERENCED"],
    queueItems: [QUEUE_ITEMS.pullback],
    automatable: true,
  },
  {
    stage: HUMAN_ONLY_STAGE,
    owner: "A_HUMAN_THROUGH_THE_SEPARATELY_GOVERNED_DECISION_PATH",
    items: 2,
    blocked: 0,
    awaiting: ["A_HUMAN_DECISION_THAT_NO_AUTOMATION_MAY_TAKE"],
    inputs: ["A_READY_PACKET"],
    outputs: ["A_RECORDED_HUMAN_DECISION_WITH_AUTHORITY_TIME_AND_REASONING"],
    refusals: ["A_HUMAN_MAY_REFUSE_FOR_ANY_REASON_AND_THE_REASON_IS_RECORDED"],
    pins: ["THE_PACKET_AND_EVERY_VERSION_IT_AFFECTS"],
    queueItems: [QUEUE_ITEMS.pullback],
    /** **THE TENTH MAY NOT, EVER.** */
    automatable: false,
  },
];

export function syntheticFeedbackPipeline(asOf: string): FeedbackPipelinePayload {
  const stages: FeedbackStage[] = STAGE_SPECS.map((spec) => ({
    stage: demoReason(spec.stage),
    item_count: count("feedback.stage_items", spec.items, asOf),
    blocked_count: count("feedback.stage_blocked", spec.blocked, asOf),
    awaiting_authorizations: spec.awaiting.map(demoReason),
    item_refs: refListOf(
      spec.queueItems.map((id) => demoRef(id, "queue_item", "ENDPOINT")),
      "ZERO_OR_MORE",
      asOf,
    ),
    owner: demoReason(spec.owner),
    inputs: spec.inputs.map(demoReason),
    outputs: spec.outputs.map(demoReason),
    refusal_reasons: spec.refusals.map(demoReason),
    pins: spec.pins.map(demoReason),
    item_reference_scope: demoReason(
      "THE_QUEUE_ITEM_IDENTITY_EVERY_DOWNSTREAM_ITEM_STILL_CARRIES",
    ),
    automatable: spec.automatable,
  }));

  return {
    stages,
    human_only_stage: demoReason(HUMAN_ONLY_STAGE),
    environment: "RESEARCH",
    pins: {
      strategy_version: notApplicable("governance.version_pin", "DIMENSIONLESS"),
      factor_definition_version: "factor-definitions-demo-v2",
      risk_policy_version: "risk-policy-demo-0.0.0",
      entry_policy_version: notApplicable("governance.version_pin", "DIMENSIONLESS"),
      exit_policy_version: notApplicable("governance.version_pin", "DIMENSIONLESS"),
      model_version: notApplicable("governance.version_pin", "DIMENSIONLESS"),
      prompt_version: notApplicable("governance.version_pin", "DIMENSIONLESS"),
      code_identity: REPRODUCIBILITY.code_identity,
      config_identity: REPRODUCIBILITY.config_identity,
    },
  };
}
