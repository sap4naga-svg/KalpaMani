/**
 * Regressions for the two residual freshness defects found in the merged C3 foundation.
 *
 *   A  a negative age could still become a measured ZERO
 *   B  a composite over MIXED required failures was ORDER-DEPENDENT
 *
 * Each block states the defect, drives the REAL admission path where the defect could reach a
 * screen, and carries a NEGATIVE CONTROL: the pre-correction expression is reimplemented
 * inline and shown to violate the invariant the corrected code holds. A regression that only
 * asserts the new behaviour cannot show that the old behaviour was different.
 *
 * Every instant here comes from an explicit, controlled clock. Nothing reads `Date.now()`.
 */
import { describe, expect, it } from "vitest";

import {
  CLOCK_SKEW_TOLERANCE_SECONDS,
  effectiveComposite,
  freshnessReportFailure,
  isFlaggedClockSkew,
  reportableAgeSeconds,
  requiredFailureSignatures,
  type FreshnessInput,
  type FreshnessReport,
} from "@/contracts/freshness";
import { absent, available, emptyRefList, pinsOf } from "@/contracts/factories";
import { attentionListEnvelope } from "@/contracts/read-models";
import { admit, ContractViolationError } from "@/data/client/read-client";
import { buildFreshness, type InputSpec } from "@/data/fixtures/envelopes";

const ORIGIN = Date.parse("2026-09-05T12:00:00.000Z");
const AS_OF = "2026-09-05T12:00:00.000Z";

const seconds = (value: number, metricId: string) =>
  available({ metricId, unit: "SECONDS", value, asOf: AS_OF });

const unknownAge = (reason: "SOURCE_TIMESTAMP_MISSING" | "CLOCK_UNSYNCHRONIZED") =>
  absent("NOT_YET_AVAILABLE", reason, "freshness.source_age", "SECONDS");

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

/**
 * A report whose composite fields are DERIVED from its inputs, so a test states only the
 * thing it is testing. §3.1 fixes the composite `source_age` as the oldest required input's
 * own age, and this helper obeys that rather than restating a number.
 */
function reportOf(
  inputs: readonly FreshnessInput[],
  composite: FreshnessReport["composite_state"],
  over: Partial<FreshnessReport> = {},
): FreshnessReport {
  const required = inputs.filter((entry) => entry.required);
  const ages = required.map((entry) =>
    typeof entry.source_age.value === "number" ? entry.source_age.value : null,
  );
  const measurable = ages.every((age): age is number => age !== null);
  const oldest = measurable && ages.length > 0 ? Math.max(...ages) : null;
  return {
    inputs: [...inputs],
    oldest_required:
      oldest === null
        ? required[0]?.input_id
        : required.find((entry) => entry.source_age.value === oldest)?.input_id,
    source_age:
      oldest === null
        ? unknownAge("SOURCE_TIMESTAMP_MISSING")
        : seconds(oldest, "freshness.source_age"),
    projection_lag: seconds(0, "freshness.projection_lag"),
    build_age: seconds(0, "freshness.build_age"),
    composite_state: composite,
    evaluation_time: AS_OF,
    ...over,
  };
}

/** Drives a freshness report through the REAL envelope admission path. */
function admitting(freshness: FreshnessReport): () => unknown {
  const candidate = {
    schema_version: "cockpit.attention_list.v1",
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
    metric_definition_version: "metrics.v1",
    watermark: AS_OF,
    pins: pinsOf(),
    payload: { items: [] },
  };
  return () => admit("AttentionItem", attentionListEnvelope, candidate, "PUBLIC_EDGE");
}

const spec = (over: Partial<InputSpec> & Pick<InputSpec, "id">): InputSpec => ({
  required: true,
  ageAtOriginSeconds: 60,
  contractMaxAgeSeconds: 600,
  ...over,
});

/* ================================================================= CORRECTION A */

describe("correction A -- an invalid ordering never becomes a measured zero", () => {
  /**
   * THE DEFECT: `buildInput` refused only BEYOND the tolerance, then applied
   * `Math.max(0, Math.floor(exact))`. A source dated up to two seconds AFTER its evaluation
   * instant floored to -1 or -2 and was lifted back to a clean `0`, carrying `AVAILABLE` and
   * `NONE` -- a fabricated "just now" beside no indication at all that two clocks disagreed.
   * `wholeSeconds` clamped `projection_lag` and `build_age` the same way.
   */

  it("NEGATIVE CONTROL -- the retired expression turns every negative age into zero", () => {
    const retired = (exact: number) => Math.max(0, Math.floor(exact));
    for (const exact of [-0.5, -1.5, -2, -600]) {
      // The retired expression answers "just now" for all four.
      expect(retired(exact)).toBe(0);
    }
    // The corrected one separates them: flagged zero inside tolerance, UNKNOWN beyond it.
    expect(reportableAgeSeconds(-0.5)).toBe(0);
    expect(reportableAgeSeconds(-1.5)).toBe(0);
    expect(reportableAgeSeconds(-CLOCK_SKEW_TOLERANCE_SECONDS)).toBe(0);
    expect(reportableAgeSeconds(-CLOCK_SKEW_TOLERANCE_SECONDS - 0.001)).toBeNull();
    expect(reportableAgeSeconds(-600)).toBeNull();
    // And it never deepens a negative into a smaller negative.
    expect(reportableAgeSeconds(-1.5)).not.toBe(Math.floor(-1.5));
  });

  it("keeps a valid source age of exactly zero valid, measured and unflagged", () => {
    const report = buildFreshness([spec({ id: "mark", ageAtOriginSeconds: 0 })], ORIGIN, ORIGIN, ORIGIN);
    expect(report.inputs[0].source_age.value).toBe(0);
    expect(report.inputs[0].source_age.availability).toBe("AVAILABLE");
    expect(report.inputs[0].state).toBe("AVAILABLE");
    expect(report.inputs[0].reason).toBe("NONE");
    // A measured zero is a RESULT (ADR-0029 section 2.1), and no skew occurred to flag.
    expect(report.inputs[0].clock_skew_flagged).toBeUndefined();
    expect(isFlaggedClockSkew(0)).toBe(false);
    expect(freshnessReportFailure(report)).toBeNull();
    expect(admitting(report)).not.toThrow();
  });

  it("reports a source slightly AHEAD of evaluation as zero AND FLAGGED, never silently", () => {
    // 1.5 seconds ahead: inside the declared tolerance, so 3.1 asks for a flagged zero.
    const report = buildFreshness(
      [spec({ id: "mark", ageAtOriginSeconds: -1.5 })],
      ORIGIN,
      ORIGIN,
      ORIGIN,
    );
    expect(report.inputs[0].source_age.value).toBe(0);
    expect(report.inputs[0].clock_skew_flagged).toBe(true);
    // The zero is real, so the state is not fabricated into a failure either.
    expect(report.inputs[0].state).toBe("AVAILABLE");
    expect(report.inputs[0].reason).toBe("NONE");
    expect(freshnessReportFailure(report)).toBeNull();
    expect(admitting(report)).not.toThrow();
  });

  it("refuses that same zero when it is reported WITHOUT the flag", () => {
    const silent = reportOf(
      [
        input({
          input_id: "mark",
          source_effective_time: "2026-09-05T12:00:01.500Z",
          source_age: seconds(0, "freshness.source_age"),
        }),
      ],
      "AVAILABLE",
    );
    expect(freshnessReportFailure(silent)).toMatch(/flagged rather than reported silently/);
    expect(admitting(silent)).toThrow(ContractViolationError);
  });

  it("refuses a flag on an input whose source does not follow the evaluation time", () => {
    const overclaimed = reportOf([input({ clock_skew_flagged: true })], "AVAILABLE");
    expect(freshnessReportFailure(overclaimed)).toMatch(/does not follow the evaluation time/);
    expect(admitting(overclaimed)).toThrow(ContractViolationError);
  });

  it("refuses a source BEYOND the tolerance, and refuses a zero age reported beside it", () => {
    // Fixture construction refuses it outright rather than emitting an unrenderable age.
    expect(() =>
      buildFreshness([spec({ id: "mark", ageAtOriginSeconds: -600 })], ORIGIN, ORIGIN, ORIGIN),
    ).toThrow(RangeError);

    // And at the contract boundary: the state alone was never enough. A producer declaring
    // CLOCK_UNSYNCHRONIZED could still hand a screen a measured 0, which reads as "just now"
    // beside the very badge saying the clocks disagree.
    const skewed = input({
      source_effective_time: "2026-09-05T13:00:00.000Z",
      state: "NOT_YET_AVAILABLE",
      reason: "CLOCK_UNSYNCHRONIZED",
      source_age: seconds(0, "freshness.source_age"),
    });
    const fabricated = reportOf([skewed], "NOT_YET_AVAILABLE");
    expect(freshnessReportFailure(fabricated)).toMatch(/age is unknown and must not be reported/);
    expect(admitting(fabricated)).toThrow(ContractViolationError);

    // Declared honestly -- the age UNKNOWN rather than zero -- the same report is ADMITTED,
    // so the refusal above is targeted at the fabricated number and not at the state.
    const honest = reportOf([{ ...skewed, source_age: unknownAge("CLOCK_UNSYNCHRONIZED") }], "NOT_YET_AVAILABLE");
    expect(freshnessReportFailure(honest)).toBeNull();
    expect(admitting(honest)).not.toThrow();
  });

  it("refuses a zero age reported for an input with no source time at all", () => {
    const fabricated = reportOf(
      [
        input({
          source_effective_time: undefined,
          state: "NOT_YET_AVAILABLE",
          reason: "SOURCE_TIMESTAMP_MISSING",
          source_age: seconds(0, "freshness.source_age"),
        }),
      ],
      "NOT_YET_AVAILABLE",
    );
    expect(freshnessReportFailure(fabricated)).toMatch(/age is unknown and must not be reported/);
    expect(admitting(fabricated)).toThrow(ContractViolationError);
  });

  it("refuses a projection dated BEFORE the source it consumed, rather than clamping it", () => {
    expect(() =>
      buildFreshness([spec({ id: "mark", ageAtOriginSeconds: 0 })], ORIGIN, ORIGIN, ORIGIN - 5_000),
    ).toThrow(/projection_lag/);
    // NEGATIVE CONTROL: the retired clamp produced a plausible, wrong zero for that input.
    expect(Math.max(0, Math.floor((ORIGIN - 5_000 - ORIGIN) / 1000))).toBe(0);
    // And a negative lag is refused at the contract boundary too.
    const negativeLag = reportOf([input()], "AVAILABLE", {
      projection_lag: seconds(-5, "freshness.projection_lag"),
    });
    expect(freshnessReportFailure(negativeLag)).toMatch(/refused rather than clamped/);
    expect(admitting(negativeLag)).toThrow(ContractViolationError);
  });

  it("refuses an evaluation dated BEFORE the projection it read, rather than clamping it", () => {
    expect(() =>
      buildFreshness([spec({ id: "mark", ageAtOriginSeconds: 10 })], ORIGIN, ORIGIN, ORIGIN + 5_000),
    ).toThrow(/build_age/);
    const negativeBuild = reportOf([input()], "AVAILABLE", {
      build_age: seconds(-5, "freshness.build_age"),
    });
    expect(freshnessReportFailure(negativeBuild)).toMatch(/refused rather than clamped/);
    expect(admitting(negativeBuild)).toThrow(ContractViolationError);
  });

  it("holds projection lag still across a refetch with fixed source and projected instants", () => {
    const specs = [
      spec({ id: "positions.mark", ageAtOriginSeconds: 45, contractMaxAgeSeconds: 100_000 }),
      spec({ id: "governance.tracked_snapshot", ageAtOriginSeconds: 3_600, contractMaxAgeSeconds: 100_000 }),
    ];
    // Only the evaluation time moves. The source instants and the build instant do not.
    const first = buildFreshness(specs, ORIGIN, ORIGIN + 10_000, ORIGIN);
    const later = buildFreshness(specs, ORIGIN, ORIGIN + 900_000, ORIGIN);

    expect(later.projection_lag.value).toBe(first.projection_lag.value);
    expect(later.projection_lag.value).toBe(45);
    for (let index = 0; index < specs.length; index += 1) {
      expect(later.inputs[index].source_effective_time).toBe(first.inputs[index].source_effective_time);
    }
    // The two ages that MUST advance, because evaluation time is one of their endpoints.
    expect(later.source_age.value as number).toBeGreaterThan(first.source_age.value as number);
    expect(later.build_age.value as number).toBeGreaterThan(first.build_age.value as number);
  });

  it("reports the composite age as the OLDEST required input's own age, and refuses any other", () => {
    const report = buildFreshness(
      [
        spec({ id: "positions.mark", ageAtOriginSeconds: 45, contractMaxAgeSeconds: 100_000 }),
        spec({ id: "governance.tracked_snapshot", ageAtOriginSeconds: 3_600, contractMaxAgeSeconds: 100_000 }),
      ],
      ORIGIN,
      ORIGIN,
      ORIGIN,
    );
    expect(report.oldest_required).toBe("governance.tracked_snapshot");
    expect(report.source_age.value).toBe(3_600);
    // Substituting the FRESHEST input's age is CASE 2 read backwards, and is refused.
    const understated: FreshnessReport = { ...report, source_age: seconds(45, "freshness.source_age") };
    expect(freshnessReportFailure(understated)).toMatch(/where the oldest required input measures/);
    expect(admitting(understated)).toThrow(ContractViolationError);
  });
});

/* ================================================================= CORRECTION B */

describe("correction B -- a composite over mixed required failures is not order-dependent", () => {
  /**
   * THE DEFECT: `effectiveComposite` returned `inputs.find(required && !AVAILABLE)` -- the
   * FIRST failing entry in array order -- and admission accepted any composite naming ANY
   * unhealthy input's state. Reordering the same two required inputs therefore changed the
   * diagnosis a reader saw, with no change to the facts.
   *
   * THE CORRECTION USES ACCEPTED AUTHORITY AND INVENTS NO ORDERING. §3.1 says the composite
   * "takes the WORST state any required input reached" and fixes only `AVAILABLE` and
   * `STALE`; it defines no ordering across the other nine states. So a single distinct
   * failure IS the worst one, and several distinct failures are REFUSED at admission rather
   * than resolved -- with each input's own failure left intact for inspection.
   */
  const stale = input({
    input_id: "positions.mark",
    state: "STALE",
    reason: "UPSTREAM_INPUT_STALE",
    contract_max_age: 30,
  });
  const missing = input({
    input_id: "governance.tracked_snapshot",
    source_effective_time: undefined,
    state: "NOT_YET_AVAILABLE",
    reason: "SOURCE_TIMESTAMP_MISSING",
    source_age: unknownAge("SOURCE_TIMESTAMP_MISSING"),
  });
  /**
   * A third distinct failure. Its AGE is measured -- the input's `state` describes the input,
   * and `source_age` describes the age, and the two are separate axes. Reporting the age as
   * unknown while its instants measure it is itself refused, which the age block covers.
   */
  const errored = input({
    input_id: "operations.feed",
    state: "ERROR",
    reason: "PROJECTION_ERROR",
  });

  it("NEGATIVE CONTROL -- first-failure-wins gives two answers for one set of facts", () => {
    const legacy = (report: FreshnessReport) => {
      const failing = report.inputs.find((entry) => entry.required && entry.state !== "AVAILABLE");
      return failing === undefined ? "AVAILABLE" : failing.state;
    };
    const forward = reportOf([stale, missing], "STALE");
    const reversed = reportOf([missing, stale], "STALE");
    expect(legacy(forward)).toBe("STALE");
    expect(legacy(reversed)).toBe("NOT_YET_AVAILABLE");
    expect(legacy(forward)).not.toBe(legacy(reversed));

    // The corrected boundary refuses BOTH orderings instead of answering either way.
    expect(freshnessReportFailure(forward)).toMatch(/refused rather than resolved/);
    expect(freshnessReportFailure(reversed)).toMatch(/refused rather than resolved/);
  });

  it("refuses a heterogeneous composite at admission and names every way it failed", () => {
    const mixed = reportOf([stale, missing, errored], "STALE");
    const failure = freshnessReportFailure(mixed);
    expect(failure).toMatch(/failed in 3 different ways/);
    // Each distinct failure is named, so a reader is told what is unresolved rather than
    // being handed one of them as though it were the answer.
    expect(failure).toContain("STALE/UPSTREAM_INPUT_STALE");
    expect(failure).toContain("NOT_YET_AVAILABLE/SOURCE_TIMESTAMP_MISSING");
    expect(failure).toContain("ERROR/PROJECTION_ERROR");
    expect(admitting(mixed)).toThrow(ContractViolationError);
  });

  it("preserves the individual input failures for inspection on a refused report", () => {
    const mixed = reportOf([stale, missing], "STALE");
    // The report is refused as a COMPOSITE. Each input still carries its own diagnosis.
    expect(mixed.inputs.map((entry) => [entry.input_id, entry.state, entry.reason])).toEqual([
      ["positions.mark", "STALE", "UPSTREAM_INPUT_STALE"],
      ["governance.tracked_snapshot", "NOT_YET_AVAILABLE", "SOURCE_TIMESTAMP_MISSING"],
    ]);
    expect(requiredFailureSignatures(mixed)).toHaveLength(2);
  });

  it("produces the SAME result under every permutation of a supported report", () => {
    // Two required inputs failing the SAME way, plus one healthy: a supported combination.
    const secondStale = { ...stale, input_id: "positions.other_mark" };
    const healthy = input({ input_id: "market.regime" });
    const inputs = [stale, secondStale, healthy];

    const permutations: FreshnessInput[][] = [
      [inputs[0], inputs[1], inputs[2]],
      [inputs[0], inputs[2], inputs[1]],
      [inputs[1], inputs[0], inputs[2]],
      [inputs[1], inputs[2], inputs[0]],
      [inputs[2], inputs[0], inputs[1]],
      [inputs[2], inputs[1], inputs[0]],
    ];
    const results = permutations.map((ordering) =>
      effectiveComposite(reportOf(ordering, "STALE"), ORIGIN),
    );
    for (const result of results) {
      expect(result).toEqual({ state: "STALE", reason: "UPSTREAM_INPUT_STALE" });
    }
    // And every permutation is admitted, so the support is real rather than accidental.
    for (const ordering of permutations) {
      expect(freshnessReportFailure(reportOf(ordering, "STALE"))).toBeNull();
    }
  });

  it("refuses two PARTIAL inputs whose reasons differ, because the composite reason is undetermined", () => {
    const extent = input({
      input_id: "positions.mark",
      state: "PARTIAL",
      reason: "EXTENT_PARTIALLY_COVERED",
    });
    const price = input({
      input_id: "positions.other_mark",
      state: "PARTIAL",
      reason: "PRICE_PATH_INCOMPLETE",
    });
    // The STATE agrees; the REASON does not, and the composite renders both.
    expect(freshnessReportFailure(reportOf([extent, price], "PARTIAL"))).toMatch(
      /refused rather than resolved/,
    );
    // The same state with the same reason is supported and unambiguous.
    expect(
      freshnessReportFailure(
        reportOf([extent, { ...price, reason: "EXTENT_PARTIALLY_COVERED" }], "PARTIAL"),
      ),
    ).toBeNull();
  });

  it("admits a homogeneous failure and renders exactly that state and reason", () => {
    const report = reportOf([stale, input({ input_id: "market.regime" })], "STALE");
    expect(freshnessReportFailure(report)).toBeNull();
    expect(admitting(report)).not.toThrow();
    expect(effectiveComposite(report, ORIGIN)).toEqual({
      state: "STALE",
      reason: "UPSTREAM_INPUT_STALE",
    });
  });

  it("refuses a composite that names a state no required input reached", () => {
    const wrong = reportOf([stale], "ERROR");
    expect(freshnessReportFailure(wrong)).toMatch(/is not the one state its required inputs reached/);
    expect(admitting(wrong)).toThrow(ContractViolationError);
  });

  it("still refuses a composite claiming AVAILABLE over any required failure", () => {
    expect(freshnessReportFailure(reportOf([stale], "AVAILABLE"))).toMatch(/claims AVAILABLE/);
    expect(admitting(reportOf([stale], "AVAILABLE"))).toThrow(ContractViolationError);
    // ...and the renderer does not upgrade it either, whatever the composite claims.
    expect(effectiveComposite(reportOf([stale], "AVAILABLE"), ORIGIN).state).toBe("STALE");
  });

  it("never lets an OPTIONAL input conceal or create a required failure", () => {
    const optionalStale = { ...stale, input_id: "optional.feed", required: false };
    const healthy = input({ input_id: "market.regime" });

    // An optional failure does not set the composite: every REQUIRED input is available.
    const optionalOnly = reportOf([healthy, optionalStale], "AVAILABLE");
    expect(requiredFailureSignatures(optionalOnly)).toHaveLength(0);
    expect(freshnessReportFailure(optionalOnly)).toBeNull();
    expect(effectiveComposite(optionalOnly, ORIGIN).state).toBe("AVAILABLE");

    // And an optional input failing a SECOND way does not make a supported report ambiguous.
    const optionalMissing = { ...missing, input_id: "optional.other", required: false };
    const supported = reportOf([stale, optionalMissing, optionalStale], "STALE");
    expect(freshnessReportFailure(supported)).toBeNull();
    expect(effectiveComposite(supported, ORIGIN)).toEqual({
      state: "STALE",
      reason: "UPSTREAM_INPUT_STALE",
    });
  });

  it("fails closed rather than picking an answer if a mixed report ever reaches the renderer", () => {
    // Unreachable through admission. If it happens anyway, the answer is deterministic and
    // identical under permutation -- never "whichever failure was listed first".
    const forward = effectiveComposite(reportOf([stale, missing], "STALE"), ORIGIN);
    const reversed = effectiveComposite(reportOf([missing, stale], "STALE"), ORIGIN);
    expect(forward).toEqual(reversed);
    expect(forward).toEqual({ state: "ERROR", reason: "PROJECTION_ERROR" });
  });

  it("keeps every rendered (state, reason) pair valid under the 4.1.1 matrix", async () => {
    const { reasonIsPermitted } = await import("@/contracts/validity");
    const cases: FreshnessReport[] = [
      reportOf([input({ input_id: "market.regime" })], "AVAILABLE"),
      reportOf([stale], "STALE"),
      reportOf([missing], "NOT_YET_AVAILABLE"),
      reportOf([errored], "ERROR"),
      reportOf([stale, missing], "STALE"),
    ];
    for (const candidate of cases) {
      const composite = effectiveComposite(candidate, ORIGIN);
      expect(
        reasonIsPermitted(composite.state, composite.reason),
        `${composite.state}/${composite.reason} must be a permitted pair`,
      ).toBe(true);
    }
  });
});
