/**
 * Regressions for four defects found by independent review of the C3 foundation.
 *
 * Each block names the defect it locks out, and each fails against the behaviour that was
 * there before the correction. They exercise the REAL admission path -- the read client and
 * the published schemas -- rather than an isolated helper, because a payload that a helper
 * would refuse still reaches a screen if the boundary it actually passes through does not.
 */
import { ATTENTION_LIST_SCHEMA } from "@/contracts/read-models";
import { describe, expect, it } from "vitest";

import { effectiveComposite, freshUntil, isExpired } from "@/contracts/freshness";
import type { FreshnessInput, FreshnessReport } from "@/contracts/freshness";
import { available, emptyRefList, pinsOf } from "@/contracts/factories";
import {
  attentionListEnvelope,
  executiveOverviewEnvelope,
  qualificationStatusEnvelope,
} from "@/contracts/read-models";
import { METRIC_DEFINITION_VERSION, metricValue } from "@/contracts/values";
import { admit, ContractViolationError } from "@/data/client/read-client";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { buildFreshness } from "@/data/fixtures/envelopes";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

const ORIGIN = Date.parse("2026-09-05T12:00:00.000Z");
const AS_OF = "2026-09-05T12:00:00.000Z";

const seconds = (value: number, metricId: string) =>
  available({ metricId, unit: "SECONDS", value, asOf: AS_OF });

function reportOf(
  inputs: readonly FreshnessInput[],
  composite: FreshnessReport["composite_state"],
): FreshnessReport {
  return {
    inputs: [...inputs],
    oldest_required: inputs[0]?.input_id,
    source_age: seconds(0, "freshness.source_age"),
    projection_lag: seconds(0, "freshness.projection_lag"),
    build_age: seconds(0, "freshness.build_age"),
    composite_state: composite,
    evaluation_time: AS_OF,
  };
}

function input(over: Partial<FreshnessInput> = {}): FreshnessInput {
  return {
    input_id: "governance.tracked_snapshot",
    required: true,
    source_effective_time: "2026-09-05T11:59:00.000Z",
    source_age: seconds(60, "freshness.source_age"),
    contract_max_age: 600,
    state: "AVAILABLE",
    reason: "NONE",
    ...over,
  };
}

/* ------------------------------------------------------------------ FINDING A */

describe("finding A -- an age is measured from its own instants", () => {
  const specs = [
    { id: "positions.mark", required: true, ageAtOriginSeconds: 45, contractMaxAgeSeconds: 100_000 },
    {
      id: "governance.tracked_snapshot",
      required: true,
      ageAtOriginSeconds: 3_600,
      contractMaxAgeSeconds: 100_000,
    },
  ];

  /**
   * THE DEFECT: `projection_lag` reconstructed a source time as `origin - oldestAge`, where
   * `oldestAge` had been measured at EVALUATION time. With `projected_time == origin` that
   * reduces to `evaluation - source_effective` -- so the lag became a second copy of the
   * source age and GREW ON EVERY REFETCH, while the source fact and the build were both
   * unchanged. A lag between two fixed instants cannot change.
   */
  it("holds projection_lag still while only the evaluation time moves", () => {
    const early = buildFreshness(specs, ORIGIN, ORIGIN + 10_000, ORIGIN);
    const late = buildFreshness(specs, ORIGIN, ORIGIN + 600_000, ORIGIN);

    // The two ages that MUST advance, because evaluation time is one of their endpoints.
    expect(late.source_age.value as number).toBeGreaterThan(early.source_age.value as number);
    expect(late.build_age.value as number).toBeGreaterThan(early.build_age.value as number);

    // The one that must NOT: both of its endpoints are unchanged.
    expect(late.projection_lag.value).toBe(early.projection_lag.value);
    // projected_time == origin, and the NEWEST required input is 45s older than it (12.3).
    expect(early.projection_lag.value).toBe(45);
  });

  it("does not restamp an unchanged fact, and keeps its deadline where it was", () => {
    const early = buildFreshness(specs, ORIGIN, ORIGIN + 10_000, ORIGIN);
    const late = buildFreshness(specs, ORIGIN, ORIGIN + 600_000, ORIGIN);
    for (let index = 0; index < specs.length; index += 1) {
      expect(late.inputs[index].source_effective_time).toBe(
        early.inputs[index].source_effective_time,
      );
    }
    // fresh_until is absolute: a refetch spends the budget and never refills it.
    expect(freshUntil(late)).toBe(freshUntil(early));
  });

  it("reports the OLDEST required input's age, not the binding deadline's input", () => {
    // The mark is 45s old on a short contract and BINDS; the snapshot is an hour old and is
    // what section 3.1 REPORTS. Substituting one for the other is CASE 5 read backwards.
    const report = buildFreshness(
      [
        { id: "positions.mark", required: true, ageAtOriginSeconds: 45, contractMaxAgeSeconds: 60 },
        {
          id: "governance.tracked_snapshot",
          required: true,
          ageAtOriginSeconds: 3_600,
          contractMaxAgeSeconds: 100_000,
        },
      ],
      ORIGIN,
      ORIGIN,
      ORIGIN,
    );
    expect(report.oldest_required).toBe("governance.tracked_snapshot");
    expect(report.source_age.value).toBe(3_600);
  });

  it("refuses a fixture dated after its evaluation time rather than clamping it to zero", () => {
    expect(() =>
      buildFreshness(
        [{ id: "positions.mark", required: true, ageAtOriginSeconds: -600, contractMaxAgeSeconds: 60 }],
        ORIGIN,
        ORIGIN,
        ORIGIN,
      ),
    ).toThrow(RangeError);
  });
});

/* ------------------------------------------------------------------ FINDING B */

describe("finding B -- freshness refuses contradictory and unreal input", () => {
  /**
   * THE DEFECT: the instant regex validated SPELLING. `Date.parse` then either returned
   * `NaN` -- making `serve_time >= fresh_until` false forever, so the entry never expired --
   * or SILENTLY ROLLED THE DATE OVER, computing a real deadline from a day that does not
   * exist.
   */
  it("refuses an instant that is spelled correctly but names no real day", () => {
    for (const unreal of [
      "2026-02-30T00:00:00.000Z", // silently rolls over to 2026-03-02
      "2026-02-29T00:00:00.000Z", // 2026 is not a leap year
      "2026-13-01T00:00:00.000Z", // NaN
      "2026-01-32T00:00:00.000Z", // NaN
      "2026-01-01T25:00:00.000Z", // NaN
    ]) {
      const parsed = metricValue.safeParse({
        value: 1,
        unit: "SECONDS",
        availability: "AVAILABLE",
        reason: "NONE",
        as_of: unreal,
        metric_id: "freshness.source_age",
        metric_definition_version: METRIC_DEFINITION_VERSION,
      });
      expect(parsed.success, `${unreal} must be refused`).toBe(false);
    }
  });

  it("never treats an unestablishable deadline as fresh", () => {
    const report = reportOf([input({ source_effective_time: undefined, state: "NOT_YET_AVAILABLE", reason: "SOURCE_TIMESTAMP_MISSING" })], "NOT_YET_AVAILABLE");
    expect(freshUntil(report)).toBeNull();
    expect(isExpired(report, ORIGIN)).toBe(true);
  });

  /** THE DEFECT: a missing source time was reported as an invented STALE value. */
  it("reports a missing source time with ITS state and ITS reason, never as stale", () => {
    const report = reportOf(
      [
        input({
          source_effective_time: undefined,
          state: "NOT_YET_AVAILABLE",
          reason: "SOURCE_TIMESTAMP_MISSING",
        }),
      ],
      "NOT_YET_AVAILABLE",
    );
    const effective = effectiveComposite(report, ORIGIN);
    expect(effective.state).toBe("NOT_YET_AVAILABLE");
    expect(effective.reason).toBe("SOURCE_TIMESTAMP_MISSING");
  });

  /** THE DEFECT: a composite claiming AVAILABLE upgraded a failing required input. */
  it("never lets a claimed AVAILABLE composite upgrade a failing required input", () => {
    // Its deadline is still in the future, so expiry alone would not have caught this.
    const stale = input({ state: "STALE", reason: "UPSTREAM_INPUT_STALE", contract_max_age: 100_000 });
    expect(effectiveComposite(reportOf([stale], "STALE"), ORIGIN).state).toBe("STALE");

    // And the contradiction itself is refused at the boundary rather than resolved.
    const contradictory = reportOf([stale], "AVAILABLE");
    expect(effectiveComposite(contradictory, ORIGIN).state).not.toBe("AVAILABLE");
    expect(envelopeWith(contradictory)).toThrow(ContractViolationError);
  });

  it("refuses an unhealthy required input that is not declared as one", () => {
    // No source time, but claimed AVAILABLE: section 3.1 fixes exactly one state for this.
    const lying = input({ source_effective_time: undefined, state: "AVAILABLE", reason: "NONE" });
    expect(envelopeWith(reportOf([lying], "AVAILABLE"))).toThrow(ContractViolationError);
  });

  it("refuses a source time dated after the evaluation time beyond tolerance", () => {
    const skewed = input({ source_effective_time: "2026-09-05T13:00:00.000Z" });
    expect(envelopeWith(reportOf([skewed], "AVAILABLE"))).toThrow(ContractViolationError);
  });

  it("refuses a report with no required input at all", () => {
    const optionalOnly = input({ required: false });
    expect(envelopeWith(reportOf([optionalOnly], "AVAILABLE"))).toThrow(ContractViolationError);
  });

  it("expires AT the deadline, and an optional input never sets it", () => {
    const report = reportOf(
      [input({ contract_max_age: 60 }), input({ input_id: "optional.feed", required: false, contract_max_age: 1 })],
      "AVAILABLE",
    );
    const deadline = freshUntil(report);
    expect(deadline).toBe(Date.parse("2026-09-05T12:00:00.000Z"));
    expect(isExpired(report, (deadline as number) - 1)).toBe(false);
    expect(isExpired(report, deadline as number)).toBe(true);
    expect(effectiveComposite(report, deadline as number).state).toBe("STALE");
  });
});

/** Drives a freshness report through the REAL envelope admission path. */
function envelopeWith(freshness: FreshnessReport): () => unknown {
  const candidate = {
    schema_version: ATTENTION_LIST_SCHEMA,
    api_version: "v1",
    entity_id: "attention-list",
    correlation_id: "attention-list-v1",
    source_refs: emptyRefList(AS_OF),
    event_time: AS_OF,
    observed_time: AS_OF,
    as_of_time: AS_OF,
    projected_time: AS_OF,
    environment: "RESEARCH",
    maturity_stage: "RESEARCH",
    provenance: "SYNTHETIC",
    availability: "AVAILABLE",
    availability_reason: "NONE",
    freshness,
    coverage: { present: 1, requested: 1 },
    completeness: "COMPLETE",
    snapshot_version: "fixture",
    classification: "PUBLIC_SAFE",
    access_scope: "executive:read",
    metric_definition_version: METRIC_DEFINITION_VERSION,
    watermark: AS_OF,
    pins: pinsOf(),
    payload: { items: [] },
  };
  return () => admit("AttentionItem", attentionListEnvelope, candidate, "PUBLIC_EDGE");
}

/* ------------------------------------------------------------------ FINDING C */

describe("finding C -- a metric payload is validated to its actual type", () => {
  const metric = (over: Record<string, unknown>) => ({
    value: "0.00",
    unit: "USD",
    availability: "AVAILABLE",
    reason: "NONE",
    as_of: AS_OF,
    metric_id: "portfolio.cash",
    metric_definition_version: METRIC_DEFINITION_VERSION,
    ...over,
  });

  /**
   * THE DEFECT: `MetricValue.value` was `unknown`, and only its PRESENCE was checked -- so
   * `null`, an object, a boolean and `NaN` all reached a formatter on an AVAILABLE reading.
   */
  it("refuses null, objects, booleans and non-finite numbers on a value-bearing state", () => {
    for (const value of [null, {}, { amount: "1.00" }, [], true, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(metricValue.safeParse(metric({ value })).success).toBe(false);
    }
  });

  it("refuses a malformed decimal, a wrong precision and a wrong unit", () => {
    expect(metricValue.safeParse(metric({ value: "1,000.00" })).success).toBe(false);
    expect(metricValue.safeParse(metric({ value: "62450" })).success).toBe(false);
    expect(metricValue.safeParse(metric({ value: 62_450 })).success).toBe(false);
    expect(metricValue.safeParse(metric({ unit: "PERCENT" })).success).toBe(false);
  });

  it("refuses an unregistered metric id and any dictionary version but the current one", () => {
    expect(metricValue.safeParse(metric({ metric_id: "risk.drawdown" })).success).toBe(false);
    /*
     * BOTH DIRECTIONS, because ADR-0032 advanced the dictionary to `metrics.v2`. The retired
     * version and a future one are each refused rather than coerced, which is the original
     * property this case guards -- it is checked here against a version that is genuinely not
     * the current one rather than against whichever string happened to be next.
     */
    for (const version of ["metrics.v1", "metrics.v3", "metrics.v0", "metrics"]) {
      expect(
        metricValue.safeParse(metric({ metric_definition_version: version })).success,
        version,
      ).toBe(false);
    }
    expect(
      metricValue.safeParse(metric({ metric_definition_version: METRIC_DEFINITION_VERSION }))
        .success,
    ).toBe(true);
  });

  it("keeps a measured zero, and keeps a stale value with its qualification", () => {
    expect(metricValue.safeParse(metric({ value: "0.00" })).success).toBe(true);
    expect(
      metricValue.safeParse(
        metric({ value: "-318.40", availability: "STALE", reason: "UPSTREAM_INPUT_STALE" }),
      ).success,
    ).toBe(true);
    // An absence still carries no value at all.
    expect(
      metricValue.safeParse({
        unit: "USD",
        availability: "NOT_IMPLEMENTED",
        reason: "PRODUCER_NOT_IMPLEMENTED",
        metric_id: "portfolio.cash",
        metric_definition_version: METRIC_DEFINITION_VERSION,
      }).success,
    ).toBe(true);
  });

  it("refuses a malformed payload through the real read-client admission path", () => {
    const client = new FixtureReadClient({ clock: fixedClock(ORIGIN), originMs: ORIGIN });
    return client
      .executiveOverview({ ...DEFAULT_SCOPE, scenario: "demo" })
      .then((good) => {
        const corrupted = {
          ...good,
          payload: { ...good.payload, cash: { ...good.payload?.cash, value: null } },
        };
        expect(() =>
          admit("ExecutiveOverview", executiveOverviewEnvelope, corrupted, "PUBLIC_EDGE"),
        ).toThrow(ContractViolationError);
      });
  });

  it("carries a date gate as a real date, and never as a count of days", async () => {
    const client = new FixtureReadClient({ clock: fixedClock(ORIGIN), originMs: ORIGIN });
    const status = await client.qualificationStatus(DEFAULT_SCOPE);
    const runB = status.payload?.run_authorizations.find(
      (entry) => entry.run.code === "RUN_B",
    );
    expect(runB?.date_gate.value).toBe("2026-09-12");
    // CALENDAR_DAYS is a DURATION unit, and 2026-09-12 is not a number of days.
    expect(runB?.date_gate.unit).not.toBe("CALENDAR_DAYS");
    // Authorization and date eligibility stay two separate facts, and neither authorizes.
    expect(runB?.authorization.code).toBe("NOT_AUTHORIZED");
  });
});

/* ------------------------------------------------------------------ FINDING D */

describe("finding D -- environment, maturity and provenance", () => {
  const client = () => new FixtureReadClient({ clock: fixedClock(ORIGIN), originMs: ORIGIN });

  /**
   * THE DEFECT: `scope.environment` was applied to reused fixtures while `maturity_stage`
   * stayed hard-coded `RESEARCH`, so selecting Paper or Live re-badged THE SAME RECORDS --
   * including the real tracked governance facts -- as Paper or Live evidence.
   */
  it("shows no facts at all under an unpopulated environment", async () => {
    for (const environment of ["PAPER", "LIVE"] as const) {
      const reads = await Promise.all([
        client().qualificationStatus({ ...DEFAULT_SCOPE, environment }),
        client().executiveOverview({ ...DEFAULT_SCOPE, environment, scenario: "demo" }),
        client().attention({ ...DEFAULT_SCOPE, environment, scenario: "demo" }),
        client().whatChanged({ ...DEFAULT_SCOPE, environment, scenario: "demo" }),
      ]);
      for (const envelope of reads) {
        expect(envelope.payload).toBeUndefined();
        expect(envelope.availability).toBe("NOT_IMPLEMENTED");
        expect(envelope.availability_reason).toBe("PRODUCER_NOT_IMPLEMENTED");
        // No maturity stage is claimed for a stage nothing has reached.
        expect(envelope.maturity_stage).toBeUndefined();
      }
    }
  });

  it("only ever carries facts under the environment that produced them", async () => {
    for (const environment of ["RESEARCH", "PAPER", "LIVE"] as const) {
      for (const scenario of ["project", "demo"] as const) {
        const envelope = await client().qualificationStatus({
          ...DEFAULT_SCOPE,
          environment,
          scenario,
        });
        if (envelope.payload !== undefined) {
          expect(envelope.environment).toBe("RESEARCH");
          expect(envelope.maturity_stage).toBe("RESEARCH");
        }
      }
    }
  });

  it("refuses a maturity stage the accepted mapping does not pair with the environment", async () => {
    const good = await client().qualificationStatus(DEFAULT_SCOPE);
    // AUTOMATED_PAPER is produced in PAPER, and MICRO_LIVE in LIVE -- never in RESEARCH.
    for (const maturity of ["AUTOMATED_PAPER", "MICRO_LIVE", "SCALED_LIVE"] as const) {
      expect(() =>
        admit(
          "QualificationStatus",
          qualificationStatusEnvelope,
          { ...good, maturity_stage: maturity },
          "PUBLIC_EDGE",
        ),
      ).toThrow(ContractViolationError);
    }
  });

  it("keeps real tracked facts REPOSITORY_TRACKED in the demo scenario too", async () => {
    for (const scenario of ["project", "demo"] as const) {
      const status = await client().qualificationStatus({ ...DEFAULT_SCOPE, scenario });
      expect(status.provenance).toBe("REPOSITORY_TRACKED");
      // And fixture output is never promoted to a tracked fact by the project selector.
      const overview = await client().executiveOverview({ ...DEFAULT_SCOPE, scenario });
      expect(overview.provenance).toBe("SYNTHETIC");
    }
  });
});
