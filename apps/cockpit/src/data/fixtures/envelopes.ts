/**
 * Envelope construction for the fixture adapter.
 *
 * A fixture's `source_effective_time` is pinned at a SESSION ORIGIN captured once, so
 * REFETCHING AN UNCHANGED FIXTURE CANNOT REFRESH ITS SOURCE TIMESTAMP (ADR-0029 §2.2).
 * Only `evaluation_time` moves between fetches, which is exactly the behaviour of a real
 * source fact observed at a fixed instant.
 */
import type { FreshnessInput, FreshnessReport } from "@/contracts/freshness";
import {
  isFlaggedClockSkew,
  reportableAgeSeconds,
  requiredFailureSignatures,
} from "@/contracts/freshness";
import type { EnvelopeOf } from "@/contracts/envelope";
import type {
  AvailabilityState,
  Completeness,
  DataClassification,
  DataProvenance,
  Environment,
  FieldReasonCode,
  MaturityStage,
} from "@/contracts/vocabularies";

import {
  absent,
  available,
  emptyRefList,
  instantOf,
  METRIC_DEFINITION_VERSION,
  pinsOf,
} from "@/contracts/factories";

export interface InputSpec {
  readonly id: string;
  readonly required: boolean;
  /** Age of the SOURCE FACT at the session origin, in seconds. */
  readonly ageAtOriginSeconds: number;
  /** THIS input's own contract, in seconds. */
  readonly contractMaxAgeSeconds: number;
  /**
   * The input carries NO USABLE SOURCE TIME, and §3.1's answer for that is fixed:
   * `NOT_YET_AVAILABLE` with `SOURCE_TIMESTAMP_MISSING`, and an age that is UNKNOWN.
   *
   * It exists so a caller that CANNOT establish a source time has somewhere honest to put
   * that, instead of computing an age from an instant it does not trust. `ageAtOriginSeconds`
   * is ignored when this is set.
   */
  readonly sourceTimeUnavailable?: boolean;
}

/** One input, and the exact instant its fact was true at — `null` when there is none. */
interface BuiltInput {
  readonly input: FreshnessInput;
  /** THE ACTUAL SOURCE INSTANT. Every age this module reports is measured from it. */
  readonly effectiveMs: number | null;
}

function buildInput(spec: InputSpec, originMs: number, evaluationMs: number): BuiltInput {
  if (spec.sourceTimeUnavailable === true) {
    /*
     * §3.1 fixes ONE state and ONE reason for unknown timing, and fixes the age as UNKNOWN
     * rather than zero. Nothing here is computed: there is no instant to compute from, and
     * an age derived from an untrusted one is exactly the fabrication this branch avoids.
     */
    return {
      effectiveMs: null,
      input: {
        input_id: spec.id,
        required: spec.required,
        source_age: absent(
          "NOT_YET_AVAILABLE",
          "SOURCE_TIMESTAMP_MISSING",
          "freshness.source_age",
          "SECONDS",
        ),
        contract_max_age: spec.contractMaxAgeSeconds,
        state: "NOT_YET_AVAILABLE",
        reason: "SOURCE_TIMESTAMP_MISSING",
      },
    };
  }
  const effectiveMs = originMs - spec.ageAtOriginSeconds * 1000;
  const exactAgeSeconds = (evaluationMs - effectiveMs) / 1000;
  /*
   * §3.1's three bands, applied by the ONE function that owns them. `Math.max(0, ...)` used
   * to stand here and collapsed the middle band into the third: a source dated up to two
   * seconds AFTER its evaluation instant was floored to -1 or -2 and then lifted back to a
   * clean `0` with `AVAILABLE`/`NONE` beside it. That is a fabricated "just now", and §3.1
   * asks for a zero that is FLAGGED, "because a small skew is ordinary and a silent one is
   * not".
   */
  const ageSeconds = reportableAgeSeconds(exactAgeSeconds);
  if (ageSeconds === null) {
    /*
     * Beyond the tolerance. A fixture dated after the instant it is evaluated at is a
     * programming error, not a state to render, so fixture construction REFUSES IT rather
     * than emitting the NOT_YET_AVAILABLE/CLOCK_UNSYNCHRONIZED report a real skewed producer
     * would emit. Either way, no age is invented.
     */
    throw new RangeError(`fixture input ${spec.id} is dated after its evaluation time`);
  }
  const skewFlagged = isFlaggedClockSkew(exactAgeSeconds);
  const stale = ageSeconds >= spec.contractMaxAgeSeconds;
  return {
    effectiveMs,
    input: {
      input_id: spec.id,
      required: spec.required,
      source_effective_time: instantOf(effectiveMs),
      source_age: available({
        metricId: "freshness.source_age",
        unit: "SECONDS",
        value: ageSeconds,
        asOf: instantOf(evaluationMs),
      }),
      contract_max_age: spec.contractMaxAgeSeconds,
      state: stale ? "STALE" : "AVAILABLE",
      reason: stale ? "UPSTREAM_INPUT_STALE" : "NONE",
      /** Absent rather than `false`, so a flag is a positive statement and never noise. */
      ...(skewFlagged ? { clock_skew_flagged: true } : {}),
    },
  };
}

/**
 * A duration between two instants, in whole seconds, under §3.1's SAME three bands.
 *
 * `projection_lag` and `build_age` are durations whose ordering follows from what they
 * measure: a projection does not precede the source it consumed, and an evaluation does not
 * precede the build it read. Both orderings are nonetheless measured across two clocks, so a
 * small negative is the ordinary skew §3.1 already describes — reported as zero, and never
 * silently, because the input that carries that skew is flagged.
 *
 * Beyond the tolerance the ordering is genuinely violated, and that REFUSES. It does not
 * clamp: clamping does not restore the ordering, it conceals that the ordering was broken and
 * reports a fabricated `0` in its place.
 */
function elapsedSeconds(fromMs: number, toMs: number, description: string): number {
  const seconds = reportableAgeSeconds((toMs - fromMs) / 1000);
  if (seconds === null) {
    throw new RangeError(
      `fixture ${description} is negative beyond the declared clock tolerance, and a ` +
        "duration is refused rather than clamped",
    );
  }
  return seconds;
}

/**
 * §3.1: the composite reports the OLDEST required input and takes the WORST state any
 * required input reached. One fresh input NEVER raises a view carrying a stale one, and an
 * optional input never sets the composite state.
 */
export function buildFreshness(
  specs: readonly InputSpec[],
  originMs: number,
  evaluationMs: number,
  projectedMs: number,
): FreshnessReport {
  const built = specs.map((spec) => buildInput(spec, originMs, evaluationMs));
  const required = built.filter((entry) => entry.input.required);
  if (required.length === 0) {
    throw new RangeError("a freshness report states at least one required input");
  }
  /*
   * THREE AGES, EACH MEASURED FROM ITS OWN PAIR OF INSTANTS.
   *
   * The retired formula reconstructed a source time as `origin - oldestAge`, where
   * `oldestAge` had been measured at EVALUATION time. With `projected_time == origin` that
   * reduces to `evaluation - source_effective`, so `projection_lag` became a second copy of
   * `source_age` AND MOVED EVERY TIME THE VIEW WAS REFETCHED -- while the source fact and
   * the build were both unchanged. A lag between two fixed instants cannot change.
   *
   * 3.1 reports the composite `source_age` against the OLDEST required input; 12.3 defines
   * `projection_lag` against the NEWEST required input the projection consumed. They are
   * different questions and they name different inputs, so both are computed here.
   */
  /*
   * AN UNKNOWN AGE IS NOT AN OLD ONE, so it cannot take part in a maximum.
   *
   * Where any required input carries no usable source time, the composite has no measured
   * age to report: §3.1's composite age IS the oldest required input's age, and "oldest" is
   * undefined over a set containing an unknown. The report names the input that blocked the
   * measurement and reports the age as UNKNOWN — never as the oldest of the ones that
   * happened to be measurable, which would understate the age of the whole view.
   */
  const timed = required.filter(
    (entry): entry is BuiltInput & { effectiveMs: number } => entry.effectiveMs !== null,
  );
  const untimed = required.find((entry) => entry.effectiveMs === null);
  const oldest =
    untimed ??
    timed.reduce((worst, entry) => (entry.effectiveMs < worst.effectiveMs ? entry : worst));
  const newest =
    timed.length === 0
      ? undefined
      : timed.reduce((freshest, entry) =>
          entry.effectiveMs > freshest.effectiveMs ? entry : freshest,
        );
  /*
   * The composite takes the WORST state any required input reached, and §3.1 defines no
   * ordering across the eleven states -- so where the required inputs failed in more than
   * one distinct way, there is no unique worst and this REFUSES rather than picking one.
   */
  const failures = requiredFailureSignatures({ inputs: built.map((entry) => entry.input) });
  if (failures.length > 1) {
    throw new RangeError(
      "fixture required inputs failed in more than one distinct way, and the composite state " +
        "is undetermined",
    );
  }
  const compositeState: AvailabilityState = failures[0]?.state ?? "AVAILABLE";
  const evaluationInstant = instantOf(evaluationMs);
  return {
    inputs: built.map((entry) => entry.input),
    oldest_required: oldest.input.input_id,
    /**
     * evaluation_time - source_effective_time, of the OLDEST required input.
     *
     * Taken from that input's OWN reported age rather than recomputed from its instants. Two
     * spellings of one measurement are two values that can disagree, and the composite age
     * §3.1 asks for is definitionally the oldest input's age -- not a second opinion of it.
     */
    source_age:
      oldest.effectiveMs === null
        ? absent(
            "NOT_YET_AVAILABLE",
            "SOURCE_TIMESTAMP_MISSING",
            "freshness.source_age",
            "SECONDS",
          )
        : available({
            metricId: "freshness.source_age",
            unit: "SECONDS",
            value: oldest.input.source_age.value,
            asOf: evaluationInstant,
          }),
    /**
     * projected_time - source_effective_time, of the NEWEST required input (§12.3).
     * It depends on NEITHER the evaluation time NOR a reconstructed instant, so a refetch
     * over unchanged fixtures leaves it exactly where it was.
     *
     * With no required input carrying a source time there is no lag to measure, and an
     * unmeasured lag is UNKNOWN rather than zero.
     */
    projection_lag:
      newest === undefined
        ? absent(
            "NOT_YET_AVAILABLE",
            "SOURCE_TIMESTAMP_MISSING",
            "freshness.projection_lag",
            "SECONDS",
          )
        : available({
            metricId: "freshness.projection_lag",
            unit: "SECONDS",
            value: elapsedSeconds(
              newest.effectiveMs,
              projectedMs,
              "projection_lag: the projection is dated before the newest source it consumed",
            ),
            asOf: evaluationInstant,
          }),
    /** evaluation_time - projected_time. The ONLY age a rebuild resets. */
    build_age: available({
      metricId: "freshness.build_age",
      unit: "SECONDS",
      value: elapsedSeconds(
        projectedMs,
        evaluationMs,
        "build_age: the evaluation time precedes the projection it read",
      ),
      asOf: evaluationInstant,
    }),
    composite_state: compositeState,
    evaluation_time: evaluationInstant,
  };
}

export interface EnvelopeSpec<T> {
  readonly schemaVersion: string;
  readonly entityId: string;
  readonly availability: AvailabilityState;
  readonly availabilityReason: FieldReasonCode;
  readonly provenance: DataProvenance;
  readonly classification: DataClassification;
  readonly environment: Environment;
  /** ABSENT where no strategy version is involved -- 3 states it applies where applicable. */
  readonly maturityStage?: MaturityStage;
  readonly accessScope: string;
  readonly inputs: readonly InputSpec[];
  readonly payload?: T;
  readonly originMs: number;
  readonly evaluationMs: number;
  /** `PARTIAL` where the payload itself covers only part of its requested extent. */
  readonly completeness?: Completeness;
}

export function buildEnvelope<T>(spec: EnvelopeSpec<T>): EnvelopeOf<T> {
  const projectedMs = spec.originMs;
  const evaluationInstant = instantOf(spec.evaluationMs);
  const originInstant = instantOf(spec.originMs);
  const freshness = buildFreshness(
    spec.inputs,
    spec.originMs,
    spec.evaluationMs,
    projectedMs,
  );
  const bearing = spec.payload !== undefined;
  /*
   * THE OLDEST REQUIRED SOURCE INSTANT is how far this projection has read.
   *
   * A watermark is "the source position the projection has CONSUMED TO -- the boundary beyond
   * which this row knows nothing" (3). The OLDEST required input is the conservative reading:
   * this row knows nothing past the point its LEAST advanced required input reached, and
   * claiming the newest one would assert knowledge of source that one of its own inputs never
   * supplied.
   */
  const watermarkInput = spec.inputs.reduce<InputSpec | undefined>(
    (oldest, input) =>
      !input.required
        ? oldest
        : oldest === undefined || input.ageAtOriginSeconds > oldest.ageAtOriginSeconds
          ? input
          : oldest,
    undefined,
  );
  const watermark =
    watermarkInput === undefined
      ? undefined
      : instantOf(spec.originMs - watermarkInput.ageAtOriginSeconds * 1000);
  return {
    schema_version: spec.schemaVersion,
    api_version: "v1",
    entity_id: spec.entityId,
    correlation_id: `${spec.entityId}-${spec.schemaVersion}`,
    source_refs: emptyRefList(evaluationInstant),
    event_time: originInstant,
    observed_time: originInstant,
    as_of_time: evaluationInstant,
    projected_time: originInstant,
    environment: spec.environment,
    maturity_stage: spec.maturityStage,
    provenance: spec.provenance,
    availability: spec.availability,
    availability_reason: spec.availabilityReason,
    freshness,
    coverage: { present: bearing ? 1 : 0, requested: 1 },
    completeness: bearing ? (spec.completeness ?? "COMPLETE") : "UNKNOWN",
    snapshot_version: `fixture-${originInstant}`,
    /** A payloadless absence has consumed nothing to a position, so it states none. */
    watermark: bearing ? watermark : undefined,
    classification: spec.classification,
    access_scope: spec.accessScope,
    metric_definition_version: METRIC_DEFINITION_VERSION,
    /**
     * Every pin states that it DOES NOT APPLY, except the two identities that genuinely do.
     *
     * No strategy version, factor definition, risk policy, entry or exit policy, model or
     * prompt exists to pin, because none of those subsystems exists -- and §4.2 asks for that
     * to be SAID rather than left out. The two that do exist are this response's own
     * read-model schema and the fixture scenario that produced it.
     */
    pins: bearing
      ? pinsOf({
          code_identity: spec.schemaVersion.replace(/\./g, "-"),
          config_identity: `fixture-${spec.environment.toLowerCase()}`,
        })
      : undefined,
    payload: spec.payload,
  };
}
