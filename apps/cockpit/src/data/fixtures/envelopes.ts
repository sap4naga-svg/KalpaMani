/**
 * Envelope construction for the fixture adapter.
 *
 * A fixture's `source_effective_time` is pinned at a SESSION ORIGIN captured once, so
 * REFETCHING AN UNCHANGED FIXTURE CANNOT REFRESH ITS SOURCE TIMESTAMP (ADR-0029 §2.2).
 * Only `evaluation_time` moves between fetches, which is exactly the behaviour of a real
 * source fact observed at a fixed instant.
 */
import type { FreshnessInput, FreshnessReport } from "@/contracts/freshness";
import { CLOCK_SKEW_TOLERANCE_SECONDS } from "@/contracts/freshness";
import type { EnvelopeOf } from "@/contracts/envelope";
import type {
  AvailabilityState,
  DataClassification,
  DataProvenance,
  Environment,
  FieldReasonCode,
  MaturityStage,
} from "@/contracts/vocabularies";

import { available, instantOf, METRIC_DEFINITION_VERSION } from "@/contracts/factories";

export interface InputSpec {
  readonly id: string;
  readonly required: boolean;
  /** Age of the SOURCE FACT at the session origin, in seconds. */
  readonly ageAtOriginSeconds: number;
  /** THIS input's own contract, in seconds. */
  readonly contractMaxAgeSeconds: number;
}

/** One input, and the exact instant its fact was true at. */
interface BuiltInput {
  readonly input: FreshnessInput;
  /** THE ACTUAL SOURCE INSTANT. Every age this module reports is measured from it. */
  readonly effectiveMs: number;
}

function buildInput(spec: InputSpec, originMs: number, evaluationMs: number): BuiltInput {
  const effectiveMs = originMs - spec.ageAtOriginSeconds * 1000;
  const exactAgeSeconds = (evaluationMs - effectiveMs) / 1000;
  if (exactAgeSeconds < -CLOCK_SKEW_TOLERANCE_SECONDS) {
    /*
     * A fixture dated after the instant it is evaluated at is a programming error, not a
     * state to render. It is refused here rather than clamped to zero: a clamp turns a
     * negative age into a legitimate-looking "just now" (read-model-contracts.md 3.1).
     */
    throw new RangeError(`fixture input ${spec.id} is dated after its evaluation time`);
  }
  const ageSeconds = Math.max(0, Math.floor(exactAgeSeconds));
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
    },
  };
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
  const oldest = required.reduce((worst, entry) =>
    entry.effectiveMs < worst.effectiveMs ? entry : worst,
  );
  const newest = required.reduce((freshest, entry) =>
    entry.effectiveMs > freshest.effectiveMs ? entry : freshest,
  );
  const compositeState: AvailabilityState = required.some(
    (entry) => entry.input.state === "STALE",
  )
    ? "STALE"
    : "AVAILABLE";
  const evaluationInstant = instantOf(evaluationMs);
  const wholeSeconds = (fromMs: number, toMs: number): number =>
    Math.max(0, Math.floor((toMs - fromMs) / 1000));
  return {
    inputs: built.map((entry) => entry.input),
    oldest_required: oldest.input.input_id,
    /** evaluation_time - source_effective_time, of the OLDEST required input. */
    source_age: available({
      metricId: "freshness.source_age",
      unit: "SECONDS",
      value: wholeSeconds(oldest.effectiveMs, evaluationMs),
      asOf: evaluationInstant,
    }),
    /**
     * projected_time - source_effective_time, of the NEWEST required input (12.3).
     * It depends on NEITHER the evaluation time NOR a reconstructed instant, so a refetch
     * over unchanged fixtures leaves it exactly where it was.
     */
    projection_lag: available({
      metricId: "freshness.projection_lag",
      unit: "SECONDS",
      value: wholeSeconds(newest.effectiveMs, projectedMs),
      asOf: evaluationInstant,
    }),
    /** evaluation_time - projected_time. The ONLY age a rebuild resets. */
    build_age: available({
      metricId: "freshness.build_age",
      unit: "SECONDS",
      value: wholeSeconds(projectedMs, evaluationMs),
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
  return {
    schema_version: spec.schemaVersion,
    api_version: "v1",
    entity_id: spec.entityId,
    correlation_id: `${spec.entityId}-${spec.schemaVersion}`,
    source_refs: { items: [], cardinality: "ZERO_OR_MORE", truncated: false },
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
    coverage: { present: spec.payload === undefined ? 0 : 1, requested: 1 },
    completeness: spec.payload === undefined ? "UNKNOWN" : "COMPLETE",
    snapshot_version: `fixture-${originInstant}`,
    classification: spec.classification,
    access_scope: spec.accessScope,
    metric_definition_version: METRIC_DEFINITION_VERSION,
    payload: spec.payload,
  };
}
