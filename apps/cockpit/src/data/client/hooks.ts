"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { EnvelopeOf } from "@/contracts/envelope";
import type {
  ExecutiveOverviewPayload,
  PerformanceSeriesPayload,
  QualificationStatusPayload,
} from "@/contracts/read-models";
import { useReadClient } from "@/components/shell/providers";
import type { ViewScope } from "@/lib/scope";

import { readModelKey } from "./query-keys";
import {
  ATTENTION_IDENTITY,
  EXECUTIVE_OVERVIEW_IDENTITY,
  PERFORMANCE_SERIES_IDENTITY,
  QUALIFICATION_IDENTITY,
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
    queryKey: readModelKey(PERFORMANCE_SERIES_IDENTITY, scope, [scope.period]),
    queryFn: () => client.performanceSeries(scope),
  });
}
