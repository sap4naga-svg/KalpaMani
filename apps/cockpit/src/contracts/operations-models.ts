/**
 * The C8 data-quality, operations and alert payload contracts — `read-model-contracts.md`
 * §4.5 *Data, operations and audit*, Areas 22, 23 and 27.
 *
 * **Read-only presentation.** Displaying a data condition does not read a provider, displaying
 * a job does not run one, and displaying an alert does not notify anybody. **No field on any
 * contract here can carry a start, stop, retry, trigger, acknowledge, resolve, snooze or
 * dismiss**, because no such value exists in any of its closed vocabularies and no such
 * parameter exists on any of its shapes.
 *
 * FIVE SEPARATIONS THESE CONTRACTS EXIST TO KEEP, and each one is a refinement rather than a
 * convention:
 *
 *   A PROFILE IS DECLARED, NEVER INFERRED     the three accepted members and nothing else, and
 *                                             a subject whose information origin is
 *                                             `PROVIDER_DERIVED` may not declare `PUBLIC_PIT`
 *   COVERAGE NAMES ITS POPULATION             `present` and `requested` are separate counts,
 *                                             and a subject covering less than it was asked
 *                                             for must NAME the gap rather than look complete
 *   LAST SUCCESS IS NOT CURRENT HEALTH        two fields, and a claim of present health
 *                                             requires a PRESENT observation to rest on
 *   AN OPEN INCIDENT HAS NO CLOSE TIME        and a closed one has one. Neither is inferred
 *                                             from the other
 *   ONE CONDITION IS ONE ALERT                the collection REFUSES two rows sharing a
 *                                             `dedup_key`, because "a hundred copies of a true
 *                                             alert is an outage of the alerting system"
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { freshnessReport } from "./freshness";
import { collectionPayload } from "./pagination";
import { refListFieldOf, refOf } from "./references";
import {
  instant,
  metricOf,
  metricValue,
  parseInstantMs,
  reasonCoded,
  safeId,
} from "./values";
import { isValueBearing } from "./validity";
import {
  availabilityState,
  dataClassification,
  dataProvenance,
  fieldReasonCode,
  informationProfile,
} from "./vocabularies";

/* ===================================================================== shared helpers === */

/** The numeric value of a metric, or `null` where it carries none this rule can read. */
function numberOf(metric: z.infer<typeof metricValue>): number | null {
  if (!isValueBearing(metric.availability)) {
    return null;
  }
  return typeof metric.value === "number" ? metric.value : null;
}

/** The instant a metric carries as its value, in milliseconds, or `null`. */
function instantValueMs(metric: z.infer<typeof metricValue>): number | null {
  if (!isValueBearing(metric.availability) || typeof metric.value !== "string") {
    return null;
  }
  return parseInstantMs(metric.value);
}

/** A closed-vocabulary code, refused when it is outside the stated set. */
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

/* ======================================================= Area 22 — DataQuality (§4.5) === */

/**
 * How a subject's information-set profile came to be what it says.
 *
 * §2.9 and Area 22: "**No default profile is invented**; a profile is declared, never
 * inferred." `INFERRED_FROM_OBSERVED_DATA` is therefore **not a member**, and a producer that
 * wanted to state it has nowhere to put it.
 */
export const PROFILE_BASES = [
  "DECLARED_BY_ACCEPTED_DECISION",
  "DECLARED_BY_INGESTION_CONTRACT",
  "DECLARED_BY_SYNTHETIC_FIXTURE_DEFINITION",
] as const;

/**
 * Where a subject's information actually comes from — a SEPARATE axis from the profile.
 *
 * ADR-0010 leaves Q7 `PUBLICLY_UNRESOLVED`, so all Sharadar price data stays
 * `PROVIDER_DERIVED` and **is never represented as `PUBLIC_PIT`**. The refinement below
 * enforces exactly that pairing, for every subject and not only for one vendor.
 */
export const INFORMATION_ORIGINS = [
  "PROVIDER_DERIVED",
  "PUBLIC_SOURCE_OBSERVED",
  "SYSTEM_DERIVED",
  "ORIGIN_NOT_ESTABLISHED",
] as const;

/** What a recorded quality check concluded. A check that did not run says so. */
export const QUALITY_CHECK_RESULTS = [
  "PASSED",
  "FAILED",
  "INCONCLUSIVE",
  "NOT_RUN",
] as const;

export const qualityCheck = z
  .object({
    check: reasonCoded,
    result: reasonCoded,
    as_of: instant,
    /**
     * ADDITIVE: the population the check was run over.
     *
     * A passed check over eleven rows and a passed check over eleven thousand are different
     * evidence, and a result with no population is a verdict with no scope.
     */
    population: metricOf("data_quality.check_population"),
  })
  .superRefine((candidate, ctx) => {
    requireMember(candidate.result.code, QUALITY_CHECK_RESULTS, "quality check result", ctx);
    /*
     * A CHECK THAT DID NOT RUN MEASURED NO POPULATION.
     *
     * Reporting `NOT_RUN` beside a population count states that something was examined, which
     * is the opposite of what the result says.
     */
    if (candidate.result.code === "NOT_RUN" && isValueBearing(candidate.population.availability)) {
      ctx.addIssue({
        code: "custom",
        message: "a check that did not run reports no population it examined",
      });
    }
  });
export type QualityCheck = z.infer<typeof qualityCheck>;

/** What a revision observation found when the same subject was read again. */
export const REVISION_KINDS = [
  "ROWS_REVISED_IN_PLACE",
  "ROWS_ARRIVED_LATE",
  "NO_REVISION_OBSERVED",
  "REVISION_NOT_MEASURABLE",
] as const;

/**
 * One recorded revision observation.
 *
 * **Information time stays bounded regardless of outcome.** The vendor's update column is
 * date-granular, so `information_time_resolution` travels with every observation and a screen
 * can never present a date as an instant.
 */
export const revisionObservation = z
  .object({
    observed_at: instant,
    revision_kind: reasonCoded,
    affected_rows: metricOf("data_quality.revised_rows"),
    information_time_resolution: reasonCoded,
  })
  .superRefine((candidate, ctx) => {
    requireMember(candidate.revision_kind.code, REVISION_KINDS, "revision kind", ctx);
    /*
     * A MEASURED ZERO AND AN UNMEASURABLE ONE ARE DIFFERENT ANSWERS (ADR-0029 §2.1).
     *
     * `NO_REVISION_OBSERVED` means the comparison RAN and found nothing, so it carries a
     * measured zero; `REVISION_NOT_MEASURABLE` means it could not run, so it carries no value
     * at all and never a zero standing in for one.
     */
    if (candidate.revision_kind.code === "NO_REVISION_OBSERVED" && numberOf(candidate.affected_rows) !== 0) {
      ctx.addIssue({
        code: "custom",
        message: "an observation that found no revision reports a measured zero",
      });
    }
    if (
      candidate.revision_kind.code === "REVISION_NOT_MEASURABLE" &&
      isValueBearing(candidate.affected_rows.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "an unmeasurable revision reports no row count",
      });
    }
  });
export type RevisionObservation = z.infer<typeof revisionObservation>;

/** A recorded corporate action and the two dates that make its timing checkable. */
export const corporateActionEvidence = z.object({
  action: reasonCoded,
  announced_on: metricOf("corporate_action.announced_on"),
  effective_on: metricOf("corporate_action.effective_on"),
  /** How the timing was established. An approximation says so rather than passing as exact. */
  timing_basis: reasonCoded,
  treatment: reasonCoded,
});

/** A named gap in a subject's coverage. A gap with no name is a subject that looks complete. */
export const coverageGap = z.object({
  gap: reasonCoded,
  sessions: metricOf("data_quality.missing_sessions"),
  extent: reasonCoded,
});

/** A strategy a recorded data condition affects, named by its exact version. */
export const affectedStrategy = z.object({
  strategy_module: reasonCoded,
  version_ref: refOf("DataQuality.affected_strategies[].version_ref"),
  condition: reasonCoded,
  /** What the condition did — and it is a RECORDED effect, never an action taken here. */
  effect: reasonCoded,
});

export const dataQuality = z
  .object({
    subject_id: safeId,
    subject: reasonCoded,
    /** Exactly the three accepted members. No fourth exists, and no default is invented. */
    information_profile: informationProfile,
    profile_basis: reasonCoded,
    information_origin: reasonCoded,
    /** Kept SEPARATE from the profile: three different questions, three fields. */
    provenance: dataProvenance,
    classification: dataClassification,
    coverage: z.object({
      present: metricOf("data_quality.present"),
      requested: metricOf("data_quality.requested"),
      ratio: metricOf("coverage"),
      /** WHAT population the counts are over. A ratio with no extent has no denominator. */
      extent: reasonCoded,
    }),
    missingness: z.array(coverageGap),
    history_depth: metricOf("data_quality.history_depth"),
    earliest_record: metricOf("data_quality.earliest_record"),
    /** §4.5: per required input, with source age and projection lag reported separately. */
    freshness: freshnessReport,
    dataset_version: safeId,
    lineage_refs: refListFieldOf("DataQuality.lineage_refs"),
    quality_checks: z.array(qualityCheck),
    revision_view: z.array(revisionObservation),
    corporate_actions: z.array(corporateActionEvidence),
    /** Borrow-data quality, as its own recorded evidence. G5 is OPEN and this claims nothing. */
    borrow_quality: z.object({
      state: reasonCoded,
      records: metricOf("data_quality.borrow_records"),
      note: reasonCoded,
    }),
    incident_refs: refListFieldOf("DataQuality.incident_refs"),
    alert_refs: refListFieldOf("DataQuality.alert_refs"),
    affected_strategies: z.array(affectedStrategy),
    /** The row's own availability, so one degraded subject does not degrade the page. */
    subject_state: z.object({ availability: availabilityState, reason: fieldReasonCode }),
  })
  .superRefine((candidate, ctx) => {
    requireMember(candidate.profile_basis.code, PROFILE_BASES, "profile basis", ctx);
    requireMember(candidate.information_origin.code, INFORMATION_ORIGINS, "information origin", ctx);
    /*
     * PROVIDER-DERIVED INFORMATION IS NEVER `PUBLIC_PIT` (Area 22, ADR-0010 Q7).
     *
     * The rule is stated over the ORIGIN rather than over a vendor name, so it holds for every
     * provider and cannot be evaded by renaming one.
     */
    if (
      candidate.information_origin.code === "PROVIDER_DERIVED" &&
      candidate.information_profile === "PUBLIC_PIT"
    ) {
      ctx.addIssue({
        code: "custom",
        message: "provider-derived information never renders as PUBLIC_PIT",
      });
    }
    /*
     * AN UNESTABLISHED ORIGIN CANNOT CARRY THE STRONGEST PROFILE EITHER.
     *
     * `PUBLIC_PIT` is a claim about what was publicly knowable at a time. An origin nobody
     * established supports no such claim.
     */
    if (
      candidate.information_origin.code === "ORIGIN_NOT_ESTABLISHED" &&
      candidate.information_profile === "PUBLIC_PIT"
    ) {
      ctx.addIssue({
        code: "custom",
        message: "an unestablished information origin does not support a PUBLIC_PIT profile",
      });
    }
    const present = numberOf(candidate.coverage.present);
    const requested = numberOf(candidate.coverage.requested);
    if (present !== null && requested !== null) {
      if (present > requested) {
        ctx.addIssue({
          code: "custom",
          message: "coverage cannot present more of an extent than was requested",
        });
      }
      /*
       * A PARTIAL SUBJECT NAMES ITS GAP.
       *
       * "Coverage must name its population and extent; partial records must not appear
       * complete." A shortfall with no named gap renders as a number a reader has to notice.
       */
      if (present < requested && candidate.missingness.length === 0) {
        ctx.addIssue({
          code: "custom",
          message: "a subject covering less than its requested extent names the gap",
        });
      }
      if (present === requested && candidate.missingness.length > 0) {
        ctx.addIssue({
          code: "custom",
          message: "a fully covered subject names no gap",
        });
      }
    }
  });
export type DataQuality = z.infer<typeof dataQuality>;

export const dataQualityPayload = collectionPayload(dataQuality, {
  /** The three accepted profiles, rendered as a legend so none is invented on a screen. */
  information_profiles: z.array(informationProfile),
  /** The window this page's coverage and freshness were evaluated over. */
  window: z.object({
    from: instant,
    to: instant,
    calendar: reasonCoded,
    timezone: z.literal("UTC"),
  }),
  /** What real feeds exist. In this application: none, and the page says so. */
  real_feed_state: z.object({
    availability: availabilityState,
    reason: fieldReasonCode,
    note: reasonCoded,
  }),
});
export type DataQualityPayload = z.infer<typeof dataQualityPayload>;

export const DATA_QUALITY_SCHEMA = "cockpit.data_quality.v1";
export const dataQualityEnvelope = envelope(dataQualityPayload, DATA_QUALITY_SCHEMA);

/* ======================================================== Area 23 — SystemJob (§4.5) === */

/** What a recorded run concluded. */
export const JOB_RUN_OUTCOMES = [
  "SUCCEEDED",
  "FAILED",
  "PARTIALLY_COMPLETED",
  "NOT_RUN",
] as const;

/**
 * The job's CURRENT state — a different question from how its last run ended.
 *
 * `OPERATING_NORMALLY` is the only member that claims present health, and the refinement below
 * refuses it without a present observation to rest on. **A last success is not current
 * health**, and no member of this vocabulary can be derived from `last_run`.
 */
export const JOB_STATES = [
  "OPERATING_NORMALLY",
  "DEGRADED",
  "FAILING",
  "NOT_OBSERVED",
  "NEVER_OBSERVED",
] as const;

/**
 * Whether the SUBSYSTEM this row names exists at all.
 *
 * **A synthetic row naming a service is not evidence that the service exists.** Every row in
 * this application declares `NO_RUNTIME_SERVICE_EXISTS`, and the vocabulary exists so the
 * claim is a field a reader can see rather than a caveat in a paragraph.
 */
export const SERVICE_EXISTENCE = [
  "NO_RUNTIME_SERVICE_EXISTS",
  "RUNTIME_SERVICE_RECORDED",
] as const;

export const systemJob = z
  .object({
    job_id: safeId,
    kind: reasonCoded,
    /** Which part of the deterministic core this job would belong to. */
    subsystem_role: reasonCoded,
    service_existence: reasonCoded,
    last_run: z.object({ at: instant, outcome: reasonCoded }),
    /** §4.5: "last success carries its as-of time". It is an INSTANT, and never a boolean. */
    last_success: metricOf("job.last_success_at"),
    duration: metricOf("job.duration"),
    queue_depth: metricOf("job.queue_depth"),
    next_scheduled: metricOf("job.next_scheduled_at"),
    /** ADDITIVE: the current state, which `last_run` does not determine. */
    current_state: reasonCoded,
    /**
     * ADDITIVE: the PRESENT observation a claim of present health has to rest on.
     *
     * Absent for every job here, because nothing observes a running service — which is exactly
     * why no row may claim `OPERATING_NORMALLY`.
     */
    current_observation: metricOf("job.latency"),
    availability: metricOf("job.availability"),
    restarts: metricOf("job.restarts"),
    evidence_refs: refListFieldOf("SystemJob.evidence_refs"),
    incident_refs: refListFieldOf("SystemJob.incident_refs"),
  })
  .superRefine((candidate, ctx) => {
    requireMember(candidate.last_run.outcome.code, JOB_RUN_OUTCOMES, "last run outcome", ctx);
    requireMember(candidate.current_state.code, JOB_STATES, "current state", ctx);
    requireMember(candidate.service_existence.code, SERVICE_EXISTENCE, "service existence", ctx);
    /*
     * A CLAIM OF PRESENT HEALTH NEEDS A PRESENT OBSERVATION.
     *
     * This is the whole of "separate last successful run from current status", written as a
     * rule rather than as a layout convention: without a current observation the honest states
     * are `NOT_OBSERVED` and `NEVER_OBSERVED`, and a screen cannot promote a historical
     * success into a health claim.
     */
    if (
      candidate.current_state.code === "OPERATING_NORMALLY" &&
      !isValueBearing(candidate.current_observation.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a job claiming present health carries a present observation",
      });
    }
    /*
     * A SERVICE THAT DOES NOT EXIST HAS NOT BEEN OBSERVED RUNNING.
     */
    if (
      candidate.service_existence.code === "NO_RUNTIME_SERVICE_EXISTS" &&
      isValueBearing(candidate.current_observation.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a job with no runtime service carries no present observation of one",
      });
    }
    /*
     * A LAST SUCCESS IS DATED WHEN IT HAPPENED, AND NEVER AFTER THE RUN THAT FOLLOWED IT.
     */
    const success = instantValueMs(candidate.last_success);
    const lastRun = parseInstantMs(candidate.last_run.at);
    if (success !== null && lastRun !== null && success > lastRun) {
      ctx.addIssue({
        code: "custom",
        message: "a last success is not dated after the last recorded run",
      });
    }
    /*
     * A JOB THAT HAS NEVER SUCCEEDED CARRIES NO SUCCESS TIME.
     */
    if (
      candidate.current_state.code === "NEVER_OBSERVED" &&
      isValueBearing(candidate.last_success.availability)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "a never-observed job records no successful run",
      });
    }
  });
export type SystemJob = z.infer<typeof systemJob>;

export const systemJobPayload = collectionPayload(systemJob, {
  /** The closed control surface this screen does NOT have, named so the absence is visible. */
  absent_controls: z.array(reasonCoded),
  scheduler_state: z.object({
    availability: availabilityState,
    reason: fieldReasonCode,
    note: reasonCoded,
  }),
});
export type SystemJobPayload = z.infer<typeof systemJobPayload>;

export const SYSTEM_JOB_SCHEMA = "cockpit.system_job.v1";
export const systemJobEnvelope = envelope(systemJobPayload, SYSTEM_JOB_SCHEMA);

/* =================================================== Area 23 — SystemIncident (§4.5) === */

export const INCIDENT_STATES = ["OPEN", "MITIGATED", "CLOSED"] as const;
export const INCIDENT_SEVERITIES = ["HIGH", "MEDIUM", "LOW"] as const;

/** One entry on an incident's recorded timeline. */
export const incidentTimelineEntry = z.object({
  at: instant,
  event: reasonCoded,
  /** What the entry establishes, and never what it implies. */
  detail: reasonCoded,
});

export const systemIncident = z
  .object({
    incident_id: safeId,
    opened_at: instant,
    /** ABSENT while the incident is open — an open incident has no close time to carry. */
    closed_at: metricOf("incident.closed_at"),
    open_duration: metricOf("incident.open_duration"),
    severity: reasonCoded,
    subject: reasonCoded,
    state: reasonCoded,
    timeline: z.array(incidentTimelineEntry),
    evidence_refs: refListFieldOf("SystemIncident.evidence_refs"),
    alert_refs: refListFieldOf("SystemIncident.alert_refs"),
  })
  .superRefine((candidate, ctx) => {
    requireMember(candidate.state.code, INCIDENT_STATES, "incident state", ctx);
    requireMember(candidate.severity.code, INCIDENT_SEVERITIES, "incident severity", ctx);
    const closed = candidate.state.code === "CLOSED";
    const hasClose = isValueBearing(candidate.closed_at.availability);
    if (closed && !hasClose) {
      ctx.addIssue({ code: "custom", message: "a closed incident records when it closed" });
    }
    if (!closed && hasClose) {
      ctx.addIssue({
        code: "custom",
        message: "an incident that is not closed records no close time",
      });
    }
    const closedMs = instantValueMs(candidate.closed_at);
    const openedMs = parseInstantMs(candidate.opened_at);
    if (closedMs !== null && openedMs !== null && closedMs < openedMs) {
      ctx.addIssue({ code: "custom", message: "an incident does not close before it opened" });
    }
    /*
     * A TIMELINE STARTS AT THE OPENING, AND NO ENTRY PRECEDES IT.
     */
    for (const entry of candidate.timeline) {
      const at = parseInstantMs(entry.at);
      if (at !== null && openedMs !== null && at < openedMs) {
        ctx.addIssue({
          code: "custom",
          message: "an incident timeline carries no entry before the incident opened",
        });
        return;
      }
    }
  });
export type SystemIncident = z.infer<typeof systemIncident>;

export const systemIncidentPayload = collectionPayload(systemIncident, {
  incident_states: z.array(reasonCoded),
  /**
   * The open count, as its own measurement.
   *
   * §4.5: it is `EMPTY_VERIFIED` when the producer ran and found none, and `NOT_IMPLEMENTED`
   * when it did not run at all — never a zero standing in for either.
   */
  open_count: metricOf("operations.open_incidents"),
});
export type SystemIncidentPayload = z.infer<typeof systemIncidentPayload>;

export const SYSTEM_INCIDENT_SCHEMA = "cockpit.system_incident.v1";
export const systemIncidentEnvelope = envelope(systemIncidentPayload, SYSTEM_INCIDENT_SCHEMA);

/* ============================================================ Area 27 — Alert (§4.5) === */

/**
 * The accepted severity vocabulary, in RANK ORDER.
 *
 * "Do not infer severity by comparing arbitrary strings." Order comes from this declared list
 * and from nowhere else; the payload carries it so a screen sorts by a stated rank rather than
 * by whatever `localeCompare` happens to do to three words.
 */
export const ALERT_SEVERITIES = ["HIGH", "MEDIUM", "LOW"] as const;
export const alertSeverity = z.enum(ALERT_SEVERITIES);
export type AlertSeverity = z.infer<typeof alertSeverity>;

/** The rank a severity sorts at. Lower is more severe, and the mapping is declared. */
export const SEVERITY_RANK: Readonly<Record<AlertSeverity, number>> = {
  HIGH: 0,
  MEDIUM: 1,
  LOW: 2,
};

export const ALERT_STATES = ["OPEN", "RESOLVED"] as const;

export const alert = z
  .object({
    alert_id: safeId,
    condition: reasonCoded,
    severity: reasonCoded,
    /** §4.5 identity. ONE condition produces ONE alert, and this is what says which. */
    dedup_key: safeId,
    first_seen: instant,
    last_seen: instant,
    occurrence_count: metricOf("alert.occurrence_count"),
    state: z.enum(ALERT_STATES),
    /** ABSENT while open. A resolved alert records when it resolved. */
    resolved_at: metricOf("alert.resolved_at"),
    /** How many duplicate observations this one row folded, so nothing vanishes silently. */
    deduplicated_away: metricOf("alert.deduplicated_away"),
    impact: metricValue,
    evidence_refs: refListFieldOf("Alert.evidence_refs"),
    incident_refs: refListFieldOf("Alert.incident_refs"),
  })
  .superRefine((candidate, ctx) => {
    requireMember(candidate.severity.code, ALERT_SEVERITIES, "alert severity", ctx);
    /*
     * THE ALERT RECORD AND THE CONDITION IT IS ABOUT ARE TWO IDENTITIES.
     *
     * §4.5 gives this read model `dedup_key` as its IDENTITY — one condition, one alert — and
     * `alert_id` names the row that carries it. The executive attention projection is a
     * SEPARATE record over the SAME condition identity, which is what lets the two views
     * reconcile without either becoming the other. Collapsing the two identifiers here would
     * make that reconciliation unstateable.
     */
    if (candidate.alert_id === candidate.dedup_key) {
      ctx.addIssue({
        code: "custom",
        message: "an alert record is identified separately from the condition it is about",
      });
    }
    const first = parseInstantMs(candidate.first_seen);
    const last = parseInstantMs(candidate.last_seen);
    if (first !== null && last !== null && last < first) {
      ctx.addIssue({ code: "custom", message: "an alert is not last seen before it was first seen" });
    }
    /*
     * A RECORDED ALERT OCCURRED AT LEAST ONCE.
     *
     * A zero occurrence count on a row that exists is a contradiction: the row IS the record
     * of an occurrence.
     */
    const occurrences = numberOf(candidate.occurrence_count);
    if (occurrences !== null && occurrences < 1) {
      ctx.addIssue({
        code: "custom",
        message: "a recorded alert occurred at least once",
      });
    }
    /*
     * FOLDED DUPLICATES ARE FEWER THAN THE OCCURRENCES THEY WERE FOLDED INTO.
     */
    const folded = numberOf(candidate.deduplicated_away);
    if (occurrences !== null && folded !== null && folded >= occurrences) {
      ctx.addIssue({
        code: "custom",
        message: "more rows were folded away than occurrences were recorded",
      });
    }
    const resolved = candidate.state === "RESOLVED";
    const hasResolution = isValueBearing(candidate.resolved_at.availability);
    if (resolved && !hasResolution) {
      ctx.addIssue({ code: "custom", message: "a resolved alert records when it resolved" });
    }
    if (!resolved && hasResolution) {
      ctx.addIssue({ code: "custom", message: "an open alert records no resolution time" });
    }
    const resolvedMs = instantValueMs(candidate.resolved_at);
    if (resolvedMs !== null && last !== null && resolvedMs < last) {
      ctx.addIssue({
        code: "custom",
        message: "an alert does not resolve before it was last seen",
      });
    }
  });
export type Alert = z.infer<typeof alert>;

export const alertPayload = collectionPayload(alert, {
  /** The severity vocabulary, in declared rank order. A screen sorts by this, never by text. */
  severity_order: z.array(alertSeverity),
  /**
   * How many rows the deduplication folded away across the whole page.
   *
   * §8: a total that is hidden and unstated is how a reader misreads a subset as the whole.
   */
  folded_total: metricOf("alert.deduplicated_away"),
  /** The notification integrations that do not exist, named rather than merely absent. */
  absent_integrations: z.array(reasonCoded),
});
export type AlertPayload = z.infer<typeof alertPayload>;

/**
 * The collection rule §4.5 states as this read model's invariant.
 *
 * **"One condition produces one alert with an occurrence count."** Two rows sharing a
 * `dedup_key` is the outage this rule exists to prevent, and it is a property of the PAGE
 * rather than of any row — so it is enforced where the whole page is visible.
 */
export const alertCollection = alertPayload.superRefine((candidate, ctx) => {
  const conditions = new Set(candidate.items.map((row) => row.dedup_key));
  if (conditions.size !== candidate.items.length) {
    ctx.addIssue({
      code: "custom",
      message: "one condition produces one alert, and this page carries a condition twice",
    });
  }
  const ids = new Set(candidate.items.map((row) => row.alert_id));
  if (ids.size !== candidate.items.length) {
    ctx.addIssue({ code: "custom", message: "an alert page carries each alert record once" });
  }
  /*
   * THE FOLDED TOTAL IS THE SUM OF WHAT THE ROWS FOLDED.
   *
   * A page-level count that disagrees with its own rows tells a reader that something was
   * hidden without saying what, which is the opposite of what stating it is for.
   */
  let folded = 0;
  let measurable = true;
  for (const row of candidate.items) {
    const value = numberOf(row.deduplicated_away);
    if (value === null) {
      measurable = false;
      break;
    }
    folded += value;
  }
  const total = numberOf(candidate.folded_total);
  if (measurable && total !== null && total !== folded) {
    ctx.addIssue({
      code: "custom",
      message: "the folded total states the sum of what the delivered rows folded away",
    });
  }
});

export const ALERT_SCHEMA = "cockpit.alert.v1";
export const alertEnvelope = envelope(alertCollection, ALERT_SCHEMA);
