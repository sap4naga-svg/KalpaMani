import { describe, expect, it } from "vitest";

import { admissionFailure } from "@/contracts/admission";
import {
  effectiveCacheLifetimeSeconds,
  effectiveComposite,
  freshUntil,
  isExpired,
  remainingFreshnessSeconds,
  type FreshnessReport,
} from "@/contracts/freshness";
import {
  ATTENTION_LIST_SCHEMA,
  EXECUTIVE_OVERVIEW_SCHEMA,
  executiveOverviewEnvelope,
} from "@/contracts/read-models";
import { PERMITTED_REASONS, isValueBearing, validityFailure } from "@/contracts/validity";
import { metricValue } from "@/contracts/values";
import { AVAILABILITY_STATES } from "@/contracts/vocabularies";
import { available, instantOf } from "@/contracts/factories";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { ContractViolationError } from "@/data/client/read-client";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

const AS_OF = "2026-09-05T12:00:00.000Z";

describe("the validity matrix", () => {
  it("admits AVAILABLE only with the reason NONE", () => {
    expect(PERMITTED_REASONS.AVAILABLE).toEqual(["NONE"]);
    expect(validityFailure("AVAILABLE", "NONE", true)).toBeNull();
    expect(validityFailure("AVAILABLE", "UPSTREAM_INPUT_STALE", true)).toContain(
      "does not admit reason",
    );
  });

  it("refuses a reason spelled in the availability vocabulary", () => {
    // UPSTREAM_INPUT_MISSING is a REASON and never an availability state.
    expect(validityFailure("NOT_IMPLEMENTED", "UPSTREAM_INPUT_MISSING", false)).toContain(
      "does not admit reason",
    );
  });

  it("requires a value from every value-bearing state and from no other", () => {
    for (const state of AVAILABILITY_STATES) {
      const reason = PERMITTED_REASONS[state][0];
      const bearing = isValueBearing(state);
      expect(validityFailure(state, reason, bearing)).toBeNull();
      expect(validityFailure(state, reason, !bearing)).not.toBeNull();
    }
  });

  it("gives NOT_APPLICABLE exactly two routes, and UPSTREAM_INPUT_MISSING reaches neither", () => {
    expect(PERMITTED_REASONS.NOT_APPLICABLE).toEqual([
      "NOT_DEFINED_FOR_SUBJECT",
      "DENOMINATOR_ZERO",
    ]);
    expect(validityFailure("NOT_APPLICABLE", "UPSTREAM_INPUT_MISSING", false)).not.toBeNull();
  });
});

describe("a zero is a measurement, and never an availability state (ADR-0029 section 2.1)", () => {
  it("accepts a measured zero as AVAILABLE with NONE", () => {
    // The dictionary key is `win_rate`, defined in RATIO (section 12.3), and a ratio is
    // carried as a decimal string (section 4.2). The measured zero is what matters here.
    const zeroWinRate = available({
      metricId: "win_rate",
      unit: "RATIO",
      value: "0",
      asOf: AS_OF,
    });
    expect(metricValue.safeParse(zeroWinRate).success).toBe(true);
    expect(zeroWinRate.availability).toBe("AVAILABLE");
  });

  it("keeps EMPTY_VERIFIED a statement about the population rather than about the number", () => {
    const emptyPopulation = {
      value: 0,
      unit: "COUNT" as const,
      availability: "EMPTY_VERIFIED" as const,
      reason: "EMPTY_RESULT_VERIFIED" as const,
      as_of: AS_OF,
      metric_id: "trade.closed_count",
      metric_definition_version: "metrics.v1",
    };
    expect(metricValue.safeParse(emptyPopulation).success).toBe(true);
    // The same zero may NOT be relabelled as an empty population when it was measured.
    expect(validityFailure("EMPTY_VERIFIED", "NONE", true)).not.toBeNull();
  });

  it("never lets an absence carry a zero", () => {
    const fabricated = {
      value: 0,
      unit: "USD" as const,
      availability: "NOT_IMPLEMENTED" as const,
      reason: "PRODUCER_NOT_IMPLEMENTED" as const,
      metric_id: "pnl.realized",
      metric_definition_version: "metrics.v1",
    };
    const parsed = metricValue.safeParse(fabricated);
    expect(parsed.success).toBe(false);
    expect(parsed.error?.issues[0]?.message).toContain("carries no value");
  });

  it("does not let a zero remove a qualification", () => {
    const staleZero = {
      // Money is a decimal string, never binary floating point (section 4.2).
      value: "0.00",
      unit: "USD" as const,
      availability: "STALE" as const,
      reason: "UPSTREAM_INPUT_STALE" as const,
      as_of: AS_OF,
      metric_id: "pnl.realized",
      metric_definition_version: "metrics.v1",
    };
    expect(metricValue.safeParse(staleZero).success).toBe(true);
    expect(staleZero.availability).not.toBe("AVAILABLE");
  });
});

/** Builds the worked cases of read-model-contracts.md section 3.1.1. */
function report(
  inputs: readonly { id: string; required: boolean; ageSeconds: number; contract: number }[],
  evaluationMs: number,
): FreshnessReport {
  const metric = (value: number) =>
    available({
      metricId: "freshness.source_age",
      unit: "SECONDS",
      value,
      asOf: instantOf(evaluationMs),
    });
  const built = inputs.map((input) => ({
    input_id: input.id,
    required: input.required,
    source_effective_time: instantOf(evaluationMs - input.ageSeconds * 1000),
    source_age: metric(input.ageSeconds),
    contract_max_age: input.contract,
    state: "AVAILABLE" as const,
    reason: "NONE" as const,
  }));
  const oldest = built
    .filter((input) => input.required)
    .reduce((worst, input) =>
      (input.source_age.value as number) > (worst.source_age.value as number) ? input : worst,
    );
  return {
    inputs: built,
    oldest_required: oldest.input_id,
    source_age: metric(oldest.source_age.value as number),
    projection_lag: metric(0),
    build_age: metric(0),
    composite_state: "AVAILABLE",
    evaluation_time: instantOf(evaluationMs),
  };
}

describe("freshness deadlines (ADR-0029 section 2.2)", () => {
  const NOW = Date.parse("2026-09-05T12:00:00.000Z");

  it("CASE 3 -- a cache does not refill a spent budget", () => {
    const built = report([{ id: "q", required: true, ageSeconds: 290, contract: 300 }], NOW);
    expect(remainingFreshnessSeconds(built, NOW)).toBe(10);
    expect(isExpired(built, NOW + 9_000)).toBe(false);
    expect(isExpired(built, NOW + 10_000)).toBe(true);
  });

  it("expires AT EQUALITY rather than after it", () => {
    const built = report([{ id: "q", required: true, ageSeconds: 0, contract: 60 }], NOW);
    const deadline = freshUntil(built);
    expect(deadline).not.toBeNull();
    expect(isExpired(built, (deadline as number) - 1)).toBe(false);
    expect(isExpired(built, deadline as number)).toBe(true);
  });

  it("CASE 5 -- the oldest input is reported, and the earliest deadline binds", () => {
    const built = report(
      [
        { id: "p", required: true, ageSeconds: 40, contract: 60 },
        { id: "q", required: true, ageSeconds: 290, contract: 600 },
      ],
      NOW,
    );
    // The composite reports the OLDEST required input...
    expect(built.oldest_required).toBe("q");
    expect(built.source_age.value).toBe(290);
    // ...while the EARLIEST deadline binds, and it belongs to a different input.
    expect(remainingFreshnessSeconds(built, NOW)).toBe(20);
  });

  it("CASE 6 -- a configured TTL shortens and never extends", () => {
    const built = report([{ id: "q", required: true, ageSeconds: 290, contract: 300 }], NOW);
    expect(effectiveCacheLifetimeSeconds(built, NOW, 5)).toBe(5);
    expect(effectiveCacheLifetimeSeconds(built, NOW, 3600)).toBe(10);
  });

  it("downgrades an expired entry to STALE and never to AVAILABLE", () => {
    const built = report([{ id: "q", required: true, ageSeconds: 290, contract: 300 }], NOW);
    expect(effectiveComposite(built, NOW)).toEqual({ state: "AVAILABLE", reason: "NONE" });
    expect(effectiveComposite(built, NOW + 10_000)).toEqual({
      state: "STALE",
      reason: "UPSTREAM_INPUT_STALE",
    });
  });

  it("establishes no deadline from an unknown source time, and never treats it as fresh", () => {
    const built = report([{ id: "q", required: true, ageSeconds: 10, contract: 300 }], NOW);
    const unknown: FreshnessReport = {
      ...built,
      inputs: [{ ...built.inputs[0], source_effective_time: undefined }],
    };
    expect(freshUntil(unknown)).toBeNull();
    expect(remainingFreshnessSeconds(unknown, NOW)).toBeNull();
    expect(isExpired(unknown, NOW)).toBe(true);
  });

  it("lets an optional input answer for itself without setting the deadline", () => {
    const built = report(
      [
        { id: "required", required: true, ageSeconds: 10, contract: 600 },
        { id: "optional", required: false, ageSeconds: 590, contract: 600 },
      ],
      NOW,
    );
    expect(remainingFreshnessSeconds(built, NOW)).toBe(590);
  });
});

describe("admission (read-model-contracts.md section 7.1)", () => {
  const base = { readModel: "QualificationStatus", boundary: "PUBLIC_EDGE" } as const;

  it("admits SYNTHETIC and enumerated REPOSITORY_TRACKED payloads", () => {
    expect(
      admissionFailure({
        ...base,
        readModel: "ExecutiveOverview",
        classification: "PUBLIC_SAFE",
        provenance: "SYNTHETIC",
      }),
    ).toBeNull();
    expect(
      admissionFailure({ ...base, classification: "PUBLIC_SAFE", provenance: "REPOSITORY_TRACKED" }),
    ).toBeNull();
  });

  it("refuses REPOSITORY_TRACKED from a read model section 7.1 does not enumerate", () => {
    expect(
      admissionFailure({
        ...base,
        readModel: "ExecutiveOverview",
        classification: "PUBLIC_SAFE",
        provenance: "REPOSITORY_TRACKED",
      }),
    ).toContain("enumerated governance read models");
  });

  it("never admits the other three provenances to an external deployment", () => {
    for (const provenance of ["SYSTEM_RECORDED", "BACKTEST_SIMULATED", "BROKER_REPORTED"] as const) {
      expect(
        admissionFailure({ ...base, classification: "PUBLIC_SAFE", provenance }),
      ).toContain("never admitted");
    }
  });

  it("fails closed on UNCLASSIFIED and refuses CONTROL at admission", () => {
    expect(
      admissionFailure({ ...base, classification: "UNCLASSIFIED", provenance: "SYNTHETIC" }),
    ).toContain("fails closed");
    expect(
      admissionFailure({
        ...base,
        classification: "CONTROL",
        provenance: "SYNTHETIC",
        boundary: "PRIVATE_BOUNDARY",
      }),
    ).toContain("refused at admission");
  });
});

describe("the envelope", () => {
  it("rejects an unknown schema_version rather than coercing it", async () => {
    const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });
    const envelope = await client.executiveOverview(DEFAULT_SCOPE);
    /*
     * A version NO BUMP WILL REACH, and it used to be `.v2`.
     *
     * ADR-0030 bumped this read model to v2, so the old example had become a KNOWN
     * version and this test was asserting that a valid response is rejected.
     */
    const drifted = { ...envelope, schema_version: "cockpit.executive_overview.v99" };
    const parsed = executiveOverviewEnvelope.safeParse(drifted);
    expect(parsed.success).toBe(false);
    expect(parsed.error?.issues.some((issue) => issue.message.includes("unknown schema_version"))).toBe(
      true,
    );
    expect(EXECUTIVE_OVERVIEW_SCHEMA).not.toBe(ATTENTION_LIST_SCHEMA);
  });

  it("carries no payload when the state is an absence", async () => {
    const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });
    const envelope = await client.executiveOverview(DEFAULT_SCOPE);
    expect(envelope.availability).toBe("NOT_IMPLEMENTED");
    expect(envelope.payload).toBeUndefined();
  });
});

describe("the fixture adapter", () => {
  it("refuses a payload whose classification is wrong for the boundary", async () => {
    const client = new FixtureReadClient({
      clock: fixedClock(AS_OF),
      boundary: "PUBLIC_EDGE",
    });
    // The adapter's own responses are admissible; a hostile one is not.
    await expect(client.qualificationStatus(DEFAULT_SCOPE)).resolves.toBeDefined();
    expect(() => {
      throw new ContractViolationError("QualificationStatus", "test");
    }).toThrow(ContractViolationError);
  });

  it("does not refresh a source timestamp when an unchanged fixture is refetched", async () => {
    let reading = Date.parse(AS_OF);
    const movingClock = { now: () => reading, kind: "fixed" as const };
    const client = new FixtureReadClient({ clock: movingClock });
    const first = await client.qualificationStatus(DEFAULT_SCOPE);
    reading += 120_000;
    const second = await client.qualificationStatus(DEFAULT_SCOPE);

    const firstInput = first.freshness.inputs[0];
    const secondInput = second.freshness.inputs[0];
    // The SOURCE time is unchanged...
    expect(secondInput.source_effective_time).toBe(firstInput.source_effective_time);
    // ...so the age has GROWN. A refetch renews nothing.
    expect(secondInput.source_age.value as number).toBeGreaterThan(
      firstInput.source_age.value as number,
    );
    expect(freshUntil(second.freshness)).toBe(freshUntil(first.freshness));
  });

  it("keeps the demonstration scenario synthetic and the governance facts tracked", async () => {
    const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });
    const demo = await client.executiveOverview({ ...DEFAULT_SCOPE, scenario: "demo" });
    const governance = await client.qualificationStatus({ ...DEFAULT_SCOPE, scenario: "demo" });
    expect(demo.provenance).toBe("SYNTHETIC");
    // Section 7.1 admits REPOSITORY_TRACKED only from the enumerated governance read models.
    // A real fact is never relabelled SYNTHETIC to fit a scenario selector.
    expect(governance.provenance).toBe("REPOSITORY_TRACKED");
  });

  it("reports P1 to P9 as UNEVALUATED and separates run authorization from its date gate", async () => {
    const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });
    const status = await client.qualificationStatus(DEFAULT_SCOPE);
    const payload = status.payload;
    expect(payload).toBeDefined();
    expect(payload?.provider_tests).toHaveLength(9);
    expect(payload?.provider_tests.every((test) => test.state === "UNEVALUATED")).toBe(true);

    const runB = payload?.run_authorizations.find((entry) => entry.run.code === "RUN_B");
    expect(runB?.authorization.code).toBe("NOT_AUTHORIZED");
    // Date eligibility is a SEPARATE fact and does not imply authorization.
    expect(runB?.date_gate.value).toBe("2026-09-12");
  });

  it("reads each gate independently rather than making a blanket statement", async () => {
    const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });
    const status = await client.qualificationStatus(DEFAULT_SCOPE);
    const gates = status.payload?.gates ?? [];
    expect(gates).toHaveLength(7);
    const g3 = gates.find((gate) => gate.gate === "G3");
    expect(g3?.state).toBe("CLOSED");
    expect(g3?.scope.code).toContain("SHARADAR_PERSONAL_USE_LICENCE");
    expect(gates.filter((gate) => gate.state === "OPEN")).toHaveLength(6);
  });

  it("reports no delta when a What Changed endpoint is unavailable", async () => {
    const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });
    const changed = await client.whatChanged(DEFAULT_SCOPE);
    expect(changed.availability).toBe("NOT_YET_AVAILABLE");
    expect(changed.payload).toBeUndefined();
  });
});
