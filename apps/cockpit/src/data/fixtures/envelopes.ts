/**
 * Envelope construction for the fixture adapter.
 *
 * A fixture's `source_effective_time` is pinned at a SESSION ORIGIN captured once, so
 * REFETCHING AN UNCHANGED FIXTURE CANNOT REFRESH ITS SOURCE TIMESTAMP (ADR-0029 §2.2).
 * Only `evaluation_time` moves between fetches, which is exactly the behaviour of a real
 * source fact observed at a fixed instant.
 */
import type { FreshnessInput, FreshnessReport } from "@/contracts/freshness";
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

function buildInput(spec: InputSpec, originMs: number, evaluationMs: number): FreshnessInput {
  const effectiveMs = originMs - spec.ageAtOriginSeconds * 1000;
  const ageSeconds = Math.max(0, Math.floor((evaluationMs - effectiveMs) / 1000));
  const stale = ageSeconds >= spec.contractMaxAgeSeconds;
  return {
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
  const inputs = specs.map((spec) => buildInput(spec, originMs, evaluationMs));
  const required = inputs.filter((input) => input.required);
  const oldest = required.reduce<FreshnessInput | undefined>((worst, input) => {
    const age = input.source_age.value as number;
    const worstAge = worst === undefined ? -1 : (worst.source_age.value as number);
    return age > worstAge ? input : worst;
  }, undefined);
  const compositeState: AvailabilityState = required.some((input) => input.state === "STALE")
    ? "STALE"
    : "AVAILABLE";
  const evaluationInstant = instantOf(evaluationMs);
  const oldestAge = oldest === undefined ? 0 : (oldest.source_age.value as number);
  return {
    inputs,
    oldest_required: oldest?.input_id,
    source_age: available({
      metricId: "freshness.source_age",
      unit: "SECONDS",
      value: oldestAge,
      asOf: evaluationInstant,
    }),
    projection_lag: available({
      metricId: "freshness.projection_lag",
      unit: "SECONDS",
      value: Math.max(0, Math.floor((projectedMs - (originMs - oldestAge * 1000)) / 1000)),
      asOf: evaluationInstant,
    }),
    /** The ONLY age a rebuild resets. */
    build_age: available({
      metricId: "freshness.build_age",
      unit: "SECONDS",
      value: Math.max(0, Math.floor((evaluationMs - projectedMs) / 1000)),
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
  readonly maturityStage: MaturityStage;
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
