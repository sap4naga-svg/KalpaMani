/**
 * The C3 payload contracts, transcribed from `read-model-contracts.md` §4.5.
 *
 * SCOPE: `ExecutiveOverview`, `AttentionItem`, `WhatChangedEntry` and `QualificationStatus`
 * — the read models the C3 foundation actually renders. The catalog is larger, and no
 * claim is made here that every catalogued read model exists.
 */
import { z } from "zod";

import { envelope } from "./envelope";
import {
  countValue,
  dateOnly,
  instant,
  magnitude,
  metricValue,
  money,
  policyRef,
  reasonCoded,
  recordValue,
  refList,
  safeId,
} from "./values";
import { availabilityState, fieldReasonCode } from "./vocabularies";

/** §4.4 — the four risk quantities, kept apart. C3 renders two of them. */
export const currentOpenPlannedRisk = z.object({
  amount: money,
  as_of: instant,
  policy: policyRef,
  staleness: z.enum(["FRESH", "STALE"]),
});

export const permittedRisk = z.object({
  amount: money,
  policy: policyRef,
  scope: z.literal("OPEN_PORTFOLIO"),
});

const pnlWindow = z.object({
  window: z.enum(["DAY", "WEEK", "MONTH", "CUMULATIVE"]),
  /** realized and unrealized are NEVER summed into one unlabelled figure. */
  realized: metricValue,
  unrealized: metricValue,
});

export const executiveOverviewPayload = z.object({
  /** USD 80,000, authoritative. NEVER substituted by broker-reported equity. */
  strategy_capital: money,
  /** OBSERVED, informational, and never substituted for strategy capital. */
  broker_reported_equity: metricValue,
  cash: metricValue,
  pnl: z.array(pnlWindow),
  return_pct: metricValue,
  exposure: z.object({
    long: magnitude,
    short: magnitude,
    gross: magnitude,
    net: magnitude,
  }),
  open_planned_risk: recordValue(currentOpenPlannedRisk),
  permitted_open_risk: recordValue(permittedRisk),
  drawdown: metricValue,
  system_health: reasonCoded,
  /** The age of the OLDEST required input, never the newest and never the build age. */
  data_freshness: metricValue,
  active_strategies: countValue,
  open_incidents: countValue,
  /** One entry per tile, so a PARTIAL page names its failing parts. */
  tile_availability: z.array(
    z.object({ tile_id: safeId, availability: availabilityState, reason: fieldReasonCode }),
  ),
});
export type ExecutiveOverviewPayload = z.infer<typeof executiveOverviewPayload>;

export const EXECUTIVE_OVERVIEW_SCHEMA = "cockpit.executive_overview.v1";
export const executiveOverviewEnvelope = envelope(
  executiveOverviewPayload,
  EXECUTIVE_OVERVIEW_SCHEMA,
);

/**
 * §4.5 `AttentionItem`. An item missing any of the five presented things is NOT RENDERED,
 * and `recommended_action` is drawn from a closed governance vocabulary containing no
 * order, stop, capital, risk, promotion or provider verb.
 */
export const attentionItemPayload = z.object({
  item_id: safeId,
  what_happened: reasonCoded,
  why_it_matters: reasonCoded,
  impact: metricValue,
  evidence_refs: refList,
  recommended_action: reasonCoded,
  severity: reasonCoded,
  materiality_rank: z.number().int(),
  dedup_key: safeId,
  first_seen: instant,
  last_seen: instant,
  occurrence_count: countValue,
});
export type AttentionItemPayload = z.infer<typeof attentionItemPayload>;

export const ATTENTION_LIST_SCHEMA = "cockpit.attention_list.v1";
export const attentionListEnvelope = envelope(
  z.object({ items: z.array(attentionItemPayload) }),
  ATTENTION_LIST_SCHEMA,
);

/**
 * §4.5 `WhatChangedEntry`. A change with no resolvable evidence reference is not rendered,
 * and a change is NEVER synthesised from the absence of a value.
 */
export const whatChangedEntryPayload = z.object({
  change_id: safeId,
  subject: reasonCoded,
  change_kind: reasonCoded,
  /** Present when a prior value exists. A delta against a missing baseline is fabricated. */
  before: metricValue.optional(),
  after: metricValue,
  materiality: reasonCoded,
  evidence_refs: refList,
});
export type WhatChangedEntryPayload = z.infer<typeof whatChangedEntryPayload>;

export const WHAT_CHANGED_SCHEMA = "cockpit.what_changed.v1";
export const whatChangedEnvelope = envelope(
  z.object({
    /** The comparison window is explicit and displayed; both endpoints carry their as-of. */
    baseline_label: z.string().min(1),
    baseline_as_of: instant.optional(),
    comparison_as_of: instant.optional(),
    /** Present only when BOTH endpoints are available; otherwise the state says so. */
    entries: z.array(whatChangedEntryPayload),
  }),
  WHAT_CHANGED_SCHEMA,
);

/**
 * §4.5 `QualificationStatus` — REAL facts, provenance `REPOSITORY_TRACKED`, classification
 * `PUBLIC_SAFE`. Each fact carries the tracked source it was read from, each gate is read
 * INDEPENDENTLY, P1-P9 render `UNEVALUATED`, and Run B authorization and its date gate
 * render as TWO SEPARATE FACTS.
 */
const trackedSource = z.object({
  /** The exact tracked path the fact was read from. */
  path: z.string().min(1),
  /** The exact repository commit the fact was read at. */
  commit: z.string().regex(/^[0-9a-f]{40}$/, "commit must be a full 40-character SHA"),
});

export const qualificationStatusPayload = z.object({
  facts: z.array(
    z.object({
      fact_id: safeId,
      subject: reasonCoded,
      state: reasonCoded,
      as_of: dateOnly,
      source: trackedSource,
    }),
  ),
  gates: z.array(
    z.object({
      gate: z.enum(["G1", "G2", "G3", "G4", "G5", "G6", "G7"]),
      state: z.enum(["OPEN", "CLOSED"]),
      scope: reasonCoded,
      source: trackedSource,
    }),
  ),
  adr_states: z.array(
    z.object({ adr: safeId, state: reasonCoded, source: trackedSource }),
  ),
  /** P1 to P9, and UNEVALUATED is the only state this payload can carry today. */
  provider_tests: z.array(
    z.object({ test: reasonCoded, state: z.literal("UNEVALUATED") }),
  ),
  /** Authorization and date eligibility are TWO SEPARATE FACTS. */
  run_authorizations: z.array(
    z.object({
      run: reasonCoded,
      authorization: reasonCoded,
      date_gate: metricValue,
      source: trackedSource,
    }),
  ),
  phase_state: reasonCoded,
  live_trading: reasonCoded,
  /** The repository revision the facts were read from -- the payload identity. */
  read_at_commit: z.string().regex(/^[0-9a-f]{40}$/),
});
export type QualificationStatusPayload = z.infer<typeof qualificationStatusPayload>;

export const QUALIFICATION_STATUS_SCHEMA = "cockpit.qualification_status.v1";
export const qualificationStatusEnvelope = envelope(
  qualificationStatusPayload,
  QUALIFICATION_STATUS_SCHEMA,
);
