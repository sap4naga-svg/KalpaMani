import { describe, expect, it } from "vitest";

import { auditEventEnvelope } from "@/contracts/audit-models";
import {
  executionQualityEnvelope,
  reconciliationEnvelope,
} from "@/contracts/execution-quality-page";
import {
  ALERT_SEVERITIES,
  SEVERITY_RANK,
  alertEnvelope,
  dataQualityEnvelope,
  systemIncidentEnvelope,
  systemJobEnvelope,
  type AlertSeverity,
} from "@/contracts/operations-models";
import { REFERENCE_FIELDS } from "@/contracts/references";
import { C3_METRIC_DICTIONARY } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";
import { INFORMATION_PROFILES } from "@/contracts/vocabularies";
import { readModelKey } from "@/data/client/query-keys";
import {
  ALERT_IDENTITY,
  AUDIT_EVENT_IDENTITY,
  DATA_QUALITY_IDENTITY,
  EXECUTION_QUALITY_IDENTITY,
  RECONCILIATION_IDENTITY,
  SYSTEM_INCIDENT_IDENTITY,
  SYSTEM_JOB_IDENTITY,
} from "@/data/client/read-model-identity";
import { ContractViolationError, admit } from "@/data/client/read-client";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { MULTI_EXIT_TRADE } from "@/data/fixtures/book";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE, type ViewScope } from "@/lib/scope";

/**
 * The seven C8 read models, exercised through the SAME boundary a screen uses.
 *
 * Every assertion is about a property the accepted contracts state, and the negative controls
 * at the end mutate a CONFORMANT payload and assert that admission REFUSES it — so a rule that
 * quietly stopped being enforced is visible here rather than silently absent.
 *
 * Nothing here reads `Date.now()`, opens a socket or touches a file at request time.
 */

const ORIGIN_MS = Date.parse("2026-09-08T12:00:00.000Z");
const DEMO: ViewScope = { ...DEFAULT_SCOPE, scenario: "demo" };
const PROJECT: ViewScope = { ...DEFAULT_SCOPE, scenario: "project" };
const PAPER: ViewScope = { ...DEFAULT_SCOPE, scenario: "demo", environment: "PAPER" };
const LIVE: ViewScope = { ...DEFAULT_SCOPE, scenario: "demo", environment: "LIVE" };

function client(): FixtureReadClient {
  return new FixtureReadClient({ clock: fixedClock(ORIGIN_MS), originMs: ORIGIN_MS });
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** Every C8 read, as one call, so a scope assertion can be made over all seven at once. */
async function readAll(scope: ViewScope) {
  const read = client();
  return {
    execution: await read.executionQuality(scope),
    reconciliation: await read.reconciliation(scope),
    dataQuality: await read.dataQuality(scope),
    jobs: await read.systemJobs(scope),
    incidents: await read.systemIncidents(scope),
    alerts: await read.alerts(scope),
    audit: await read.auditEvents(scope),
  };
}

/* ================================================== scope, provenance and availability */

describe("every C8 read model is honest about what it is showing", () => {
  it("serves all seven in the demonstration scenario, labelled SYNTHETIC", async () => {
    const responses = Object.values(await readAll(DEMO));
    expect(responses).toHaveLength(7);
    for (const response of responses) {
      expect(response.payload).toBeDefined();
      expect(response.provenance).toBe("SYNTHETIC");
      expect(response.classification).toBe("PUBLIC_SAFE");
      expect(response.environment).toBe("RESEARCH");
    }
  });

  it("reports all seven PAYLOADLESS in project scope, with the producer named", async () => {
    for (const response of Object.values(await readAll(PROJECT))) {
      expect(response.payload).toBeUndefined();
      expect(response.availability).toBe("NOT_IMPLEMENTED");
      expect(response.availability_reason).toBe("PRODUCER_NOT_IMPLEMENTED");
      /* A payloadless absence pins nothing, and has consumed nothing to a watermark. */
      expect(response.pins).toBeUndefined();
      expect(response.watermark).toBeUndefined();
    }
  });

  it("shows an absence rather than the same record under a Paper or Live badge", async () => {
    for (const scope of [PAPER, LIVE]) {
      for (const response of Object.values(await readAll(scope))) {
        expect(response.payload, scope.environment).toBeUndefined();
        expect(response.availability, scope.environment).toBe("NOT_IMPLEMENTED");
        expect(response.environment, scope.environment).toBe(scope.environment);
        /*
         * NOTHING HAS REACHED `AUTOMATED_PAPER`, so an unpopulated environment states NO
         * maturity stage at all rather than claiming one it never reached.
         */
        expect(response.maturity_stage, scope.environment).toBeUndefined();
      }
    }
  });

  it("keys each read model separately, and never shares a cache entry across scopes", () => {
    const identities = [
      EXECUTION_QUALITY_IDENTITY,
      RECONCILIATION_IDENTITY,
      DATA_QUALITY_IDENTITY,
      SYSTEM_JOB_IDENTITY,
      SYSTEM_INCIDENT_IDENTITY,
      ALERT_IDENTITY,
      AUDIT_EVENT_IDENTITY,
    ];
    const keys = identities.map((identity) => readModelKey(identity, DEMO).join("|"));
    expect(new Set(keys).size).toBe(identities.length);
    for (const identity of identities) {
      const research = readModelKey(identity, DEMO).join("|");
      const paper = readModelKey(identity, PAPER).join("|");
      const project = readModelKey(identity, PROJECT).join("|");
      expect(research, identity.readModel).not.toBe(paper);
      expect(research, identity.readModel).not.toBe(project);
      /* Provenance and access scope travel in the key, from the read model's own identity. */
      expect(research).toContain(identity.provenance);
      expect(research).toContain(identity.accessScope);
    }
    /* The audit projection is the one read model under `audit:read`, and it keys separately. */
    expect(AUDIT_EVENT_IDENTITY.accessScope).toBe("audit:read");
    expect(EXECUTION_QUALITY_IDENTITY.accessScope).toBe("execution:read");
    expect(DATA_QUALITY_IDENTITY.accessScope).toBe("system:read");
  });

  it("registers every metric it renders in the closed dictionary", async () => {
    const payloads = await readAll(DEMO);
    const seen = new Set<string>();
    const walk = (value: unknown): void => {
      if (Array.isArray(value)) {
        for (const entry of value) {
          walk(entry);
        }
        return;
      }
      if (value === null || typeof value !== "object") {
        return;
      }
      const record = value as Record<string, unknown>;
      if (typeof record.metric_id === "string" && typeof record.unit === "string") {
        seen.add(record.metric_id);
      }
      for (const entry of Object.values(record)) {
        walk(entry);
      }
    };
    walk(payloads);
    expect(seen.size).toBeGreaterThan(20);
    for (const metricId of seen) {
      expect(C3_METRIC_DICTIONARY[metricId], metricId).toBeDefined();
    }
  });
});

/* ====================================================== Area 9 — slippage and latency */

describe("execution quality states its whole definition", () => {
  it("carries a named reference price, its instant and the side convention on every row", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    expect(page.items.length).toBeGreaterThan(0);
    for (const row of page.items) {
      const reference = row.quality.reference_price;
      expect(reference.name.code.length).toBeGreaterThan(0);
      expect(Number.isFinite(Date.parse(reference.at)), row.record_id).toBe(true);
      expect(reference.side_convention.code.length).toBeGreaterThan(0);
      /* A slippage that carries a value carries it in signed basis points. */
      if (isValueBearing(row.quality.slippage.availability)) {
        expect(row.quality.slippage.unit, row.record_id).toBe("BPS");
        expect(row.quality.slippage.metric_id, row.record_id).toBe("slippage");
      }
    }
  });

  it("reports the aggregate as INSUFFICIENT_OBSERVATIONS below its declared minimum", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    const observed = page.aggregate_population.observed.value as number;
    const minimum = page.aggregate_population.minimum.value as number;
    expect(minimum).toBe(20);
    expect(observed).toBeLessThan(minimum);
    expect(page.aggregate.slippage.availability).toBe("INSUFFICIENT_OBSERVATIONS");
    expect(page.aggregate.slippage.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
    /* An absence carries NO value — never a zero standing in for a rule it did not meet. */
    expect(page.aggregate.slippage.value).toBeUndefined();
    expect(page.aggregate.slippage.metric_id).toBe("slippage.aggregate");
  });

  it("counts what it excluded from the aggregate, and names why", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    expect(page.aggregate_population.excluded.value).toBe(1);
    expect(page.aggregate_population.exclusion_reasons.length).toBeGreaterThan(0);
    /* The excluded observation is on the page, and its slippage is an absence, not a zero. */
    const unreferenced = page.items.find(
      (row) => row.quality.reference_price.name.code === "REFERENCE_PRICE_NOT_RECORDED",
    )!;
    expect(unreferenced).toBeDefined();
    expect(unreferenced.quality.slippage.availability).toBe("NOT_YET_AVAILABLE");
    expect(unreferenced.quality.slippage.reason).toBe("UPSTREAM_INPUT_MISSING");
    expect(unreferenced.quality.slippage.value).toBeUndefined();
  });

  it("states every latency in seconds, with its clock source and accuracy", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    for (const row of page.items) {
      expect(row.quality.signal_to_order_latency.unit, row.record_id).toBe("SECONDS");
      expect(row.quality.order_to_fill_latency.unit, row.record_id).toBe("SECONDS");
      expect(row.quality.clock_source.code.length).toBeGreaterThan(0);
      expect(row.quality.clock_accuracy.unit).toBe("SECONDS");
    }
    expect(page.aggregate.clock_accuracy.unit).toBe("SECONDS");
  });

  it("reports a modelled and a recorded cost separately, and never a combined one", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    for (const row of page.items) {
      expect(row.modelled_cost.metric_id, row.record_id).toBe("execution.modelled_cost");
      expect(row.recorded_cost.metric_id, row.record_id).toBe("execution.recorded_cost");
      expect(row.cost_treatment.code.length).toBeGreaterThan(0);
      /* There is no field on this contract in which the two could be combined. */
      expect(Object.keys(row)).not.toContain("net_cost");
      expect(Object.keys(row)).not.toContain("total_cost");
    }
  });

  it("never claims working protection without a recorded confirmation", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    const confirmed = page.items.filter(
      (row) => row.protective_order_state.code === "CONFIRMED_WORKING",
    );
    expect(confirmed.length).toBeGreaterThan(0);
    for (const row of confirmed) {
      expect(isValueBearing(row.protection_confirmed_at.availability), row.record_id).toBe(
        true,
      );
    }
    const submitted = page.items.filter(
      (row) => row.protective_order_state.code === "SUBMITTED_NOT_CONFIRMED",
    );
    for (const row of submitted) {
      expect(isValueBearing(row.protection_confirmed_at.availability), row.record_id).toBe(
        false,
      );
    }
  });

  it("keeps the lifecycle vocabulary free of any exit member", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    const states = new Set(page.items.map((row) => row.lifecycle_state));
    for (const state of states) {
      expect(state).not.toMatch(/EXIT|CLOSE|LIQUIDAT/);
    }
    /* And a cancelled order reports what it filled, without becoming a position event. */
    const cancelled = page.items.find((row) => row.lifecycle_state === "CANCELLED")!;
    expect(cancelled).toBeDefined();
    expect(cancelled.filled_quantity.value).toBeLessThan(
      cancelled.ordered_quantity.value as number,
    );
  });

  it("names its illustrative rows, and computes the aggregate without them", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    expect(page.illustrative_record_ids.length).toBe(3);
    const delivered = new Set(page.items.map((row) => row.record_id));
    for (const id of page.illustrative_record_ids) {
      expect(delivered.has(id), id).toBe(true);
    }
    /*
     * THE AGGREGATE POPULATION IS THE RECORDED FILLS, AND NOT THE ROWS ON THE PAGE.
     *
     * An illustrative row could otherwise move a headline, which is precisely what naming
     * them exists to prevent.
     */
    const observed = page.aggregate_population.observed.value as number;
    expect(observed).toBe(page.items.length - page.illustrative_record_ids.length);
  });

  it("reports an unmeasured outcome as UNEVALUATED rather than as zero", async () => {
    const page = (await client().executionQuality(DEMO)).payload!;
    const missed = page.outcomes.find((entry) => entry.outcome.code === "MISSED_FILLS")!;
    expect(missed.count.availability).toBe("UNEVALUATED");
    expect(missed.count.reason).toBe("NOT_YET_ASSESSED");
    expect(missed.count.value).toBeUndefined();
    /* And a measured zero stays a measured zero beside it. */
    const duplicates = page.outcomes.find(
      (entry) => entry.outcome.code === "DUPLICATES_SUPPRESSED",
    )!;
    expect(duplicates.count.availability).toBe("AVAILABLE");
    expect(typeof duplicates.count.value).toBe("number");
  });
});

/* ============================================ Area 10 — mismatch, missing and stale */

describe("reconciliation reports comparisons, not health", () => {
  it("names the latest run and reports present health separately from it", async () => {
    const page = (await client().reconciliation(DEMO)).payload!;
    const latest = page.items.find((run) => run.run_id === page.latest_run_id)!;
    expect(latest).toBeDefined();
    /* The newest recorded run found a mismatch... */
    expect(latest.result.code).toBe("MISMATCH_RECORDED");
    /* ...and present health is a SEPARATE statement, with its own availability. */
    expect(page.current_health.availability).toBe("NOT_IMPLEMENTED");
    expect(page.current_health.reason).toBe("PRODUCER_NOT_IMPLEMENTED");
    /* An older run reconciled cleanly, and that success is not promoted to the present. */
    const clean = page.items.find((run) => run.result.code === "RECONCILED")!;
    expect(clean).toBeDefined();
    expect(Date.parse(clean.as_of)).toBeLessThan(Date.parse(latest.as_of));
    expect(isValueBearing(clean.age.availability)).toBe(true);
  });

  it("reports a mismatch with what disagreed", async () => {
    const page = (await client().reconciliation(DEMO)).payload!;
    const mismatch = page.items.find((run) => run.result.code === "MISMATCH_RECORDED")!;
    expect(mismatch.position_diffs.length).toBeGreaterThan(0);
    expect(mismatch.order_diffs.length).toBeGreaterThan(0);
    expect(mismatch.ownership_findings.length).toBeGreaterThan(0);
    expect(mismatch.orphans.value).toBe(1);
    for (const diff of mismatch.position_diffs) {
      expect(diff.expected.unit).toBe("SHARES");
      expect(diff.observed.unit).toBe("SHARES");
      expect(diff.difference.unit).toBe("SHARES");
    }
  });

  it("treats a missing comparison input as neither zero nor a match", async () => {
    const page = (await client().reconciliation(DEMO)).payload!;
    const missing = page.items.find(
      (run) => run.result.code === "COMPARISON_INPUT_MISSING",
    )!;
    expect(missing.missing_inputs.length).toBeGreaterThan(0);
    /* The count it could not compute is ABSENT — never a zero standing in for agreement. */
    expect(isValueBearing(missing.orphans.availability)).toBe(false);
    expect(missing.orphans.value).toBeUndefined();
    expect(missing.result.code).not.toBe("RECONCILED");
    /* And the broker side it could not read is stated as unrecorded, not as aligned. */
    expect(isValueBearing(missing.broker_as_of.availability)).toBe(false);
    expect(missing.as_of_alignment.code).toBe("BROKER_AS_OF_NOT_RECORDED");
  });

  it("states the alignment of the two as-of times it compared across", async () => {
    const page = (await client().reconciliation(DEMO)).payload!;
    for (const run of page.items) {
      if (!isValueBearing(run.broker_as_of.availability)) {
        expect(run.as_of_alignment.code, run.run_id).toBe("BROKER_AS_OF_NOT_RECORDED");
        continue;
      }
      const aligned =
        Date.parse(run.broker_as_of.value as string) === Date.parse(run.internal_as_of);
      expect(run.as_of_alignment.code, run.run_id).toBe(
        aligned ? "AS_OF_TIMES_ALIGNED" : "AS_OF_TIMES_DIFFER",
      );
    }
  });

  it("labels broker-reported equity informational, and never as sizing authority", async () => {
    const page = (await client().reconciliation(DEMO)).payload!;
    const equity = page.items
      .flatMap((run) => run.balances)
      .find((entry) => entry.measure.code === "BROKER_REPORTED_EQUITY")!;
    expect(equity).toBeDefined();
    expect(equity.informational_only).toBe(true);
    /* The two figures are carried separately and differ, which is the point of showing them. */
    expect(equity.internal.value).not.toBe(equity.broker_reported.value);
    expect(equity.internal.value).toBe("80000.00");
  });

  it("offers no connect, refresh or repair value anywhere in the payload", async () => {
    const page = (await client().reconciliation(DEMO)).payload!;
    const named = page.absent_controls.map((control) => control.code);
    for (const control of [
      "CONNECT",
      "RECONNECT",
      "AUTHENTICATE",
      "REFRESH_FROM_BROKER",
      "REPAIR",
    ]) {
      expect(named, control).toContain(control);
    }
    expect(page.broker_session.availability).toBe("NOT_IMPLEMENTED");
  });
});

/* ==================================================== Area 22 — the PIT vocabulary */

describe("data quality declares a profile and never infers one", () => {
  it("renders the three accepted profiles and no fourth", async () => {
    const page = (await client().dataQuality(DEMO)).payload!;
    expect(page.information_profiles).toEqual([...INFORMATION_PROFILES]);
    for (const subject of page.items) {
      expect(INFORMATION_PROFILES as readonly string[]).toContain(
        subject.information_profile,
      );
      expect(subject.profile_basis.code, subject.subject_id).toMatch(/^DECLARED_BY_/);
    }
  });

  it("never pairs provider-derived information with PUBLIC_PIT", async () => {
    const page = (await client().dataQuality(DEMO)).payload!;
    const providerDerived = page.items.filter(
      (subject) => subject.information_origin.code === "PROVIDER_DERIVED",
    );
    expect(providerDerived.length).toBeGreaterThan(0);
    for (const subject of providerDerived) {
      expect(subject.information_profile, subject.subject_id).not.toBe("PUBLIC_PIT");
    }
    /* And the one PUBLIC_PIT subject is publicly observed, not provider-derived. */
    const publicPit = page.items.filter(
      (subject) => subject.information_profile === "PUBLIC_PIT",
    );
    expect(publicPit.length).toBeGreaterThan(0);
    for (const subject of publicPit) {
      expect(subject.information_origin.code, subject.subject_id).toBe(
        "PUBLIC_SOURCE_OBSERVED",
      );
    }
  });

  it("keeps profile, provenance and classification as three separate axes", async () => {
    const page = (await client().dataQuality(DEMO)).payload!;
    for (const subject of page.items) {
      expect(subject.provenance).toBe("SYNTHETIC");
      expect(subject.classification).toBe("PUBLIC_SAFE");
      /* A profile is never spelled in a provenance's vocabulary, or the other way round. */
      expect(subject.information_profile as string).not.toBe(subject.provenance as string);
      expect(subject.information_profile as string).not.toBe(
        subject.classification as string,
      );
    }
  });

  it("names the gap wherever a subject covers less than its requested extent", async () => {
    const page = (await client().dataQuality(DEMO)).payload!;
    let partial = 0;
    for (const subject of page.items) {
      const present = subject.coverage.present.value as number;
      const requested = subject.coverage.requested.value as number;
      expect(present, subject.subject_id).toBeLessThanOrEqual(requested);
      if (present < requested) {
        partial += 1;
        expect(subject.missingness.length, subject.subject_id).toBeGreaterThan(0);
        expect(subject.coverage.extent.code.length).toBeGreaterThan(0);
      } else {
        expect(subject.missingness, subject.subject_id).toHaveLength(0);
      }
    }
    expect(partial).toBeGreaterThan(0);
  });

  it("reports source age and projection lag separately, per subject", async () => {
    const page = (await client().dataQuality(DEMO)).payload!;
    for (const subject of page.items) {
      expect(subject.freshness.source_age.metric_id).toBe("freshness.source_age");
      expect(subject.freshness.projection_lag.metric_id).toBe("freshness.projection_lag");
      expect(subject.freshness.build_age.metric_id).toBe("freshness.build_age");
      expect(subject.freshness.inputs.length).toBeGreaterThan(0);
    }
    /* One subject is deliberately past its own contract, and its composite says so. */
    const stale = page.items.find(
      (subject) => subject.freshness.composite_state === "STALE",
    );
    expect(stale).toBeDefined();
  });

  it("distinguishes a measured zero revision from an unmeasurable one", async () => {
    const page = (await client().dataQuality(DEMO)).payload!;
    const observations = page.items.flatMap((subject) => subject.revision_view);
    const measuredZero = observations.find(
      (entry) => entry.revision_kind.code === "NO_REVISION_OBSERVED",
    )!;
    expect(measuredZero.affected_rows.availability).toBe("AVAILABLE");
    expect(measuredZero.affected_rows.value).toBe(0);
    const unmeasurable = observations.find(
      (entry) => entry.revision_kind.code === "REVISION_NOT_MEASURABLE",
    )!;
    expect(isValueBearing(unmeasurable.affected_rows.availability)).toBe(false);
    expect(unmeasurable.affected_rows.value).toBeUndefined();
  });

  it("states that no real feed exists, and claims no provider qualification", async () => {
    const page = (await client().dataQuality(DEMO)).payload!;
    expect(page.real_feed_state.availability).toBe("NOT_IMPLEMENTED");
    const serialized = JSON.stringify(page);
    for (const claim of ["QUALIFIED", "PROVIDER_SELECTED", "P1_PASSED", "APPROVED"]) {
      expect(serialized, claim).not.toContain(claim);
    }
  });
});

/* ======================================= Area 23 — last success against current health */

describe("system operations separates a last success from present health", () => {
  it("carries the last success with its own instant, on a separate field", async () => {
    const page = (await client().systemJobs(DEMO)).payload!;
    const succeeded = page.items.filter((job) =>
      isValueBearing(job.last_success.availability),
    );
    expect(succeeded.length).toBeGreaterThan(0);
    for (const job of succeeded) {
      expect(job.last_success.metric_id, job.job_id).toBe("job.last_success_at");
      expect(Number.isFinite(Date.parse(job.last_success.value as string))).toBe(true);
      /* The historical fact does not determine the present state. */
      expect(job.current_state.code, job.job_id).not.toBe("OPERATING_NORMALLY");
    }
  });

  it("claims present health nowhere, because no row carries a present observation", async () => {
    const page = (await client().systemJobs(DEMO)).payload!;
    for (const job of page.items) {
      expect(job.service_existence.code, job.job_id).toBe("NO_RUNTIME_SERVICE_EXISTS");
      expect(isValueBearing(job.current_observation.availability), job.job_id).toBe(false);
      expect(job.current_state.code, job.job_id).not.toBe("OPERATING_NORMALLY");
    }
    /* A job whose last run SUCCEEDED still reports a current state of NOT_OBSERVED. */
    const succeeded = page.items.find((job) => job.last_run.outcome.code === "SUCCEEDED")!;
    expect(succeeded.current_state.code).toBe("NOT_OBSERVED");
  });

  it("records a never-observed job with no success time at all", async () => {
    const page = (await client().systemJobs(DEMO)).payload!;
    const never = page.items.filter((job) => job.current_state.code === "NEVER_OBSERVED");
    expect(never.length).toBeGreaterThan(0);
    for (const job of never) {
      expect(isValueBearing(job.last_success.availability), job.job_id).toBe(false);
    }
  });

  it("names every control it does not have", async () => {
    const page = (await client().systemJobs(DEMO)).payload!;
    const named = page.absent_controls.map((control) => control.code);
    for (const control of ["START", "STOP", "RETRY", "TRIGGER", "RESTART", "SCHEDULE"]) {
      expect(named, control).toContain(control);
    }
  });

  it("gives an open incident no close time and a closed one exactly when", async () => {
    const page = (await client().systemIncidents(DEMO)).payload!;
    const open = page.items.filter((incident) => incident.state.code !== "CLOSED");
    const closed = page.items.filter((incident) => incident.state.code === "CLOSED");
    expect(open.length).toBeGreaterThan(0);
    expect(closed.length).toBeGreaterThan(0);
    for (const incident of open) {
      expect(isValueBearing(incident.closed_at.availability), incident.incident_id).toBe(
        false,
      );
    }
    for (const incident of closed) {
      expect(isValueBearing(incident.closed_at.availability), incident.incident_id).toBe(
        true,
      );
      expect(Date.parse(incident.closed_at.value as string)).toBeGreaterThan(
        Date.parse(incident.opened_at),
      );
    }
    /* The open count is a MEASURED count over the delivered population. */
    expect(page.open_count.availability).toBe("AVAILABLE");
    expect(page.open_count.value).toBe(open.length);
  });
});

/* ============================================ Area 26 — projection, correction, tombstone */

describe("the audit projection is not the events it projects", () => {
  it("identifies the projection separately from every event", async () => {
    const page = (await client().auditEvents(DEMO)).payload!;
    const eventIds = new Set(page.items.map((event) => event.event_id));
    expect(eventIds.has(page.projection.projection_id)).toBe(false);
    expect(isValueBearing(page.projection.rebuild_count.availability)).toBe(true);
    expect(page.projection.source_stream_state.availability).toBe("NOT_IMPLEMENTED");
  });

  it("appends a correction and leaves the corrected event on the timeline", async () => {
    const page = (await client().auditEvents(DEMO)).payload!;
    const correction = page.items.find(
      (event) => event.event_kind.code === "CORRECTION_APPENDED",
    )!;
    expect(correction.supersedes).toBeDefined();
    expect(correction.tombstone_of).toBeUndefined();
    const corrected = page.items.find(
      (event) => event.event_id === correction.supersedes!.ref_id,
    )!;
    /* The corrected event is STILL HERE, and its own kind is unchanged. */
    expect(corrected).toBeDefined();
    expect(corrected.event_kind.code).not.toBe("CORRECTION_APPENDED");
    /* The correction happened AFTER what it corrects — it appended, it did not replace. */
    expect(Date.parse(correction.event_time)).toBeGreaterThan(
      Date.parse(corrected.event_time),
    );
  });

  it("records a deletion as a tombstone naming its authority", async () => {
    const page = (await client().auditEvents(DEMO)).payload!;
    const tombstone = page.items.find(
      (event) => event.event_kind.code === "RECORD_TOMBSTONED",
    )!;
    expect(tombstone.tombstone_of).toBeDefined();
    expect(tombstone.supersedes).toBeUndefined();
    expect(tombstone.deletion_authority).toBeDefined();
    /* The withdrawn record stays addressable: its own event is still on the timeline. */
    const withdrawn = page.items.find(
      (event) => event.event_id === tombstone.tombstone_of!.ref_id,
    )!;
    expect(withdrawn).toBeDefined();
    /* And only a tombstone carries a deletion authority. */
    for (const event of page.items) {
      if (event.event_kind.code !== "RECORD_TOMBSTONED") {
        expect(event.deletion_authority, event.event_id).toBeUndefined();
      }
    }
  });

  it("carries a digest of its own record, and no licensed payload", async () => {
    const page = (await client().auditEvents(DEMO)).payload!;
    for (const event of page.items) {
      expect(event.record_digest, event.event_id).toMatch(
        /^kalpamani-record-[0-9a-f]{16}$/,
      );
      /* Subjects arrive as classified REFERENCES, never as payload copies. */
      for (const reference of event.subject_refs.items) {
        expect(reference.ref_kind).toBe("source_fact");
        expect(reference.classification).toBe("PUBLIC_SAFE");
        expect(Object.keys(reference)).not.toContain("payload");
      }
    }
  });

  it("states a gap rather than inferring an event over it", async () => {
    const page = (await client().auditEvents(DEMO)).payload!;
    expect(page.gaps.length).toBeGreaterThan(0);
    for (const gap of page.gaps) {
      expect(Date.parse(gap.to)).toBeGreaterThan(Date.parse(gap.from));
      expect(gap.reason).toBe("UPSTREAM_INPUT_MISSING");
      /* No event this page carries sits inside a stated gap. */
      for (const event of page.items) {
        const at = Date.parse(event.event_time);
        expect(at >= Date.parse(gap.from) && at < Date.parse(gap.to), event.event_id).toBe(
          false,
        );
      }
    }
  });

  it("retains the observed time separately, so a late arrival sits where it happened", async () => {
    const page = (await client().auditEvents(DEMO)).payload!;
    const late = page.items.find(
      (event) => Date.parse(event.observed_time) > Date.parse(event.event_time),
    )!;
    expect(late).toBeDefined();
    for (const event of page.items) {
      expect(
        Date.parse(event.observed_time) >= Date.parse(event.event_time),
        event.event_id,
      ).toBe(true);
    }
  });
});

/* ==================================================== Area 27 — one condition, one alert */

describe("alerts deduplicate deterministically", () => {
  it("carries each condition exactly once, with an occurrence count", async () => {
    const page = (await client().alerts(DEMO)).payload!;
    const conditions = page.items.map((row) => row.dedup_key);
    expect(new Set(conditions).size).toBe(conditions.length);
    for (const row of page.items) {
      expect(row.occurrence_count.value as number, row.dedup_key).toBeGreaterThanOrEqual(1);
      /* The record's own identity is not the condition's. */
      expect(row.alert_id, row.dedup_key).not.toBe(row.dedup_key);
    }
  });

  it("states how many duplicates it folded, at the row and at the page", async () => {
    const page = (await client().alerts(DEMO)).payload!;
    const folded = page.items.reduce(
      (total, row) => total + (row.deduplicated_away.value as number),
      0,
    );
    expect(page.folded_total.value).toBe(folded);
    expect(folded).toBeGreaterThan(0);
    /* A folded count never exceeds the occurrences it was folded into. */
    for (const row of page.items) {
      expect(row.deduplicated_away.value as number, row.dedup_key).toBeLessThan(
        row.occurrence_count.value as number,
      );
    }
  });

  it("orders severity by the declared rank rather than by comparing text", async () => {
    const page = (await client().alerts(DEMO)).payload!;
    expect(page.severity_order).toEqual([...ALERT_SEVERITIES]);
    /*
     * The declared order is NOT the order the three words sort in, which is the whole reason
     * a rank map exists: alphabetically `HIGH` < `LOW` < `MEDIUM`.
     */
    const alphabetical = [...ALERT_SEVERITIES].toSorted((left, right) =>
      left.localeCompare(right),
    );
    expect(page.severity_order).not.toEqual(alphabetical);
    for (const row of page.items) {
      expect(
        SEVERITY_RANK[row.severity.code as AlertSeverity],
        row.dedup_key,
      ).toBeGreaterThanOrEqual(0);
    }
  });

  it("gives an open alert no resolution time and a resolved one exactly when", async () => {
    const page = (await client().alerts(DEMO)).payload!;
    const open = page.items.filter((row) => row.state === "OPEN");
    const resolved = page.items.filter((row) => row.state === "RESOLVED");
    expect(open.length).toBeGreaterThan(0);
    expect(resolved.length).toBeGreaterThan(0);
    for (const row of open) {
      expect(isValueBearing(row.resolved_at.availability), row.dedup_key).toBe(false);
    }
    for (const row of resolved) {
      expect(isValueBearing(row.resolved_at.availability), row.dedup_key).toBe(true);
      expect(Date.parse(row.resolved_at.value as string)).toBeGreaterThanOrEqual(
        Date.parse(row.last_seen),
      );
    }
  });

  it("names the notification integrations that do not exist", async () => {
    const page = (await client().alerts(DEMO)).payload!;
    const named = page.absent_integrations.map((entry) => entry.code);
    for (const integration of ["EMAIL", "SMS", "PUSH", "CHAT_WEBHOOK", "PAGING"]) {
      expect(named, integration).toContain(integration);
    }
  });

  it("distinguishes a measured zero impact from an unmeasured one", async () => {
    const page = (await client().alerts(DEMO)).payload!;
    const measured = page.items.find(
      (row) => row.impact.availability === "AVAILABLE" && row.impact.value === "0.00",
    )!;
    expect(measured).toBeDefined();
    const unmeasured = page.items.find(
      (row) => row.impact.availability === "NOT_APPLICABLE",
    )!;
    expect(unmeasured).toBeDefined();
    expect(unmeasured.impact.value).toBeUndefined();
  });
});

/* ================================================== cross-screen identity and references */

describe("the C8 screens reconcile against the records they came from", () => {
  it("reuses the executive attention list's own condition identities", async () => {
    const read = client();
    const attention = (await read.attention(DEMO)).payload!;
    const alerts = (await read.alerts(DEMO)).payload!;
    const conditions = new Set(alerts.items.map((row) => row.dedup_key));
    const attentionKeys = new Set(attention.items.map((item) => item.dedup_key));
    expect(attentionKeys.size).toBeGreaterThan(0);
    for (const key of attentionKeys) {
      expect(conditions.has(key), key).toBe(true);
    }
    /*
     * THE TWO VIEWS ARE SEPARATE RECORDS OVER ONE CONDITION.
     *
     * No alert record identity equals an attention item identity, and the occurrence counts
     * over a shared condition agree — which is what makes the two reconcilable rather than
     * two counts of the same thing.
     */
    const attentionIds = new Set(attention.items.map((item) => item.item_id));
    for (const row of alerts.items) {
      expect(attentionIds.has(row.alert_id), row.alert_id).toBe(false);
    }
    const markStaleness = alerts.items.find(
      (row) => row.dedup_key === "demo-dedup-mark-staleness",
    )!;
    const attentionItem = attention.items.find(
      (item) => item.item_id === "demo-attention-2",
    )!;
    expect(attentionItem.dedup_key).toBe(markStaleness.dedup_key);
    expect(markStaleness.occurrence_count.value).toBe(attentionItem.occurrence_count.value);
  });

  it("binds the trade detail's reconciliation references to actual recorded runs", async () => {
    const read = client();
    const detail = (await read.tradeDetail(DEMO, MULTI_EXIT_TRADE)).payload!;
    const runs = (await read.reconciliation(DEMO)).payload!;
    const known = new Set(runs.items.map((run) => run.run_id));
    expect(detail.reconciliation_refs.items.length).toBeGreaterThan(0);
    for (const reference of detail.reconciliation_refs.items) {
      expect(reference.ref_kind).toBe("reconciliation");
      expect(reference.resolution).toBe("ENDPOINT");
      expect(known.has(reference.ref_id), reference.ref_id).toBe(true);
    }
  });

  it("binds the trade detail's audit references to actual recorded events", async () => {
    const read = client();
    const detail = (await read.tradeDetail(DEMO, MULTI_EXIT_TRADE)).payload!;
    const audit = (await read.auditEvents(DEMO)).payload!;
    const known = new Set(audit.items.map((event) => event.event_id));
    expect(detail.audit_refs.items.length).toBeGreaterThan(0);
    for (const reference of detail.audit_refs.items) {
      expect(reference.ref_kind).toBe("audit_event");
      expect(known.has(reference.ref_id), reference.ref_id).toBe(true);
    }
  });

  it("binds the data-quality subject to the incident and the alert it raised", async () => {
    const read = client();
    const quality = (await read.dataQuality(DEMO)).payload!;
    const incidents = (await read.systemIncidents(DEMO)).payload!;
    const alerts = (await read.alerts(DEMO)).payload!;
    const incidentIds = new Set(incidents.items.map((incident) => incident.incident_id));
    const alertIds = new Set(alerts.items.map((row) => row.alert_id));
    const marks = quality.items.find(
      (subject) => subject.subject_id === "us-equity-daily-marks",
    )!;
    expect(marks.incident_refs.items.length).toBeGreaterThan(0);
    for (const reference of marks.incident_refs.items) {
      expect(incidentIds.has(reference.ref_id), reference.ref_id).toBe(true);
    }
    expect(marks.alert_refs.items.length).toBeGreaterThan(0);
    for (const reference of marks.alert_refs.items) {
      expect(alertIds.has(reference.ref_id), reference.ref_id).toBe(true);
    }
    /* And the job behind the condition names the same incident. */
    const jobs = (await read.systemJobs(DEMO)).payload!;
    const refresh = jobs.items.find((job) => job.job_id === "demo-job-mark-refresh")!;
    expect(refresh.incident_refs.items.length).toBeGreaterThan(0);
    for (const reference of refresh.incident_refs.items) {
      expect(incidentIds.has(reference.ref_id), reference.ref_id).toBe(true);
    }
  });

  it("declares an owning area only where the accepted table assigns one", async () => {
    const page = (await client().dataQuality(DEMO)).payload!;
    const areas = page.items
      .flatMap((subject) => [
        ...subject.incident_refs.items,
        ...subject.alert_refs.items,
        ...subject.lineage_refs.items,
      ])
      .map((reference) => reference.owning_area)
      .filter((area) => area !== undefined);
    expect(areas.length).toBeGreaterThan(0);
    for (const area of areas) {
      expect([
        "SYSTEM_OPERATIONS",
        "ALERTS",
        "AUDIT_TRAIL",
        "DATA_QUALITY",
        "RECONCILIATION",
      ]).toContain(area);
    }
    /* A strategy-version reference declares NO area: the table assigns none for that record. */
    const affected = page.items.flatMap((subject) => subject.affected_strategies);
    expect(affected.length).toBeGreaterThan(0);
    for (const entry of affected) {
      expect(entry.version_ref.owning_area).toBeUndefined();
    }
  });

  it("records every new reference field in the catalogue, with a kind", () => {
    for (const key of [
      "ExecutionQualityRecord.trade_ref",
      "ExecutionQualityRecord.order_ref",
      "ExecutionQualityRecord.protective_order_refs",
      "ReconciliationStatus.ownership_findings[].local_ref",
      "ReconciliationStatus.trade_refs",
      "DataQuality.alert_refs",
      "DataQuality.affected_strategies[].version_ref",
      "SystemJob.evidence_refs",
      "SystemJob.incident_refs",
      "SystemIncident.alert_refs",
      "Alert.incident_refs",
      "AuditEvent.related_refs",
    ] as (keyof typeof REFERENCE_FIELDS)[]) {
      const declaration = REFERENCE_FIELDS[key];
      expect(declaration, key).toBeDefined();
      expect(declaration.kinds.length, key).toBeGreaterThan(0);
      expect(declaration.implemented, key).toBe(true);
    }
  });
});

/* ========================================================= no mutation anywhere at all */

describe("nothing in the C8 surface can change anything", () => {
  it("exposes only reads on the client boundary", () => {
    const read = client();
    const methods = [
      "executionQuality",
      "reconciliation",
      "dataQuality",
      "systemJobs",
      "systemIncidents",
      "alerts",
      "auditEvents",
    ] as const;
    for (const method of methods) {
      expect(typeof read[method], method).toBe("function");
    }
    const surface = Object.getOwnPropertyNames(Object.getPrototypeOf(read));
    for (const forbidden of [
      "submitOrder",
      "cancelOrder",
      "runJob",
      "retryJob",
      "acknowledgeAlert",
      "resolveAlert",
      "appendAuditEvent",
      "reconnectBroker",
      "notify",
    ]) {
      expect(surface, forbidden).not.toContain(forbidden);
    }
  });

  it("carries no verb that would change state in any delivered payload", async () => {
    const serialized = JSON.stringify(await readAll(DEMO));
    for (const verb of [
      '"acknowledge"',
      '"resolve_alert"',
      '"submit_order"',
      '"cancel_order"',
      '"trigger_job"',
      '"send_notification"',
    ]) {
      expect(serialized, verb).not.toContain(verb);
    }
  });
});

/* =================================================================== negative controls */

describe("the boundary refuses a payload that breaks a stated rule", () => {
  it("refuses provider-derived information declared PUBLIC_PIT", async () => {
    const response = clone(await client().dataQuality(DEMO));
    const payload = response.payload as unknown as {
      items: { information_origin: { code: string }; information_profile: string }[];
    };
    const subject = payload.items.find(
      (entry) => entry.information_origin.code === "PROVIDER_DERIVED",
    )!;
    subject.information_profile = "PUBLIC_PIT";
    expect(() => admit("DataQuality", dataQualityEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses a partial subject that names no gap", async () => {
    const response = clone(await client().dataQuality(DEMO));
    const payload = response.payload as unknown as { items: { missingness: unknown[] }[] };
    const partial = payload.items.find((entry) => entry.missingness.length > 0)!;
    partial.missingness = [];
    expect(() => admit("DataQuality", dataQualityEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses a job claiming present health with no present observation", async () => {
    const response = clone(await client().systemJobs(DEMO));
    const payload = response.payload as unknown as {
      items: { current_state: { code: string } }[];
    };
    payload.items[0].current_state.code = "OPERATING_NORMALLY";
    expect(() => admit("SystemJob", systemJobEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses an open incident that records a close time", async () => {
    const response = clone(await client().systemIncidents(DEMO));
    const payload = response.payload as unknown as {
      items: {
        state: { code: string };
        closed_at: Record<string, unknown>;
        opened_at: string;
      }[];
    };
    const open = payload.items.find((entry) => entry.state.code !== "CLOSED")!;
    open.closed_at = {
      value: open.opened_at,
      unit: "DIMENSIONLESS",
      availability: "AVAILABLE",
      reason: "NONE",
      as_of: open.opened_at,
      metric_id: "incident.closed_at",
      metric_definition_version: "metrics.v1",
    };
    expect(() =>
      admit("SystemIncident", systemIncidentEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses two alert rows carrying one condition identity", async () => {
    const response = clone(await client().alerts(DEMO));
    const payload = response.payload as unknown as { items: { dedup_key: string }[] };
    payload.items[1].dedup_key = payload.items[0].dedup_key;
    expect(() => admit("Alert", alertEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses an alert record identified by its own condition", async () => {
    const response = clone(await client().alerts(DEMO));
    const payload = response.payload as unknown as {
      items: { alert_id: string; dedup_key: string }[];
    };
    payload.items[0].alert_id = payload.items[0].dedup_key;
    expect(() => admit("Alert", alertEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses a projection identified by one of its own events", async () => {
    const response = clone(await client().auditEvents(DEMO));
    const payload = response.payload as unknown as {
      items: { event_id: string }[];
      projection: { projection_id: string };
    };
    payload.projection.projection_id = payload.items[0].event_id;
    expect(() => admit("AuditEvent", auditEventEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses a tombstone with no deletion authority", async () => {
    const response = clone(await client().auditEvents(DEMO));
    const payload = response.payload as unknown as {
      items: { event_kind: { code: string }; deletion_authority?: unknown }[];
    };
    const tombstone = payload.items.find(
      (entry) => entry.event_kind.code === "RECORD_TOMBSTONED",
    )!;
    delete tombstone.deletion_authority;
    expect(() => admit("AuditEvent", auditEventEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses a record digest that is not KalpaMani's own", async () => {
    const response = clone(await client().auditEvents(DEMO));
    const payload = response.payload as unknown as { items: { record_digest: string }[] };
    payload.items[0].record_digest = "9f2c4b1a7e3d5068";
    expect(() => admit("AuditEvent", auditEventEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses a reconciled run that names a missing comparison input", async () => {
    const response = clone(await client().reconciliation(DEMO));
    const payload = response.payload as unknown as {
      items: { result: { code: string }; missing_inputs: unknown[] }[];
    };
    const clean = payload.items.find((entry) => entry.result.code === "RECONCILED")!;
    clean.missing_inputs = [
      {
        code: "BROKER_POSITION_SNAPSHOT_NOT_RECORDED",
        vocabulary: "kalpamani.demo",
        vocabulary_version: "v1",
      },
    ];
    expect(() =>
      admit("ReconciliationStatus", reconciliationEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses an as-of alignment that disagrees with the instants beside it", async () => {
    const response = clone(await client().reconciliation(DEMO));
    const payload = response.payload as unknown as {
      items: { as_of_alignment: { code: string }; broker_as_of: { availability: string } }[];
    };
    const compared = payload.items.find(
      (entry) => entry.broker_as_of.availability === "AVAILABLE",
    )!;
    compared.as_of_alignment.code =
      compared.as_of_alignment.code === "AS_OF_TIMES_ALIGNED"
        ? "AS_OF_TIMES_DIFFER"
        : "AS_OF_TIMES_ALIGNED";
    expect(() =>
      admit("ReconciliationStatus", reconciliationEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses a latest run that is not the newest run the page delivered", async () => {
    const response = clone(await client().reconciliation(DEMO));
    const payload = response.payload as unknown as {
      items: { run_id: string }[];
      latest_run_id: string;
    };
    payload.latest_run_id = payload.items[payload.items.length - 1].run_id;
    expect(() =>
      admit("ReconciliationStatus", reconciliationEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses a filled order that did not account for its ordered quantity", async () => {
    const response = clone(await client().executionQuality(DEMO));
    const payload = response.payload as unknown as {
      items: { lifecycle_state: string; filled_quantity: { value: number } }[];
    };
    const filled = payload.items.find((entry) => entry.lifecycle_state === "FILLED")!;
    filled.filled_quantity.value -= 1;
    expect(() =>
      admit("ExecutionQuality", executionQualityEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses confirmed protective cover with no recorded confirmation", async () => {
    const response = clone(await client().executionQuality(DEMO));
    const payload = response.payload as unknown as {
      items: {
        protective_order_state: { code: string };
        protection_confirmed_at: Record<string, unknown>;
      }[];
    };
    const confirmed = payload.items.find(
      (entry) => entry.protective_order_state.code === "CONFIRMED_WORKING",
    )!;
    confirmed.protection_confirmed_at = {
      unit: "DIMENSIONLESS",
      availability: "NOT_YET_AVAILABLE",
      reason: "UPSTREAM_INPUT_MISSING",
      metric_id: "execution.protection_confirmed_at",
      metric_definition_version: "metrics.v1",
    };
    expect(() =>
      admit("ExecutionQuality", executionQualityEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses an aggregate reporting a number below its declared minimum", async () => {
    const response = clone(await client().executionQuality(DEMO));
    const payload = response.payload as unknown as {
      aggregate: { slippage: Record<string, unknown> };
      window: { to: string };
    };
    payload.aggregate.slippage = {
      value: "3.50",
      unit: "BPS",
      availability: "AVAILABLE",
      reason: "NONE",
      as_of: payload.window.to,
      metric_id: "slippage.aggregate",
      metric_definition_version: "metrics.v1",
    };
    expect(() =>
      admit("ExecutionQuality", executionQualityEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses an illustrative identifier the page does not carry", async () => {
    const response = clone(await client().executionQuality(DEMO));
    const payload = response.payload as unknown as { illustrative_record_ids: string[] };
    payload.illustrative_record_ids = [...payload.illustrative_record_ids, "demo-not-a-row"];
    expect(() =>
      admit("ExecutionQuality", executionQualityEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("admits the unmutated payload, so each refusal above is about the mutation", async () => {
    const responses = await readAll(DEMO);
    expect(() =>
      admit(
        "ExecutionQuality",
        executionQualityEnvelope,
        clone(responses.execution),
        "PUBLIC_EDGE",
      ),
    ).not.toThrow();
    expect(() =>
      admit(
        "ReconciliationStatus",
        reconciliationEnvelope,
        clone(responses.reconciliation),
        "PUBLIC_EDGE",
      ),
    ).not.toThrow();
    expect(() =>
      admit("DataQuality", dataQualityEnvelope, clone(responses.dataQuality), "PUBLIC_EDGE"),
    ).not.toThrow();
    expect(() =>
      admit("SystemJob", systemJobEnvelope, clone(responses.jobs), "PUBLIC_EDGE"),
    ).not.toThrow();
    expect(() =>
      admit(
        "SystemIncident",
        systemIncidentEnvelope,
        clone(responses.incidents),
        "PUBLIC_EDGE",
      ),
    ).not.toThrow();
    expect(() =>
      admit("Alert", alertEnvelope, clone(responses.alerts), "PUBLIC_EDGE"),
    ).not.toThrow();
    expect(() =>
      admit("AuditEvent", auditEventEnvelope, clone(responses.audit), "PUBLIC_EDGE"),
    ).not.toThrow();
  });
});
