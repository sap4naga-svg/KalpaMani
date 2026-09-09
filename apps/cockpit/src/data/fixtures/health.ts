/**
 * `StrategyHealth` and `StrategyVersion`, projected from the demonstration book and the
 * synthetic research lineage — Areas 5 and 20.
 *
 * **THE VIEW CAUSES NO TRANSITION.** Every state, transition, drift measure and failure
 * cluster below is a recorded fixture; nothing here evaluates a threshold, fires a rule,
 * reduces an entry, restores one or mutates a parameter. **A degradation shows the research
 * queue entry it created**, and it creates none.
 *
 * **THE HEALTH FIGURES A SUMMARY OWNS ARE THE SUMMARY'S.** Expectancy, drawdown, win rate and
 * the observation count come from `buildPerformanceSummary` — the same builder the strategy
 * performance screen reads — so this screen and that one cannot report two different numbers
 * for one version under one metric identifier (§12.2). The measures that are genuinely this
 * projection's own carry their own C7 identifiers and are not a second opinion of anything.
 */
import type { StrategyHealth, StrategyHealthPayload } from "@/contracts/strategy-models";
import type { StrategyVersionPayload, StrategyVersionRecord } from "@/contracts/strategy-models";
import type { MetricValue, VersionPins } from "@/contracts/values";
import { STRATEGY_HEALTH_STATES, type MaturityStage } from "@/contracts/vocabularies";
import type { StrategyHealthState } from "@/contracts/vocabularies";

import { BOOK, STRATEGY_VERSIONS, strategyVersionOf } from "./book";
import { capacityFor } from "./capacity";
import {
  count,
  demoRef,
  demoReason,
  insufficient,
  notApplicable,
  refListOf,
  scaled,
  sessionInstant,
  unavailable,
} from "./common";
import {
  CHALLENGER_VERSIONS,
  LINEAGE_SESSIONS,
  QUEUE_ITEMS,
  REGISTRATIONS,
  openTradesByVersion,
} from "./lineage";
import { buildPerformanceSummary } from "./summary";
import { buildRollingTailLoss } from "./tail-loss";

/**
 * The minimum observations the health contract declares.
 *
 * A PRESENTATION DEFINITION OF THIS DEMONSTRATION, and **not a production rule**: no
 * numerical value appearing in a synthetic example becomes one (feedback §3.3). It exists so
 * `INSUFFICIENT_OBSERVATIONS` renders the count AND the minimum rather than half the rule.
 */
export const HEALTH_MINIMUM_OBSERVATIONS = 20;

interface RecordedTransition {
  readonly from: StrategyHealthState;
  readonly to: StrategyHealthState;
  readonly session: number;
  readonly rule: string;
  readonly authority: string;
  readonly inputs: readonly string[];
}

interface HealthRecord {
  readonly versionId: string;
  readonly sinceSession: number;
  readonly transitions: readonly RecordedTransition[];
  readonly queueItem?: string;
  readonly recoveryAuthority: string;
  readonly recoveryRequirements: readonly string[];
  readonly safetyAction: string;
  readonly humanAction: string;
  readonly clusters: readonly {
    readonly cluster: string;
    readonly count: number;
    readonly evidence: readonly { readonly id: string; readonly area?: "SHORT_SIDE" | "DATA_QUALITY" }[];
  }[];
  /** Hundredths. A recorded drift score, never a computed one. */
  readonly factorDriftHundredths: number | null;
  readonly correlationHundredths: number | null;
  /*
   * THERE IS NO RECORDED TAIL-LOSS FIELD ANY MORE, AND THAT IS THE POINT.
   *
   * This record used to carry `tailLossHundredths` — four hand-written literals that were not
   * computed under any declared rule, which ADR-0032 §5.3 names in as many words. The rolling
   * tail loss is now CALCULATED from the same demonstration book every other figure on this
   * screen is projected from, so nothing is left here for a literal to contradict.
   */
}

/**
 * The recorded health of every book version.
 *
 * The STATE and its REASON are the book's own, so this screen and the strategy performance
 * screen read one record rather than two. What is added here is the history, the drift, the
 * clusters, the recovery authority and the queue entry a degradation created — Area 5's
 * subject, and the part the strategy screen deliberately declined to carry.
 */
const HEALTH_RECORDS: readonly HealthRecord[] = [
  {
    versionId: "breakout-long-v3",
    sinceSession: 320,
    transitions: [],
    recoveryAuthority: "NO_RECOVERY_REQUIRED_STATE_IS_HEALTHY",
    recoveryRequirements: [],
    safetyAction: "NONE_TAKEN",
    humanAction: "NONE_REQUIRED",
    clusters: [],
    factorDriftHundredths: 12,
    correlationHundredths: 31,
  },
  {
    versionId: "breakout-long-v2",
    sinceSession: LINEAGE_SESSIONS.retirement,
    transitions: [
      {
        from: "HEALTHY",
        to: "RETIRED",
        session: LINEAGE_SESSIONS.retirement,
        rule: "SUPERSEDED_BY_A_LATER_VERSION",
        authority: "HUMAN_GOVERNANCE_DECISION",
        inputs: ["demo-fact-supersession-breakout-long-v2"],
      },
    ],
    /*
     * NO QUEUE ENTRY, AND THAT IS NOT AN OMISSION.
     *
     * `RETIRED` here is a supersession, not a degradation, and Area 5 attaches a research
     * queue entry to a DEGRADATION. Attaching one anyway would report that a healthy version
     * being replaced had raised a research question nobody asked.
     */
    recoveryAuthority: "NONE_RETIRED_IS_TERMINAL_FOR_THIS_VERSION",
    recoveryRequirements: ["A_NEW_VERSION_IS_REQUIRED_RETIREMENT_IS_NOT_REVERSIBLE"],
    safetyAction: "NEW_ENTRIES_STOPPED_ON_RETIREMENT",
    humanAction: "NONE_REQUIRED",
    clusters: [],
    factorDriftHundredths: null,
    correlationHundredths: null,
  },
  {
    versionId: "pullback-long-v2",
    sinceSession: LINEAGE_SESSIONS.healthWatch,
    transitions: [
      {
        from: "HEALTHY",
        to: "WATCH",
        session: LINEAGE_SESSIONS.healthWatch,
        rule: "ROLLING_EXPECTANCY_BELOW_RESEARCHED_BAND",
        authority: "AUTOMATIC_PREAPPROVED_MONITORING_RULE",
        inputs: [
          "demo-fact-rolling-expectancy-pullback-long-v2",
          "demo-fact-factor-drift-pullback-long-v2",
        ],
      },
    ],
    /** THE ANCHOR OF THE LINEAGE: this transition created the research queue entry. */
    queueItem: QUEUE_ITEMS.pullback,
    recoveryAuthority: "AUTOMATIC_MONITORING_MAY_LOWER_ENTRIES_ONLY_RESTORATION_IS_HUMAN",
    recoveryRequirements: [
      "ROLLING_EXPECTANCY_BACK_INSIDE_THE_RESEARCHED_BAND",
      "A_COMPLETED_RESEARCH_RUN_AGAINST_THE_QUEUE_ENTRY",
    ],
    safetyAction: "MONITORING_ONLY_NO_ENTRY_REDUCTION_APPLIED",
    humanAction: "REVIEW_THE_RESEARCH_QUEUE_ENTRY",
    clusters: [
      {
        cluster: "ENTRY_INTO_A_FADING_TREND",
        count: 3,
        evidence: [
          { id: "demo-evidence-cluster-fading-trend-0001" },
          { id: "demo-evidence-cluster-fading-trend-0002" },
        ],
      },
    ],
    factorDriftHundredths: 47,
    correlationHundredths: 58,
  },
  {
    versionId: "pead-long-v1",
    sinceSession: 400,
    transitions: [],
    recoveryAuthority: "NO_RECOVERY_REQUIRED_STATE_IS_HEALTHY",
    recoveryRequirements: [],
    safetyAction: "NONE_TAKEN",
    humanAction: "NONE_REQUIRED",
    clusters: [],
    /** Below the declared minimum, so every drift measure reports its rule and no number. */
    factorDriftHundredths: null,
    correlationHundredths: null,
  },
  {
    versionId: "pead-short-v1",
    sinceSession: LINEAGE_SESSIONS.healthReduced,
    transitions: [
      {
        from: "HEALTHY",
        to: "WATCH",
        session: 436,
        rule: "BORROW_AVAILABILITY_INCIDENTS_RECORDED",
        authority: "AUTOMATIC_PREAPPROVED_MONITORING_RULE",
        inputs: ["demo-fact-borrow-incident-0001"],
      },
      {
        from: "WATCH",
        to: "DEGRADED",
        session: LINEAGE_SESSIONS.healthDegraded,
        rule: "REPEATED_BORROW_RECALL_BEFORE_TARGET",
        authority: "AUTOMATIC_PREAPPROVED_MONITORING_RULE",
        inputs: ["demo-fact-borrow-incident-0002", "demo-fact-borrow-incident-0003"],
      },
      {
        from: "DEGRADED",
        to: "NEW_ENTRIES_REDUCED",
        session: LINEAGE_SESSIONS.healthReduced,
        rule: "PREAPPROVED_ENTRY_REDUCTION_ON_REPEATED_BORROW_FAILURE",
        authority: "AUTOMATIC_PREAPPROVED_SAFETY_RULE",
        inputs: ["demo-fact-borrow-incident-0004"],
      },
    ],
    queueItem: QUEUE_ITEMS.borrow,
    /**
     * REDUCTION IS AUTOMATIC; RESTORATION IS NOT (ADR-0026 §13).
     *
     * The authority is displayed exactly as recorded, and **is neither strengthened nor
     * widened here**. Nothing on this screen restores an entry, and no control exists that
     * could ask for one.
     */
    recoveryAuthority: "REDUCTION_WAS_AUTOMATIC_RESTORATION_REQUIRES_HUMAN_AUTHORITY",
    recoveryRequirements: [
      "A_RECORDED_BORROW_FEED_WITH_QUALIFIED_HISTORY",
      "A_HUMAN_AUTHORIZATION_TO_RESTORE_NEW_ENTRIES",
    ],
    safetyAction: "NEW_ENTRIES_REDUCED_BY_A_PREAPPROVED_SAFETY_RULE",
    humanAction: "AUTHORIZE_OR_DECLINE_RESTORATION_OF_NEW_ENTRIES",
    clusters: [
      {
        cluster: "BORROW_RECALL_BEFORE_TARGET",
        count: 4,
        evidence: [
          { id: "demo-evidence-borrow-recall-0001", area: "SHORT_SIDE" },
          { id: "demo-evidence-borrow-recall-0002", area: "SHORT_SIDE" },
        ],
      },
      {
        cluster: "STALE_BORROW_RECORD_AT_DECISION_TIME",
        count: 2,
        evidence: [{ id: "demo-evidence-borrow-staleness-0001", area: "DATA_QUALITY" }],
      },
    ],
    factorDriftHundredths: 63,
    correlationHundredths: 44,
  },
  {
    versionId: "deterioration-short-v1",
    sinceSession: 380,
    transitions: [],
    recoveryAuthority: "NO_RECOVERY_REQUIRED_STATE_IS_HEALTHY",
    recoveryRequirements: [],
    safetyAction: "NONE_TAKEN",
    humanAction: "NONE_REQUIRED",
    clusters: [],
    factorDriftHundredths: 22,
    correlationHundredths: 39,
  },
];

/** The ADR-0026 §13 health inputs, in the order the specification names them. */
const HEALTH_INPUT_ORDER = [
  "EXPECTANCY",
  "DRAWDOWN",
  "TAIL_LOSSES",
  "OPPORTUNITY_COUNT",
  "TURNOVER",
  "SLIPPAGE",
  "MODELED_VERSUS_REALIZED_EXECUTION",
  "CAPACITY",
  "FACTOR_EXPOSURE",
  "CROSS_STRATEGY_CORRELATION",
  "REGIME_BEHAVIOUR",
  "BORROW_FAILURES",
  "DATA_QUALITY_INCIDENTS",
  "AI_CONTRIBUTION",
  "RECONCILIATION_INCIDENTS",
] as const;

export function syntheticStrategyHealth(
  asOf: string,
  days: readonly string[],
): StrategyHealthPayload {
  const items: StrategyHealth[] = HEALTH_RECORDS.map((record) => {
    const version = strategyVersionOf(record.versionId);
    const trades = BOOK.trades.filter((trade) => trade.versionId === record.versionId);
    const closed = trades.filter((trade) => trade.status === "CLOSED");
    /*
     * THE SAME BUILDER THE STRATEGY PERFORMANCE SCREEN READS.
     *
     * Expectancy, drawdown, win rate and the observation count are taken from it verbatim, so
     * the two screens cannot disagree about one version under one metric identifier.
     */
    const summary = buildPerformanceSummary({
      days,
      asOf,
      closed,
      periodReturns: [],
      totalReturnHundredths: 0,
      maxDrawdownHundredths: 0,
      populationCode: "CLOSED_TRADES_OF_THIS_EXACT_VERSION",
    });
    const observed = typeof summary.observation_count.value === "number"
      ? summary.observation_count.value
      : 0;
    const met = observed >= HEALTH_MINIMUM_OBSERVATIONS;

    /*
     * THE ROLLING TAIL LOSS, COMPUTED FROM THIS VERSION'S OWN CLOSED TRADES — ADR-0032 §D1.
     *
     * The book is read, not written: no trade is added, removed, reordered or re-priced, and
     * **the population is not enlarged to make a window full**. A version whose eligible
     * closed-trade count is short of thirty reports `INSUFFICIENT_OBSERVATIONS` and carries
     * no value at all, which is the honest answer rather than a smaller window quietly used.
     */
    const tailLoss = buildRollingTailLoss(closed, days, asOf);

    /*
     * THE CAPACITY ADMISSION GATE, read here exactly as Area 4 reads it (§12.3.3).
     *
     * Area 5 lists capacity among the ADR-0026 §13 health inputs, so it answers through the
     * same gate rather than through a second literal that could disagree with the strategy
     * screen about one `metric_id`.
     */
    const capacity = capacityFor({
      strategyVersion: record.versionId,
      windowScope: `${days[0]}/${days[days.length - 1]}`,
      evaluationMs: Date.parse(asOf),
      shortExposurePresent: trades.some((trade) => trade.direction === "SHORT"),
      asOf,
    });

    const drift: { measure: ReturnType<typeof demoReason>; value: MetricValue }[] = [
      {
        measure: demoReason("FACTOR_EXPOSURE_DRIFT"),
        value:
          record.factorDriftHundredths === null
            ? insufficient("strategy.factor_drift", "DIMENSIONLESS")
            : scaled(
                "strategy.factor_drift",
                "DIMENSIONLESS",
                record.factorDriftHundredths,
                asOf,
              ),
      },
      {
        measure: demoReason("CROSS_STRATEGY_CORRELATION"),
        value:
          record.correlationHundredths === null
            ? insufficient("strategy.correlation", "RATIO")
            : scaled("strategy.correlation", "RATIO", record.correlationHundredths, asOf),
      },
      {
        /*
         * THE COMPUTED STATISTIC, AND THE SAME OBJECT THE `tail_loss` FIELD CARRIES.
         *
         * The drift entry, the `TAIL_LOSSES` health input and the disclosure panel are one
         * value read three times rather than three computations of one name (§12.2).
         */
        measure: demoReason("TAIL_LOSS_R_MULTIPLE"),
        value: tailLoss.value,
      },
    ];

    const healthInputs = HEALTH_INPUT_ORDER.map((input) => {
      switch (input) {
        case "EXPECTANCY":
          return { input: demoReason(input), value: summary.expectancy };
        case "DRAWDOWN":
          return { input: demoReason(input), value: summary.max_drawdown };
        case "TAIL_LOSSES":
          return { input: demoReason(input), value: drift[2].value };
        case "OPPORTUNITY_COUNT":
          return {
            input: demoReason(input),
            value: count("strategy.opportunity_count", trades.length, asOf),
          };
        case "FACTOR_EXPOSURE":
          return { input: demoReason(input), value: drift[0].value };
        case "CROSS_STRATEGY_CORRELATION":
          return { input: demoReason(input), value: drift[1].value };
        case "TURNOVER":
          /*
           * TURNOVER IS THE STRATEGY SCREEN'S FIGURE, AND IT IS NOT RESTATED HERE.
           *
           * Recomputing it would be "a screen reporting a different metric under the same
           * name" the moment either formula changed, so this input names the read model that
           * owns it and reports no number of its own.
           */
          return {
            input: demoReason(input),
            value: unavailable(
              "strategy.turnover",
              "RATIO",
              "NOT_YET_AVAILABLE",
              "UPSTREAM_INPUT_MISSING",
            ),
          };
        case "SLIPPAGE":
        case "MODELED_VERSUS_REALIZED_EXECUTION":
          return {
            input: demoReason(input),
            value: unavailable(
              "slippage.aggregate",
              "BPS",
              "NOT_IMPLEMENTED",
              "PRODUCER_NOT_IMPLEMENTED",
            ),
          };
        case "CAPACITY":
          /*
           * THE GATE'S ANSWER, NOT A SECOND OPINION OF IT (§12.2).
           *
           * `slippage.aggregate` above is `NOT_IMPLEMENTED` because **no producer exists** for
           * it at all. Capacity is a different state and the distinction is load-bearing: a
           * producer DOES exist — the §12.3.3 admission gate — it ran, and it refused at the
           * required-input stage. Reporting a missing producer here would send a reader to
           * look for broken code rather than at nine dependencies that do not exist.
           */
          return { input: demoReason(input), value: capacity.value };
        case "REGIME_BEHAVIOUR":
          return {
            input: demoReason(input),
            value: unavailable(
              "market.regime_state",
              "DIMENSIONLESS",
              "NOT_YET_AVAILABLE",
              "UPSTREAM_INPUT_MISSING",
            ),
          };
        case "BORROW_FAILURES":
          return {
            input: demoReason(input),
            value: count(
              "strategy.failure_count",
              record.clusters
                .filter((cluster) => cluster.cluster.startsWith("BORROW"))
                .reduce((total, cluster) => total + cluster.count, 0),
              asOf,
            ),
          };
        case "DATA_QUALITY_INCIDENTS":
        case "RECONCILIATION_INCIDENTS":
          return {
            input: demoReason(input),
            value: unavailable(
              "operations.open_incidents",
              "COUNT",
              "NOT_IMPLEMENTED",
              "PRODUCER_NOT_IMPLEMENTED",
            ),
          };
        case "AI_CONTRIBUTION":
          /* No AI agent exists, and experiment E has not been run. */
          return {
            input: demoReason(input),
            value: unavailable(
              "expectancy.r",
              "R_MULTIPLE",
              "NOT_IMPLEMENTED",
              "PRODUCER_NOT_IMPLEMENTED",
            ),
          };
      }
    });

    const state = version.healthState as StrategyHealthState;
    /*
     * THE QUEUE ENTRY COMES FROM THIS RECORD, AND FROM NOWHERE ELSE.
     *
     * A fallback stood here that substituted the pullback lineage's queue item for any
     * degradation whose own record named none -- a NEAREST MATCH, which is what §4.3.1
     * refuses of a resolver and what the contract's degradation rule exists to catch. It made
     * a fixture satisfy the rule by inventing the link the rule asks for. A degradation
     * recording no queue entry is refused at admission instead, which is the honest answer:
     * the record is wrong, not the rule.
     */
    const queueItem = record.queueItem;

    return {
      strategy_version: record.versionId,
      strategy_module: demoReason(version.module),
      state,
      since: sessionInstant(days[Math.min(record.sinceSession, days.length - 1)]),
      transitions: record.transitions.map((transition) => ({
        from: transition.from,
        to: transition.to,
        at: sessionInstant(days[Math.min(transition.session, days.length - 1)]),
        rule: demoReason(transition.rule),
        authority: demoReason(transition.authority),
        input_refs: refListOf(
          transition.inputs.map((id) => demoRef(id, "source_fact", "AUTHORIZED_READ")),
          "ZERO_OR_MORE",
          asOf,
        ),
      })),
      drift,
      tail_loss: tailLoss,
      failure_clusters: record.clusters.map((cluster) => ({
        cluster: demoReason(cluster.cluster),
        count: count("strategy.failure_count", cluster.count, asOf),
        evidence_refs: refListOf(
          cluster.evidence.map((entry) =>
            demoRef(entry.id, "evidence", "AUTHORIZED_READ", entry.area),
          ),
          "ZERO_OR_MORE",
          asOf,
        ),
      })),
      minimum_observations_met: met,
      observation_count: summary.observation_count,
      minimum_observations: count(
        "performance.minimum_observations",
        HEALTH_MINIMUM_OBSERVATIONS,
        asOf,
      ),
      health_inputs: healthInputs,
      ...(queueItem === undefined
        ? {}
        : { queue_item_ref: demoRef(queueItem, "queue_item", "ENDPOINT") }),
      recovery_authority: demoReason(record.recoveryAuthority),
      recovery_requirements: record.recoveryRequirements.map(demoReason),
      safety_action: demoReason(record.safetyAction),
      human_action_required: demoReason(record.humanAction),
    };
  });

  return {
    items,
    page: {
      page_size: 25,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("HEALTH_STATE_SEVERITY_DESCENDING"),
      tiebreak: demoReason("STRATEGY_VERSION_ASCENDING"),
    },
    /** The closed vocabulary itself, delivered, so no screen keeps a second copy of it. */
    health_states: [...STRATEGY_HEALTH_STATES],
  };
}

/* ================================================================= Area 20 — versions */

/** The pins a demonstration version records. No AI model or prompt exists to pin. */
function pinsFor(versionId: string, module: string): VersionPins {
  const slug = module.toLowerCase().replace(/_/g, "-");
  const notPinned = notApplicable("governance.version_pin", "DIMENSIONLESS");
  return {
    strategy_version: versionId,
    factor_definition_version: "factor-definitions-demo-v2",
    risk_policy_version: "risk-policy-demo-0.0.0",
    entry_policy_version: `${slug}-entry-policy-v1`,
    exit_policy_version: `${slug}-exit-policy-v1`,
    /** No AI agent exists, so there is no model and no prompt to pin (§4.2). */
    model_version: notPinned,
    prompt_version: notPinned,
    code_identity: "research-code-demo-0001",
    config_identity: "research-config-demo-0001",
  };
}

const LIFECYCLE_BY_BOOK_STAGE: Readonly<Record<string, string>> = {
  PRODUCTION: "LOCKED_OUT_OF_SAMPLE_VALIDATION",
  SUPERSEDED: "RETIRED",
};

export function syntheticStrategyVersions(
  asOf: string,
  days: readonly string[],
): StrategyVersionPayload {
  const openByVersion = openTradesByVersion();
  const instantAt = (session: number) =>
    sessionInstant(days[Math.max(0, Math.min(session, days.length - 1))]);

  const bookRows: StrategyVersionRecord[] = STRATEGY_VERSIONS.map((version) => {
    const open = openByVersion.get(version.versionId) ?? [];
    const pins = pinsFor(version.versionId, version.module);
    const retired = version.lifecycle === "SUPERSEDED";
    return {
      strategy_version: version.versionId,
      module: demoReason(version.module),
      lifecycle_stage: demoReason(
        LIFECYCLE_BY_BOOK_STAGE[version.lifecycle] ?? "BASELINE_RESEARCH",
      ),
      /*
       * NOTHING HAS REACHED AN ORDER-PRODUCING STAGE.
       *
       * `AUTOMATED_PAPER` is "the first order-producing stage" and requires human approval,
       * and it has never been reached. Every version here is at `RESEARCH`, and `RETIRED` is
       * a LIFECYCLE STATUS rather than a position on the maturity ladder (§4.1).
       */
      maturity_stage: "RESEARCH" satisfies MaturityStage,
      role: demoReason(retired ? "SUPERSEDED_VERSION" : "CHAMPION"),
      created_at: instantAt(retired ? 120 : 200),
      immutable: true,
      pins,
      lineage_refs: refListOf(
        [
          demoRef(
            `demo-fact-lineage-${version.versionId}`,
            "source_fact",
            "AUTHORIZED_READ",
          ),
        ],
        "ZERO_OR_MORE",
        asOf,
      ),
      open_position_refs: refListOf(
        open.map((trade) =>
          demoRef(`demo-position-${trade.tradeId}`, "source_fact", "AUTHORIZED_READ"),
        ),
        "ZERO_OR_MORE",
        asOf,
      ),
      open_positions: open.map((trade) => ({
        position_ref: demoRef(
          `demo-position-${trade.tradeId}`,
          "source_fact",
          "AUTHORIZED_READ",
        ),
        trade_ref: demoRef(trade.tradeId, "trade", "ENDPOINT"),
        opened_at: instantAt(trade.stages[0].session),
        pinned: pins,
      })),
      open_position_count: count("strategy.open_position_count", open.length, asOf),
      registration_refs: refListOf(
        version.versionId === "pullback-long-v2"
          ? [
              demoRef(REGISTRATIONS.original, "registration", "ENDPOINT"),
              demoRef(REGISTRATIONS.amendment, "registration", "ENDPOINT"),
            ]
          : version.versionId === "pead-short-v1"
            ? [demoRef(REGISTRATIONS.unknownHistory, "registration", "ENDPOINT")]
            : [],
        "ZERO_OR_MORE",
        asOf,
      ),
      history: retired
        ? [
            {
              event: demoReason("ACTIVATED_IN_RESEARCH"),
              at: instantAt(120),
              authority: demoReason("HUMAN_GOVERNANCE_DECISION"),
            },
            {
              event: demoReason("RETIRED_ON_SUPERSESSION"),
              at: instantAt(LINEAGE_SESSIONS.retirement),
              authority: demoReason("HUMAN_GOVERNANCE_DECISION"),
            },
          ]
        : [
            {
              event: demoReason("ACTIVATED_IN_RESEARCH"),
              at: instantAt(200),
              authority: demoReason("HUMAN_GOVERNANCE_DECISION"),
            },
          ],
      /*
       * NO ROLLBACK IS RECORDED ANYWHERE IN THIS DEMONSTRATION, and the field is absent
       * rather than filled. A rollback is a governed event; inventing one so a conditional
       * field renders would put an event on the screen that never happened.
       */
    };
  });

  const challengerRows: StrategyVersionRecord[] = CHALLENGER_VERSIONS.map((challenger) => {
    const pins = pinsFor(challenger.versionId, challenger.module);
    return {
      strategy_version: challenger.versionId,
      module: demoReason(challenger.module),
      lifecycle_stage: demoReason("SHADOW"),
      /** `SHADOW` carries NO order authority, in any environment. */
      maturity_stage: "SHADOW" satisfies MaturityStage,
      role: demoReason("CHALLENGER"),
      created_at: instantAt(challenger.createdSession),
      immutable: true,
      pins,
      lineage_refs: refListOf(
        [
          demoRef(
            `demo-fact-derived-from-${challenger.championId}`,
            "source_fact",
            "AUTHORIZED_READ",
          ),
        ],
        "ZERO_OR_MORE",
        asOf,
      ),
      /*
       * A CHALLENGER GOVERNS NO OPEN POSITION, AND CANNOT.
       *
       * "Shadow produces no order, in any environment", so the population is EMPTY and it is
       * empty as a verified fact rather than as a gap.
       */
      open_position_refs: refListOf([], "ZERO_OR_MORE", asOf),
      open_positions: [],
      open_position_count: count("strategy.open_position_count", 0, asOf),
      registration_refs: refListOf(
        [demoRef(challenger.registrationId, "registration", "ENDPOINT")],
        "ZERO_OR_MORE",
        asOf,
      ),
      history: [
        {
          event: demoReason("CREATED_FROM_A_REGISTERED_HYPOTHESIS"),
          at: instantAt(challenger.createdSession),
          authority: demoReason("AUTOMATIC_WITHIN_PREAPPROVED_RESEARCH_BOUNDS"),
        },
      ],
    };
  });

  const items = [...bookRows, ...challengerRows];
  return {
    items,
    page: {
      page_size: 50,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("CREATED_AT_DESCENDING"),
      tiebreak: demoReason("STRATEGY_VERSION_ASCENDING"),
    },
  };
}
