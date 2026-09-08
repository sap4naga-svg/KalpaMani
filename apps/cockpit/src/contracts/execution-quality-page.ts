/**
 * The C8 execution and reconciliation payload contracts — Areas 9 and 10.
 *
 * `execution-models.ts` holds the per-trade `ExecutionQuality` record `TradeDetail` resolves
 * to. **This is the AREA 9 and AREA 10 surface**: the aggregate view over a window of recorded
 * orders and fills, and the recorded comparisons of internal state against a broker's.
 *
 * **DISPLAYING AN ORDER LIFECYCLE IS NOT PARTICIPATING IN ONE**, and displaying a
 * reconciliation is not opening a broker session. There is no submit, cancel, amend, retry,
 * reconnect, refresh-from-broker or repair value in any vocabulary here, and no field on any
 * shape could carry one.
 *
 * FIVE SEPARATIONS, EACH A REFINEMENT:
 *
 *   AN ORDER ROW IS NOT A TRADE               a fill is never counted as a trade, and the row
 *                                             carries the trade it belongs to by reference
 *                                             rather than becoming one
 *   A CANCELLATION IS NOT AN EXIT             the lifecycle vocabulary holds no exit member,
 *                                             and a cancelled order reports what it filled
 *   SUBMITTED PROTECTION IS NOT ACTIVE        a claim of confirmed protection requires a
 *                                             recorded confirmation, and a reference list is
 *                                             never accepted as one
 *   A MODELLED COST IS NOT SUBTRACTED         §12.4: an actual fill already contains what it
 *                                             crossed. The two costs sit side by side under
 *                                             stated treatments and are never combined
 *   A PAST RECONCILIATION IS NOT PRESENT      every run shows its own as-of, the two compared
 *   HEALTH                                    as-of times are separate fields, and a missing
 *                                             comparison input is neither zero nor a match
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { executionQuality, orderSide } from "./execution-models";
import { collectionPayload } from "./pagination";
import { refListFieldOf, refOf } from "./references";
import {
  countValue,
  instant,
  metricOf,
  metricValue,
  parseInstantMs,
  reasonCoded,
  safeId,
} from "./values";
import { isValueBearing } from "./validity";
import { availabilityState, fieldReasonCode } from "./vocabularies";

function numberOf(metric: z.infer<typeof metricValue>): number | null {
  if (!isValueBearing(metric.availability)) {
    return null;
  }
  return typeof metric.value === "number" ? metric.value : null;
}

function requireMember(
  code: string,
  members: readonly string[],
  field: string,
  ctx: z.RefinementCtx,
): void {
  if (!members.includes(code)) {
    ctx.addIssue({ code: "custom", message: `${field} carries a code outside its closed set` });
  }
}

/* ================================================ Area 9 — recorded order lifecycle === */

/**
 * The recorded lifecycle states of ONE order.
 *
 * **There is no exit member, and that is the point.** An exit is a position event; a
 * cancellation is an order event. Area 36.3 keeps Trade History, Trade Detail, Execution
 * History and the Audit Trail apart, and collapsing a cancel into an exit is how the third
 * becomes the first.
 */
export const ORDER_LIFECYCLE_STATES = [
  "SUBMITTED",
  "ACKNOWLEDGED",
  "PARTIALLY_FILLED",
  "FILLED",
  "REJECTED",
  "CANCELLED",
] as const;
export const orderLifecycleState = z.enum(ORDER_LIFECYCLE_STATES);
export type OrderLifecycleState = z.infer<typeof orderLifecycleState>;

/**
 * What the duplicate-order protection recorded for this order.
 *
 * ADR-0004 governs deterministic order identity and idempotency. This DISPLAYS an outcome the
 * execution runtime would have recorded; it implements no protection and performs no check.
 */
export const DUPLICATE_PROTECTION_OUTCOMES = [
  "DETERMINISTIC_IDENTITY_ACCEPTED",
  "DUPLICATE_SUPPRESSED_BY_DETERMINISTIC_IDENTITY",
  "NO_DUPLICATE_OBSERVED",
  "PROTECTION_OUTCOME_NOT_RECORDED",
] as const;

/**
 * What the record shows about protective cover for the position this order touched.
 *
 * `SUBMITTED_NOT_CONFIRMED` and `CONFIRMED_WORKING` are deliberately different members: a
 * submitted protective order is a submission, and cover is what a confirmation establishes.
 */
export const PROTECTION_STATES = [
  "CONFIRMED_WORKING",
  "SUBMITTED_NOT_CONFIRMED",
  "CANCELLED_RECORDED",
  "NONE_RECORDED",
] as const;

/** How a modelled cost relates to a recorded one. Neither member permits a subtraction. */
export const COST_COMPARISON_BASES = [
  "MODELLED_AND_RECORDED_REPORTED_SEPARATELY",
  "MODELLED_NOT_AVAILABLE_FOR_THIS_ORDER",
] as const;

export const executionQualityRecord = z
  .object({
    record_id: safeId,
    /** The accepted §4.5 measurement, unchanged and carried whole. */
    quality: executionQuality,
    trade_ref: refOf("ExecutionQualityRecord.trade_ref"),
    order_ref: refOf("ExecutionQualityRecord.order_ref"),
    lifecycle_state: orderLifecycleState,
    side: orderSide,
    ordered_quantity: metricOf("execution.ordered_quantity"),
    filled_quantity: metricOf("execution.quantity"),
    event_time: instant,
    observed_time: instant,
    strategy_module: reasonCoded,
    duplicate_protection: reasonCoded,
    protective_order_state: reasonCoded,
    protective_order_refs: refListFieldOf("ExecutionQualityRecord.protective_order_refs"),
    /**
     * The recorded confirmation a claim of working protection rests on.
     *
     * ABSENT wherever nothing confirmed the order, which is what makes
     * `SUBMITTED_NOT_CONFIRMED` a state rather than a hedge.
     */
    protection_confirmed_at: metricValue,
    /**
     * The modelled cost and the recorded one, under stated treatments (§12.1, §12.4).
     *
     * They are never summed, never netted and never subtracted from one another. An actual
     * fill price already incorporates the spread crossed and the slippage realized.
     */
    modelled_cost: metricOf("execution.modelled_cost"),
    recorded_cost: metricOf("execution.recorded_cost"),
    cost_treatment: reasonCoded,
    cost_comparison_basis: reasonCoded,
  })
  .superRefine((candidate, ctx) => {
    requireMember(
      candidate.duplicate_protection.code,
      DUPLICATE_PROTECTION_OUTCOMES,
      "duplicate protection outcome",
      ctx,
    );
    requireMember(
      candidate.protective_order_state.code,
      PROTECTION_STATES,
      "protective order state",
      ctx,
    );
    requireMember(
      candidate.cost_comparison_basis.code,
      COST_COMPARISON_BASES,
      "cost comparison basis",
      ctx,
    );
    /*
     * AN AREA 9 ROW MEASURES A FILL OR AN ORDER. THE WINDOW AGGREGATE IS A SEPARATE FIELD.
     *
     * §12.3 gives `slippage` and `slippage.aggregate` different minimum-observation rules, so
     * an aggregate hidden among the rows would be averaged with them.
     */
    if (candidate.quality.scope === "AGGREGATE") {
      ctx.addIssue({
        code: "custom",
        message: "the window aggregate is carried once, beside the rows and never among them",
      });
    }
    /*
     * THE ROW AND ITS MEASUREMENT AGREE ABOUT THE SIDE.
     *
     * §12.3.1's `side_sign` is derived from the side, so two spellings that could disagree is
     * how a book of adverse fills comes to report zero.
     */
    if (candidate.side !== candidate.quality.side) {
      ctx.addIssue({
        code: "custom",
        message: "a row and its measurement state one side",
      });
    }
    const ordered = numberOf(candidate.ordered_quantity);
    const filled = numberOf(candidate.filled_quantity);
    if (ordered !== null && filled !== null) {
      if (filled > ordered) {
        ctx.addIssue({
          code: "custom",
          message: "an order does not fill more than it asked for",
        });
      }
      switch (candidate.lifecycle_state) {
        case "FILLED":
          if (filled !== ordered) {
            ctx.addIssue({
              code: "custom",
              message: "a filled order accounts for the whole ordered quantity",
            });
          }
          break;
        case "PARTIALLY_FILLED":
          if (filled === 0 || filled >= ordered) {
            ctx.addIssue({
              code: "custom",
              message: "a partially filled order filled some of its quantity and not all of it",
            });
          }
          break;
        case "REJECTED":
          if (filled !== 0) {
            ctx.addIssue({
              code: "custom",
              message: "a rejected order filled nothing",
            });
          }
          break;
        case "SUBMITTED":
        case "ACKNOWLEDGED":
          if (filled !== 0) {
            ctx.addIssue({
              code: "custom",
              message: "an order that has not filled reports no filled quantity",
            });
          }
          break;
        case "CANCELLED":
          /*
           * A CANCELLED ORDER MAY HAVE FILLED PART OF ITS QUANTITY, AND THAT IS NOT AN EXIT.
           *
           * Nothing is asserted here beyond the `filled <= ordered` bound above: a cancel is
           * an order event, and what it filled before it was cancelled is a fact about the
           * order rather than about the position.
           */
          break;
      }
    }
    /*
     * A SUBMITTED PROTECTIVE ORDER IS NOT PROOF OF ACTIVE PROTECTION.
     */
    if (
      candidate.protective_order_state.code === "CONFIRMED_WORKING" &&
      !isValueBearing(candidate.protection_confirmed_at.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "confirmed protective cover rests on a recorded confirmation",
      });
    }
    if (
      candidate.protective_order_state.code === "NONE_RECORDED" &&
      candidate.protective_order_refs.items.length > 0
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a row recording no protective order carries no protective reference",
      });
    }
    /*
     * A MODELLED COST THAT IS NOT AVAILABLE IS ABSENT, AND NEVER A ZERO.
     */
    if (
      candidate.cost_comparison_basis.code === "MODELLED_NOT_AVAILABLE_FOR_THIS_ORDER" &&
      isValueBearing(candidate.modelled_cost.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "an unavailable modelled cost carries no value",
      });
    }
    /*
     * AN EVENT IS NOT OBSERVED BEFORE IT HAPPENED.
     */
    const eventMs = parseInstantMs(candidate.event_time);
    const observedMs = parseInstantMs(candidate.observed_time);
    if (eventMs !== null && observedMs !== null && observedMs < eventMs) {
      ctx.addIssue({
        code: "custom",
        message: "a recorded execution event is not observed before it occurred",
      });
    }
  });
export type ExecutionQualityRecord = z.infer<typeof executionQualityRecord>;

/** One recorded lifecycle outcome and how many observations carried it, in the window. */
export const executionOutcomeCount = z.object({
  outcome: reasonCoded,
  count: metricOf("execution.outcome_count"),
});

/**
 * The window aggregate — and it is deliberately NOT an `ExecutionQuality`.
 *
 * §4.5's `ExecutionQuality` carries a `subject_ref` whose kind follows its scope: an order, a
 * fill, or the trade a trade-level aggregate was measured over. **A window is none of the
 * three, and `RefKind` names no window.** Reusing that contract here would have forced this
 * aggregate to point at an order, a fill or a trade it was not measured over — which is the
 * container conflation ADR-0030 R8 refuses — or to invent a kind, which §4.3.2 forbids
 * outright. So the window aggregate carries the measurements and names the method, and it
 * carries no subject reference at all, because it has no single subject to reference.
 *
 * §12.3's rules are unchanged by that: the identifier is `slippage.aggregate`, the method is
 * named, and the population it was computed over is stated separately by the page.
 */
export const executionWindowAggregate = z.object({
  /** §12.3: an aggregate names the method it was aggregated by. */
  aggregation_method: reasonCoded,
  /** `slippage.aggregate`, and never the per-fill `slippage`: two rules, two identifiers. */
  slippage: metricOf("slippage.aggregate"),
  fill_rate: metricOf("execution.fill_rate"),
  signal_to_order_latency: metricOf("latency.signal_to_order"),
  order_to_fill_latency: metricOf("latency.order_to_fill"),
  quantity: metricOf("execution.quantity"),
  clock_source: reasonCoded,
  clock_accuracy: metricOf("clock.accuracy"),
});
export type ExecutionWindowAggregate = z.infer<typeof executionWindowAggregate>;

export const executionQualityPagePayload = collectionPayload(executionQualityRecord, {
  window: z.object({
    from: instant,
    to: instant,
    calendar: reasonCoded,
    timezone: z.literal("UTC"),
  }),
  /**
   * The window aggregate, kept OUT of the rows.
   *
   * §12.3 declares a minimum of twenty fills for `slippage.aggregate`. Where the window holds
   * fewer, this reports `INSUFFICIENT_OBSERVATIONS` — **the rule working, and never a headline
   * manufactured from a smaller sample**.
   */
  aggregate: executionWindowAggregate,
  /**
   * The aggregate's population, stated so a reader can check the rule rather than trust it.
   *
   * §12.3: "Fills with no reference are excluded and counted, and the result is `PARTIAL`
   * naming how many — an average over a silently reduced population is a different metric."
   */
  aggregate_population: z.object({
    observed: countValue,
    excluded: metricOf("execution.excluded_fills"),
    minimum: countValue,
    /** Why a fill was excluded, where any was. */
    exclusion_reasons: z.array(reasonCoded),
  }),
  /** Rejects, cancels, missed fills and duplicate suppressions, each with its own count. */
  outcomes: z.array(executionOutcomeCount),
  /** The reference price every row was measured against, named once for the window. */
  reference_basis: z.object({
    name: reasonCoded,
    side_convention: reasonCoded,
    clock_source: reasonCoded,
  }),
  /** The execution runtime this page would read. It does not exist, and the page says so. */
  runtime_state: z.object({
    availability: availabilityState,
    reason: fieldReasonCode,
    note: reasonCoded,
  }),
  /**
   * The rows that are ILLUSTRATIVE rather than projected from the recorded book.
   *
   * The recorded execution evidence contains no rejected order, no cancelled order and no fill
   * whose reference price went unrecorded, so three lifecycle outcomes this area exists to show
   * have no row to render. They are named HERE, by identifier, rather than being left
   * indistinguishable from the projected ones — and the aggregate population states separately
   * which observations it was computed over, so an illustrative row cannot move a headline.
   */
  illustrative_record_ids: z.array(safeId),
});
export type ExecutionQualityPagePayload = z.infer<typeof executionQualityPagePayload>;

export const executionQualityPage = executionQualityPagePayload.superRefine(
  (candidate, ctx) => {
    /*
     * A VALUE BELOW ITS DECLARED MINIMUM IS NOT COMPUTED (§12.1).
     *
     * The per-record contract already enforces this for one record; this states it for the
     * page, where the observed population and the declared minimum are both visible and a
     * reader could otherwise be shown a headline the rule forbids.
     */
    const observed = numberOf(candidate.aggregate_population.observed);
    const minimum = numberOf(candidate.aggregate_population.minimum);
    if (
      observed !== null &&
      minimum !== null &&
      observed < minimum &&
      isValueBearing(candidate.aggregate.slippage.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a window aggregate below its declared minimum reports the state, not a number",
      });
    }
    /*
     * AN EXCLUSION IS COUNTED AND NAMED, OR IT DID NOT HAPPEN.
     */
    const excluded = numberOf(candidate.aggregate_population.excluded);
    if (
      excluded !== null &&
      excluded > 0 &&
      candidate.aggregate_population.exclusion_reasons.length === 0
    ) {
      ctx.addIssue({
        code: "custom",
        message: "an excluded observation names why it was excluded",
      });
    }
    if (
      excluded === 0 &&
      candidate.aggregate_population.exclusion_reasons.length > 0
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a page that excluded nothing names no exclusion reason",
      });
    }
    /*
     * EVERY ROW IS ITS OWN RECORD.
     */
    const ids = new Set(candidate.items.map((row) => row.record_id));
    if (ids.size !== candidate.items.length) {
      ctx.addIssue({ code: "custom", message: "an execution page carries each record once" });
    }
    /*
     * AN ILLUSTRATIVE ROW IS NAMED, AND IT IS A ROW THIS PAGE ACTUALLY DELIVERED.
     *
     * Naming an identifier the page does not carry would state a caveat about nothing, and
     * carrying an illustrative row this list omits would leave it indistinguishable from a
     * projected one.
     */
    for (const illustrative of candidate.illustrative_record_ids) {
      if (!ids.has(illustrative)) {
        ctx.addIssue({
          code: "custom",
          message: "an illustrative record is one of the rows this page delivered",
        });
        return;
      }
    }
  },
);

export const EXECUTION_QUALITY_SCHEMA = "cockpit.execution_quality.v1";
export const executionQualityEnvelope = envelope(
  executionQualityPage,
  EXECUTION_QUALITY_SCHEMA,
);

/* ============================================ Area 10 — ReconciliationStatus (§4.5) === */

/** What a recorded reconciliation concluded. */
export const RECONCILIATION_RESULTS = [
  "RECONCILED",
  "MISMATCH_RECORDED",
  "COMPARISON_INPUT_MISSING",
  "NOT_ATTEMPTED",
] as const;

/**
 * The recorded broker session condition.
 *
 * **This is a RECORD, not a session.** The Cockpit holds no brokerage credential and opens no
 * brokerage session, so every member describes something that was written down elsewhere.
 */
export const SESSION_STATES = [
  "SESSION_RECORDED_CONNECTED",
  "SESSION_RECORDED_RECONNECTED",
  "SESSION_RECORDED_DISCONNECTED",
  "SESSION_STATE_NOT_RECORDED",
] as const;

/** Whether the two sides of a comparison were taken at the same instant. */
export const AS_OF_ALIGNMENTS = [
  "AS_OF_TIMES_ALIGNED",
  "AS_OF_TIMES_DIFFER",
  "BROKER_AS_OF_NOT_RECORDED",
] as const;

/** One position the two sides disagreed about, or agreed about. */
export const positionDiff = z.object({
  security_ref: refOf("ReconciliationStatus.position_diffs[].security_ref"),
  expected: metricOf("reconciliation.expected_quantity"),
  observed: metricOf("reconciliation.observed_quantity"),
  difference: metricOf("reconciliation.quantity_difference"),
  finding: reasonCoded,
});

/** One order the two sides disagreed about. */
export const orderDiff = z.object({
  local_ref: refOf("ReconciliationStatus.order_diffs[].local_ref"),
  disposition: reasonCoded,
});

/** One ownership finding. Ownership is a separate question from quantity. */
export const ownershipFinding = z.object({
  local_ref: refOf("ReconciliationStatus.ownership_findings[].local_ref"),
  finding: reasonCoded,
  disposition: reasonCoded,
});

/**
 * A cash or equity comparison.
 *
 * **Broker equity is informational and never sizing authority** (CLAUDE.md §6). The literal
 * below is a field a reader can see rather than a sentence a screen might forget.
 */
export const balanceComparison = z.object({
  measure: reasonCoded,
  internal: metricOf("reconciliation.internal_amount"),
  broker_reported: metricOf("reconciliation.broker_amount"),
  difference: metricOf("reconciliation.amount_difference"),
  informational_only: z.literal(true),
});

/** A recorded reconnect, restart or authentication condition. */
export const sessionEvent = z.object({
  at: instant,
  event: reasonCoded,
});

export const reconciliationStatus = z
  .object({
    run_id: safeId,
    /** §4.5: "a past reconciliation always shows its `as_of`". Required, always. */
    as_of: instant,
    result: reasonCoded,
    /** WHAT was compared. A result whose scope is unstated is a result about nothing. */
    comparison_scope: reasonCoded,
    internal_as_of: instant,
    /** ABSENT where the broker side recorded no as-of. It is not a match, and not a zero. */
    broker_as_of: metricOf("reconciliation.broker_as_of"),
    as_of_alignment: reasonCoded,
    position_diffs: z.array(positionDiff),
    order_diffs: z.array(orderDiff),
    ownership_findings: z.array(ownershipFinding),
    balances: z.array(balanceComparison),
    orphans: metricOf("reconciliation.orphans"),
    session_state: reasonCoded,
    session_events: z.array(sessionEvent),
    /** Inputs the comparison did not have. A missing input is neither zero nor a match. */
    missing_inputs: z.array(reasonCoded),
    incident_refs: refListFieldOf("ReconciliationStatus.incident_refs"),
    trade_refs: refListFieldOf("ReconciliationStatus.trade_refs"),
    /** How long ago this ran, so a historical success is never read as present health. */
    age: metricOf("reconciliation.age"),
  })
  .superRefine((candidate, ctx) => {
    requireMember(candidate.result.code, RECONCILIATION_RESULTS, "reconciliation result", ctx);
    requireMember(candidate.session_state.code, SESSION_STATES, "session state", ctx);
    requireMember(candidate.as_of_alignment.code, AS_OF_ALIGNMENTS, "as-of alignment", ctx);
    const reconciled = candidate.result.code === "RECONCILED";
    /*
     * A MISSING COMPARISON INPUT IS NOT A MATCH.
     *
     * A run that could not read one side has not reconciled anything, whatever the diffs it
     * managed to compute.
     */
    if (reconciled && candidate.missing_inputs.length > 0) {
      ctx.addIssue({
        code: "custom",
        message: "a run missing a comparison input has not reconciled",
      });
    }
    if (candidate.result.code === "COMPARISON_INPUT_MISSING" && candidate.missing_inputs.length === 0) {
      ctx.addIssue({
        code: "custom",
        message: "a run reporting a missing input names which input was missing",
      });
    }
    /*
     * A RECONCILED RUN FOUND NOTHING TO REPORT, AND ITS ORPHAN COUNT IS A MEASURED ZERO.
     */
    if (reconciled) {
      if (candidate.position_diffs.length > 0 || candidate.order_diffs.length > 0) {
        ctx.addIssue({
          code: "custom",
          message: "a reconciled run records no position or order difference",
        });
      }
      if (numberOf(candidate.orphans) !== 0) {
        ctx.addIssue({
          code: "custom",
          message: "a reconciled run reports a measured zero orphans",
        });
      }
    }
    /*
     * A MISMATCH REPORTS WHAT DISAGREED.
     */
    if (
      candidate.result.code === "MISMATCH_RECORDED" &&
      candidate.position_diffs.length === 0 &&
      candidate.order_diffs.length === 0 &&
      candidate.ownership_findings.length === 0 &&
      numberOf(candidate.orphans) === 0
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a recorded mismatch names what disagreed",
      });
    }
    /*
     * A RUN THAT WAS NOT ATTEMPTED COMPARED NOTHING.
     */
    if (candidate.result.code === "NOT_ATTEMPTED") {
      if (candidate.position_diffs.length > 0 || candidate.order_diffs.length > 0) {
        ctx.addIssue({
          code: "custom",
          message: "a run that was not attempted records no comparison",
        });
      }
      if (isValueBearing(candidate.orphans.availability)) {
        ctx.addIssue({
          code: "custom",
          message: "a run that was not attempted counted no orphans",
        });
      }
    }
    /*
     * THE ALIGNMENT STATEMENT MATCHES THE TWO AS-OF TIMES IT DESCRIBES.
     *
     * "Compare matching scope and as-of times" is only checkable when the comparison itself is
     * recorded, so the declared alignment is verified against the instants beside it rather
     * than trusted.
     */
    const brokerAsOf =
      isValueBearing(candidate.broker_as_of.availability) &&
      typeof candidate.broker_as_of.value === "string"
        ? parseInstantMs(candidate.broker_as_of.value)
        : null;
    const internalAsOf = parseInstantMs(candidate.internal_as_of);
    if (brokerAsOf === null) {
      if (candidate.as_of_alignment.code !== "BROKER_AS_OF_NOT_RECORDED") {
        ctx.addIssue({
          code: "custom",
          message: "an unrecorded broker as-of cannot be described as aligned or differing",
        });
      }
      if (reconciled) {
        ctx.addIssue({
          code: "custom",
          message: "a run with no recorded broker as-of has not reconciled against one",
        });
      }
    } else if (internalAsOf !== null) {
      const aligned = brokerAsOf === internalAsOf;
      const declared = candidate.as_of_alignment.code === "AS_OF_TIMES_ALIGNED";
      if (aligned !== declared) {
        ctx.addIssue({
          code: "custom",
          message: "the declared as-of alignment disagrees with the two recorded instants",
        });
      }
    }
  });
export type ReconciliationStatus = z.infer<typeof reconciliationStatus>;

export const reconciliationPayload = collectionPayload(reconciliationStatus, {
  /**
   * The LATEST recorded run, and what it does and does not establish.
   *
   * §4.5: "a historical success is not current health". The current state is its own field and
   * is never derived from the newest result.
   */
  latest_run_id: safeId,
  current_health: z.object({
    availability: availabilityState,
    reason: fieldReasonCode,
    note: reasonCoded,
  }),
  /** The broker session this page would read. There is none, and there is no path to one. */
  broker_session: z.object({
    availability: availabilityState,
    reason: fieldReasonCode,
    note: reasonCoded,
  }),
  /** The controls this screen does not have, named so their absence is visible. */
  absent_controls: z.array(reasonCoded),
});
export type ReconciliationPayload = z.infer<typeof reconciliationPayload>;

export const reconciliationCollection = reconciliationPayload.superRefine(
  (candidate, ctx) => {
    const ids = new Set(candidate.items.map((run) => run.run_id));
    if (ids.size !== candidate.items.length) {
      ctx.addIssue({ code: "custom", message: "a reconciliation page carries each run once" });
    }
    /*
     * THE NAMED LATEST RUN IS ON THE PAGE, AND IT IS THE NEWEST ONE.
     *
     * A "latest" that names a row the page does not carry, or an older row than one it does,
     * is a claim a reader cannot check against what they were shown.
     */
    if (candidate.items.length > 0) {
      if (!ids.has(candidate.latest_run_id)) {
        ctx.addIssue({
          code: "custom",
          message: "the named latest run is one of the runs this page delivered",
        });
        return;
      }
      let newest = candidate.items[0];
      for (const run of candidate.items) {
        const at = parseInstantMs(run.as_of);
        const best = parseInstantMs(newest.as_of);
        if (at !== null && best !== null && at > best) {
          newest = run;
        }
      }
      if (newest.run_id !== candidate.latest_run_id) {
        ctx.addIssue({
          code: "custom",
          message: "the named latest run is the newest run this page delivered",
        });
      }
    }
  },
);

export const RECONCILIATION_SCHEMA = "cockpit.reconciliation_status.v1";
export const reconciliationEnvelope = envelope(
  reconciliationCollection,
  RECONCILIATION_SCHEMA,
);
