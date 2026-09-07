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
import { targetAvailability } from "@/contracts/reference-access";
import type { ProducerState } from "@/contracts/reference-access";
import {
  attentionListEnvelope,
  executiveOverviewEnvelope,
  performanceSeriesEnvelope,
  qualificationStatusEnvelope,
  whatChangedEnvelope,
} from "@/contracts/read-models";
import {
  exposureAggregateEnvelope,
  performanceSummaryEnvelope,
  positionSnapshotEnvelope,
  tradeDetailEnvelope,
  tradeLifecycleEnvelope,
  tradeSummaryEnvelope,
} from "@/contracts/portfolio-models";
import type {
  ExposureAggregatePayload,
  PerformanceSummaryPayload,
  PositionSnapshotPayload,
  TradeDetailPayload,
  TradeLifecyclePayload,
  TradeSummaryPayload,
} from "@/contracts/portfolio-models";
import {
  candidateDetailEnvelope,
  candidateFunnelEnvelope,
  candidateSummaryEnvelope,
  missedOpportunityEnvelope,
} from "@/contracts/signal-models";
import type {
  CandidateDetailPayload,
  CandidateFunnelPayload,
  CandidateSummaryPayload,
  MissedOpportunityPayload,
} from "@/contracts/signal-models";
import { strategyPerformanceEnvelope } from "@/contracts/strategy-models";
import type { StrategyPerformancePayload } from "@/contracts/strategy-models";
import {
  marketRegimeEnvelope,
  riskSnapshotEnvelope,
  shortSideSnapshotEnvelope,
} from "@/contracts/risk-market-models";
import type {
  MarketRegimePayload,
  RiskSnapshotPayload,
  ShortSideSnapshotPayload,
} from "@/contracts/risk-market-models";
import type {
  ExecutiveOverviewPayload,
  PerformanceSeriesPayload,
  QualificationStatusPayload,
} from "@/contracts/read-models";
import { CLOCK_SKEW_TOLERANCE_SECONDS } from "@/contracts/freshness";
import type { EnvelopeOf } from "@/contracts/envelope";
import type {
  AvailabilityState,
  Completeness,
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
  CANDIDATE_DETAIL_IDENTITY,
  CANDIDATE_FUNNEL_IDENTITY,
  CANDIDATE_SUMMARY_IDENTITY,
  EXECUTIVE_OVERVIEW_IDENTITY,
  MISSED_OPPORTUNITY_IDENTITY,
  EXPOSURE_AGGREGATE_IDENTITY,
  MARKET_REGIME_IDENTITY,
  PERFORMANCE_SERIES_IDENTITY,
  PERFORMANCE_SUMMARY_IDENTITY,
  POSITION_SNAPSHOT_IDENTITY,
  QUALIFICATION_IDENTITY,
  RISK_SNAPSHOT_IDENTITY,
  SHORT_SIDE_IDENTITY,
  STRATEGY_PERFORMANCE_IDENTITY,
  TRADE_DETAIL_IDENTITY,
  TRADE_LIFECYCLE_IDENTITY,
  TRADE_SUMMARY_IDENTITY,
  WHAT_CHANGED_IDENTITY,
  type ReadModelIdentity,
} from "@/data/client/read-model-identity";
import type { Clock } from "@/lib/clock";
import { systemClock } from "@/lib/clock";
import type { PerformancePeriod, ViewScope } from "@/lib/scope";

import { instantOf } from "@/contracts/factories";
import { buildEnvelope, type InputSpec } from "./envelopes";
import { BOOK, bookSessions } from "./book";
import { equityWindow } from "./equity";
import { syntheticPerformanceSeries } from "./performance";
import { syntheticExposure, syntheticPositions } from "./positions";
import { syntheticMarketRegime } from "./regime";
import { syntheticRiskSnapshot, syntheticShortSide } from "./risk";
import { syntheticStrategyPerformance } from "./strategy";
import { buildPerformanceSummary } from "./summary";
import {
  findBookTrade,
  syntheticTradeDetail,
  syntheticTradeLifecycle,
  syntheticTrades,
} from "./trades";
import {
  syntheticAttention,
  syntheticExecutiveOverview,
  syntheticWhatChanged,
} from "./synthetic";
import {
  candidateRecord,
  syntheticCandidateDetail,
  syntheticCandidateFunnel,
  syntheticCandidates,
  syntheticMissedOpportunities,
} from "./signals";
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
  const exactAgeSeconds = (originMs - snapshotMs) / 1000;
  /*
   * NOT CLAMPED AT ZERO, and not thrown either.
   *
   * `Math.max(0, ...)` stood here and reported a snapshot dated AFTER the session origin --
   * a workstation whose clock disagrees with the transcription date -- as a snapshot
   * transcribed THIS INSTANT: the freshest required input on the page, on the one read model
   * whose facts are real.
   *
   * The honest answer is neither a zero nor a crash. Beyond the declared tolerance, this
   * clock cannot establish when the snapshot was true, so the input carries NO SOURCE TIME
   * and §3.1's fixed answer applies -- NOT_YET_AVAILABLE, SOURCE_TIMESTAMP_MISSING, and an
   * age that is UNKNOWN. The page still renders, and it says what it does not know. Within
   * the tolerance the negative age reaches `buildInput`, which flags it.
   */
  if (exactAgeSeconds < -CLOCK_SKEW_TOLERANCE_SECONDS) {
    return {
      id: "governance.tracked_snapshot",
      required: true,
      ageAtOriginSeconds: 0,
      contractMaxAgeSeconds: GOVERNANCE_SNAPSHOT_CONTRACT_SECONDS,
      sourceTimeUnavailable: true,
    };
  }
  return {
    id: "governance.tracked_snapshot",
    required: true,
    ageAtOriginSeconds: Math.floor(exactAgeSeconds),
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
  /** `PARTIAL` where the payload covers only part of the extent it was asked for. */
  readonly completeness?: Completeness;
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

/**
 * What a read model reports when a REQUESTED TARGET IDENTITY could not be served.
 *
 * The rule lives once, in `contracts/reference-access.ts`, and this is the ordinary read path
 * running into it -- not a helper only a test calls. `producer` is `IMPLEMENTED` exactly
 * where this application has a synthetic producer for the requested scope, and `located` is
 * whether that producer holds a record for the requested identity.
 *
 * **An implemented producer that lacks one record is `REFERENT_NOT_FOUND` (ADR-0030 R6, R9)**,
 * and it used to be `NOT_APPLICABLE` with `NOT_DEFINED_FOR_SUBJECT`. R9 refuses that reading
 * outright: an identifier that names nothing is *we do not have it*, the question still
 * applies to the subject, and `NOT_APPLICABLE` keeps its two ADR-0028 routes.
 */
function targetResolution<T>(producer: ProducerState, located: boolean): Resolution<T> {
  const absence = targetAvailability(producer, located);
  return { availability: absence.availability, availabilityReason: absence.reason };
}

/** Whether this application produces the operational read models for the requested scope. */
function producerFor(scope: ViewScope): ProducerState {
  return scope.scenario === "demo" ? "IMPLEMENTED" : "NOT_IMPLEMENTED_FOR_SCOPE";
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
      completeness: resolution.completeness,
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
          payload: demo ? syntheticExecutiveOverview(asOf, this.originMs) : undefined,
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
          payload: demo ? syntheticAttention(asOf, instantOf(this.originMs - 86_400_000)) : undefined,
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
   *
   * The demonstration variant selects WHICH of §7's four behaviours to show, and is only
   * honoured inside the already-labelled synthetic scenario. In project scope the answer is
   * the same one it has always been, because there is genuinely no baseline endpoint to
   * compare against: no projection exists that could have produced one.
   */
  async whatChanged(scope: ViewScope): Promise<EnvelopeOf<WhatChangedPayload>> {
    const asOf = instantOf(this.clock.now());
    const demo = scope.scenario === "demo";
    const populated = isPopulated(scope);
    const baselineAsOf = instantOf(this.originMs - 86_400_000);
    const variant = scope.changes === "auto" ? "valid" : scope.changes;
    const payload = demo ? syntheticWhatChanged(variant, asOf, baselineAsOf) : undefined;
    const resolution: Resolution<WhatChangedPayload> = !populated
      ? unpopulated()
      : {
          // In project scope there is no baseline endpoint at all.
          availability: demo ? "AVAILABLE" : "NOT_YET_AVAILABLE",
          availabilityReason: demo ? "NONE" : "UPSTREAM_INPUT_MISSING",
          payload,
          maturityStage: POPULATED_MATURITY,
          /*
           * A comparison whose endpoints are degraded, or which has no baseline at all, has
           * not covered the extent it was asked for. The envelope says PARTIAL rather than
           * letting a complete-looking response carry an incomplete answer.
           */
          completeness:
            payload !== undefined &&
            (variant === "degraded" || payload.baseline_state !== undefined)
              ? "PARTIAL"
              : "COMPLETE",
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
   * The performance overview's series.
   *
   * `PerformanceSeries` is §4.5's own contract, so the chart draws a validated read model
   * with provenance, an as-of, coverage and an availability state -- rather than a
   * chart-shaped array that would bypass admission and carry none of them.
   *
   * IN PROJECT SCOPE THERE IS NO SERIES AT ALL. The portfolio projection does not exist, so
   * there is no equity history, and the honest answer is a PAYLOADLESS `NOT_IMPLEMENTED` --
   * never a flat line at strategy capital, which would read as a portfolio that traded and
   * returned nothing.
   */
  async performanceSeries(scope: ViewScope): Promise<EnvelopeOf<PerformanceSeriesPayload>> {
    const asOf = instantOf(this.clock.now());
    const demo = scope.scenario === "demo";
    const populated = isPopulated(scope);
    /** The `ALL` period demonstrates a gapped extent, so `PARTIAL` is reachable on screen. */
    const withGap = scope.period === "ALL";
    const payload = demo
      ? syntheticPerformanceSeries({
          period: scope.period,
          granularity: scope.granularity,
          originMs: this.originMs,
          asOf,
          withGap,
        })
      : undefined;
    const resolution: Resolution<PerformanceSeriesPayload> = !populated
      ? unpopulated()
      : {
          availability: demo ? "AVAILABLE" : "NOT_IMPLEMENTED",
          availabilityReason: demo ? "NONE" : "PRODUCER_NOT_IMPLEMENTED",
          payload,
          maturityStage: POPULATED_MATURITY,
          completeness: payload === undefined ? undefined : withGap ? "PARTIAL" : "COMPLETE",
        };
    return this.respond(
      PERFORMANCE_SERIES_IDENTITY,
      "performance-series",
      scope,
      populated && demo
        ? [DEMO_MARK_INPUT, governanceInput(this.originMs)]
        : [governanceInput(this.originMs)],
      resolution,
      performanceSeriesEnvelope,
    );
  }

  /* ================================================================ added by C5 */

  /**
   * One resolution, for a read model whose whole payload is synthetic.
   *
   * Every C5 read model resolves the same way: the producing runtime does not exist, so the
   * honest project-scope answer is a PAYLOADLESS `NOT_IMPLEMENTED`, and the demonstration
   * scenario carries the repository-owned fixture. Written once, because thirteen copies of
   * one branch is thirteen places for one of them to drift.
   */
  private syntheticResolution<T>(
    scope: ViewScope,
    build: () => T,
    completeness?: Completeness,
  ): Resolution<T> {
    if (!isPopulated(scope)) {
      return unpopulated();
    }
    const demo = scope.scenario === "demo";
    return {
      availability: demo ? "AVAILABLE" : "NOT_IMPLEMENTED",
      availabilityReason: demo ? "NONE" : "PRODUCER_NOT_IMPLEMENTED",
      payload: demo ? build() : undefined,
      maturityStage: POPULATED_MATURITY,
      completeness: demo ? completeness : undefined,
    };
  }

  /** The inputs a demonstration payload depends on: a live mark, and the tracked snapshot. */
  private inputsFor(scope: ViewScope): readonly InputSpec[] {
    return isPopulated(scope) && scope.scenario === "demo"
      ? [DEMO_MARK_INPUT, governanceInput(this.originMs)]
      : [governanceInput(this.originMs)];
  }

  /** The retained extent's sessions, pinned to the session origin. */
  private sessions(): readonly string[] {
    return bookSessions(this.originMs);
  }

  async performanceSummary(
    scope: ViewScope,
    window: PerformancePeriod,
  ): Promise<EnvelopeOf<PerformanceSummaryPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<PerformanceSummaryPayload>(scope, () => {
      const equity = equityWindow(this.originMs, window);
      const firstSession = this.sessions().length - equity.days.length;
      return buildPerformanceSummary({
        days: equity.days,
        asOf,
        /*
         * The population is the trades that CLOSED INSIDE THE WINDOW, not the trades that
         * were open during it: a ratio over "closed trades" is a ratio over closed trades.
         */
        closed: BOOK.closedTrades.filter(
          (trade) => trade.exits[trade.exits.length - 1].session >= firstSession,
        ),
        periodReturns: equity.periodReturns,
        totalReturnHundredths: equity.totalReturnHundredths,
        maxDrawdownHundredths: equity.maxDrawdownHundredths,
        populationCode: "CLOSED_TRADES_IN_THE_REQUESTED_WINDOW",
      });
    });
    return this.respond(
      PERFORMANCE_SUMMARY_IDENTITY,
      `performance-summary-${window.toLowerCase()}`,
      scope,
      this.inputsFor(scope),
      resolution,
      performanceSummaryEnvelope,
    );
  }

  async positions(scope: ViewScope): Promise<EnvelopeOf<PositionSnapshotPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<PositionSnapshotPayload>(
      scope,
      () => syntheticPositions(asOf, this.sessions()),
      /** One assessment in the snapshot is STALE, so the page it covers is PARTIAL. */
      "PARTIAL",
    );
    return this.respond(
      POSITION_SNAPSHOT_IDENTITY,
      "position-snapshot",
      scope,
      this.inputsFor(scope),
      resolution,
      positionSnapshotEnvelope,
    );
  }

  async exposure(scope: ViewScope): Promise<EnvelopeOf<ExposureAggregatePayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<ExposureAggregatePayload>(
      scope,
      () => syntheticExposure(asOf, this.sessions()),
      "PARTIAL",
    );
    return this.respond(
      EXPOSURE_AGGREGATE_IDENTITY,
      "exposure-aggregate",
      scope,
      this.inputsFor(scope),
      resolution,
      exposureAggregateEnvelope,
    );
  }

  async trades(scope: ViewScope): Promise<EnvelopeOf<TradeSummaryPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<TradeSummaryPayload>(scope, () =>
      syntheticTrades(asOf, this.sessions()),
    );
    return this.respond(
      TRADE_SUMMARY_IDENTITY,
      "trade-summary",
      scope,
      this.inputsFor(scope),
      resolution,
      tradeSummaryEnvelope,
    );
  }

  /**
   * One trade's story.
   *
   * An unknown identity is `NOT_YET_AVAILABLE` with `REFERENT_NOT_FOUND`, and it used to be
   * `NOT_APPLICABLE` with `NOT_DEFINED_FOR_SUBJECT`. The ledger was searched, the producer
   * exists for this scope and there is no such trade — which ADR-0030 R9 states is exactly
   * *we do not have it*, so the question still applies to the subject and `NOT_APPLICABLE`
   * keeps its two ADR-0028 routes. It is **not `EMPTY_VERIFIED`** — that state is
   * value-bearing and describes a collection that came back empty, and a single read model
   * has no empty list to return. It is also not a 404 a caller has to interpret.
   */
  async tradeDetail(
    scope: ViewScope,
    tradeId: string,
  ): Promise<EnvelopeOf<TradeDetailPayload>> {
    const asOf = instantOf(this.clock.now());
    const trade = findBookTrade(tradeId);
    const producer = producerFor(scope);
    const resolution: Resolution<TradeDetailPayload> = !isPopulated(scope)
      ? unpopulated()
      : producer === "NOT_IMPLEMENTED_FOR_SCOPE" || trade === undefined
        ? targetResolution(producer, false)
        : {
            availability: "AVAILABLE",
            availabilityReason: "NONE",
            payload: syntheticTradeDetail(trade, this.sessions(), asOf),
            maturityStage: POPULATED_MATURITY,
            /** Every trade's detail names the stages it does not carry. */
            completeness: "PARTIAL",
          };
    return this.respond(
      TRADE_DETAIL_IDENTITY,
      `trade-detail-${tradeId}`,
      scope,
      this.inputsFor(scope),
      resolution,
      tradeDetailEnvelope,
    );
  }

  async tradeLifecycle(
    scope: ViewScope,
    tradeId: string,
  ): Promise<EnvelopeOf<TradeLifecyclePayload>> {
    const asOf = instantOf(this.clock.now());
    const trade = findBookTrade(tradeId);
    const producer = producerFor(scope);
    const resolution: Resolution<TradeLifecyclePayload> = !isPopulated(scope)
      ? unpopulated()
      : producer === "NOT_IMPLEMENTED_FOR_SCOPE" || trade === undefined
        ? targetResolution(producer, false)
        : {
            availability: "AVAILABLE",
            availabilityReason: "NONE",
            payload: syntheticTradeLifecycle(trade, this.sessions(), asOf),
            maturityStage: POPULATED_MATURITY,
            /** The basic lifecycle carries the trade stages and names every absent kind. */
            completeness: "PARTIAL",
          };
    return this.respond(
      TRADE_LIFECYCLE_IDENTITY,
      `trade-lifecycle-${tradeId}`,
      scope,
      this.inputsFor(scope),
      resolution,
      tradeLifecycleEnvelope,
    );
  }

  async strategyPerformance(
    scope: ViewScope,
  ): Promise<EnvelopeOf<StrategyPerformancePayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<StrategyPerformancePayload>(scope, () =>
      syntheticStrategyPerformance(asOf, this.sessions()),
    );
    return this.respond(
      STRATEGY_PERFORMANCE_IDENTITY,
      "strategy-performance",
      scope,
      this.inputsFor(scope),
      resolution,
      strategyPerformanceEnvelope,
    );
  }

  async riskSnapshot(scope: ViewScope): Promise<EnvelopeOf<RiskSnapshotPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<RiskSnapshotPayload>(
      scope,
      () => syntheticRiskSnapshot(asOf, this.sessions(), this.originMs),
      "PARTIAL",
    );
    return this.respond(
      RISK_SNAPSHOT_IDENTITY,
      "risk-snapshot",
      scope,
      this.inputsFor(scope),
      resolution,
      riskSnapshotEnvelope,
    );
  }

  async shortSide(scope: ViewScope): Promise<EnvelopeOf<ShortSideSnapshotPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<ShortSideSnapshotPayload>(
      scope,
      () => syntheticShortSide(asOf, this.sessions()),
      /** One borrow record is missing, so the snapshot covers part of its short book. */
      "PARTIAL",
    );
    return this.respond(
      SHORT_SIDE_IDENTITY,
      "short-side-snapshot",
      scope,
      this.inputsFor(scope),
      resolution,
      shortSideSnapshotEnvelope,
    );
  }

  async marketRegime(scope: ViewScope): Promise<EnvelopeOf<MarketRegimePayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<MarketRegimePayload>(scope, () =>
      syntheticMarketRegime(asOf, this.sessions()),
    );
    return this.respond(
      MARKET_REGIME_IDENTITY,
      "market-regime",
      scope,
      this.inputsFor(scope),
      resolution,
      marketRegimeEnvelope,
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
  /* ---------------------------------------------------------- added by C6 */

  async candidateFunnel(scope: ViewScope): Promise<EnvelopeOf<CandidateFunnelPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<CandidateFunnelPayload>(scope, () =>
      syntheticCandidateFunnel(asOf, this.sessions()),
    );
    return this.respond(
      CANDIDATE_FUNNEL_IDENTITY,
      "candidate-funnel",
      scope,
      this.inputsFor(scope),
      resolution,
      candidateFunnelEnvelope,
    );
  }

  async candidates(scope: ViewScope): Promise<EnvelopeOf<CandidateSummaryPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<CandidateSummaryPayload>(scope, () =>
      syntheticCandidates(asOf, this.sessions()),
    );
    return this.respond(
      CANDIDATE_SUMMARY_IDENTITY,
      "candidate-summary",
      scope,
      this.inputsFor(scope),
      resolution,
      candidateSummaryEnvelope,
    );
  }

  /**
   * One candidate's explanation.
   *
   * An unknown identity is `NOT_YET_AVAILABLE` with `REFERENT_NOT_FOUND` (ADR-0030 R6, R9) —
   * the journal was searched, the synthetic producer exists for this scope, and no such
   * candidate was recorded. It is the state the blocked-short references reach: the two
   * `blocked_shorts[].candidate_ref` identifiers are not in the book, and following one used
   * to report that the question did not apply rather than that the record was not written.
   * **It is never another candidate**, and never a default fixture: serving the nearest row
   * under a requested identity is how a reader ends up reading one decision's evidence under
   * another decision's name.
   */
  async candidateDetail(
    scope: ViewScope,
    candidateId: string,
  ): Promise<EnvelopeOf<CandidateDetailPayload>> {
    const asOf = instantOf(this.clock.now());
    const record = candidateRecord(candidateId);
    const producer = producerFor(scope);
    const resolution: Resolution<CandidateDetailPayload> = !isPopulated(scope)
      ? unpopulated()
      : producer === "NOT_IMPLEMENTED_FOR_SCOPE" || record === undefined
        ? targetResolution(producer, false)
        : {
            availability: "AVAILABLE",
            availabilityReason: "NONE",
            payload: syntheticCandidateDetail(record, this.sessions(), asOf),
            maturityStage: POPULATED_MATURITY,
            /** Every candidate names the evidence its decision did not have. */
            completeness: "PARTIAL",
          };
    return this.respond(
      CANDIDATE_DETAIL_IDENTITY,
      `candidate-detail-${candidateId}`,
      scope,
      this.inputsFor(scope),
      resolution,
      candidateDetailEnvelope,
    );
  }

  async missedOpportunities(
    scope: ViewScope,
  ): Promise<EnvelopeOf<MissedOpportunityPayload>> {
    const asOf = instantOf(this.clock.now());
    const resolution = this.syntheticResolution<MissedOpportunityPayload>(scope, () =>
      syntheticMissedOpportunities(asOf, this.sessions()),
    );
    return this.respond(
      MISSED_OPPORTUNITY_IDENTITY,
      "missed-opportunity",
      scope,
      this.inputsFor(scope),
      resolution,
      missedOpportunityEnvelope,
    );
  }

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
