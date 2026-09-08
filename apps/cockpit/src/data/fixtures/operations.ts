/**
 * The C8 data-quality, operations and alert projections — Areas 22, 23 and 27.
 *
 * ONE COHERENT OPERATIONAL NARRATIVE, built on identities the earlier cycles already
 * established rather than on new ones:
 *
 *   a data condition      the position mark is older than its freshness contract — the same
 *                         input the executive overview already degrades on
 *   a strategy affected   the exact version holding the trade whose risk assessment is STALE
 *   a job behind it       the mark-refresh job's last run FAILED, and its queue is backing up
 *   an incident           opened against the mark feed, still OPEN, with its own timeline
 *   an alert              the SAME condition identity the attention list deduplicates on, so
 *                         the executive and operator views reconcile instead of double-counting
 *   a reconciliation      the orphan finding Area 10 records, linked through its own incident
 *
 * **Nothing here is forced into that story.** The borrow-quality subject, the two research
 * jobs and the resolved scheduler alert are separate conditions and stay separate; no
 * unrelated fact is folded into the incident to make a link resolve.
 *
 * **NO PROVIDER, SCHEDULER, SERVICE OR NOTIFICATION EXISTS.** No feed is read, no job is run,
 * no alert is sent, and every figure is a repository-owned deterministic fixture.
 */
import { available, instantOf } from "@/contracts/factories";
import type {
  Alert,
  AlertPayload,
  DataQuality,
  DataQualityPayload,
  SystemIncident,
  SystemIncidentPayload,
  SystemJob,
  SystemJobPayload,
} from "@/contracts/operations-models";
import { ALERT_SEVERITIES } from "@/contracts/operations-models";
import { INFORMATION_PROFILES } from "@/contracts/vocabularies";
import type { Ref } from "@/contracts/values";

import { buildFreshness, type InputSpec } from "./envelopes";
import {
  CALENDAR,
  count,
  demoRef,
  demoReason,
  instantValue,
  notApplicable,
  refListOf,
  scaled,
  seconds,
  unavailable,
  usd,
} from "./common";
import { RECONCILIATION_MISMATCH_RUN } from "./quality";

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/* ================================================ the shared condition identities === */

/**
 * The condition identities the executive attention projection already deduplicates on.
 *
 * **They are reused rather than re-invented**, which is what makes the two views reconcile:
 * one condition, one alert record, and one attention item over the same identity.
 */
export const CONDITION_MARK_STALENESS = "demo-dedup-mark-staleness";
export const CONDITION_STRATEGY_HEALTH = "demo-dedup-strategy-health";
export const CONDITION_BORROW = "demo-dedup-borrow";
export const CONDITION_RECONCILIATION = "demo-dedup-reconciliation";
export const CONDITION_UNSOURCED = "demo-dedup-unsourced";
/** A sixth condition, resolved, so the resolved history is not an empty section. */
export const CONDITION_SCHEDULER_LAG = "demo-dedup-scheduler-lag";

export const MARK_FEED_INCIDENT = "demo-incident-0001";
export const RECONCILIATION_INCIDENT = "demo-incident-0002";
export const SCHEDULER_INCIDENT = "demo-incident-0003";

export const MARK_REFRESH_JOB = "demo-job-mark-refresh";

/** The data-quality subject the whole narrative turns on. */
export const MARK_DATA_SUBJECT = "us-equity-daily-marks";

/* ================================================ Area 22 — DataQuality projections === */

const PAGE_SIZE_DATA_QUALITY = 50;
const PAGE_SIZE_JOBS = 50;
const PAGE_SIZE_INCIDENTS = 25;
const PAGE_SIZE_ALERTS = 50;

/**
 * One subject's freshness report, built by the SAME builder the envelope uses.
 *
 * §3.1 is not re-implemented here: `buildFreshness` owns the three bands, the composite state
 * and the separation of source age from projection lag, and this passes it one required input
 * per subject so the composite has exactly one way to fail.
 */
function subjectFreshness(
  inputId: string,
  ageSeconds: number,
  contractSeconds: number,
  originMs: number,
  evaluationMs: number,
) {
  const spec: InputSpec = {
    id: inputId,
    required: true,
    ageAtOriginSeconds: ageSeconds,
    contractMaxAgeSeconds: contractSeconds,
  };
  return buildFreshness([spec], originMs, evaluationMs, originMs);
}

/** A whole number of calendar days. History depth is a duration, and it carries its unit. */
function calendarDays(metricId: string, value: number, asOf: string) {
  return available({ metricId, unit: "CALENDAR_DAYS", value, asOf });
}

function lineage(ids: readonly string[], asOf: string) {
  const refs: Ref[] = ids.map((id) => demoRef(id, "source_fact", "AUTHORIZED_READ", "AUDIT_TRAIL"));
  return refListOf(refs, "ZERO_OR_MORE", asOf);
}

function incidentRefs(ids: readonly string[], asOf: string) {
  const refs: Ref[] = ids.map((id) =>
    demoRef(id, "incident", "ENDPOINT", "SYSTEM_OPERATIONS"),
  );
  return refListOf(refs, "ZERO_OR_MORE", asOf);
}

function alertRefs(ids: readonly string[], asOf: string) {
  const refs: Ref[] = ids.map((id) => demoRef(id, "alert", "ENDPOINT", "ALERTS"));
  return refListOf(refs, "ZERO_OR_MORE", asOf);
}

export function syntheticDataQuality(
  asOf: string,
  originMs: number,
  evaluationMs: number,
): DataQualityPayload {
  const noGaps: DataQuality["missingness"] = [];

  /**
   * THE SUBJECT THE NARRATIVE TURNS ON.
   *
   * `PROVIDER_REALISTIC_PIT` over `PROVIDER_DERIVED` information — the pairing ADR-0010 leaves
   * in force while Q7 is `PUBLICLY_UNRESOLVED`. **It is never `PUBLIC_PIT`**, and the contract
   * refuses that pairing rather than relying on a reviewer noticing.
   */
  const marks: DataQuality = {
    subject_id: MARK_DATA_SUBJECT,
    subject: demoReason("US_EQUITY_DAILY_MARKS"),
    information_profile: "PROVIDER_REALISTIC_PIT",
    profile_basis: demoReason("DECLARED_BY_SYNTHETIC_FIXTURE_DEFINITION"),
    information_origin: demoReason("PROVIDER_DERIVED"),
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
    coverage: {
      present: count("data_quality.present", 497, asOf),
      requested: count("data_quality.requested", 504, asOf),
      ratio: scaled("coverage", "RATIO", 98, asOf),
      extent: demoReason("RETAINED_SESSION_EXTENT"),
    },
    missingness: [
      {
        gap: demoReason("SESSIONS_NOT_DELIVERED"),
        sessions: count("data_quality.missing_sessions", 7, asOf),
        extent: demoReason("RETAINED_SESSION_EXTENT"),
      },
    ],
    history_depth: calendarDays("data_quality.history_depth", 730, asOf),
    earliest_record: instantValue("data_quality.earliest_record", "2024-09-09", asOf),
    freshness: subjectFreshness("marks.feed", 7_200, 3_600, originMs, evaluationMs),
    dataset_version: "demo-dataset-marks-0007",
    lineage_refs: lineage(["demo-source-marks-manifest"], asOf),
    quality_checks: [
      {
        check: demoReason("SESSION_CONTINUITY"),
        result: demoReason("FAILED"),
        as_of: instantOf(originMs - 2 * HOUR_MS),
        population: count("data_quality.check_population", 504, asOf),
      },
      {
        check: demoReason("PRICE_BOUNDS"),
        result: demoReason("PASSED"),
        as_of: instantOf(originMs - 2 * HOUR_MS),
        population: count("data_quality.check_population", 497, asOf),
      },
      {
        /** A check that did not run examined no population, and reports none. */
        check: demoReason("CROSS_SOURCE_AGREEMENT"),
        result: demoReason("NOT_RUN"),
        as_of: instantOf(originMs - 2 * HOUR_MS),
        population: unavailable(
          "data_quality.check_population",
          "COUNT",
          "NOT_IMPLEMENTED",
          "PRODUCER_NOT_IMPLEMENTED",
        ),
      },
    ],
    revision_view: [
      {
        observed_at: instantOf(originMs - DAY_MS),
        revision_kind: demoReason("ROWS_ARRIVED_LATE"),
        affected_rows: count("data_quality.revised_rows", 3, asOf),
        /**
         * DATE-GRANULAR, AND THAT BOUND TRAVELS WITH EVERY OBSERVATION.
         *
         * A date cannot supply an instant, so information time stays bounded regardless of
         * what the comparison found.
         */
        information_time_resolution: demoReason("DATE_GRANULAR"),
      },
    ],
    corporate_actions: [
      {
        action: demoReason("SPLIT"),
        announced_on: instantValue("corporate_action.announced_on", "2026-08-14", asOf),
        effective_on: instantValue("corporate_action.effective_on", "2026-08-28", asOf),
        /** The announcement date is APPROXIMATED, and the basis says so. */
        timing_basis: demoReason("ANNOUNCEMENT_DATE_APPROXIMATED_FROM_EFFECTIVE_DATE"),
        treatment: demoReason("ADJUSTED_SERIES_KEPT_SEPARATE_FROM_ACTUAL_FILLS"),
      },
    ],
    borrow_quality: {
      state: demoReason("NOT_APPLICABLE_TO_THIS_SUBJECT"),
      records: notApplicable("data_quality.borrow_records", "COUNT"),
      note: demoReason("BORROW_QUALITY_IS_RECORDED_ON_ITS_OWN_SUBJECT"),
    },
    incident_refs: incidentRefs([MARK_FEED_INCIDENT], asOf),
    alert_refs: alertRefs([`alert-${CONDITION_MARK_STALENESS}`], asOf),
    affected_strategies: [
      {
        strategy_module: demoReason("PEAD_SHORT"),
        version_ref: demoRef("pead-short-v1", "strategy_version", "ENDPOINT"),
        condition: demoReason("MARK_DATA_OLDER_THAN_CONTRACT"),
        /** A RECORDED effect. Nothing on this screen caused it and nothing can reverse it. */
        effect: demoReason("OPEN_PLANNED_RISK_ASSESSMENT_REPORTED_STALE"),
      },
    ],
    subject_state: { availability: "STALE", reason: "UPSTREAM_INPUT_STALE" },
  };

  /** Corporate actions: fully covered, and every check passed. A clean subject exists too. */
  const actions: DataQuality = {
    subject_id: "corporate-actions",
    subject: demoReason("CORPORATE_ACTIONS"),
    information_profile: "PROVIDER_REALISTIC_PIT",
    profile_basis: demoReason("DECLARED_BY_SYNTHETIC_FIXTURE_DEFINITION"),
    information_origin: demoReason("PROVIDER_DERIVED"),
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
    coverage: {
      present: count("data_quality.present", 504, asOf),
      requested: count("data_quality.requested", 504, asOf),
      ratio: scaled("coverage", "RATIO", 100, asOf),
      extent: demoReason("RETAINED_SESSION_EXTENT"),
    },
    missingness: noGaps,
    history_depth: calendarDays("data_quality.history_depth", 730, asOf),
    earliest_record: instantValue("data_quality.earliest_record", "2024-09-09", asOf),
    freshness: subjectFreshness("actions.feed", 900, 86_400, originMs, evaluationMs),
    dataset_version: "demo-dataset-actions-0003",
    lineage_refs: lineage(["demo-source-actions-manifest"], asOf),
    quality_checks: [
      {
        check: demoReason("EFFECTIVE_DATE_PRESENT"),
        result: demoReason("PASSED"),
        as_of: instantOf(originMs - 900_000),
        population: count("data_quality.check_population", 41, asOf),
      },
      {
        check: demoReason("ANNOUNCEMENT_DATE_PRESENT"),
        result: demoReason("INCONCLUSIVE"),
        as_of: instantOf(originMs - 900_000),
        population: count("data_quality.check_population", 41, asOf),
      },
    ],
    revision_view: [
      {
        observed_at: instantOf(originMs - 2 * DAY_MS),
        revision_kind: demoReason("NO_REVISION_OBSERVED"),
        /** A MEASURED zero: the comparison ran and found nothing revised. */
        affected_rows: count("data_quality.revised_rows", 0, asOf),
        information_time_resolution: demoReason("DATE_GRANULAR"),
      },
    ],
    corporate_actions: [
      {
        action: demoReason("CASH_DIVIDEND"),
        announced_on: instantValue("corporate_action.announced_on", "2026-07-02", asOf),
        effective_on: instantValue("corporate_action.effective_on", "2026-07-16", asOf),
        timing_basis: demoReason("BOTH_DATES_RECORDED"),
        treatment: demoReason("ADJUSTED_SERIES_KEPT_SEPARATE_FROM_ACTUAL_FILLS"),
      },
      {
        action: demoReason("SPINOFF"),
        announced_on: unavailable(
          "corporate_action.announced_on",
          "DIMENSIONLESS",
          "NOT_YET_AVAILABLE",
          "UPSTREAM_INPUT_MISSING",
        ),
        effective_on: instantValue("corporate_action.effective_on", "2026-06-11", asOf),
        timing_basis: demoReason("ANNOUNCEMENT_DATE_NOT_RECORDED"),
        /** The provider's spinoff semantics are undocumented, and the treatment says so. */
        treatment: demoReason("SPINOFF_TREATMENT_UNDOCUMENTED"),
      },
    ],
    borrow_quality: {
      state: demoReason("NOT_APPLICABLE_TO_THIS_SUBJECT"),
      records: notApplicable("data_quality.borrow_records", "COUNT"),
      note: demoReason("BORROW_QUALITY_IS_RECORDED_ON_ITS_OWN_SUBJECT"),
    },
    incident_refs: refListOf([], "ZERO_OR_MORE", asOf),
    alert_refs: refListOf([], "ZERO_OR_MORE", asOf),
    affected_strategies: [],
    subject_state: { availability: "AVAILABLE", reason: "NONE" },
  };

  /**
   * BORROW AVAILABILITY — a `FORWARD_SYSTEM` subject, and G5 is OPEN.
   *
   * A borrow record observed today says what is borrowable today. It is not a point-in-time
   * history, and the profile that says so is the accepted one rather than a new member.
   */
  const borrow: DataQuality = {
    subject_id: "borrow-availability",
    subject: demoReason("BORROW_AVAILABILITY"),
    information_profile: "FORWARD_SYSTEM",
    profile_basis: demoReason("DECLARED_BY_ACCEPTED_DECISION"),
    information_origin: demoReason("SYSTEM_DERIVED"),
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
    coverage: {
      present: count("data_quality.present", 6, asOf),
      requested: count("data_quality.requested", 11, asOf),
      ratio: scaled("coverage", "RATIO", 55, asOf),
      extent: demoReason("SHORTABLE_UNIVERSE"),
    },
    missingness: [
      {
        gap: demoReason("NO_BORROW_RECORD_FOR_SUBJECT"),
        sessions: count("data_quality.missing_sessions", 5, asOf),
        extent: demoReason("SHORTABLE_UNIVERSE"),
      },
    ],
    history_depth: unavailable(
      "data_quality.history_depth",
      "CALENDAR_DAYS",
      "NOT_YET_AVAILABLE",
      "UPSTREAM_INPUT_MISSING",
    ),
    earliest_record: unavailable(
      "data_quality.earliest_record",
      "DIMENSIONLESS",
      "NOT_YET_AVAILABLE",
      "UPSTREAM_INPUT_MISSING",
    ),
    freshness: subjectFreshness("borrow.feed", 1_800, 7_200, originMs, evaluationMs),
    dataset_version: "demo-dataset-borrow-0001",
    lineage_refs: lineage(["demo-source-borrow-manifest"], asOf),
    quality_checks: [
      {
        check: demoReason("BORROW_RECORD_PRESENT"),
        result: demoReason("FAILED"),
        as_of: instantOf(originMs - 1_800_000),
        population: count("data_quality.check_population", 11, asOf),
      },
    ],
    revision_view: [
      {
        observed_at: instantOf(originMs - 3 * DAY_MS),
        /** No prior snapshot was retained, so no comparison could run at all. */
        revision_kind: demoReason("REVISION_NOT_MEASURABLE"),
        affected_rows: unavailable(
          "data_quality.revised_rows",
          "COUNT",
          "NOT_YET_AVAILABLE",
          "UPSTREAM_INPUT_MISSING",
        ),
        information_time_resolution: demoReason("NO_HISTORY_RETAINED"),
      },
    ],
    corporate_actions: [],
    borrow_quality: {
      state: demoReason("PARTIAL_COVERAGE_RECORDED"),
      records: count("data_quality.borrow_records", 6, asOf),
      note: demoReason("G5_HISTORICAL_BORROW_QUALIFICATION_IS_OPEN"),
    },
    incident_refs: refListOf([], "ZERO_OR_MORE", asOf),
    alert_refs: alertRefs([`alert-${CONDITION_BORROW}`], asOf),
    affected_strategies: [
      {
        strategy_module: demoReason("DETERIORATION_SHORT"),
        version_ref: demoRef("deterioration-short-v1", "strategy_version", "ENDPOINT"),
        condition: demoReason("BORROW_WITHDRAWN_FOR_A_SHORT_CANDIDATE"),
        effect: demoReason("SHORT_CANDIDATE_RECORDED_BLOCKED_BORROW"),
      },
    ],
    subject_state: { availability: "PARTIAL", reason: "EXTENT_PARTIALLY_COVERED" },
  };

  /**
   * A subject that legitimately IS `PUBLIC_PIT`, because its information is publicly observed.
   *
   * It exists so the vocabulary is shown used exactly rather than as one profile everywhere —
   * and it is emphatically not a provider price feed, which stays `PROVIDER_DERIVED`.
   */
  const filings: DataQuality = {
    subject_id: "public-filings-index",
    subject: demoReason("PUBLIC_FILINGS_INDEX"),
    information_profile: "PUBLIC_PIT",
    profile_basis: demoReason("DECLARED_BY_ACCEPTED_DECISION"),
    information_origin: demoReason("PUBLIC_SOURCE_OBSERVED"),
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
    coverage: {
      present: count("data_quality.present", 0, asOf),
      requested: count("data_quality.requested", 504, asOf),
      ratio: scaled("coverage", "RATIO", 0, asOf),
      extent: demoReason("RETAINED_SESSION_EXTENT"),
    },
    missingness: [
      {
        gap: demoReason("NO_FEED_CONNECTED"),
        sessions: count("data_quality.missing_sessions", 504, asOf),
        extent: demoReason("RETAINED_SESSION_EXTENT"),
      },
    ],
    history_depth: unavailable(
      "data_quality.history_depth",
      "CALENDAR_DAYS",
      "NOT_IMPLEMENTED",
      "PRODUCER_NOT_IMPLEMENTED",
    ),
    earliest_record: unavailable(
      "data_quality.earliest_record",
      "DIMENSIONLESS",
      "NOT_IMPLEMENTED",
      "PRODUCER_NOT_IMPLEMENTED",
    ),
    freshness: subjectFreshness("filings.index", 5, 86_400, originMs, evaluationMs),
    dataset_version: "demo-dataset-filings-0000",
    lineage_refs: refListOf([], "ZERO_OR_MORE", asOf),
    quality_checks: [
      {
        check: demoReason("FILING_TIMESTAMP_PRESENT"),
        result: demoReason("NOT_RUN"),
        as_of: instantOf(originMs - 5_000),
        population: unavailable(
          "data_quality.check_population",
          "COUNT",
          "NOT_IMPLEMENTED",
          "PRODUCER_NOT_IMPLEMENTED",
        ),
      },
    ],
    revision_view: [],
    corporate_actions: [],
    borrow_quality: {
      state: demoReason("NOT_APPLICABLE_TO_THIS_SUBJECT"),
      records: notApplicable("data_quality.borrow_records", "COUNT"),
      note: demoReason("BORROW_QUALITY_IS_RECORDED_ON_ITS_OWN_SUBJECT"),
    },
    incident_refs: refListOf([], "ZERO_OR_MORE", asOf),
    alert_refs: refListOf([], "ZERO_OR_MORE", asOf),
    affected_strategies: [],
    subject_state: { availability: "NOT_IMPLEMENTED", reason: "PRODUCER_NOT_IMPLEMENTED" },
  };

  const items = [marks, borrow, actions, filings];
  return {
    items,
    page: {
      page_size: PAGE_SIZE_DATA_QUALITY,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("SUBJECT_STATE_THEN_SUBJECT_ASCENDING"),
      tiebreak: demoReason("SUBJECT_ID_ASCENDING"),
    },
    information_profiles: [...INFORMATION_PROFILES],
    window: {
      from: instantOf(originMs - 504 * DAY_MS),
      to: asOf,
      calendar: CALENDAR,
      timezone: "UTC",
    },
    real_feed_state: {
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
      note: demoReason("NO_PROVIDER_IS_SELECTED_AND_P1_TO_P9_ARE_UNEVALUATED"),
    },
  };
}

/* ==================================================== Area 23 — jobs and incidents === */

function evidenceRefs(ids: readonly string[], asOf: string) {
  const refs: Ref[] = ids.map((id) => demoRef(id, "source_fact", "AUTHORIZED_READ", "AUDIT_TRAIL"));
  return refListOf(refs, "ZERO_OR_MORE", asOf);
}

/**
 * Every job declares that NO RUNTIME SERVICE EXISTS.
 *
 * The contract then refuses any present observation and, through that, any claim of present
 * health — so "a synthetic row naming a service is not evidence that the service exists" is a
 * rule the payload cannot break rather than a caveat a screen might omit.
 */
const NO_SERVICE = "NO_RUNTIME_SERVICE_EXISTS";

function neverObservedNow() {
  return unavailable(
    "job.latency",
    "SECONDS",
    "NOT_IMPLEMENTED",
    "PRODUCER_NOT_IMPLEMENTED",
  );
}

function noAvailability() {
  return unavailable(
    "job.availability",
    "PERCENT",
    "NOT_IMPLEMENTED",
    "PRODUCER_NOT_IMPLEMENTED",
  );
}

function noSchedule() {
  return unavailable(
    "job.next_scheduled_at",
    "DIMENSIONLESS",
    "NOT_IMPLEMENTED",
    "PRODUCER_NOT_IMPLEMENTED",
  );
}

export function syntheticSystemJobs(asOf: string, originMs: number): SystemJobPayload {
  const jobs: SystemJob[] = [
    {
      /** The job behind the data condition. Its last run FAILED and its queue is backing up. */
      job_id: MARK_REFRESH_JOB,
      kind: demoReason("MARKET_DATA_MARK_REFRESH"),
      subsystem_role: demoReason("DATA_PLATFORM"),
      service_existence: demoReason(NO_SERVICE),
      last_run: {
        at: instantOf(originMs - 2 * HOUR_MS),
        outcome: demoReason("FAILED"),
      },
      /** The last SUCCESS, with its own as-of. It is not current health. */
      last_success: instantValue(
        "job.last_success_at",
        instantOf(originMs - 26 * HOUR_MS),
        asOf,
      ),
      duration: seconds("job.duration", 41, asOf),
      queue_depth: count("job.queue_depth", 3, asOf),
      next_scheduled: noSchedule(),
      current_state: demoReason("FAILING"),
      current_observation: neverObservedNow(),
      availability: noAvailability(),
      restarts: count("job.restarts", 2, asOf),
      evidence_refs: evidenceRefs(["demo-source-mark-refresh-log"], asOf),
      incident_refs: incidentRefs([MARK_FEED_INCIDENT], asOf),
    },
    {
      job_id: "demo-job-reconciliation-sweep",
      kind: demoReason("BROKER_RECONCILIATION_SWEEP"),
      subsystem_role: demoReason("EXECUTION_PLATFORM"),
      service_existence: demoReason(NO_SERVICE),
      last_run: { at: instantOf(originMs - HOUR_MS), outcome: demoReason("SUCCEEDED") },
      last_success: instantValue("job.last_success_at", instantOf(originMs - HOUR_MS), asOf),
      duration: seconds("job.duration", 12, asOf),
      queue_depth: count("job.queue_depth", 0, asOf),
      next_scheduled: noSchedule(),
      /**
       * ITS LAST RUN SUCCEEDED, AND ITS CURRENT STATE IS `NOT_OBSERVED`.
       *
       * This is the separation the area exists to keep: nothing observes this job now, so a
       * historical success cannot be promoted into a statement about the present.
       */
      current_state: demoReason("NOT_OBSERVED"),
      current_observation: neverObservedNow(),
      availability: noAvailability(),
      restarts: count("job.restarts", 0, asOf),
      evidence_refs: evidenceRefs([`demo-source-${RECONCILIATION_MISMATCH_RUN}`], asOf),
      incident_refs: incidentRefs([RECONCILIATION_INCIDENT], asOf),
    },
    {
      job_id: "demo-job-borrow-refresh",
      kind: demoReason("BORROW_AVAILABILITY_REFRESH"),
      subsystem_role: demoReason("DATA_PLATFORM"),
      service_existence: demoReason(NO_SERVICE),
      last_run: {
        at: instantOf(originMs - 30 * MINUTE_MS),
        outcome: demoReason("PARTIALLY_COMPLETED"),
      },
      last_success: instantValue(
        "job.last_success_at",
        instantOf(originMs - 4 * HOUR_MS),
        asOf,
      ),
      duration: seconds("job.duration", 9, asOf),
      queue_depth: count("job.queue_depth", 1, asOf),
      next_scheduled: noSchedule(),
      current_state: demoReason("DEGRADED"),
      current_observation: neverObservedNow(),
      availability: noAvailability(),
      restarts: count("job.restarts", 0, asOf),
      evidence_refs: evidenceRefs(["demo-source-borrow-refresh-log"], asOf),
      incident_refs: refListOf([], "ZERO_OR_MORE", asOf),
    },
    {
      job_id: "demo-job-candidate-scanner",
      kind: demoReason("CANDIDATE_SCANNER"),
      subsystem_role: demoReason("BRAIN_RUNTIME"),
      service_existence: demoReason(NO_SERVICE),
      last_run: { at: instantOf(originMs - 6 * HOUR_MS), outcome: demoReason("NOT_RUN") },
      /** It has never succeeded, so it records no success time at all. */
      last_success: unavailable(
        "job.last_success_at",
        "DIMENSIONLESS",
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
      ),
      duration: unavailable(
        "job.duration",
        "SECONDS",
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
      ),
      queue_depth: unavailable(
        "job.queue_depth",
        "COUNT",
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
      ),
      next_scheduled: noSchedule(),
      current_state: demoReason("NEVER_OBSERVED"),
      current_observation: neverObservedNow(),
      availability: noAvailability(),
      restarts: unavailable(
        "job.restarts",
        "COUNT",
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
      ),
      evidence_refs: refListOf([], "ZERO_OR_MORE", asOf),
      incident_refs: refListOf([], "ZERO_OR_MORE", asOf),
    },
    {
      job_id: "demo-job-research-runner",
      kind: demoReason("RESEARCH_RUN_EXECUTOR"),
      subsystem_role: demoReason("RESEARCH_RUNTIME"),
      service_existence: demoReason(NO_SERVICE),
      last_run: { at: instantOf(originMs - 12 * HOUR_MS), outcome: demoReason("NOT_RUN") },
      last_success: unavailable(
        "job.last_success_at",
        "DIMENSIONLESS",
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
      ),
      duration: unavailable(
        "job.duration",
        "SECONDS",
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
      ),
      queue_depth: count("job.queue_depth", 0, asOf),
      next_scheduled: noSchedule(),
      current_state: demoReason("NEVER_OBSERVED"),
      current_observation: neverObservedNow(),
      availability: noAvailability(),
      restarts: unavailable(
        "job.restarts",
        "COUNT",
        "NOT_IMPLEMENTED",
        "PRODUCER_NOT_IMPLEMENTED",
      ),
      evidence_refs: refListOf([], "ZERO_OR_MORE", asOf),
      incident_refs: refListOf([], "ZERO_OR_MORE", asOf),
    },
    {
      job_id: "demo-job-audit-projection",
      kind: demoReason("AUDIT_PROJECTION_REBUILD"),
      subsystem_role: demoReason("AUDIT_PROJECTION"),
      service_existence: demoReason(NO_SERVICE),
      last_run: { at: instantOf(originMs - 15 * MINUTE_MS), outcome: demoReason("SUCCEEDED") },
      last_success: instantValue(
        "job.last_success_at",
        instantOf(originMs - 15 * MINUTE_MS),
        asOf,
      ),
      duration: seconds("job.duration", 3, asOf),
      queue_depth: count("job.queue_depth", 0, asOf),
      next_scheduled: noSchedule(),
      current_state: demoReason("NOT_OBSERVED"),
      current_observation: neverObservedNow(),
      availability: noAvailability(),
      restarts: count("job.restarts", 0, asOf),
      evidence_refs: evidenceRefs(["demo-source-audit-projection-log"], asOf),
      incident_refs: refListOf([], "ZERO_OR_MORE", asOf),
    },
  ];

  return {
    items: jobs,
    page: {
      page_size: PAGE_SIZE_JOBS,
      total: count("reference.total", jobs.length, asOf),
      truncated: false,
      sort: demoReason("LAST_RUN_DESCENDING"),
      tiebreak: demoReason("JOB_ID_ASCENDING"),
    },
    absent_controls: [
      demoReason("START"),
      demoReason("STOP"),
      demoReason("RETRY"),
      demoReason("TRIGGER"),
      demoReason("RESTART"),
      demoReason("SCHEDULE"),
      demoReason("REPAIR"),
    ],
    scheduler_state: {
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
      note: demoReason("NO_SCHEDULER_OR_SERVICE_RUNTIME_EXISTS"),
    },
  };
}

export function syntheticIncidents(asOf: string, originMs: number): SystemIncidentPayload {
  const openedMark = originMs - 26 * HOUR_MS;
  const openedRecon = originMs - HOUR_MS;
  const openedScheduler = originMs - 5 * DAY_MS;
  const closedScheduler = originMs - 4 * DAY_MS;

  const incidents: SystemIncident[] = [
    {
      incident_id: MARK_FEED_INCIDENT,
      opened_at: instantOf(openedMark),
      /** OPEN, so it records no close time. An absence, and never a zero. */
      closed_at: notApplicable("incident.closed_at", "DIMENSIONLESS"),
      open_duration: seconds(
        "incident.open_duration",
        (Date.parse(asOf) - openedMark) / 1000,
        asOf,
      ),
      severity: demoReason("HIGH"),
      subject: demoReason("US_EQUITY_DAILY_MARKS"),
      state: demoReason("OPEN"),
      timeline: [
        {
          at: instantOf(openedMark),
          event: demoReason("MARK_REFRESH_RUN_FAILED"),
          detail: demoReason("LAST_SUCCESSFUL_REFRESH_RECORDED_BEFORE_THIS_POINT"),
        },
        {
          at: instantOf(openedMark + 2 * HOUR_MS),
          event: demoReason("MARK_AGE_EXCEEDED_CONTRACT"),
          detail: demoReason("EXPOSURE_FIGURES_REPORTED_STALE"),
        },
        {
          at: instantOf(originMs - 2 * HOUR_MS),
          event: demoReason("MARK_REFRESH_RUN_FAILED"),
          detail: demoReason("QUEUE_DEPTH_INCREASED"),
        },
      ],
      evidence_refs: evidenceRefs(
        ["demo-source-mark-refresh-log", "demo-source-marks-manifest"],
        asOf,
      ),
      alert_refs: alertRefs([`alert-${CONDITION_MARK_STALENESS}`], asOf),
    },
    {
      incident_id: RECONCILIATION_INCIDENT,
      opened_at: instantOf(openedRecon),
      closed_at: notApplicable("incident.closed_at", "DIMENSIONLESS"),
      open_duration: seconds(
        "incident.open_duration",
        (Date.parse(asOf) - openedRecon) / 1000,
        asOf,
      ),
      severity: demoReason("LOW"),
      subject: demoReason("BROKER_RECONCILIATION"),
      state: demoReason("MITIGATED"),
      timeline: [
        {
          at: instantOf(openedRecon),
          event: demoReason("ORPHAN_OBSERVED_IN_RECONCILIATION_SWEEP"),
          detail: demoReason("RECORDED_FOR_HUMAN_REVIEW"),
        },
      ],
      evidence_refs: evidenceRefs([`demo-source-${RECONCILIATION_MISMATCH_RUN}`], asOf),
      alert_refs: alertRefs([`alert-${CONDITION_RECONCILIATION}`], asOf),
    },
    {
      incident_id: SCHEDULER_INCIDENT,
      opened_at: instantOf(openedScheduler),
      /** CLOSED, so it records exactly when. */
      closed_at: instantValue("incident.closed_at", instantOf(closedScheduler), asOf),
      open_duration: seconds(
        "incident.open_duration",
        (closedScheduler - openedScheduler) / 1000,
        asOf,
      ),
      severity: demoReason("MEDIUM"),
      subject: demoReason("JOB_SCHEDULING"),
      state: demoReason("CLOSED"),
      timeline: [
        {
          at: instantOf(openedScheduler),
          event: demoReason("QUEUE_DEPTH_EXCEEDED_THRESHOLD"),
          detail: demoReason("RECORDED_FOR_HUMAN_REVIEW"),
        },
        {
          at: instantOf(closedScheduler),
          event: demoReason("QUEUE_DEPTH_RETURNED_WITHIN_THRESHOLD"),
          detail: demoReason("INCIDENT_CLOSED"),
        },
      ],
      evidence_refs: evidenceRefs(["demo-source-scheduler-log"], asOf),
      alert_refs: alertRefs([`alert-${CONDITION_SCHEDULER_LAG}`], asOf),
    },
  ];

  return {
    items: incidents,
    page: {
      page_size: PAGE_SIZE_INCIDENTS,
      total: count("reference.total", incidents.length, asOf),
      truncated: false,
      sort: demoReason("OPENED_AT_DESCENDING"),
      tiebreak: demoReason("INCIDENT_ID_ASCENDING"),
    },
    incident_states: [demoReason("OPEN"), demoReason("MITIGATED"), demoReason("CLOSED")],
    /** The producer RAN and counted two incidents that are not closed. A measured value. */
    open_count: count(
      "operations.open_incidents",
      incidents.filter((incident) => incident.state.code !== "CLOSED").length,
      asOf,
    ),
  };
}

/* ================================================================ Area 27 — alerts === */

/**
 * One alert per condition, over the SAME identities the attention projection deduplicates on.
 *
 * The occurrence counts match what the attention list already records, so the executive and
 * operator views reconcile: `demo-dedup-mark-staleness` was seen six times and the attention
 * projection folded a second observation of it away, which is exactly what
 * `deduplicated_away` states here.
 */
export function syntheticAlerts(asOf: string, originMs: number): AlertPayload {
  const earlier = originMs - DAY_MS;
  const empty = refListOf([], "ZERO_OR_MORE", asOf);

  const alerts: Alert[] = [
    {
      alert_id: `alert-${CONDITION_STRATEGY_HEALTH}`,
      condition: demoReason("STRATEGY_ENTERED_DEGRADED"),
      severity: demoReason("HIGH"),
      dedup_key: CONDITION_STRATEGY_HEALTH,
      first_seen: instantOf(earlier),
      last_seen: instantOf(originMs),
      occurrence_count: count("alert.occurrence_count", 2, asOf),
      state: "OPEN",
      resolved_at: notApplicable("alert.resolved_at", "DIMENSIONLESS"),
      deduplicated_away: count("alert.deduplicated_away", 0, asOf),
      impact: scaled("strategy.health_impact", "R_MULTIPLE", -42, asOf),
      evidence_refs: refListOf(
        [demoRef("demo-evidence-health", "source_fact", "AUTHORIZED_READ", "STRATEGY_HEALTH")],
        "ZERO_OR_MORE",
        asOf,
      ),
      incident_refs: empty,
    },
    {
      alert_id: `alert-${CONDITION_MARK_STALENESS}`,
      condition: demoReason("MARK_DATA_OLDER_THAN_CONTRACT"),
      severity: demoReason("MEDIUM"),
      dedup_key: CONDITION_MARK_STALENESS,
      first_seen: instantOf(earlier),
      last_seen: instantOf(originMs),
      occurrence_count: count("alert.occurrence_count", 6, asOf),
      state: "OPEN",
      resolved_at: notApplicable("alert.resolved_at", "DIMENSIONLESS"),
      /** One earlier observation of this same condition was folded into this row. */
      deduplicated_away: count("alert.deduplicated_away", 1, asOf),
      /** NOBODY MEASURED THE IMPACT. It is not ranked as zero impact. */
      impact: notApplicable("attention.impact", "DIMENSIONLESS"),
      evidence_refs: refListOf(
        [
          demoRef("demo-evidence-data-quality", "source_fact", "AUTHORIZED_READ", "DATA_QUALITY"),
        ],
        "ZERO_OR_MORE",
        asOf,
      ),
      incident_refs: incidentRefs([MARK_FEED_INCIDENT], asOf),
    },
    {
      alert_id: `alert-${CONDITION_BORROW}`,
      condition: demoReason("BORROW_WITHDRAWN_FOR_A_SHORT_CANDIDATE"),
      severity: demoReason("MEDIUM"),
      dedup_key: CONDITION_BORROW,
      first_seen: instantOf(originMs),
      last_seen: instantOf(originMs),
      occurrence_count: count("alert.occurrence_count", 1, asOf),
      state: "OPEN",
      resolved_at: notApplicable("alert.resolved_at", "DIMENSIONLESS"),
      deduplicated_away: count("alert.deduplicated_away", 0, asOf),
      /** A MEASURED zero impact — a real answer, and not the same thing as no answer. */
      impact: usd("alert.impact_usd", 0, asOf),
      evidence_refs: refListOf(
        [demoRef("demo-evidence-borrow", "source_fact", "AUTHORIZED_READ", "SHORT_SIDE")],
        "ZERO_OR_MORE",
        asOf,
      ),
      incident_refs: empty,
    },
    {
      alert_id: `alert-${CONDITION_RECONCILIATION}`,
      condition: demoReason("RECONCILIATION_ORPHAN_OBSERVED"),
      severity: demoReason("LOW"),
      dedup_key: CONDITION_RECONCILIATION,
      first_seen: instantOf(earlier),
      last_seen: instantOf(originMs),
      occurrence_count: count("alert.occurrence_count", 3, asOf),
      state: "OPEN",
      resolved_at: notApplicable("alert.resolved_at", "DIMENSIONLESS"),
      deduplicated_away: count("alert.deduplicated_away", 0, asOf),
      impact: unavailable(
        "attention.impact",
        "DIMENSIONLESS",
        "INSUFFICIENT_OBSERVATIONS",
        "BELOW_MINIMUM_OBSERVATIONS",
      ),
      evidence_refs: refListOf(
        [
          demoRef(
            "demo-evidence-reconciliation",
            "source_fact",
            "AUTHORIZED_READ",
            "RECONCILIATION",
          ),
        ],
        "ZERO_OR_MORE",
        asOf,
      ),
      incident_refs: incidentRefs([RECONCILIATION_INCIDENT], asOf),
    },
    {
      alert_id: `alert-${CONDITION_UNSOURCED}`,
      condition: demoReason("UNSOURCED_OBSERVATION"),
      severity: demoReason("LOW"),
      dedup_key: CONDITION_UNSOURCED,
      first_seen: instantOf(originMs),
      last_seen: instantOf(originMs),
      occurrence_count: count("alert.occurrence_count", 1, asOf),
      state: "OPEN",
      resolved_at: notApplicable("alert.resolved_at", "DIMENSIONLESS"),
      deduplicated_away: count("alert.deduplicated_away", 0, asOf),
      impact: notApplicable("attention.impact", "DIMENSIONLESS"),
      /** No evidence reference exists for this condition, and the row says so. */
      evidence_refs: empty,
      incident_refs: empty,
    },
    {
      /** A RESOLVED alert, so the resolved history is a record rather than an empty section. */
      alert_id: `alert-${CONDITION_SCHEDULER_LAG}`,
      condition: demoReason("SCHEDULER_QUEUE_DEPTH_EXCEEDED"),
      severity: demoReason("MEDIUM"),
      dedup_key: CONDITION_SCHEDULER_LAG,
      first_seen: instantOf(originMs - 5 * DAY_MS),
      last_seen: instantOf(originMs - 4 * DAY_MS - HOUR_MS),
      occurrence_count: count("alert.occurrence_count", 4, asOf),
      state: "RESOLVED",
      resolved_at: instantValue(
        "alert.resolved_at",
        instantOf(originMs - 4 * DAY_MS),
        asOf,
      ),
      deduplicated_away: count("alert.deduplicated_away", 2, asOf),
      impact: notApplicable("attention.impact", "DIMENSIONLESS"),
      evidence_refs: evidenceRefs(["demo-source-scheduler-log"], asOf),
      incident_refs: incidentRefs([SCHEDULER_INCIDENT], asOf),
    },
  ];

  const folded = alerts.reduce(
    (total, row) => total + (typeof row.deduplicated_away.value === "number" ? row.deduplicated_away.value : 0),
    0,
  );

  return {
    items: alerts,
    page: {
      page_size: PAGE_SIZE_ALERTS,
      total: count("reference.total", alerts.length, asOf),
      truncated: false,
      sort: demoReason("SEVERITY_RANK_THEN_LAST_SEEN_DESCENDING"),
      tiebreak: demoReason("DEDUP_KEY_ASCENDING"),
    },
    severity_order: [...ALERT_SEVERITIES],
    folded_total: count("alert.deduplicated_away", folded, asOf),
    absent_integrations: [
      demoReason("EMAIL"),
      demoReason("SMS"),
      demoReason("PUSH"),
      demoReason("CHAT_WEBHOOK"),
      demoReason("PAGING"),
    ],
  };
}
