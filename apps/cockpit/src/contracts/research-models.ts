/**
 * The C7 research and feedback payload contracts — `read-model-contracts.md` §4.5, Areas
 * 14, 15, 16, 17, 18 and 21.
 *
 * **These are shapes a recorded research fact would arrive in. No research engine exists, no
 * backtest has run, no shadow Challenger has operated and no result is asserted anywhere in
 * this module.** Backtesting is **NOT STARTED**, no provider is selected, and **G1 and G2 are
 * OPEN**.
 *
 * FIVE RULES THIS MODULE ENFORCES AT THE BOUNDARY RATHER THAN IN A SCREEN, because a screen
 * that noticed any of them would have no honest way to render the disagreement:
 *
 *   A NAMED BASELINE COMES FIRST      a run without a resolvable baseline is displayed as
 *                                     INCOMPLETE rather than as a result (Area 14, ADR-0026
 *                                     §22). The comparison field says so, and it is not left
 *                                     to a reader to notice the reference resolves to nothing
 *   EVERY TERMINAL STATE COUNTS       `FAILED` and `ABANDONED` count against the trial budget
 *                                     exactly as `COMPLETED` does (§2.7). A run that is
 *                                     quietly discarded is the one that most needs counting
 *   THE CLASS IS CARRIED, NEVER       `evaluation_class` is declared in the registration and
 *   DERIVED                           travels with every result. It is never inferred from a
 *                                     state, a date or an outcome (§4.5, §2.7.1)
 *   EXPOSURE FOLLOWS THE DATA         the ledger is keyed by the LOCKED SET and read across
 *                                     the lineage, so a new registration, Challenger or name
 *                                     leaves the data exactly as exposed as it was
 *   HYPOTHETICAL IS NEVER REALIZED    shadow economics carry their own identifier, their own
 *                                     label and their own assumptions, and are never placed
 *                                     in a series with a realized result (§2.8)
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { collectionPayload } from "./pagination";
import { analysisWindow } from "./portfolio-models";
import { refListFieldOf, refOf } from "./references";
import { instant, metricOf, metricValue, reasonCoded, safeId, versionPins } from "./values";
import { availabilityState, environment, fieldReasonCode } from "./vocabularies";

/**
 * The three evaluation classes of the feedback specification §2.7.1 — **and only one of them
 * is confirmation.**
 *
 * CONSUMED, never extended, and never inferred. A run that declares `CONFIRMATORY` against a
 * set the ledger records as exposed is REFUSED rather than downgraded silently; the
 * researcher may re-declare it `EXPLORATORY_REUSE` and proceed with the disclosure that
 * entails.
 */
export const EVALUATION_CLASSES = [
  "DETERMINISTIC_REPRODUCTION",
  "EXPLORATORY_REUSE",
  "CONFIRMATORY",
] as const;
export const evaluationClass = z.enum(EVALUATION_CLASSES);
export type EvaluationClass = z.infer<typeof evaluationClass>;

/** §4.5 `ResearchRun.state` — five members, and every terminal one counts. */
export const RESEARCH_RUN_STATES = [
  "PLANNED",
  "RUNNING",
  "COMPLETED",
  "FAILED",
  "ABANDONED",
] as const;
export const researchRunState = z.enum(RESEARCH_RUN_STATES);
export type ResearchRunState = z.infer<typeof researchRunState>;

/** The three states that end a run. Each one spends a trial. */
export const TERMINAL_RUN_STATES: readonly ResearchRunState[] = [
  "COMPLETED",
  "FAILED",
  "ABANDONED",
];

/** §4.5 `ResearchQueueItem.state` — the §2.4 transitions, and nothing else. */
export const RESEARCH_QUEUE_STATES = [
  "QUEUED",
  "PREREGISTRATION_DRAFTED",
  "REGISTERED",
  "WITHDRAWN",
] as const;
export const researchQueueState = z.enum(RESEARCH_QUEUE_STATES);
export type ResearchQueueState = z.infer<typeof researchQueueState>;

/** §4.5 `ChampionChallengerComparison.evidence_completeness`. */
export const EVIDENCE_COMPLETENESS = ["COMPLETE", "PARTIAL", "UNKNOWN"] as const;
export const evidenceCompleteness = z.enum(EVIDENCE_COMPLETENESS);

/* ==================================================================== Area 14 — runs */

/**
 * §4.5 `ResearchRun.reproducibility` — enough to reproduce the run **without a network**
 * (§2.7). Every identity is stated; none is defaulted into existence.
 */
export const runReproducibility = z.object({
  manifest: safeId,
  /** The declared information-set profile. `PUBLIC_PIT` is not reachable here. */
  profile: reasonCoded,
  revision_view: safeId,
  code_identity: safeId,
  config_identity: safeId,
  seeds: z.array(z.number().int()),
  environment,
});

export const researchRun = z
  .object({
    run_id: safeId,
    /** §4.5 kind `registration`. */
    registration_ref: refOf("ResearchRun.registration_ref"),
    challenger_version: safeId,
    /**
     * §4.5 kind `strategy_version` — **a run without a NAMED baseline renders incomplete.**
     *
     * The reference is REQUIRED and stays present even when it names nothing: §4.3 keeps a
     * reference visible so a reader knows the join exists, and `baseline_comparison` below is
     * where the absence lands as a state.
     */
    baseline_ref: refOf("ResearchRun.baseline_ref"),
    state: researchRunState,
    /** Per §2.7, and **NEVER inferred from the state**. */
    evaluation_class: evaluationClass,
    /** §4.5 kind `evidence` — the locked-set identity this run touched. */
    dataset_ref: refOf("ResearchRun.dataset_ref"),
    /** True for every terminal state, `FAILED` and `ABANDONED` included. */
    counts_against_budget: z.boolean(),
    /** Read from the registry record, and never recounted by a view. */
    trial_ordinal: metricOf("research.trial_ordinal"),
    results: z.array(z.object({ measure: reasonCoded, value: metricValue })),
    decomposition: z.array(
      z.object({ axis: reasonCoded, bucket: reasonCoded, value: metricValue }),
    ),
    capacity: metricOf("strategy.capacity"),
    stress: z.array(z.object({ scenario: reasonCoded, value: metricValue })),
    reproducibility: runReproducibility,
    /**
     * ADDITIVE: the baseline comparison, as a value-bearing field.
     *
     * **A missing baseline must visibly prevent a complete comparison** (Area 14). The
     * reference alone cannot say that — §4.3 gives a `Ref` no availability and no reason — so
     * the comparison the baseline would have supported carries the state and the reason code
     * instead. An unresolvable baseline lands here as `NOT_YET_AVAILABLE` /
     * `REFERENT_NOT_FOUND`, never as a zero difference.
     */
    baseline_comparison: z.array(z.object({ measure: reasonCoded, value: metricValue })),
    /** ADDITIVE: whether the named baseline resolved at all, stated rather than implied. */
    baseline_state: z.object({ availability: availabilityState, reason: fieldReasonCode }),
    /** ADDITIVE: §5.1 sorts `/research/runs` by `started_at`, and a sort needs its field. */
    started_at: metricOf("research.run_started_at"),
    completed_at: metricOf("research.run_completed_at"),
    /** ADDITIVE: the window the run evaluated over, with its calendar and timezone. */
    window: analysisWindow,
    /** ADDITIVE: why a `FAILED` or `ABANDONED` run ended. A closed code, never prose. */
    state_reason: reasonCoded,
    /**
     * ADDITIVE: every reuse this run's evidence rests on (§2.7.1).
     *
     * **An `EXPLORATORY_REUSE` result is never displayed as fresh out-of-sample evidence**,
     * and the disclosure travels with the result rather than living on a neighbouring screen.
     */
    exposure_disclosure: z.array(reasonCoded),
    /** ADDITIVE: what this run does NOT establish, named rather than left to a reader. */
    limitations: z.array(reasonCoded),
  })
  .superRefine((candidate, ctx) => {
    /*
     * EVERY TERMINAL STATE COUNTS — EXCEPT A DETERMINISTIC REPRODUCTION, WHICH SPENDS NONE.
     *
     * TWO ACCEPTED CLAUSES MEET HERE, AND THEY ARE RECONCILED RATHER THAN CHOSEN BETWEEN.
     * §4.5 states `counts_against_budget` is "true for every terminal state, including FAILED
     * and ABANDONED" — a rule about which STATES count, written to stop a discarded run
     * quietly shrinking the multiple-testing denominator. §2.7.1 then carves out one CLASS:
     * a `DETERMINISTIC_REPRODUCTION` "adds no new exposure entry beyond a reproduction note,
     * and it does not consume trial budget", because re-executing a frozen run at its exact
     * manifest, seeds and code identity "confirms reproducibility and nothing else" and so
     * tests no new hypothesis.
     *
     * The later, narrower clause governs its own class and the broader one governs the rest.
     * Reading §4.5 as absolute would make a terminal reproduction unrepresentable; reading
     * §2.7.1 as general would let any run avoid the denominator by declaring a class. Neither
     * clause is amended, and **nothing here relaxes the accounting for the other two classes:
     * a FAILED or ABANDONED exploratory or confirmatory run still spends a trial.**
     */
    const terminal = TERMINAL_RUN_STATES.includes(candidate.state);
    const reproduction = candidate.evaluation_class === "DETERMINISTIC_REPRODUCTION";
    const expected = terminal && !reproduction;
    if (expected !== candidate.counts_against_budget) {
      ctx.addIssue({
        code: "custom",
        message:
          "a terminal run counts against the trial budget unless it is a deterministic " +
          "reproduction, which consumes none",
      });
    }
    /*
     * AN UNRESOLVED BASELINE LEAVES NO COMPLETE COMPARISON BEHIND.
     *
     * Where `baseline_state` is not value-bearing, every comparison figure the baseline would
     * have supported is an absence too. A run reporting a clean difference against a baseline
     * it could not resolve has compared against nothing.
     */
    const baselineBearing = ["AVAILABLE", "STALE", "PARTIAL", "EMPTY_VERIFIED"].includes(
      candidate.baseline_state.availability,
    );
    if (!baselineBearing) {
      for (const entry of candidate.baseline_comparison) {
        if (entry.value.value !== undefined) {
          ctx.addIssue({
            code: "custom",
            message:
              "a run whose named baseline did not resolve carries no baseline comparison value",
          });
          return;
        }
      }
    }
  });
export type ResearchRun = z.infer<typeof researchRun>;

export const researchRunPayload = collectionPayload(researchRun, {
  /** The classes this read model may carry, delivered rather than re-spelled by a screen. */
  evaluation_classes: z.array(evaluationClass),
  /** The states it may carry, for the same reason. */
  run_states: z.array(researchRunState),
});
export type ResearchRunPayload = z.infer<typeof researchRunPayload>;

export const RESEARCH_RUN_SCHEMA = "cockpit.research_run.v1";
export const researchRunEnvelope = envelope(researchRunPayload, RESEARCH_RUN_SCHEMA);

/* =================================================================== Area 17 — queue */

export const researchQueueItem = z
  .object({
    item_id: safeId,
    /** §4.5 kind `source_fact` — the health transition, drift or cluster that raised it. */
    trigger_ref: refOf("ResearchQueueItem.trigger_ref"),
    issue: reasonCoded,
    proposed_experiment: reasonCoded,
    /** §4.5 kind `strategy_version`. An item with no named baseline is refused at admission. */
    baseline_ref: refOf("ResearchQueueItem.baseline_ref"),
    state: researchQueueState,
    /** Required when `WITHDRAWN`, and absent otherwise. */
    withdrawal_reason: metricValue.optional(),
    /**
     * **A queue entry is not an authorization**, and every item displays what it waits on.
     * The list is non-empty for every item that has not been withdrawn.
     */
    awaiting_authorizations: z.array(reasonCoded),
    priority: reasonCoded,
    /** ADDITIVE: §5.1 sorts `/research/queue` by `created_at`, and a sort needs its field. */
    queued_at: metricOf("research.queued_at"),
    /** ADDITIVE: the module the issue was raised against. §5.1 declares no module filter
     * here, and the field exists because Area 17 presents the strategy beside the issue. */
    strategy_module: reasonCoded,
    /** ADDITIVE: Area 17 presents "supporting evidence". Kind `evidence`. */
    evidence_refs: refListFieldOf("ResearchQueueItem.evidence_refs"),
    /** ADDITIVE: Area 17 presents "dependencies". Closed codes, never prose. */
    dependencies: z.array(reasonCoded),
    /** ADDITIVE: Area 17 presents the "associated Challenger", where one exists. */
    challenger_ref: refOf("ResearchQueueItem.challenger_ref").optional(),
    /** ADDITIVE: the registration this item became, where it reached `REGISTERED`. */
    registration_ref: refOf("ResearchQueueItem.registration_ref").optional(),
    /** ADDITIVE: Area 17 presents "its result and history". A record, never an action log. */
    history: z.array(
      z.object({ state: researchQueueState, at: instant, note: reasonCoded }),
    ),
  })
  .superRefine((candidate, ctx) => {
    if ((candidate.state === "WITHDRAWN") !== (candidate.withdrawal_reason !== undefined)) {
      ctx.addIssue({
        code: "custom",
        message: "a withdrawn item states its withdrawal reason, and no other item carries one",
      });
    }
    /*
     * A QUEUE ENTRY IS NOT AN AUTHORIZATION (§2.4, Area 17).
     *
     * An open item with an empty authorization list reads as an item that may proceed, which
     * is the exact misreading this rule exists to prevent. A withdrawn item awaits nothing.
     */
    if (candidate.state !== "WITHDRAWN" && candidate.awaiting_authorizations.length === 0) {
      ctx.addIssue({
        code: "custom",
        message: "an open queue item names at least one authorization it is waiting on",
      });
    }
    if (
      candidate.state === "REGISTERED" &&
      candidate.registration_ref === undefined
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a registered item names the registration it became",
      });
    }
    for (let index = 1; index < candidate.history.length; index += 1) {
      if (candidate.history[index].at <= candidate.history[index - 1].at) {
        ctx.addIssue({
          code: "custom",
          message: "queue history entries are ordered in time, with no two at one instant",
        });
        return;
      }
    }
  });
export type ResearchQueueItem = z.infer<typeof researchQueueItem>;

export const researchQueuePayload = collectionPayload(researchQueueItem, {
  queue_states: z.array(researchQueueState),
});
export type ResearchQueuePayload = z.infer<typeof researchQueuePayload>;

export const RESEARCH_QUEUE_SCHEMA = "cockpit.research_queue.v1";
export const researchQueueEnvelope = envelope(researchQueuePayload, RESEARCH_QUEUE_SCHEMA);

/* ============================================================== Area 18 — hypotheses */

/**
 * One entry in a locked set's exposure ledger (§2.7.1).
 *
 * **The ledger is attached to the LOCKED SET, not to a registration**, and a registration
 * reads the whole ledger for the sets it names **and for every set overlapping them**,
 * including entries written under other registrations. That is why an entry names its own
 * registration: the entries a reader is looking at were mostly written by something else.
 */
export const exposureLedgerEntry = z.object({
  entry_id: safeId,
  /** The registration that wrote the entry. Kind `registration`. */
  registration_ref: refOf("HypothesisRegistration.exposure_ledger.entries[].registration_ref"),
  challenger_version: safeId,
  research_code_identity: safeId,
  evaluation_class: evaluationClass,
  at: instant,
  requested_extent: reasonCoded,
  /**
   * **MEASURED overlap with prior entries, and never assumed.**
   *
   * "Incomparable is not disjoint": where the extents cannot be compared the value is
   * `NOT_YET_AVAILABLE`, which is what `EXPOSURE_HISTORY_UNKNOWN` is built on — never a zero,
   * which would read as a clean set.
   */
  measured_overlap: metricOf("research.overlap_fraction"),
});

export const hypothesisRegistration = z
  .object({
    registration_id: safeId,
    registered_at: instant,
    /** Always true. A registry that permits an edit records what the researcher wishes. */
    immutable: z.literal(true),
    /** §4.5 kind `queue_item`. */
    trigger_ref: refOf("HypothesisRegistration.trigger_ref"),
    strategy_module: reasonCoded,
    thesis: reasonCoded,
    /** §4.5 kind `strategy_version`. */
    baseline_ref: refOf("HypothesisRegistration.baseline_ref"),
    variation: reasonCoded,
    /**
     * **READ ACROSS THE LINEAGE.** A new registration identity resets none of these three,
     * which is the whole point of §2.7.1: a control a rename defeats is not a control.
     */
    trial_budget: z.object({
      granted: metricOf("research.trial_budget_granted"),
      consumed: metricOf("research.trial_budget_consumed"),
      remaining: metricOf("research.trial_budget_remaining"),
    }),
    /**
     * ADDITIVE: the trials THIS identity ran on its own.
     *
     * It exists so the screen can show the difference between an identity's own count and its
     * lineage consumption. A registration whose own count is one and whose lineage
     * consumption is nine is exactly the case the rename rule exists for.
     */
    own_trial_count: metricOf("research.trials_own"),
    success_criteria: z.array(reasonCoded),
    /** NON-EMPTY: **a hypothesis that cannot fail has not been stated.** */
    failure_criteria: z.array(reasonCoded).min(1),
    data_requirements: z.array(reasonCoded),
    pins: z.object({
      manifest: safeId,
      profile: reasonCoded,
      revision_view: safeId,
      factor_definition_version: safeId,
      research_code_identity: safeId,
    }),
    lineage: z.object({
      parent_registration: refOf(
        "HypothesisRegistration.lineage.parent_registration",
      ).optional(),
      related_registrations: refListFieldOf(
        "HypothesisRegistration.lineage.related_registrations",
      ),
      amendment_chain: refListFieldOf("HypothesisRegistration.lineage.amendment_chain"),
      superseded_by: refOf("HypothesisRegistration.lineage.superseded_by").optional(),
    }),
    /** §4.5 kind `evidence` — the locked-set exposure ledger, which SPANS registrations. */
    exposure_ledger_ref: refOf("HypothesisRegistration.exposure_ledger_ref"),
    /**
     * ADDITIVE: the ledger itself, read across the lineage.
     *
     * Area 18 requires the exposure ledger and the trial budget to render "across the research
     * lineage, so a new registration identity resets neither", and a bare reference to an
     * artefact §5 catalogues no endpoint for cannot render anything at all.
     */
    exposure_ledger: z.object({
      locked_set: safeId,
      entry_count: metricOf("research.exposure_entries"),
      entries: z.array(exposureLedgerEntry),
      /** Whether the ledger can be shown to be COMPLETE. Incomplete fails closed. */
      completeness: evidenceCompleteness,
      /** The refusal the ledger produces for this registration, where it produces one. */
      refusal: reasonCoded.optional(),
    }),
    /** ADDITIVE: declared in the registration and checked BEFORE the run starts (§2.7.1). */
    declared_evaluation_class: evaluationClass,
    /** ADDITIVE: §5.1 declares a `state` filter on `/research/hypotheses`. */
    state: reasonCoded,
    /** §4.5 kind `research_run` — results APPEND and never edit the registration. */
    linked_results: refListFieldOf("HypothesisRegistration.linked_results"),
  })
  .superRefine((candidate, ctx) => {
    /*
     * A CONFIRMATORY DECLARATION AGAINST AN EXPOSED SET IS REFUSED, NOT DOWNGRADED (§2.7.1).
     *
     * "Any overlap disqualifies a confirmatory claim", and there is no threshold below which
     * reuse becomes fresh. A registration declaring `CONFIRMATORY` while its ledger records a
     * measured overlap must carry the refusal, so the screen cannot present it as untouched.
     */
    /*
     * ONLY EXPOSURE THAT PRECEDES THE DECLARATION DISQUALIFIES IT.
     *
     * The ledger is append-only and spans registrations, so a registration that legitimately
     * declared `CONFIRMATORY` over an untouched holdout accumulates later entries — its own
     * run's, and every subsequent one's. Refusing it for those would refuse a correct
     * declaration in retrospect, and the rule is about what was ALREADY exposed when the class
     * was declared and checked (§2.7.1: "checked against the ledger before the run starts").
     */
    const prior = candidate.exposure_ledger.entries.filter(
      (entry) => entry.at < candidate.registered_at,
    );
    const overlapping = prior.some(
      (entry) =>
        typeof entry.measured_overlap.value === "string" &&
        /[1-9]/.test(entry.measured_overlap.value),
    );
    const unmeasurable = prior.some(
      (entry) => entry.measured_overlap.value === undefined,
    );
    const confirmatory = candidate.declared_evaluation_class === "CONFIRMATORY";
    if (confirmatory && (overlapping || unmeasurable) && candidate.exposure_ledger.refusal === undefined) {
      ctx.addIssue({
        code: "custom",
        message:
          "a confirmatory declaration over an exposed or unmeasurable ledger carries its refusal",
      });
    }
    /*
     * AN INCOMPLETE LEDGER CANNOT SUPPORT A FRESH OUT-OF-SAMPLE CLAIM.
     *
     * "An absence of recorded exposure is not evidence of absent exposure", so a ledger that
     * cannot be shown complete fails closed rather than reading as a clean set.
     */
    if (
      confirmatory &&
      candidate.exposure_ledger.completeness !== "COMPLETE" &&
      candidate.exposure_ledger.refusal === undefined
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a ledger that cannot be shown complete refuses a confirmatory declaration",
      });
    }
    /*
     * THE LEDGER COUNT IS THE LEDGER'S, and never the page's.
     *
     * `entries` may be a page of the ledger; `entry_count` is how many exist. They may differ,
     * and the count may never be SMALLER than what is carried.
     */
    const count = candidate.exposure_ledger.entry_count.value;
    if (typeof count === "number" && count < candidate.exposure_ledger.entries.length) {
      ctx.addIssue({
        code: "custom",
        message: "the exposure ledger states a count at least as large as the entries carried",
      });
    }
    /*
     * THE BUDGET ARITHMETIC IS THE RECORD'S, and it must at least be self-consistent.
     *
     * A granted budget with a consumption and a remainder that do not add up is a budget
     * nobody can read, and the screen would render three numbers that contradict each other.
     */
    const granted = candidate.trial_budget.granted.value;
    const consumed = candidate.trial_budget.consumed.value;
    const remaining = candidate.trial_budget.remaining.value;
    if (
      typeof granted === "number" &&
      typeof consumed === "number" &&
      typeof remaining === "number" &&
      granted - consumed !== remaining
    ) {
      ctx.addIssue({
        code: "custom",
        message: "the trial budget's granted, consumed and remaining counts agree",
      });
    }
    /*
     * THE LINEAGE CONSUMPTION IS AT LEAST THIS IDENTITY'S OWN COUNT.
     *
     * The budget is read across the lineage, so it can never be smaller than the trials this
     * registration ran by itself — which is what a reset would look like from outside.
     */
    const own = candidate.own_trial_count.value;
    if (typeof own === "number" && typeof consumed === "number" && own > consumed) {
      ctx.addIssue({
        code: "custom",
        message:
          "the lineage trial consumption includes this registration's own trials, so it is " +
          "never smaller than them",
      });
    }
  });
export type HypothesisRegistration = z.infer<typeof hypothesisRegistration>;

export const hypothesisRegistrationPayload = collectionPayload(hypothesisRegistration, {
  evaluation_classes: z.array(evaluationClass),
});
export type HypothesisRegistrationPayload = z.infer<typeof hypothesisRegistrationPayload>;

export const HYPOTHESIS_REGISTRATION_SCHEMA = "cockpit.hypothesis_registration.v1";
export const hypothesisRegistrationEnvelope = envelope(
  hypothesisRegistrationPayload,
  HYPOTHESIS_REGISTRATION_SCHEMA,
);

/* ================================================== Area 15 — Champion / Challenger */

export const championChallengerComparison = z
  .object({
    champion_version: safeId,
    challenger_version: safeId,
    /** §4.5 kind `registration`. */
    registration_ref: refOf("ChampionChallengerComparison.registration_ref"),
    overlap: z.array(z.object({ measure: reasonCoded, value: metricValue })),
    divergence: z.array(z.object({ measure: reasonCoded, value: metricValue })),
    exposure_difference: z.array(z.object({ axis: reasonCoded, value: metricValue })),
    evidence_completeness: evidenceCompleteness,
    /** **DISPLAYED, never conferred.** The screen shows readiness; it grants none. */
    readiness: reasonCoded,
    /** The §2.7 disclosures every cited result rests on. */
    data_exposure_disclosure: z.array(reasonCoded),
    /**
     * ADDITIVE: the population the two versions were compared over, and its bounds.
     *
     * **Two versions are comparable only over an explicitly comparable population and
     * window** (Area 15). A comparison with no stated population is a comparison of two
     * different questions.
     */
    comparable_population: reasonCoded,
    window: analysisWindow,
    /** ADDITIVE: carried with every result, and never derived from a state (§2.7.1). */
    evaluation_class: evaluationClass,
    /**
     * ADDITIVE: **hypothetical** shadow economics, with their assumptions stated.
     *
     * Kept in their own field, under their own metric identifier, so they are never placed in
     * a series with a realized result (§2.8).
     */
    shadow_economics: z.array(z.object({ measure: reasonCoded, value: metricValue })),
    shadow_assumptions: z.array(reasonCoded),
    /**
     * ADDITIVE: the realized outcomes of the Challenger.
     *
     * There are none, and there can be none: a Challenger produces no order in any
     * environment. It is a state rather than an empty list, so the absence says why.
     */
    realized_outcomes: z.object({
      availability: availabilityState,
      reason: fieldReasonCode,
    }),
    /** ADDITIVE: the runs this comparison rests on. Kind `research_run`. */
    evidence_refs: refListFieldOf("ChampionChallengerComparison.evidence_refs"),
    /** ADDITIVE: the shadow evidence, kept separate from the backtest evidence. */
    shadow_refs: refListFieldOf("ChampionChallengerComparison.shadow_refs"),
  })
  .superRefine((candidate, ctx) => {
    if (candidate.champion_version === candidate.challenger_version) {
      ctx.addIssue({
        code: "custom",
        message: "a comparison names two different versions",
      });
    }
    /*
     * AN EXPLORATORY RESULT CARRIES ITS DISCLOSURE (§2.7.1).
     *
     * "Every downstream comparison, packet and report carries the disclosure", so a reused
     * evaluation with an empty disclosure list would be presented as fresh out-of-sample
     * evidence by omission.
     */
    if (
      candidate.evaluation_class === "EXPLORATORY_REUSE" &&
      candidate.data_exposure_disclosure.length === 0
    ) {
      ctx.addIssue({
        code: "custom",
        message: "exploratory reuse is disclosed on every comparison that rests on it",
      });
    }
    /*
     * A CHALLENGER HAS NO REALIZED OUTCOMES, EVER (§2.8, §3.3).
     *
     * "Shadow produces no order, in any environment." A value-bearing realized-outcome state
     * would claim the Challenger traded, which is the one claim this screen must never make.
     */
    if (
      ["AVAILABLE", "STALE", "PARTIAL", "EMPTY_VERIFIED"].includes(
        candidate.realized_outcomes.availability,
      )
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a Challenger produces no order in any environment, so it has no realized outcome",
      });
    }
  });
export type ChampionChallengerComparison = z.infer<typeof championChallengerComparison>;

export const championChallengerPayload = collectionPayload(championChallengerComparison);
export type ChampionChallengerPayload = z.infer<typeof championChallengerPayload>;

export const CHAMPION_CHALLENGER_SCHEMA = "cockpit.champion_challenger.v1";
export const championChallengerEnvelope = envelope(
  championChallengerPayload,
  CHAMPION_CHALLENGER_SCHEMA,
);

/* ============================================================ Area 21 — AI contribution */

export const aiContribution = z
  .object({
    /** §4.5 kind `registration` — experiment E of ADR-0026 §23, which **has not been run**. */
    experiment_ref: refOf("AiContribution.experiment_ref"),
    arms: z.array(
      z.object({
        arm: reasonCoded,
        population: metricOf("ai.arm_population"),
        outcome: metricValue,
        /** The half-width of the stated interval. A difference with no uncertainty is a claim. */
        uncertainty: metricValue,
      }),
    ),
    matched: z.boolean(),
    ai_provenance: z.object({
      model_version: safeId,
      prompt_version: safeId,
      /** §4.3.1 kind `source_fact`. */
      source_refs: refListFieldOf("AiContribution.ai_provenance.source_refs"),
    }),
    outages: z.array(
      z.object({ from: instant, to: instant, handling: reasonCoded }),
    ),
    minimum_observations_met: z.boolean(),
    /** ADDITIVE: the experiment this comparison belongs to, named on the row. */
    experiment: reasonCoded,
    /** ADDITIVE: the declared minimum, so `INSUFFICIENT_OBSERVATIONS` shows both numbers. */
    minimum_observations: metricOf("performance.minimum_observations"),
    /** ADDITIVE: what the arms were matched ON. An unmatched comparison says so. */
    matching_basis: reasonCoded,
    /** ADDITIVE: the assumptions the comparison rests on, as closed codes. */
    assumptions: z.array(reasonCoded),
    /**
     * ADDITIVE: the causal claim this view deliberately does not make.
     *
     * **A descriptive difference between two arms is not attribution.** Experiment E has not
     * been run, no AI agent exists, and the field states that rather than leaving a blank a
     * reader would fill in — the same shape the family roll-up uses for G7.
     */
    causal_attribution: z.object({
      availability: availabilityState,
      reason: fieldReasonCode,
      gate: reasonCoded,
    }),
    /** ADDITIVE: how much of the window the arms actually cover, given the outages. */
    coverage_note: reasonCoded,
  })
  .superRefine((candidate, ctx) => {
    /*
     * A SMALL POPULATION RENDERS `INSUFFICIENT_OBSERVATIONS` AND NO DIFFERENCE (Area 21, U4).
     *
     * "Where the matched population is too small, the view reports INSUFFICIENT_OBSERVATIONS
     * instead of a difference", so an arm carrying an outcome value while the minimum is
     * unmet is the ratio the rule refuses, wearing an arm's shape.
     */
    if (!candidate.minimum_observations_met) {
      for (const arm of candidate.arms) {
        if (arm.outcome.value !== undefined) {
          ctx.addIssue({
            code: "custom",
            message:
              "an unmet minimum renders INSUFFICIENT_OBSERVATIONS rather than an arm outcome",
          });
          return;
        }
      }
    }
    /*
     * AN UNMATCHED COMPARISON CARRIES NO OUTCOME DIFFERENCE EITHER.
     *
     * Area 21 asks for "matched comparisons and stated uncertainty". Two arms drawn from
     * different populations produce a difference that measures the populations.
     */
    if (!candidate.matched) {
      for (const arm of candidate.arms) {
        if (arm.outcome.value !== undefined) {
          ctx.addIssue({
            code: "custom",
            message: "an unmatched arm set carries no outcome, because the difference is not one",
          });
          return;
        }
      }
    }
    /*
     * EVERY OUTCOME CARRIES ITS UNCERTAINTY, IN THE SAME UNIT.
     *
     * A point estimate with no interval is a claim, and an interval in another unit cannot be
     * read against the estimate it qualifies.
     */
    for (const arm of candidate.arms) {
      if (arm.outcome.value !== undefined && arm.uncertainty.value === undefined) {
        ctx.addIssue({
          code: "custom",
          message: "an arm outcome is carried with its stated uncertainty",
        });
        return;
      }
    }
    for (const outage of candidate.outages) {
      if (outage.to <= outage.from) {
        ctx.addIssue({
          code: "custom",
          message: "an outage ends after it begins",
        });
        return;
      }
    }
  });
export type AiContribution = z.infer<typeof aiContribution>;

export const aiContributionPayload = collectionPayload(aiContribution);
export type AiContributionPayload = z.infer<typeof aiContributionPayload>;

export const AI_CONTRIBUTION_SCHEMA = "cockpit.ai_contribution.v1";
export const aiContributionEnvelope = envelope(
  aiContributionPayload,
  AI_CONTRIBUTION_SCHEMA,
);

/* ============================================================== Area 16 — the loop */

/**
 * `FeedbackPipeline` — the ten-stage loop, **read and never driven.**
 *
 * **No stage advances from this screen**, each stage shows the authorization it awaits, and
 * **the tenth is a person**. Navigation may follow an item; it may never move one.
 */
export const feedbackStage = z.object({
  stage: reasonCoded,
  item_count: metricOf("feedback.stage_items"),
  blocked_count: metricOf("feedback.stage_blocked"),
  awaiting_authorizations: z.array(reasonCoded),
  /**
   * §4.3.1 kind `queue_item` — the loop items reachable at this stage.
   *
   * The catalogue assigns ONE kind to this field, so it enumerates the QUEUE-ITEM identity
   * every downstream item still carries. Stages upstream of the queue have none, and report
   * a verified-empty list rather than borrowing another kind to look populated.
   */
  item_refs: refListFieldOf("FeedbackPipeline.stages[].item_refs"),
  /** ADDITIVE: Area 16 presents each stage's inputs, outputs, owner, pins and refusals. */
  owner: reasonCoded,
  inputs: z.array(reasonCoded),
  outputs: z.array(reasonCoded),
  refusal_reasons: z.array(reasonCoded),
  pins: z.array(reasonCoded),
  /** ADDITIVE: what `item_refs` enumerates, so an empty list is not read as an empty stage. */
  item_reference_scope: reasonCoded,
  /** ADDITIVE: whether this stage may ever run without a human. The tenth may not. */
  automatable: z.boolean(),
});
export type FeedbackStage = z.infer<typeof feedbackStage>;

export const feedbackPipelinePayload = z
  .object({
    stages: z.array(feedbackStage).length(10),
    /** The tenth, and it is a person. */
    human_only_stage: reasonCoded,
    /** ADDITIVE: the environment the snapshot describes. §5.1 declares that filter. */
    environment,
    /** ADDITIVE: the pins the whole loop is read under. */
    pins: versionPins,
  })
  .superRefine((candidate, ctx) => {
    /*
     * EXACTLY ONE STAGE IS THE HUMAN-ONLY ONE, AND IT IS THE TENTH.
     *
     * "Ten stages, and the tenth is a person. Everything before it may eventually run without
     * a human in the loop, within separately approved bounds. The tenth may not, ever."
     */
    const humanOnly = candidate.stages.filter((stage) => !stage.automatable);
    if (humanOnly.length !== 1) {
      ctx.addIssue({
        code: "custom",
        message: "exactly one stage of the loop is the human-only stage",
      });
      return;
    }
    const last = candidate.stages[candidate.stages.length - 1];
    if (last.automatable || last.stage.code !== candidate.human_only_stage.code) {
      ctx.addIssue({
        code: "custom",
        message: "the human-only stage is the tenth, and it is the one the payload names",
      });
    }
    for (const stage of candidate.stages) {
      const items = stage.item_count.value;
      const blocked = stage.blocked_count.value;
      if (typeof items === "number" && typeof blocked === "number" && blocked > items) {
        ctx.addIssue({
          code: "custom",
          message: "a stage never blocks more items than it holds",
        });
        return;
      }
    }
  });
export type FeedbackPipelinePayload = z.infer<typeof feedbackPipelinePayload>;

export const FEEDBACK_PIPELINE_SCHEMA = "cockpit.feedback_pipeline.v1";
export const feedbackPipelineEnvelope = envelope(
  feedbackPipelinePayload,
  FEEDBACK_PIPELINE_SCHEMA,
);
