/**
 * The four risk quantities of `read-model-contracts.md` §4.4, kept apart.
 *
 * **"Planned risk" was one word doing four jobs**, and the four are different facts with
 * different owners, different lifetimes and different truth conditions. A screen that shows
 * one of them under another's label is asserting something nobody computed.
 *
 * They live in their own module because five read models carry them — the executive
 * overview, positions, exposure, trades and the risk snapshot — and a record defined beside
 * any one of those would be a record that view owns. **Defined once, used everywhere**
 * (§4.2).
 *
 * WHAT THIS MODULE DOES NOT DO. It computes no risk, sums no exposure, derives no limit and
 * grants no permission. Showing a permitted limit is not granting it, and **no view computes
 * a permitted exposure** (§4.4).
 */
import { z } from "zod";

import { refOf } from "./references";

import {
  instant,
  metricOf,
  policyRef,
  ratioOf,
  reasonCoded,
  safeId,
} from "./values";
import { money } from "./values";

/**
 * §4.4 `InitialPlannedRisk` — the entry-time reference, and **IMMUTABLE**.
 *
 * **The retained records are the only denominator an R multiple may use** — this record alone
 * on a trade that never added, and the SUM of every stage's on a trade that did (§12.4). A
 * moving stop does not move it, a protective-order change does not move it, and no projection
 * recomputes it from a current price. Its money is a plain `Money` rather than a `MetricValue`: a record that exists
 * carries the amount that was recorded, and whether the record exists at all is the
 * `RecordValue` wrapper's question.
 */
export const initialPlannedRisk = z.object({
  risk_money: money,
  /** Denominator STRATEGY_CAPITAL_AT_ENTRY — the capital as it was, not as it is. */
  risk_pct_of_capital: ratioOf("STRATEGY_CAPITAL_AT_ENTRY"),
  /** The entry reference the risk was set against. */
  reference_price: money,
  /** The invalidation level used AT ENTRY, carried as a reference and **never an order**. */
  invalidation_ref: refOf("InitialPlannedRisk.invalidation_ref"),
  /** When the risk record was written. Never the response's own time (§4.4). */
  recorded_at: instant,
  risk_policy_ref: policyRef,
  /** `RISK_RECORD_AT_ENTRY`, and no other source. */
  source: z.literal("RISK_RECORD_AT_ENTRY"),
});
export type InitialPlannedRisk = z.infer<typeof initialPlannedRisk>;

/**
 * §4.4 `CurrentOpenPlannedRisk` — the risk engine's **assessment of the remaining
 * exposure**, meaningless without its `as_of`.
 *
 * The Cockpit **displays it and computes none of it**. `staleness` describes a PRESENT
 * assessment; a MISSING assessment has no record at all and is carried by the wrapper,
 * "not by a record whose required fields nobody could fill".
 */
export const currentOpenPlannedRisk = z.object({
  risk_money: metricOf("risk.open_planned"),
  /** Denominator STRATEGY_CAPITAL_AS_OF — a different denominator from the initial record. */
  risk_pct_of_capital: metricOf("risk.open_planned_pct"),
  /** The assessment instant, **always displayed**. */
  as_of: instant,
  assessment_ref: refOf("CurrentOpenPlannedRisk.assessment_ref"),
  risk_policy_ref: policyRef,
  /** From the protective-order record, never from a price. */
  protection_state: reasonCoded,
  source: z.literal("RISK_ENGINE_ASSESSMENT"),
  staleness: z.enum(["FRESH", "STALE"]),
});
export type CurrentOpenPlannedRisk = z.infer<typeof currentOpenPlannedRisk>;

/**
 * §4.4 `PermittedRisk` — a separately governed **policy** value.
 *
 * "A permitted value with no versioned reference is `POLICY_REFERENCE_MISSING`, never a
 * number", so `policy_ref` is required on the record and a limit that has none is carried
 * as an ABSENT record by the wrapper instead.
 */
export const PERMITTED_RISK_SCOPES = [
  "PER_TRADE_LONG",
  "PER_TRADE_SHORT",
  "OPEN_PORTFOLIO",
  "INDIVIDUAL_POSITION",
  "GROSS_SHORT",
] as const;

export const permittedRisk = z.object({
  limit_money: metricOf("risk.permitted"),
  limit_pct: metricOf("risk.permitted_pct"),
  /** A permitted value NEVER appears without one. */
  policy_ref: policyRef,
  scope: z.enum(PERMITTED_RISK_SCOPES),
});
export type PermittedRisk = z.infer<typeof permittedRisk>;

/**
 * §4.4 `GapEventRisk` — a **separate model**, never folded into planned risk.
 *
 * "A modelled scenario and a recorded plan are different kinds of claim", so this is never
 * added into either planned-risk figure.
 */
export const gapEventRisk = z.object({
  modelled_loss: metricOf("gap_event.modelled_loss"),
  scenario_ref: refOf("GapEventRisk.scenario_ref"),
  model_version: safeId,
  as_of: instant,
});
export type GapEventRisk = z.infer<typeof gapEventRisk>;
