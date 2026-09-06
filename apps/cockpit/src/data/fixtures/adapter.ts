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
 *
 * ONE ENVIRONMENT IS POPULATED, AND THE OTHER TWO ARE EXPLICITLY UNAVAILABLE. Every fact
 * this application holds -- the repository's own governance record, and the repository-owned
 * synthetic fixtures -- belongs to the RESEARCH runtime environment. There is no Paper and
 * no Live cockpit data, so selecting Paper or Live returns a PAYLOADLESS response saying so
 * rather than the same record under a different badge. Relabelling would fabricate evidence
 * of Paper or Live operation out of a viewer's selection, and none exists: `AUTOMATED_PAPER`
 * has never been reached and live trading is HARD-DISABLED.
 */
import {
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
import type {
  AvailabilityState,
  Environment,
  FieldReasonCode,
  HostingBoundary,
  MaturityStage,
} from "@/contracts/vocabularies";
import {
  admit,
  type AttentionListPayload,
  type ReadClient,
  type WhatChangedPayload,
} from "@/data/client/read-client";
import {
  ATTENTION_IDENTITY,
  EXECUTIVE_OVERVIEW_IDENTITY,
  QUALIFICATION_IDENTITY,
  WHAT_CHANGED_IDENTITY,
  type ReadModelIdentity,
} from "@/data/client/read-model-identity";
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
 * The one environment this application holds facts for, and the maturity stage that
 * accepted mapping pairs with it (COCKPIT_FEEDBACK_EXTENSION.md section 4.1).
 */
const POPULATED_ENVIRONMENT: Environment = "RESEARCH";
const POPULATED_MATURITY: MaturityStage = "RESEARCH";

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

/** What a read model resolves to under one scope. */
interface Resolution<T> {
  readonly availability: AvailabilityState;
  readonly availabilityReason: FieldReasonCode;
  readonly payload?: T;
  readonly maturityStage?: MaturityStage;
}

/**
 * An unpopulated scope, stated rather than papered over.
 *
 * The producing subsystem for a Paper or Live cockpit does not exist, which is what
 * `NOT_IMPLEMENTED` means exactly (`ui-ux-specification.md` section 9.2). It carries NO
 * payload and NO maturity stage: nothing has reached `AUTOMATED_PAPER`, and claiming a
 * stage here would be the fabrication this branch exists to prevent.
 */
function unpopulated<T>(): Resolution<T> {
  return { availability: "NOT_IMPLEMENTED", availabilityReason: "PRODUCER_NOT_IMPLEMENTED" };
}

function isPopulated(scope: ViewScope): boolean {
  return scope.environment === POPULATED_ENVIRONMENT;
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

  /**
   * Builds and admits one response.
   *
   * Provenance, classification and access scope come from the READ MODEL'S OWN IDENTITY --
   * the same object the cache key is built from -- so a response and its cache entry cannot
   * describe different sources.
   */
  private respond<T>(
    identity: ReadModelIdentity,
    entityId: string,
    scope: ViewScope,
    inputs: readonly InputSpec[],
    resolution: Resolution<T>,
    schema: Parameters<typeof admit>[1],
  ): EnvelopeOf<T> {
    const evaluationMs = this.clock.now();
    const candidate = buildEnvelope<T>({
      schemaVersion: identity.schemaVersion,
      entityId,
      availability: resolution.availability,
      availabilityReason: resolution.availabilityReason,
      provenance: identity.provenance,
      classification: identity.classification,
      environment: scope.environment,
      maturityStage: resolution.maturityStage,
      accessScope: identity.accessScope,
      inputs,
      payload: resolution.payload,
      originMs: this.originMs,
      evaluationMs,
    });
    return admit(identity.readModel, schema, candidate, this.boundary) as EnvelopeOf<T>;
  }

  async executiveOverview(scope: ViewScope): Promise<EnvelopeOf<ExecutiveOverviewPayload>> {
    const asOf = instantOf(this.clock.now());
    const demo = scope.scenario === "demo";
    const populated = isPopulated(scope);
    const resolution: Resolution<ExecutiveOverviewPayload> = !populated
      ? unpopulated()
      : {
          // The producing projections do not exist, so the honest default is PAYLOADLESS.
          availability: demo ? "AVAILABLE" : "NOT_IMPLEMENTED",
          availabilityReason: demo ? "NONE" : "PRODUCER_NOT_IMPLEMENTED",
          payload: demo ? syntheticExecutiveOverview(asOf) : undefined,
          maturityStage: POPULATED_MATURITY,
        };
    return this.respond(
      EXECUTIVE_OVERVIEW_IDENTITY,
      "executive-overview",
      scope,
      populated && demo
        ? [DEMO_MARK_INPUT, governanceInput(this.originMs)]
        : [governanceInput(this.originMs)],
      resolution,
      executiveOverviewEnvelope,
    );
  }

  async attention(scope: ViewScope): Promise<EnvelopeOf<AttentionListPayload>> {
    const asOf = instantOf(this.clock.now());
    const demo = scope.scenario === "demo";
    const populated = isPopulated(scope);
    const resolution: Resolution<AttentionListPayload> = !populated
      ? unpopulated()
      : {
          availability: demo ? "AVAILABLE" : "NOT_IMPLEMENTED",
          availabilityReason: demo ? "NONE" : "PRODUCER_NOT_IMPLEMENTED",
          payload: demo ? syntheticAttention(asOf) : undefined,
          maturityStage: POPULATED_MATURITY,
        };
    return this.respond(
      ATTENTION_IDENTITY,
      "attention-list",
      scope,
      [governanceInput(this.originMs)],
      resolution,
      attentionListEnvelope,
    );
  }

  /**
   * What Changed needs TWO valid, consistently scoped endpoints. Without them the correct
   * answer is the unavailable state, NEVER an invented delta -- a delta computed against a
   * missing baseline is a fabricated change (ui-ux-specification.md section 7).
   */
  async whatChanged(scope: ViewScope): Promise<EnvelopeOf<WhatChangedPayload>> {
    const asOf = instantOf(this.clock.now());
    const demo = scope.scenario === "demo";
    const populated = isPopulated(scope);
    const baselineAsOf = instantOf(this.originMs - 86_400_000);
    const resolution: Resolution<WhatChangedPayload> = !populated
      ? unpopulated()
      : {
          // In project scope there is no baseline endpoint at all.
          availability: demo ? "AVAILABLE" : "NOT_YET_AVAILABLE",
          availabilityReason: demo ? "NONE" : "UPSTREAM_INPUT_MISSING",
          payload: demo ? syntheticWhatChanged(asOf, baselineAsOf) : undefined,
          maturityStage: POPULATED_MATURITY,
        };
    return this.respond(
      WHAT_CHANGED_IDENTITY,
      "what-changed",
      scope,
      [governanceInput(this.originMs)],
      resolution,
      whatChangedEnvelope,
    );
  }

  /**
   * The one read model whose facts are REAL in both scenarios. They are REPOSITORY_TRACKED
   * and are never relabelled SYNTHETIC to fit a scenario selector.
   *
   * They are also never relabelled into another ENVIRONMENT. These are the repository's own
   * governance facts, recorded under the project's actual runtime environment, which is
   * RESEARCH; under a Paper or Live selector there is no such record to show.
   */
  async qualificationStatus(scope: ViewScope): Promise<EnvelopeOf<QualificationStatusPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution: Resolution<QualificationStatusPayload> = !isPopulated(scope)
      ? unpopulated()
      : {
          availability: "AVAILABLE",
          availabilityReason: "NONE",
          payload: qualificationStatusFacts(asOf),
          maturityStage: POPULATED_MATURITY,
        };
    return this.respond(
      QUALIFICATION_IDENTITY,
      "qualification-status",
      scope,
      [governanceInput(this.originMs)],
      resolution,
      qualificationStatusEnvelope,
    );
  }
}

export { POPULATED_ENVIRONMENT, POPULATED_MATURITY, READ_AT_COMMIT, SNAPSHOT_AS_OF };
