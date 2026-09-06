"use client";

import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { EnvelopeOf } from "@/contracts/envelope";
import type {
  ExecutiveOverviewPayload,
  PerformanceSeriesPayload,
  QualificationStatusPayload,
} from "@/contracts/read-models";
import type {
  ExposureAggregatePayload,
  PerformanceSummaryPayload,
  PositionSnapshotPayload,
  TradeDetailPayload,
  TradeLifecyclePayload,
  TradeSummaryPayload,
} from "@/contracts/portfolio-models";
import type { StrategyPerformancePayload } from "@/contracts/strategy-models";
import type {
  MarketRegimePayload,
  RiskSnapshotPayload,
  ShortSideSnapshotPayload,
} from "@/contracts/risk-market-models";
import { useReadClient } from "@/components/shell/providers";
import { PERFORMANCE_PERIODS, type PerformancePeriod, type ViewScope } from "@/lib/scope";

import { readModelKey } from "./query-keys";
import {
  ATTENTION_IDENTITY,
  EXECUTIVE_OVERVIEW_IDENTITY,
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
} from "./read-model-identity";
import type { AttentionListPayload, WhatChangedPayload } from "./read-client";

/**
 * Query hooks.
 *
 * Every key carries the API version, the schema version, the source provenance, the
 * classification, the access scope and the whole scope, so a scope change is a DIFFERENT
 * CACHE ENTRY and old data is never flashed under a new badge. React Query returns no data
 * for a key it has not seen, which is the isolation this depends on rather than a manual
 * cache clear.
 */

export function useExecutiveOverview(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<ExecutiveOverviewPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(EXECUTIVE_OVERVIEW_IDENTITY, scope),
    queryFn: () => client.executiveOverview(scope),
  });
}

export function useAttention(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<AttentionListPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(ATTENTION_IDENTITY, scope),
    queryFn: () => client.attention(scope),
  });
}

export function useWhatChanged(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<WhatChangedPayload>> {
  const client = useReadClient();
  return useQuery({
    /*
     * The comparison variant joins the key as an explicit query parameter. It selects WHICH
     * comparison is asked for, so two variants are two different reads -- and without it here
     * a variant change updated the URL while React Query served the previous variant's answer.
     */
    queryKey: readModelKey(WHAT_CHANGED_IDENTITY, scope, [scope.changes]),
    queryFn: () => client.whatChanged(scope),
  });
}

export function useQualificationStatus(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<QualificationStatusPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(QUALIFICATION_IDENTITY, scope),
    queryFn: () => client.qualificationStatus(scope),
  });
}

/**
 * The performance overview's series.
 *
 * The period joins the key as an explicit query parameter, so changing the range is a
 * DIFFERENT READ rather than the same one re-rendered — and one range's points can never be
 * drawn under another range's label while the new answer is still in flight.
 */
export function usePerformanceSeries(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<PerformanceSeriesPayload>> {
  const client = useReadClient();
  return useQuery({
    /*
     * BOTH request parameters join the key. A period changes the EXTENT and a granularity
     * changes the SAMPLING, so daily-over-a-year and monthly-over-a-year are two different
     * reads, and one range's points can never be drawn under another's label while the new
     * answer is still in flight.
     */
    queryKey: readModelKey(PERFORMANCE_SERIES_IDENTITY, scope, [
      scope.period,
      scope.granularity,
    ]),
    queryFn: () => client.performanceSeries(scope),
  });
}

/* ------------------------------------------------------------------ added by C5 */

/**
 * One window summary.
 *
 * The window is an explicit parameter, so the trailing-window table below can ask for five of
 * them at once and each keeps its own cache entry.
 */
export function usePerformanceSummary(
  scope: ViewScope,
  window: PerformancePeriod,
): UseQueryResult<EnvelopeOf<PerformanceSummaryPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(PERFORMANCE_SUMMARY_IDENTITY, scope, [window]),
    queryFn: () => client.performanceSummary(scope, window),
  });
}

/**
 * Every trailing window at once.
 *
 * `useQueries` rather than a loop of `useQuery`, because the number of hooks a component
 * calls may not vary between renders. Each window is still its own request and its own cache
 * entry — this batches the SUBSCRIPTION, not the reads.
 */
export function useTrailingWindowSummaries(
  scope: ViewScope,
): readonly UseQueryResult<EnvelopeOf<PerformanceSummaryPayload>>[] {
  const client = useReadClient();
  return useQueries({
    queries: PERFORMANCE_PERIODS.map((window) => ({
      queryKey: readModelKey(PERFORMANCE_SUMMARY_IDENTITY, scope, [window]),
      queryFn: () => client.performanceSummary(scope, window),
    })),
  });
}

export function usePositions(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<PositionSnapshotPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(POSITION_SNAPSHOT_IDENTITY, scope),
    queryFn: () => client.positions(scope),
  });
}

export function useExposure(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<ExposureAggregatePayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(EXPOSURE_AGGREGATE_IDENTITY, scope),
    queryFn: () => client.exposure(scope),
  });
}

export function useTrades(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<TradeSummaryPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(TRADE_SUMMARY_IDENTITY, scope),
    queryFn: () => client.trades(scope),
  });
}

/** The trade identity joins the key, so two trades are two entries. */
export function useTradeDetail(
  scope: ViewScope,
  tradeId: string,
): UseQueryResult<EnvelopeOf<TradeDetailPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(TRADE_DETAIL_IDENTITY, scope, [tradeId]),
    queryFn: () => client.tradeDetail(scope, tradeId),
  });
}

export function useTradeLifecycle(
  scope: ViewScope,
  tradeId: string,
): UseQueryResult<EnvelopeOf<TradeLifecyclePayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(TRADE_LIFECYCLE_IDENTITY, scope, [tradeId]),
    queryFn: () => client.tradeLifecycle(scope, tradeId),
  });
}

export function useStrategyPerformance(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<StrategyPerformancePayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(STRATEGY_PERFORMANCE_IDENTITY, scope),
    queryFn: () => client.strategyPerformance(scope),
  });
}

export function useRiskSnapshot(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<RiskSnapshotPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(RISK_SNAPSHOT_IDENTITY, scope),
    queryFn: () => client.riskSnapshot(scope),
  });
}

export function useShortSide(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<ShortSideSnapshotPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(SHORT_SIDE_IDENTITY, scope),
    queryFn: () => client.shortSide(scope),
  });
}

export function useMarketRegime(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<MarketRegimePayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey(MARKET_REGIME_IDENTITY, scope),
    queryFn: () => client.marketRegime(scope),
  });
}
