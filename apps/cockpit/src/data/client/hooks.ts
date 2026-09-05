"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { EnvelopeOf } from "@/contracts/envelope";
import {
  ATTENTION_LIST_SCHEMA,
  EXECUTIVE_OVERVIEW_SCHEMA,
  QUALIFICATION_STATUS_SCHEMA,
  WHAT_CHANGED_SCHEMA,
  type ExecutiveOverviewPayload,
  type QualificationStatusPayload,
} from "@/contracts/read-models";
import { useReadClient } from "@/components/shell/providers";
import type { ViewScope } from "@/lib/scope";

import { readModelKey } from "./query-keys";
import type { AttentionListPayload, WhatChangedPayload } from "./read-client";

/**
 * Query hooks.
 *
 * Every key carries the API version, the schema version, the environment and the source
 * provenance, so a scope change is a DIFFERENT CACHE ENTRY and old data is never flashed
 * under a new badge. React Query returns no data for a key it has not seen, which is the
 * isolation this depends on rather than a manual cache clear.
 */

export function useExecutiveOverview(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<ExecutiveOverviewPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey("executive-overview", EXECUTIVE_OVERVIEW_SCHEMA, scope),
    queryFn: () => client.executiveOverview(scope),
  });
}

export function useAttention(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<AttentionListPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey("attention", ATTENTION_LIST_SCHEMA, scope),
    queryFn: () => client.attention(scope),
  });
}

export function useWhatChanged(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<WhatChangedPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey("what-changed", WHAT_CHANGED_SCHEMA, scope),
    queryFn: () => client.whatChanged(scope),
  });
}

export function useQualificationStatus(
  scope: ViewScope,
): UseQueryResult<EnvelopeOf<QualificationStatusPayload>> {
  const client = useReadClient();
  return useQuery({
    queryKey: readModelKey("qualification-status", QUALIFICATION_STATUS_SCHEMA, scope),
    queryFn: () => client.qualificationStatus(scope),
  });
}
