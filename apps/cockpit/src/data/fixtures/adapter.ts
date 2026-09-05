/**
 * The C3 fixture adapter.
 *
 * An explicit ASYNCHRONOUS adapter behind the typed read-client boundary. It returns
 * validated, versioned response shapes and is A LOCAL SUBSTITUTE FOR THE FUTURE API
 * TRANSPORT -- not a claim that the FastAPI service or any production projection exists.
 * Neither exists and neither is authorized.
 *
 * It opens no socket, reads no file at request time, and reaches no provider, broker, AWS
 * account, GitHub API or model endpoint.
 *
 * Two scenarios, and they are PROVENANCE rather than environment:
 *
 *   project  REPOSITORY_TRACKED governance facts. Operational read models whose producing
 *            subsystem does not exist are NOT_IMPLEMENTED and PAYLOADLESS -- the honest
 *            default.
 *   demo     SYNTHETIC fixtures that populate the visual states, labelled unmissably.
 */
import {
  ATTENTION_LIST_SCHEMA,
  EXECUTIVE_OVERVIEW_SCHEMA,
  QUALIFICATION_STATUS_SCHEMA,
  WHAT_CHANGED_SCHEMA,
  attentionListEnvelope,
  executiveOverviewEnvelope,
  qualificationStatusEnvelope,
  whatChangedEnvelope,
} from "@/contracts/read-models";
import type {
  ExecutiveOverviewPayload,
  QualificationStatusPayload,
} from "@/contracts/read-models";
import type { EnvelopeOf } from "@/contracts/envelope";
import type { HostingBoundary } from "@/contracts/vocabularies";
import {
  admit,
  type AttentionListPayload,
  type ReadClient,
  type WhatChangedPayload,
} from "@/data/client/read-client";
import type { Clock } from "@/lib/clock";
import { systemClock } from "@/lib/clock";
import type { ViewScope } from "@/lib/scope";

import { instantOf } from "@/contracts/factories";
import { buildEnvelope, type InputSpec } from "./envelopes";
import {
  syntheticAttention,
  syntheticExecutiveOverview,
  syntheticWhatChanged,
} from "./synthetic";
import { READ_AT_COMMIT, SNAPSHOT_AS_OF, qualificationStatusFacts } from "./tracked-facts";

/**
 * The tracked governance snapshot's own freshness contract.
 *
 * A governance record is current for a long window; a position mark is not. Each input is
 * evaluated against ITS OWN contract, never a shared one.
 */
const GOVERNANCE_SNAPSHOT_CONTRACT_SECONDS = 60 * 60 * 24 * 30;

/**
 * The demonstration mark input. Its short contract is what makes the freshness deadline
 * OBSERVABLE: the executive demo view degrades to STALE while it stays mounted, without a
 * navigation, exactly as ADR-0029 section 2.2 requires.
 *
 * This also reproduces read-model-contracts.md section 3.1.1 CASE 5: the governance
 * snapshot is the OLDEST required input and is what `source_age` reports, while this input
 * carries the EARLIEST deadline and is what BINDS.
 */
const DEMO_MARK_CONTRACT_SECONDS = 60;
const DEMO_MARK_AGE_AT_ORIGIN_SECONDS = 45;

function governanceInput(originMs: number): InputSpec {
  const snapshotMs = Date.parse(`${SNAPSHOT_AS_OF}T00:00:00.000Z`);
  return {
    id: "governance.tracked_snapshot",
    required: true,
    ageAtOriginSeconds: Math.max(0, Math.floor((originMs - snapshotMs) / 1000)),
    contractMaxAgeSeconds: GOVERNANCE_SNAPSHOT_CONTRACT_SECONDS,
  };
}

const DEMO_MARK_INPUT: InputSpec = {
  id: "positions.mark",
  required: true,
  ageAtOriginSeconds: DEMO_MARK_AGE_AT_ORIGIN_SECONDS,
  contractMaxAgeSeconds: DEMO_MARK_CONTRACT_SECONDS,
};

export interface FixtureReadClientOptions {
  readonly clock?: Clock;
  readonly boundary?: HostingBoundary;
  /**
   * The session origin. Pinned once so REFETCHING AN UNCHANGED FIXTURE CANNOT REFRESH ITS
   * SOURCE TIMESTAMP. Defaults to the clock's first reading.
   */
  readonly originMs?: number;
}

export class FixtureReadClient implements ReadClient {
  private readonly clock: Clock;
  private readonly boundary: HostingBoundary;
  private readonly originMs: number;

  constructor(options: FixtureReadClientOptions = {}) {
    this.clock = options.clock ?? systemClock;
    this.boundary = options.boundary ?? "PUBLIC_EDGE";
    this.originMs = options.originMs ?? this.clock.now();
  }

  /** The pinned session origin, exposed so a view can label a demonstration clock. */
  get sessionOriginMs(): number {
    return this.originMs;
  }

  async executiveOverview(scope: ViewScope): Promise<EnvelopeOf<ExecutiveOverviewPayload>> {
    const evaluationMs = this.clock.now();
    const asOf = instantOf(evaluationMs);
    const demo = scope.scenario === "demo";
    const candidate = buildEnvelope<ExecutiveOverviewPayload>({
      schemaVersion: EXECUTIVE_OVERVIEW_SCHEMA,
      entityId: "executive-overview",
      // The producing projections do not exist, so the honest default is PAYLOADLESS.
      availability: demo ? "AVAILABLE" : "NOT_IMPLEMENTED",
      availabilityReason: demo ? "NONE" : "PRODUCER_NOT_IMPLEMENTED",
      // This read model is fixture-adapter output in BOTH scenarios -- populated in demo,
      // and an absence in project scope. Section 7.1 admits REPOSITORY_TRACKED only from
      // the enumerated governance read models, and this is not one of them.
      provenance: "SYNTHETIC",
      classification: "PUBLIC_SAFE",
      environment: scope.environment,
      maturityStage: "RESEARCH",
      accessScope: "executive:read",
      inputs: demo
        ? [DEMO_MARK_INPUT, governanceInput(this.originMs)]
        : [governanceInput(this.originMs)],
      payload: demo ? syntheticExecutiveOverview(asOf) : undefined,
      originMs: this.originMs,
      evaluationMs,
    });
    return admit(
      "ExecutiveOverview",
      executiveOverviewEnvelope,
      candidate,
      this.boundary,
    ) as EnvelopeOf<ExecutiveOverviewPayload>;
  }

  async attention(scope: ViewScope): Promise<EnvelopeOf<AttentionListPayload>> {
    const evaluationMs = this.clock.now();
    const asOf = instantOf(evaluationMs);
    const demo = scope.scenario === "demo";
    const candidate = buildEnvelope<AttentionListPayload>({
      schemaVersion: ATTENTION_LIST_SCHEMA,
      entityId: "attention-list",
      availability: demo ? "AVAILABLE" : "NOT_IMPLEMENTED",
      availabilityReason: demo ? "NONE" : "PRODUCER_NOT_IMPLEMENTED",
      // This read model is fixture-adapter output in BOTH scenarios -- populated in demo,
      // and an absence in project scope. Section 7.1 admits REPOSITORY_TRACKED only from
      // the enumerated governance read models, and this is not one of them.
      provenance: "SYNTHETIC",
      classification: "PUBLIC_SAFE",
      environment: scope.environment,
      maturityStage: "RESEARCH",
      accessScope: "executive:read",
      inputs: [governanceInput(this.originMs)],
      payload: demo ? syntheticAttention(asOf) : undefined,
      originMs: this.originMs,
      evaluationMs,
    });
    return admit(
      "AttentionItem",
      attentionListEnvelope,
      candidate,
      this.boundary,
    ) as EnvelopeOf<AttentionListPayload>;
  }

  /**
   * What Changed needs TWO valid, consistently scoped endpoints. Without them the correct
   * answer is the unavailable state, NEVER an invented delta -- a delta computed against a
   * missing baseline is a fabricated change (ui-ux-specification.md section 7).
   */
  async whatChanged(scope: ViewScope): Promise<EnvelopeOf<WhatChangedPayload>> {
    const evaluationMs = this.clock.now();
    const asOf = instantOf(evaluationMs);
    const demo = scope.scenario === "demo";
    const baselineAsOf = instantOf(this.originMs - 86_400_000);
    const candidate = buildEnvelope<WhatChangedPayload>({
      schemaVersion: WHAT_CHANGED_SCHEMA,
      entityId: "what-changed",
      // In project scope there is no baseline endpoint at all.
      availability: demo ? "AVAILABLE" : "NOT_YET_AVAILABLE",
      availabilityReason: demo ? "NONE" : "UPSTREAM_INPUT_MISSING",
      // This read model is fixture-adapter output in BOTH scenarios -- populated in demo,
      // and an absence in project scope. Section 7.1 admits REPOSITORY_TRACKED only from
      // the enumerated governance read models, and this is not one of them.
      provenance: "SYNTHETIC",
      classification: "PUBLIC_SAFE",
      environment: scope.environment,
      maturityStage: "RESEARCH",
      accessScope: "executive:read",
      inputs: [governanceInput(this.originMs)],
      payload: demo ? syntheticWhatChanged(asOf, baselineAsOf) : undefined,
      originMs: this.originMs,
      evaluationMs,
    });
    return admit(
      "WhatChangedEntry",
      whatChangedEnvelope,
      candidate,
      this.boundary,
    ) as EnvelopeOf<WhatChangedPayload>;
  }

  /**
   * The one read model whose facts are REAL in both scenarios. They are REPOSITORY_TRACKED
   * and are never relabelled SYNTHETIC to fit a scenario selector.
   */
  async qualificationStatus(scope: ViewScope): Promise<EnvelopeOf<QualificationStatusPayload>> {
    const evaluationMs = this.clock.now();
    const asOf = instantOf(evaluationMs);
    const candidate = buildEnvelope<QualificationStatusPayload>({
      schemaVersion: QUALIFICATION_STATUS_SCHEMA,
      entityId: "qualification-status",
      availability: "AVAILABLE",
      availabilityReason: "NONE",
      provenance: "REPOSITORY_TRACKED",
      classification: "PUBLIC_SAFE",
      environment: scope.environment,
      maturityStage: "RESEARCH",
      accessScope: "governance:read",
      inputs: [governanceInput(this.originMs)],
      payload: qualificationStatusFacts(asOf),
      originMs: this.originMs,
      evaluationMs,
    });
    return admit(
      "QualificationStatus",
      qualificationStatusEnvelope,
      candidate,
      this.boundary,
    ) as EnvelopeOf<QualificationStatusPayload>;
  }
}

export { READ_AT_COMMIT, SNAPSHOT_AS_OF };
