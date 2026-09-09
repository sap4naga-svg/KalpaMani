/**
 * `StrategyPerformance` — `read-model-contracts.md` §4.5, keyed by strategy module **and**
 * strategy version.
 *
 * **Every result is attributed to an exact strategy version.** Modules keep separate
 * attribution and share family context, and **no diversification or alpha claim is carried
 * in this payload, nor is one derivable from it** — whether Breakout Long and Pullback Long
 * are economically distinct is **open gate G7**, and nothing here decides it.
 *
 * WHAT THIS IS NOT. No strategy module exists, no strategy has ever run, and no figure this
 * contract can carry is a result. It is the shape a recorded outcome would arrive in.
 */
import { z } from "zod";

import { collectionPayload } from "./pagination";
import { refListFieldOf, refOf } from "./references";
import { envelope } from "./envelope";
import {
  analysisWindow,
  performanceSummaryPayload,
} from "./portfolio-models";
import { countValue, instant, metricOf, metricValue, reasonCoded, safeId, versionPins } from "./values";
import { ROLLING_OBSERVATION_UNITS } from "./read-models";
import {
  availabilityState,
  fieldReasonCode,
  maturityStage,
  strategyHealthState,
} from "./vocabularies";
import type { StrategyHealthState } from "./vocabularies";

/**
 * The recorded health state, and nothing that would make this a health screen.
 *
 * Area 5 — the transitions, the drift measures, the failure clusters, the recovery authority
 * and the research-queue entry a degradation creates — is **C7's**, and this cycle
 * implements none of it. What a strategy-performance reader legitimately needs is the
 * CURRENT RECORDED STATE, so results are not read as if the module were healthy when the
 * record says otherwise, plus a link to the area that owns the rest.
 *
 * **The state is displayed, never derived.** Nothing here computes a health state from a
 * performance figure, and **the view causes no transition**.
 */
export const strategyHealthContext = z.object({
  /** One of the seven ADR-0026 states, carried as a closed-vocabulary token. */
  state: metricOf("strategy.health_state"),
  /** Why the record says what it says. A closed code, never free text. */
  reason: reasonCoded,
  /** Where the transitions, drift and queue entry live — Area 5, and not implemented. */
  detail_ref: refOf("StrategyPerformance.detail_ref"),
  /** What this context deliberately does not carry, named rather than left blank. */
  omitted: z.array(
    z.object({
      subject: reasonCoded,
      availability: availabilityState,
      reason: fieldReasonCode,
    }),
  ),
});
export type StrategyHealthContext = z.infer<typeof strategyHealthContext>;

/**
 * The per-module figures Area 4 names that a `PerformanceSummary` does not carry.
 *
 * ADDITIVE, and each one is a §12.3 metric or a presentation definition this cycle proposes
 * and labels. They sit beside the summary rather than inside it, because a
 * `PerformanceSummary` is the same shape wherever it appears and widening it here would
 * change it everywhere.
 */
export const strategyModuleMetrics = z.object({
  realized_pnl: metricOf("pnl.realized"),
  unrealized_pnl: metricOf("pnl.unrealized"),
  average_holding_period: metricOf("holding_period"),
  opportunity_count: metricOf("strategy.opportunity_count"),
  turnover: metricOf("strategy.turnover"),
  /** Displayed from a record. Nothing here computes a capacity or authorizes one. */
  capacity: metricOf("strategy.capacity"),
  mfe: metricOf("mfe"),
  mae: metricOf("mae"),
  capture_ratio: metricOf("capture_ratio"),
  /** Signed basis points against a named reference, quantity-weighted by default. */
  slippage: metricOf("slippage.aggregate"),
});
export type StrategyModuleMetrics = z.infer<typeof strategyModuleMetrics>;

/**
 * Rolling expectancy over one strategy version's trailing closed trades.
 *
 * A DIFFERENT OBSERVATION UNIT FROM A PERFORMANCE SERIES' ROLLING WINDOW. That one counts
 * series periods; this one counts CLOSED TRADES, and the two never substitute. The unit is
 * carried rather than assumed, so "30" can never be read as thirty sessions.
 *
 * THE LOOKBACK IS §12.3'S OWN DECLARED MINIMUM FOR `expectancy.currency` -- thirty trades --
 * rather than a number invented here. A window shorter than the metric's minimum would
 * report `INSUFFICIENT_OBSERVATIONS` at every point by construction, which is not a window.
 *
 * THE POPULATION IS THE SUMMARY'S. Closed trades of this exact version that carry a
 * recorded initial planned risk record: the same definition `buildPerformanceSummary`
 * applies, so a rolling point and the whole-window figure cannot be computed over two
 * different populations.
 */
export const rollingExpectancy = z
  .object({
    lookback: countValue,
    minimum_observations: countValue,
    observation_unit: z.enum(ROLLING_OBSERVATION_UNITS),
    population: reasonCoded,
    /** How many closed trades the version carries in total. The axis' own denominator. */
    observed: countValue,
    /**
     * One point per closed trade, in exit order.
     *
     * IT IS NOT A `Series`, AND THAT IS DELIBERATE. A `Series` is indexed by a strictly
     * increasing instant, and two trades of one version routinely close on the same session
     * — so a time-indexed shape would have to drop one of them or invent an ordering between
     * them. The axis here is the TRADE ORDINAL, which is what an observation unit of
     * `CLOSED_TRADE` actually means, and the exit instant rides alongside it as a fact about
     * the trade rather than as the key.
     */
    points: z.array(
      z.object({
        /** 1-based position in the exit-ordered population. */
        ordinal: countValue,
        /** The exit this point was taken at, under the `DATE_ONLY` precedent. */
        at: metricValue,
        /** `expectancy.rolling`, or the reason there is none at this point. */
        value: metricValue,
      }),
    ),
  })
  .superRefine((candidate, ctx) => {
    if (candidate.observation_unit !== "CLOSED_TRADE") {
      ctx.addIssue({
        code: "custom",
        message: "a rolling expectancy counts CLOSED_TRADE observations",
      });
    }
    if (candidate.lookback.value !== candidate.minimum_observations.value) {
      ctx.addIssue({
        code: "custom",
        message: "a rolling window's declared minimum is its own lookback",
      });
    }
    if (candidate.points.length !== candidate.observed.value) {
      ctx.addIssue({
        code: "custom",
        message: "one point per closed trade the version carries",
      });
    }
    for (let index = 0; index < candidate.points.length; index += 1) {
      if (candidate.points[index].ordinal.value !== index + 1) {
        ctx.addIssue({
          code: "custom",
          message: "the ordinals are consecutive from one, in exit order",
        });
        return;
      }
    }
  });
export type RollingExpectancy = z.infer<typeof rollingExpectancy>;

export const strategyPerformance = z.object({
  strategy_module: reasonCoded,
  alpha_family: reasonCoded,
  /** The EXACT version the results below were produced by. */
  strategy_version: safeId,
  /** EMBEDDED, over this module and version only. */
  summary: performanceSummaryPayload,
  /** Sector, regime, volatility regime, trade template and factor bucket. */
  slices: z.array(
    z.object({
      axis: reasonCoded,
      bucket: reasonCoded,
      summary: performanceSummaryPayload,
    }),
  ),
  trade_population: reasonCoded,
  module_metrics: strategyModuleMetrics,
  health_context: strategyHealthContext,
  /**
   * ADDED BY THE C5 COMPLETION FOLLOW-UP -- rolling expectancy over this exact version.
   *
   * OPTIONAL, because a producer that cannot derive it must be able to omit it rather than
   * serve an empty shell. When it is present it is held to `rollingExpectancy` below.
   */
  rolling_expectancy: rollingExpectancy.optional(),
});
export type StrategyPerformance = z.infer<typeof strategyPerformance>;

/**
 * The family roll-up, carried beside the modules rather than derived from them by a screen.
 *
 * **Two modules in one family are one exposure with two names until measured otherwise**
 * (Area 4). The roll-up therefore states its member versions and carries **no
 * diversification figure at all**: there is no benefit to report, and reporting one would be
 * the claim G7 exists to withhold.
 */
export const alphaFamilyRollup = z.object({
  alpha_family: reasonCoded,
  member_versions: z.array(safeId),
  summary: performanceSummaryPayload,
  /** Stated on the roll-up, so a reader is not left to infer what it does not say. */
  diversification_claim: z.object({
    availability: availabilityState,
    reason: fieldReasonCode,
    gate: reasonCoded,
  }),
});
export type AlphaFamilyRollup = z.infer<typeof alphaFamilyRollup>;

export const strategyPerformancePayload = collectionPayload(strategyPerformance, {
  window: analysisWindow,
  families: z.array(alphaFamilyRollup),
});
export type StrategyPerformancePayload = z.infer<typeof strategyPerformancePayload>;

/** v3: each row gained `rolling_expectancy`, so a v2 consumer reads a different contract. */
export const STRATEGY_PERFORMANCE_SCHEMA = "cockpit.strategy_performance.v3";
export const strategyPerformanceEnvelope = envelope(
  strategyPerformancePayload,
  STRATEGY_PERFORMANCE_SCHEMA,
);

/* ============================================================= added by C7: Area 5 */

/**
 * `StrategyHealth` — `read-model-contracts.md` §4.5, Area 5.
 *
 * **Only the seven ADR-0026 §13 states render**, the vocabulary is CONSUMED and never
 * extended, and **the view causes no transition**. A degradation shows the research queue
 * entry it created; it does not create one, advance one or mutate a parameter.
 *
 * FOUR THINGS THIS CONTRACT KEEPS APART, because collapsing any of them puts a false
 * statement on the screen:
 *
 *   HEALTH is not LIFECYCLE          `HEALTHY` is a behaviour state; `BASELINE_RESEARCH` is a
 *                                    position on the ADR-0026 §10 ladder. `WATCH`,
 *                                    `SUSPENDED` and `RETIRED` are statuses a version holds
 *                                    WITHIN whatever stage it last reached
 *   HEALTH is not ENVIRONMENT        a `RESEARCH` runtime environment says where a version
 *                                    runs, and nothing about how it is behaving
 *   HEALTH is not AVAILABILITY       a health state is a recorded VALUE; `NOT_IMPLEMENTED` is
 *                                    the absence of a producer. A version with no recorded
 *                                    health is not a healthy one
 *   REDUCTION is not RESTORATION     reducing and disabling new entries is automatic;
 *                                    RESTORING them is not, and recovery past a governed
 *                                    suspension is never automatic
 */
/**
 * The four recorded DEGRADATION states of ADR-0026 §13.
 *
 * Reducing and disabling new entries is automatic and always permitted; suspension is a
 * governed stop. **Each of the four creates a research queue entry**, which is why the
 * conditional reference is required exactly here and nowhere else.
 */
export const DEGRADATION_HEALTH_STATES: readonly StrategyHealthState[] = [
  "DEGRADED",
  "NEW_ENTRIES_REDUCED",
  "NEW_ENTRIES_DISABLED",
  "SUSPENDED",
];

export const healthTransition = z.object({
  from: strategyHealthState,
  to: strategyHealthState,
  at: instant,
  /** The preapproved rule that fired. A closed code, never prose. */
  rule: reasonCoded,
  /** Whose authority the transition carried. Automatic reduction is not human restoration. */
  authority: reasonCoded,
  /** §4.3.1 kind `source_fact` — the inputs the rule read. */
  input_refs: refListFieldOf("StrategyHealth.transitions[].input_refs"),
});
export type HealthTransition = z.infer<typeof healthTransition>;

/**
 * A failure cluster — **losses sharing a CAUSE, not a period** (feedback specification §2.3).
 *
 * A month of losses is not a cluster; a set of losses that all followed a borrow recall is.
 */
export const failureCluster = z.object({
  cluster: reasonCoded,
  count: metricOf("strategy.failure_count"),
  /** §4.3.1 kind `evidence`. */
  evidence_refs: refListFieldOf("StrategyHealth.failure_clusters[].evidence_refs"),
});

export const strategyHealth = z
  .object({
    strategy_version: safeId,
    /**
     * ADDITIVE: §5.1 declares a `module` filter on `/strategy/health`, and a filter needs the
     * field it filters on. It is the module's identity, never a second health opinion.
     */
    strategy_module: reasonCoded,
    /** One of the seven, and only one of the seven. */
    state: strategyHealthState,
    since: instant,
    transitions: z.array(healthTransition),
    drift: z.array(z.object({ measure: reasonCoded, value: metricValue })),
    failure_clusters: z.array(failureCluster),
    minimum_observations_met: z.boolean(),
    /**
     * ADDITIVE, and required by U19 and §9.2: `INSUFFICIENT_OBSERVATIONS` renders "the
     * observation count and the minimum required, and no ratio". A boolean alone cannot show
     * either number, so a screen carrying only `minimum_observations_met` shows half the rule.
     */
    observation_count: metricOf("performance.observation_count"),
    minimum_observations: metricOf("performance.minimum_observations"),
    /**
     * ADDITIVE: the ADR-0026 §13 health INPUTS, each with its own availability.
     *
     * Area 5 names fifteen of them and several have no producer at all, so each carries a
     * `MetricValue` that says so rather than a zero standing in for a measurement nobody took.
     */
    health_inputs: z.array(z.object({ input: reasonCoded, value: metricValue })),
    /** Required when a degradation created one. §4.3.1 kind `queue_item`. */
    queue_item_ref: refOf("StrategyHealth.queue_item_ref").optional(),
    /**
     * Displayed unchanged, and **neither strengthened nor widened by this contract**.
     * Reduction and disablement are automatic; RESTORATION IS NOT.
     */
    recovery_authority: reasonCoded,
    /**
     * ADDITIVE: what the record says must be true before recovery, as closed codes.
     *
     * Displaying a requirement is not satisfying one, and nothing here initiates, requests or
     * schedules a recovery.
     */
    recovery_requirements: z.array(reasonCoded),
    /** ADDITIVE: Area 5 presents "the safety action taken" and "the human action required". */
    safety_action: reasonCoded,
    human_action_required: reasonCoded,
  })
  .superRefine((candidate, ctx) => {
    /*
     * THE TRANSITION HISTORY MUST END WHERE THE RECORD SAYS THE VERSION IS.
     *
     * A history whose last transition lands somewhere other than `state` describes a different
     * version, and a reader following the chain would arrive at the wrong answer. It is checked
     * here rather than in a renderer, because a renderer that noticed would have no honest way
     * to display the disagreement.
     */
    const last = candidate.transitions[candidate.transitions.length - 1];
    if (last !== undefined && last.to !== candidate.state) {
      ctx.addIssue({
        code: "custom",
        message: "the last recorded transition lands on the state this record reports",
      });
    }
    for (let index = 1; index < candidate.transitions.length; index += 1) {
      const previous = candidate.transitions[index - 1];
      const current = candidate.transitions[index];
      if (current.at <= previous.at) {
        ctx.addIssue({
          code: "custom",
          message: "health transitions are ordered in time, with no two at one instant",
        });
        return;
      }
      if (current.from !== previous.to) {
        ctx.addIssue({
          code: "custom",
          message: "each transition departs from the state the one before it arrived at",
        });
        return;
      }
    }
    /*
     * A DEGRADATION SHOWS THE RESEARCH QUEUE ENTRY IT CREATED (Area 5, §2.3).
     *
     * The four states below are the recorded DEGRADATIONS, and each one "creates a research
     * queue entry" rather than mutating a parameter. Without this the conditional field is
     * optional in name only and the acceptance criterion is unenforced.
     *
     * `RETIRED` is deliberately NOT one of them. A version retired on supersession has
     * degraded nothing, and requiring a queue entry there would report that a healthy version
     * being replaced had raised a research question nobody asked. `HEALTHY` and `WATCH` may
     * carry one — `WATCH` in this demonstration does — and neither is required to.
     */
    const degraded = DEGRADATION_HEALTH_STATES.includes(candidate.state);
    if (degraded && candidate.queue_item_ref === undefined) {
      ctx.addIssue({
        code: "custom",
        message: "a recorded degradation names the research queue entry it created",
      });
    }
  });
export type StrategyHealth = z.infer<typeof strategyHealth>;

export const strategyHealthPayload = collectionPayload(strategyHealth, {
  /**
   * The states this read model may EVER carry, carried in the response.
   *
   * A screen that renders the seven from a local literal is a second copy of a closed
   * vocabulary, and two copies drift. It is the contract's own list, delivered.
   */
  health_states: z.array(strategyHealthState),
});
export type StrategyHealthPayload = z.infer<typeof strategyHealthPayload>;

export const STRATEGY_HEALTH_SCHEMA = "cockpit.strategy_health.v1";
export const strategyHealthEnvelope = envelope(strategyHealthPayload, STRATEGY_HEALTH_SCHEMA);

/* ============================================================ added by C7: Area 20 */

/**
 * `StrategyVersion` — `read-model-contracts.md` §4.5, Area 20.
 *
 * **Production strategy versions are immutable, and a modification creates a new Challenger
 * version rather than an edit in place.** **An open position stays governed by the exact
 * versions that opened it**, and this registry displays that pinning explicitly so a reader
 * can see which open positions a retirement does and does not affect.
 *
 * **A hypothetical Challenger does not replace the recorded Champion.** The role is a
 * displayed property of the record; nothing on this contract promotes, activates, replaces
 * or rolls anything back, and no such field exists to carry the instruction.
 */
export const openPositionPin = z.object({
  /** §4.3.1 kind `source_fact` — the recorded position. */
  position_ref: refOf("StrategyVersion.open_positions[].position_ref"),
  /**
   * The trade the position belongs to, kind `trade`.
   *
   * ADDITIVE, and it is a DIFFERENT reference from `position_ref`: one names the recorded
   * position fact, the other names the trade read model that owns its story. They carry
   * different identifiers, and neither is derived from the other.
   */
  trade_ref: refOf("StrategyVersion.open_positions[].trade_ref"),
  opened_at: instant,
  /**
   * The exact versions that opened it. **None of them may mutate while it is open**
   * (ADR-0026 §11), which is why the whole pin set travels with the position rather than
   * being read from whatever the version registry says today.
   */
  pinned: versionPins,
});

export const strategyVersionRecord = z
  .object({
    strategy_version: safeId,
    module: reasonCoded,
    /** An ADR-0026 §10 lifecycle value. Consumed, never extended. */
    lifecycle_stage: reasonCoded,
    /** The presentation view of it (§2.5). A view over the lifecycle, never a second ladder. */
    maturity_stage: maturityStage,
    /** ADDITIVE: Champion, Challenger or neither. Displayed, and conferred by nothing here. */
    role: reasonCoded,
    created_at: instant,
    immutable: z.boolean(),
    /** ADDITIVE: Area 20 presents factor, risk, entry, exit, model, prompt, code and config. */
    pins: versionPins,
    /** §4.3.1 kind `source_fact`. */
    lineage_refs: refListFieldOf("StrategyVersion.lineage_refs"),
    /** §4.3.1 kind `source_fact` — the population; the pinning detail is beside it. */
    open_position_refs: refListFieldOf("StrategyVersion.open_position_refs"),
    /** ADDITIVE: the explicit pinning Area 20 requires, one entry per open position. */
    open_positions: z.array(openPositionPin),
    open_position_count: metricOf("strategy.open_position_count"),
    /** ADDITIVE: the registrations this version was produced by or evaluated under. */
    registration_refs: refListFieldOf("StrategyVersion.registration_refs"),
    /** ADDITIVE: activation, retirement, promotion and rollback history, as recorded. */
    history: z.array(
      z.object({
        event: reasonCoded,
        at: instant,
        authority: reasonCoded,
        /** Present where a recorded human decision carried the event. Kind `decision`. */
        decision_ref: refOf("StrategyVersion.history[].decision_ref").optional(),
      }),
    ),
    /** Required when this version rolled another back. Kind `strategy_version`. */
    rollback_of: refOf("StrategyVersion.rollback_of").optional(),
  })
  .superRefine((candidate, ctx) => {
    /*
     * THE PINNED POPULATION AND ITS DETAIL DESCRIBE ONE SET.
     *
     * `open_position_refs` is the contract's required reference list and `open_positions` is
     * the pinning detail Area 20 asks for. Two spellings of one population is how a registry
     * comes to say a retirement affects three positions while listing two.
     */
    const total = candidate.open_position_refs.total.value;
    if (typeof total === "number" && total !== candidate.open_positions.length) {
      ctx.addIssue({
        code: "custom",
        message: "the open-position references and their pinning detail describe one population",
      });
    }
    if (
      typeof candidate.open_position_count.value === "number" &&
      candidate.open_position_count.value !== candidate.open_positions.length
    ) {
      ctx.addIssue({
        code: "custom",
        message: "the open-position count is the number of pinned positions carried",
      });
    }
    /*
     * EVERY PIN NAMES THIS VERSION AS THE STRATEGY THAT OPENED IT.
     *
     * A position pinned to another version has no business in this version's registry row,
     * and admitting one would let a retirement here look as though it released a position
     * that some other version still governs.
     */
    for (const position of candidate.open_positions) {
      if (position.pinned.strategy_version !== candidate.strategy_version) {
        ctx.addIssue({
          code: "custom",
          message: "an open position pinned to another strategy version is not this version's",
        });
        return;
      }
    }
    for (let index = 1; index < candidate.history.length; index += 1) {
      if (candidate.history[index].at <= candidate.history[index - 1].at) {
        ctx.addIssue({
          code: "custom",
          message: "version history events are ordered in time, with no two at one instant",
        });
        return;
      }
    }
  });
export type StrategyVersionRecord = z.infer<typeof strategyVersionRecord>;

export const strategyVersionPayload = collectionPayload(strategyVersionRecord);
export type StrategyVersionPayload = z.infer<typeof strategyVersionPayload>;

export const STRATEGY_VERSION_SCHEMA = "cockpit.strategy_version.v1";
export const strategyVersionEnvelope = envelope(
  strategyVersionPayload,
  STRATEGY_VERSION_SCHEMA,
);
