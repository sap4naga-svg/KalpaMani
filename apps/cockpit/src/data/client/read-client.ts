/**
 * The read-client boundary.
 *
 * This is the ONE seam the presentation layer talks to. In C3 it is satisfied by a local,
 * deterministic FIXTURE ADAPTER; a later authorized cycle satisfies it with the versioned
 * read API of ADR-0027 §4.
 *
 * IT IS A LOCAL SUBSTITUTE FOR A FUTURE TRANSPORT, AND NOT A CLAIM THAT THE FASTAPI
 * SERVICE OR ANY PRODUCTION PROJECTION EXISTS. Neither exists, and neither is authorized.
 *
 * The Cockpit has NO direct access to a provider API, provider credentials, AWS secrets,
 * IBKR trading APIs, brokerage credentials, mutable Brain internals or private
 * qualification artifacts (ADR-0027 §4). Nothing in this boundary opens a network
 * connection of any kind.
 */
import type { z } from "zod";

import { admissionFailure } from "@/contracts/admission";
import { owningAreaContradiction } from "@/contracts/references";
import type { EnvelopeOf } from "@/contracts/envelope";
import type {
  AttentionItemPayload,
  ExecutiveOverviewPayload,
  PerformanceSeriesPayload,
  QualificationStatusPayload,
  WhatChangedEntryPayload,
} from "@/contracts/read-models";
import type {
  ExposureAggregatePayload,
  PerformanceSummaryPayload,
  PositionSnapshotPayload,
  TradeDetailPayload,
  TradeLifecyclePayload,
  TradeSummaryPayload,
} from "@/contracts/portfolio-models";
import type {
  CandidateDetailPayload,
  CandidateFunnelPayload,
  CandidateSummaryPayload,
  MissedOpportunityPayload,
} from "@/contracts/signal-models";
import type {
  StrategyHealthPayload,
  StrategyPerformancePayload,
  StrategyVersionPayload,
} from "@/contracts/strategy-models";
import type {
  AiContributionPayload,
  ChampionChallengerPayload,
  FeedbackPipelinePayload,
  HypothesisRegistrationPayload,
  ResearchQueuePayload,
  ResearchRunPayload,
} from "@/contracts/research-models";
import type {
  DecisionRecordPayload,
  GovernancePacketPayload,
} from "@/contracts/governance-models";
import type {
  MarketRegimePayload,
  RiskSnapshotPayload,
  ShortSideSnapshotPayload,
} from "@/contracts/risk-market-models";
import type { HostingBoundary } from "@/contracts/vocabularies";
import type { PerformancePeriod, ViewScope } from "@/lib/scope";

/**
 * The comparison window, and both of its endpoints.
 *
 * A change is a statement about two instants. Carrying the window and both as-of times in the
 * payload is what lets a screen SAY what it compared, rather than presenting a delta whose
 * endpoints the reader has to assume (`ui-ux-specification.md` §7).
 */
export interface WhatChangedPayload {
  readonly baseline_label: string;
  readonly baseline_as_of?: string;
  readonly comparison_as_of?: string;
  /** Why no comparison was possible, when none was. A missing baseline is not a zero. */
  readonly baseline_state?: {
    readonly availability: import("@/contracts/vocabularies").AvailabilityState;
    readonly reason: import("@/contracts/vocabularies").FieldReasonCode;
  };
  readonly entries: WhatChangedEntryPayload[];
}

export interface AttentionListPayload {
  readonly items: AttentionItemPayload[];
}

export interface ReadClient {
  executiveOverview(scope: ViewScope): Promise<EnvelopeOf<ExecutiveOverviewPayload>>;
  attention(scope: ViewScope): Promise<EnvelopeOf<AttentionListPayload>>;
  whatChanged(scope: ViewScope): Promise<EnvelopeOf<WhatChangedPayload>>;
  qualificationStatus(scope: ViewScope): Promise<EnvelopeOf<QualificationStatusPayload>>;
  /**
   * The performance overview's series, over the scope's period.
   *
   * The period is a REQUEST PARAMETER and not a presentation preference: it changes the
   * extent the answer covers, so a caller that varies it is asking a different question and
   * gets a different cache entry.
   */
  performanceSeries(scope: ViewScope): Promise<EnvelopeOf<PerformanceSeriesPayload>>;

  /* ------------------------------------------------------------- added by C5 */

  /**
   * The window summary — the ratios, over one defined population.
   *
   * The window is an EXPLICIT parameter rather than the scope's period, because the portfolio
   * performance page reads SEVERAL of them at once to show trailing-window performance. Each
   * is a different question and each gets its own cache entry.
   */
  performanceSummary(
    scope: ViewScope,
    window: PerformancePeriod,
  ): Promise<EnvelopeOf<PerformanceSummaryPayload>>;

  positions(scope: ViewScope): Promise<EnvelopeOf<PositionSnapshotPayload>>;
  exposure(scope: ViewScope): Promise<EnvelopeOf<ExposureAggregatePayload>>;
  trades(scope: ViewScope): Promise<EnvelopeOf<TradeSummaryPayload>>;

  /**
   * One trade's story, and one trade's basic lifecycle.
   *
   * The trade identity is a request parameter and joins the cache key, so two trades are two
   * entries and one is never served under the other's identity.
   */
  tradeDetail(scope: ViewScope, tradeId: string): Promise<EnvelopeOf<TradeDetailPayload>>;
  tradeLifecycle(
    scope: ViewScope,
    tradeId: string,
  ): Promise<EnvelopeOf<TradeLifecyclePayload>>;

  strategyPerformance(scope: ViewScope): Promise<EnvelopeOf<StrategyPerformancePayload>>;
  riskSnapshot(scope: ViewScope): Promise<EnvelopeOf<RiskSnapshotPayload>>;
  shortSide(scope: ViewScope): Promise<EnvelopeOf<ShortSideSnapshotPayload>>;
  marketRegime(scope: ViewScope): Promise<EnvelopeOf<MarketRegimePayload>>;

  /* ------------------------------------------------------------- added by C6 */

  /**
   * The signal funnel, the candidate ledger, one candidate's explanation, and the misses.
   *
   * The candidate identity is a request parameter and joins the cache key, so two candidates
   * are two entries and one is never served under the other's identity — exactly as the trade
   * identity does on `tradeDetail`.
   */
  candidateFunnel(scope: ViewScope): Promise<EnvelopeOf<CandidateFunnelPayload>>;
  candidates(scope: ViewScope): Promise<EnvelopeOf<CandidateSummaryPayload>>;
  candidateDetail(
    scope: ViewScope,
    candidateId: string,
  ): Promise<EnvelopeOf<CandidateDetailPayload>>;
  missedOpportunities(scope: ViewScope): Promise<EnvelopeOf<MissedOpportunityPayload>>;

  /* ------------------------------------------------------------- added by C7 */

  /**
   * The research, feedback and governance read models — Areas 5, 14 to 21.
   *
   * **Ten reads, and not one write.** There is no method here that advances a stage, registers
   * a hypothesis, launches a run, promotes a version, approves a packet or records a decision,
   * and the interface is where such a method would have to appear first. The learning engine
   * WRITES and the Cockpit READS; they are different systems, and **neither exists**.
   */
  strategyHealth(scope: ViewScope): Promise<EnvelopeOf<StrategyHealthPayload>>;
  strategyVersions(scope: ViewScope): Promise<EnvelopeOf<StrategyVersionPayload>>;
  researchRuns(scope: ViewScope): Promise<EnvelopeOf<ResearchRunPayload>>;
  researchQueue(scope: ViewScope): Promise<EnvelopeOf<ResearchQueuePayload>>;
  hypotheses(scope: ViewScope): Promise<EnvelopeOf<HypothesisRegistrationPayload>>;
  championChallenger(scope: ViewScope): Promise<EnvelopeOf<ChampionChallengerPayload>>;
  aiContribution(scope: ViewScope): Promise<EnvelopeOf<AiContributionPayload>>;
  feedbackPipeline(scope: ViewScope): Promise<EnvelopeOf<FeedbackPipelinePayload>>;
  governancePackets(scope: ViewScope): Promise<EnvelopeOf<GovernancePacketPayload>>;
  decisions(scope: ViewScope): Promise<EnvelopeOf<DecisionRecordPayload>>;
}

export class ContractViolationError extends Error {
  constructor(readModel: string, detail: string) {
    super(`read model ${readModel} refused at the boundary: ${detail}`);
    this.name = "ContractViolationError";
  }
}

/**
 * Validate a response against its schema and the admission rules, or refuse it.
 *
 * An unknown `schema_version` is REJECTED, never coerced (§3), and a payload that fails
 * §7.1 admission is REFUSED rather than downgraded.
 */
export function admit<S extends z.ZodTypeAny>(
  readModel: string,
  schema: S,
  candidate: unknown,
  boundary: HostingBoundary,
): z.infer<S> {
  const parsed = schema.safeParse(candidate);
  if (!parsed.success) {
    throw new ContractViolationError(readModel, parsed.error.issues[0]?.message ?? "invalid");
  }
  /*
   * THE OWNING-AREA CONTRADICTION IS AN ADMISSION-UNIT RULE, SO IT IS CHECKED HERE.
   *
   * A reference cannot see the reference beside it, and a `RefList` cannot see the scalar
   * `Ref` in another field of the same response -- so a per-reference or per-list refinement
   * would state section 4.3.2's rule narrower than its own reason. This is the one place that
   * holds the whole admission unit, which is exactly the scope the rule names.
   */
  const contradiction = owningAreaContradiction(parsed.data);
  if (contradiction !== null) {
    throw new ContractViolationError(readModel, contradiction);
  }
  const envelopeLike = parsed.data as { classification: never; provenance: never };
  const failure = admissionFailure({
    readModel,
    classification: envelopeLike.classification,
    provenance: envelopeLike.provenance,
    boundary,
  });
  if (failure !== null) {
    throw new ContractViolationError(readModel, failure);
  }
  return parsed.data;
}
