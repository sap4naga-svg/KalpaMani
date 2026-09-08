/**
 * The bounded answer builders — Area 31.
 *
 * **NOTHING HERE COMPUTES A FIGURE A SCREEN ALREADY REPORTS.** Every measured value an answer
 * carries is lifted, unchanged, from the payload the owning read model produced: its
 * availability, its reason, its unit, its `as_of` and its metric definition travel with it.
 * A second arithmetic over the same fixtures would be a second opinion, and two opinions can
 * disagree — which is exactly how an assistant ends up contradicting the page it summarizes.
 *
 * The four quantities the assistant IS the producer of are counts over populations it was
 * handed — how many attention items, how many verified changes, how many degraded subjects,
 * how many open alerts — plus the closed state token two records already carry. Each is
 * registered in the metric dictionary, and each counts a population the payload delivered.
 *
 * **An answer is never more certain than its evidence.** A measurement that is not
 * value-bearing produces an ABSTENTION carrying that measurement's own state and reason, and
 * never a substituted zero (ADR-0029 §2.1). A measured zero, by contrast, is an ANSWER.
 *
 * **A recorded reason is not an inferred cause.** `notes` reproduces the codes the record
 * carries — an exit reason, a blocking reason, a safety action, an alignment finding — and
 * there is no field anywhere in this module through which a cause could be written.
 */
import {
  ASK_MAX_SCANNED_ROWS,
  ASK_QUESTION_VOCABULARY,
  ASK_SUBJECT_VOCABULARY,
  type AskAnswerPayload,
  type AskQuestionClass,
  type AskSubjectKind,
} from "@/contracts/ask-models";
import { refListOf } from "@/contracts/factories";
import { isValueBearing } from "@/contracts/validity";
import type { MetricValue, Ref, ReasonCoded } from "@/contracts/values";
import type { OwningArea } from "@/contracts/vocabularies";
import type {
  TradeDetailPayload,
  TradeLifecyclePayload,
  PerformanceSummaryPayload,
} from "@/contracts/portfolio-models";
import type { CandidateDetailPayload } from "@/contracts/signal-models";
import type { StrategyHealthPayload } from "@/contracts/strategy-models";
import type { HypothesisRegistrationPayload } from "@/contracts/research-models";
import { SEVERITY_RANK } from "@/contracts/operations-models";
import type {
  AlertPayload,
  AlertSeverity,
  DataQualityPayload,
} from "@/contracts/operations-models";
import type { ReconciliationPayload } from "@/contracts/execution-quality-page";
import type { AttentionListPayload, WhatChangedPayload } from "@/data/client/read-client";
import { PERIOD_LABEL, type PerformancePeriod } from "@/lib/scope";

import { count, demoRef, demoReason, token, unavailable } from "./common";

/** A citation, and the record it names. `AUTHORIZED_READ` is `source_fact`'s resolution (§4.3). */
function citation(recordId: string, owningArea?: OwningArea): Ref {
  return demoRef(recordId, "source_fact", "AUTHORIZED_READ", owningArea);
}

/** Only `source_fact` references may be citations, so a mixed list is filtered, never coerced. */
function sourceFacts(items: readonly Ref[]): readonly Ref[] {
  return items.filter((reference) => reference.ref_kind === "source_fact");
}

/** De-duplicated by identity, in first-seen order, and capped so a citation list stays readable. */
function distinct(items: readonly Ref[], limit: number): Ref[] {
  const seen = new Set<string>();
  const kept: Ref[] = [];
  for (const reference of items) {
    if (seen.has(reference.ref_id)) continue;
    seen.add(reference.ref_id);
    kept.push(reference);
    if (kept.length >= limit) break;
  }
  return kept;
}

interface AnswerSpec {
  readonly questionClass: AskQuestionClass;
  readonly answer: MetricValue;
  readonly answerLabel: string;
  readonly supporting: readonly { readonly label: string; readonly value: MetricValue }[];
  readonly notes: readonly ReasonCoded[];
  /** The records the figure came from. NEVER empty — `assemble` refuses an empty list. */
  readonly citations: readonly Ref[];
  readonly subjectKind?: AskSubjectKind;
  readonly subjectId?: string;
  readonly subjectRef?: Ref;
  readonly window?: PerformancePeriod;
  /** Rows actually examined, against the endpoint's declared maximum. */
  readonly scannedRows: number;
}

/**
 * Assemble one answer.
 *
 * The abstention is DERIVED from the answer measurement's own availability rather than
 * declared beside it. A producer that could set `abstained` independently could report an
 * abstention over a value, or a value over an absence, and the payload's own refinement would
 * then be checking a claim against itself.
 */
export function assemble(spec: AnswerSpec, asOf: string): AskAnswerPayload {
  if (spec.citations.length === 0) {
    /*
     * "AN ANSWER WITH NO CITATION IS NOT RETURNED" (§4.5).
     *
     * This is a construction error rather than a state: every class here consults at least one
     * record, so a builder that produced no citation has failed to name what it read. Refusing
     * is the only safe outcome — the alternative is a manufactured reference, which is the
     * exact fabrication the ONE_OR_MORE relation exists to prevent.
     */
    throw new RangeError(`${spec.questionClass} produced an answer citing no record`);
  }
  if (spec.scannedRows > ASK_MAX_SCANNED_ROWS) {
    /* §5.2 "refusal, not truncation": beyond the declared extent, nothing is served. */
    throw new RangeError(`${spec.questionClass} scanned beyond its declared maximum extent`);
  }
  const measured = isValueBearing(spec.answer.availability);
  const abstentionCode =
    spec.answer.availability === "INSUFFICIENT_OBSERVATIONS"
      ? "MEASUREMENT_BELOW_MINIMUM_OBSERVATIONS"
      : "MEASUREMENT_UNAVAILABLE";
  return {
    question_class: {
      code: spec.questionClass,
      vocabulary: ASK_QUESTION_VOCABULARY,
      vocabulary_version: "1",
    },
    answer: spec.answer,
    answer_label: demoReason(spec.answerLabel),
    supporting: spec.supporting.map((figure) => ({
      label: demoReason(figure.label),
      value: figure.value,
    })),
    notes: [...spec.notes],
    interpretation: {
      ...(spec.subjectKind !== undefined
        ? {
            subject_kind: {
              code: spec.subjectKind,
              vocabulary: ASK_SUBJECT_VOCABULARY,
              vocabulary_version: "1",
            },
          }
        : {}),
      ...(spec.subjectId !== undefined ? { subject_id: spec.subjectId } : {}),
      ...(spec.window !== undefined ? { window: demoReason(`WINDOW_${spec.window}`) } : {}),
    },
    ...(spec.subjectRef !== undefined ? { subject_ref: spec.subjectRef } : {}),
    citations: refListOf(distinct(spec.citations, 6), "ONE_OR_MORE", asOf),
    abstained: !measured,
    ...(measured
      ? {}
      : {
          abstention_reason: token("ask.abstention_reason", abstentionCode, asOf),
        }),
    scanned_extent: count("ask.scanned_rows", spec.scannedRows, asOf),
    scanned_extent_maximum: count("ask.scanned_maximum", ASK_MAX_SCANNED_ROWS, asOf),
  };
}

/** The whole population count, where the summary reports one, and zero where it cannot. */
function observationRows(value: MetricValue): number {
  return typeof value.value === "number" ? value.value : 0;
}

/* ============================================================== portfolio performance */

export function portfolioReturnAnswer(
  summary: PerformanceSummaryPayload,
  window: PerformancePeriod,
  asOf: string,
): AskAnswerPayload {
  return assemble(
    {
      questionClass: "PORTFOLIO_RETURN",
      answer: summary.total_return,
      answerLabel: "PORTFOLIO_TIME_WEIGHTED_RETURN",
      supporting: [
        { label: "MAXIMUM_DRAWDOWN", value: summary.max_drawdown },
        { label: "WIN_RATE", value: summary.win_rate },
        { label: "OBSERVATION_COUNT", value: summary.observation_count },
      ],
      /* The population every ratio above was computed over, and the cost treatment. */
      notes: [summary.trade_population, demoReason(summary.cost_treatment)],
      citations: [citation(`performance-summary-${window.toLowerCase()}`)],
      window,
      scannedRows: observationRows(summary.observation_count),
    },
    asOf,
  );
}

export function portfolioDrawdownAnswer(
  summary: PerformanceSummaryPayload,
  window: PerformancePeriod,
  asOf: string,
): AskAnswerPayload {
  return assemble(
    {
      questionClass: "PORTFOLIO_DRAWDOWN",
      answer: summary.max_drawdown,
      answerLabel: "PORTFOLIO_MAXIMUM_DRAWDOWN",
      supporting: [
        { label: "TIME_WEIGHTED_RETURN", value: summary.total_return },
        { label: "OBSERVATION_COUNT", value: summary.observation_count },
      ],
      notes: [summary.trade_population],
      citations: [citation(`performance-summary-${window.toLowerCase()}`)],
      window,
      scannedRows: observationRows(summary.observation_count),
    },
    asOf,
  );
}

/* ==================================================================== strategy health */

export function strategyHealthAnswer(
  health: StrategyHealthPayload,
  versionId: string,
  asOf: string,
): AskAnswerPayload | null {
  const record = health.items.find((item) => item.strategy_version === versionId);
  if (record === undefined) {
    return null;
  }
  const transitionEvidence = record.transitions.flatMap((transition) =>
    sourceFacts(transition.input_refs.items),
  );
  return assemble(
    {
      questionClass: "STRATEGY_HEALTH",
      answer: token("strategy.health_state", record.state, asOf),
      answerLabel: "STRATEGY_HEALTH_STATE",
      supporting: [
        { label: "OBSERVATION_COUNT", value: record.observation_count },
        { label: "MINIMUM_OBSERVATIONS", value: record.minimum_observations },
      ],
      /*
       * THE RECORD'S OWN CODES, AND NOT A READING OF THEM.
       *
       * `recovery_authority` is displayed unchanged and is neither strengthened nor widened
       * here: reduction and disablement are automatic and RESTORATION IS NOT, which is the
       * record's statement rather than this module's.
       */
      notes: [
        record.strategy_module,
        record.safety_action,
        record.human_action_required,
        record.recovery_authority,
      ],
      citations: [
        citation(`strategy-health-${versionId}`, "STRATEGY_HEALTH"),
        ...transitionEvidence,
      ],
      subjectKind: "STRATEGY_VERSION",
      subjectId: versionId,
      subjectRef: demoRef(versionId, "strategy_version", "ENDPOINT"),
      scannedRows: health.items.length,
    },
    asOf,
  );
}

/* ===================================================================== trade outcome */

export function tradeOutcomeAnswer(
  detail: TradeDetailPayload,
  lifecycle: TradeLifecyclePayload | undefined,
  asOf: string,
): AskAnswerPayload {
  const trade = detail.summary;
  const lifecycleEvidence = sourceFacts(
    (lifecycle?.events ?? []).map((event) => event.source_ref),
  );
  return assemble(
    {
      questionClass: "TRADE_OUTCOME",
      answer: trade.r_multiple,
      answerLabel: "TRADE_R_MULTIPLE",
      supporting: [
        { label: "REALIZED_PNL", value: trade.realized_pnl },
        { label: "RETURN_PCT", value: trade.return_pct },
        { label: "RECORDED_EXIT_REASON", value: trade.exit_reason },
        { label: "HOLDING_PERIOD", value: trade.holding_period },
      ],
      /*
       * BUSINESS STATUS AND DATA COMPLETENESS ARE TWO SEPARATE FACTS, and both are the
       * record's own. The exit reason above is the RECORDED one; nothing here infers why a
       * trade lost, and no field exists in which such an inference could be written.
       */
      notes: [
        demoReason(trade.trade_status),
        demoReason(trade.data_completeness),
        trade.entry_reason,
        trade.stop_outcome,
      ],
      citations: [citation(`trade-${trade.trade_id}-record`), ...lifecycleEvidence],
      subjectKind: "TRADE",
      subjectId: trade.trade_id,
      subjectRef: demoRef(trade.trade_id, "trade", "ENDPOINT"),
      scannedRows: (lifecycle?.events.length ?? 0) + 1,
    },
    asOf,
  );
}

/* ============================================================== candidate progression */

export function candidateProgressionAnswer(
  detail: CandidateDetailPayload,
  asOf: string,
): AskAnswerPayload {
  /*
   * THE FACTOR PINS ARE THE RECORDED FACTS THE DECISION WAS BUILT FROM.
   *
   * Each `deterministic_evidence` entry carries the pin of the factor definition that
   * produced its score, so citing the pins names actual recorded identities rather than a
   * reference invented to fill a required list.
   */
  const pins = detail.deterministic_evidence.map((entry) => citation(entry.pin));
  return assemble(
    {
      questionClass: "CANDIDATE_PROGRESSION",
      answer: token("candidate.brain_state", detail.brain_state, asOf),
      answerLabel: "CANDIDATE_BRAIN_DECISION_STATE",
      supporting: [
        { label: "RANK", value: detail.rank },
        { label: "RANK_POPULATION", value: detail.rank_population },
        { label: "SETUP_QUALITY", value: detail.setup_quality },
      ],
      notes: [
        detail.strategy_module,
        detail.conviction_band,
        detail.regime_context,
        ...detail.blocking_reasons,
        ...detail.contradictions,
      ],
      citations: [citation(`candidate-${detail.candidate_id}-decision`), ...pins],
      subjectKind: "CANDIDATE",
      subjectId: detail.candidate_id,
      subjectRef: demoRef(detail.candidate_id, "candidate", "ENDPOINT"),
      scannedRows: detail.deterministic_evidence.length + detail.ai_evidence.length + 1,
    },
    asOf,
  );
}

/* ================================================================== attention summary */

export function attentionSummaryAnswer(
  attention: AttentionListPayload,
  asOf: string,
): AskAnswerPayload {
  /* Materiality rank 1 is the most material, so the head of the ranked list is the top item. */
  const ranked = [...attention.items].sort(
    (left, right) => left.materiality_rank - right.materiality_rank,
  );
  const top = ranked[0];
  const evidence = ranked.flatMap((item) => sourceFacts(item.evidence_refs.items));
  return assemble(
    {
      questionClass: "ATTENTION_SUMMARY",
      /* A measured zero is an ANSWER, not an absence (ADR-0029 §2.1). */
      answer: count("attention.item_count", attention.items.length, asOf),
      answerLabel: "OPEN_ATTENTION_ITEMS",
      supporting:
        top === undefined
          ? []
          : [
              { label: "HIGHEST_RANKED_IMPACT", value: top.impact },
              { label: "HIGHEST_RANKED_OCCURRENCES", value: top.occurrence_count },
            ],
      notes:
        top === undefined
          ? []
          : [top.severity, top.what_happened, top.why_it_matters, top.recommended_action],
      citations: [citation("attention-list"), ...evidence],
      scannedRows: attention.items.length,
    },
    asOf,
  );
}

/* =================================================================== recorded changes */

export function recordedChangesAnswer(
  changes: WhatChangedPayload,
  asOf: string,
): AskAnswerPayload {
  const evidence = changes.entries.flatMap((entry) => sourceFacts(entry.evidence_refs.items));
  /*
   * NO BASELINE IS NOT ZERO CHANGES.
   *
   * A comparison needs two endpoints. Where the baseline endpoint is missing or degraded, the
   * count is not measured, and the answer carries that endpoint's OWN state and reason rather
   * than a zero standing in for a comparison nobody made.
   */
  const answer =
    changes.baseline_state === undefined
      ? count("change.entry_count", changes.entries.length, asOf)
      : unavailable(
          "change.entry_count",
          "COUNT",
          changes.baseline_state.availability as Parameters<typeof unavailable>[2],
          changes.baseline_state.reason,
        );
  const first = changes.entries[0];
  return assemble(
    {
      questionClass: "RECORDED_CHANGES",
      answer,
      answerLabel: "VERIFIED_CHANGES_SINCE_BASELINE",
      supporting: first === undefined ? [] : [{ label: "FIRST_CHANGE_AFTER", value: first.after }],
      notes: first === undefined ? [] : [first.subject, first.change_kind, first.materiality],
      citations: [citation("what-changed"), ...evidence],
      scannedRows: changes.entries.length,
    },
    asOf,
  );
}

/* ============================================================ data quality conditions */

/**
 * The two states a data-quality subject can be in that are NOT the same fact, and must not
 * be counted as one.
 *
 * A RECORDED DEGRADATION is a subject whose state WAS assessed and came back qualified --
 * `STALE` marks, `PARTIAL` coverage. An UNASSESSED subject is one whose state carries no
 * value at all, because its producer is absent, unauthorized or has not yet run.
 *
 * Counting the second as the first is the exact confusion the section 4.6 unavailable
 * template exists to stop: "EMPTY_VERIFIED and NOT_YET_AVAILABLE look identical on a naive
 * screen and mean opposite things". It would report a subject nobody measured as a subject
 * measured badly, and -- worse -- would EXCLUDE the stale and partial subjects a reader
 * asking about data quality is actually asking about, because those states ARE value-bearing
 * (section 4.1.1).
 */
const DEGRADED_SUBJECT_STATES = ["STALE", "PARTIAL"] as const;

function subjectIsDegraded(item: {
  readonly subject_state: { readonly availability: string };
}): boolean {
  return (DEGRADED_SUBJECT_STATES as readonly string[]).includes(
    item.subject_state.availability,
  );
}

export function dataQualityAnswer(
  quality: DataQualityPayload,
  asOf: string,
): AskAnswerPayload {
  const degraded = quality.items.filter(subjectIsDegraded);
  /*
   * A SUBJECT NOBODY ASSESSED IS ITS OWN COUNT, reported beside the degradation count rather
   * than folded into it. Both are facts a reader needs, and they are different ones.
   */
  const unassessed = quality.items.filter(
    (item) => !isValueBearing(item.subject_state.availability),
  );
  /*
   * THE FOCUS IS A DEGRADED SUBJECT OR THERE IS NONE.
   *
   * There is no fallback to the first indexed row: describing an arbitrary subject's coverage
   * as "the affected one" when nothing is degraded states an affectedness the record does not
   * carry, and a measured zero needs no example to stand beside it.
   */
  const focus = degraded[0];
  const lineage = focus === undefined ? [] : sourceFacts(focus.lineage_refs.items);
  const unassessedFigure = {
    label: "SUBJECTS_WITHOUT_A_RECORDED_STATE",
    value: count("data_quality.unassessed_subjects", unassessed.length, asOf),
  };
  return assemble(
    {
      questionClass: "DATA_QUALITY_CONDITION",
      answer: count("data_quality.degraded_subjects", degraded.length, asOf),
      answerLabel: "DEGRADED_DATA_QUALITY_SUBJECTS",
      supporting:
        focus === undefined
          ? [unassessedFigure]
          : [
              unassessedFigure,
              { label: "COVERAGE_RATIO", value: focus.coverage.ratio },
              { label: "HISTORY_DEPTH", value: focus.history_depth },
            ],
      /*
       * THE PROFILE IS DECLARED, NEVER INFERRED, and the origin is carried beside it —
       * provider-derived information never renders as `PUBLIC_PIT`, and reproducing both
       * codes is what lets a reader check that rather than take it on trust.
       */
      notes:
        focus === undefined
          ? []
          : [
              focus.subject,
              demoReason(focus.information_profile),
              focus.profile_basis,
              focus.information_origin,
            ],
      citations: [citation("data-quality", "DATA_QUALITY"), ...lineage],
      scannedRows: quality.items.length,
    },
    asOf,
  );
}

/* ============================================================== reconciliation result */

export function reconciliationAnswer(
  reconciliation: ReconciliationPayload,
  asOf: string,
): AskAnswerPayload | null {
  const latest =
    reconciliation.items.find((run) => run.run_id === reconciliation.latest_run_id) ??
    reconciliation.items[0];
  if (latest === undefined) {
    return null;
  }
  return assemble(
    {
      questionClass: "RECONCILIATION_RESULT",
      answer: token("reconciliation.result", latest.result.code, asOf),
      answerLabel: "LATEST_RECONCILIATION_RESULT",
      /*
       * A PAST RECONCILIATION IS NOT PRESENT HEALTH, so the run's own age travels with its
       * result. Nothing here reads the result as a current state.
       */
      supporting: [
        { label: "RUN_AGE", value: latest.age },
        { label: "ORPHANS", value: latest.orphans },
      ],
      notes: [
        latest.comparison_scope,
        latest.as_of_alignment,
        latest.session_state,
        reconciliation.current_health.note,
        ...latest.missing_inputs,
      ],
      citations: [
        citation("reconciliation-status", "RECONCILIATION"),
        citation(latest.run_id, "RECONCILIATION"),
      ],
      scannedRows: reconciliation.items.length,
    },
    asOf,
  );
}

/* ========================================================================= open alerts */

export function openAlertsAnswer(alerts: AlertPayload, asOf: string): AskAnswerPayload {
  const open = alerts.items.filter((alert) => alert.state === "OPEN");
  /*
   * "HIGHEST SEVERITY" IS ESTABLISHED BY THE DECLARED RANK, NOT BY DELIVERY ORDER.
   *
   * `SEVERITY_RANK` is the contract's own mapping, and the alerts screen already re-ranks by
   * it rather than trusting the order a page arrives in. Reading `open[0]` would make the
   * label true only for as long as the fixture happened to deliver the most severe row first,
   * which is a claim resting on an accident rather than on a record.
   *
   * A severity the mapping does not know sorts LAST rather than first, so an unrecognised one
   * can never be promoted into the highest-severity slot; the tiebreak is the identifier, so
   * two equally severe rows resolve deterministically.
   */
  const ranked = [...open].sort((left, right) => {
    const l = SEVERITY_RANK[left.severity.code as AlertSeverity] ?? Number.MAX_SAFE_INTEGER;
    const r = SEVERITY_RANK[right.severity.code as AlertSeverity] ?? Number.MAX_SAFE_INTEGER;
    return l === r ? left.alert_id.localeCompare(right.alert_id) : l - r;
  });
  /*
   * NO FALLBACK TO A ROW THAT IS NOT OPEN.
   *
   * `open[0] ?? alerts.items[0]` reported a RESOLVED alert's severity and occurrence count
   * beside an open count of zero -- a qualifying figure for a row the answer is not about.
   * Where nothing is open, the measured zero stands alone.
   */
  const top = ranked[0];
  const evidence = top === undefined ? [] : sourceFacts(top.evidence_refs.items);
  return assemble(
    {
      questionClass: "OPEN_ALERTS",
      /* Deduplicated ROWS, and never raw occurrences: one condition is one alert. */
      answer: count("alert.open_count", open.length, asOf),
      answerLabel: "OPEN_ALERT_ROWS",
      supporting:
        top === undefined
          ? [{ label: "DEDUPLICATED_AWAY", value: alerts.folded_total }]
          : [
              { label: "DEDUPLICATED_AWAY", value: alerts.folded_total },
              { label: "HIGHEST_SEVERITY_OCCURRENCES", value: top.occurrence_count },
            ],
      notes:
        top === undefined
          ? [...alerts.absent_integrations]
          : [top.severity, top.condition, ...alerts.absent_integrations],
      citations: [citation("alert-list", "ALERTS"), ...evidence],
      scannedRows: alerts.items.length,
    },
    asOf,
  );
}

/* ==================================================================== research lineage */

export function researchLineageAnswer(
  hypotheses: HypothesisRegistrationPayload,
  registrationId: string,
  asOf: string,
): AskAnswerPayload | null {
  const record = hypotheses.items.find(
    (item) => item.registration_id === registrationId,
  );
  if (record === undefined) {
    return null;
  }
  return assemble(
    {
      questionClass: "RESEARCH_LINEAGE",
      /*
       * THE BUDGET IS READ ACROSS THE LINEAGE, not across this registration alone — a new
       * registration identity resets neither the exposure ledger nor the trial budget, and
       * the record already carries both figures separately.
       */
      answer: record.trial_budget.remaining,
      answerLabel: "TRIAL_BUDGET_REMAINING_ACROSS_LINEAGE",
      supporting: [
        { label: "TRIAL_BUDGET_GRANTED", value: record.trial_budget.granted },
        { label: "TRIAL_BUDGET_CONSUMED", value: record.trial_budget.consumed },
        { label: "TRIALS_OWN", value: record.own_trial_count },
      ],
      notes: [record.strategy_module, record.variation, record.thesis],
      citations: [
        citation(`registration-${registrationId}`),
        citation(record.pins.manifest),
        citation(record.pins.revision_view),
      ],
      subjectKind: "REGISTRATION",
      subjectId: registrationId,
      subjectRef: demoRef(registrationId, "registration", "ENDPOINT"),
      scannedRows: hypotheses.items.length,
    },
    asOf,
  );
}

/** The window label a view renders beside an interpreted period. */
export const ASK_WINDOW_LABEL = PERIOD_LABEL;
