"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { EnvelopeOf } from "@/contracts/envelope";
import type {
  ExecutiveOverviewPayload,
  QualificationStatusPayload,
} from "@/contracts/read-models";
import { useReadClient } from "@/components/shell/providers";
import type { ViewScope } from "@/lib/scope";

import { readModelKey } from "./query-keys";
import {
  ATTENTION_IDENTITY,
  EXECUTIVE_OVERVIEW_IDENTITY,
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
    queryKey: readModelKey(WHAT_CHANGED_IDENTITY, scope),
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
