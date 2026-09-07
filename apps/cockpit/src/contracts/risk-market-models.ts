/**
 * `RiskSnapshot`, `ShortSideSnapshot` and `MarketRegime` — `read-model-contracts.md` §4.5.
 *
 * **READ-ONLY, WITHOUT EXCEPTION.** These payloads change no threshold, trip no breaker and
 * reduce no exposure. The governed research values they carry are the ones in `CLAUDE.md`
 * §6, **reproduced for display context, labelled as research parameters, and changed
 * nowhere**.
 *
 * Three rules are structural here rather than advisory:
 *
 *   BORROW COMES FROM A RECORD    and is never inferred from price behaviour. An unknown
 *                                 borrow renders unknown or `BLOCKED_BORROW`, **never as
 *                                 available**, and every borrow figure carries the record
 *                                 reference it came from
 *   THE REGIME IS AN INPUT        displayed from a versioned context and **never recomputed
 *                                 by a view**. The view sizes no exposure
 *   NO PROFILE IS INVENTED        the information-set profile is **declared**, never
 *                                 inferred, and it has no default
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { refListFieldOf, refOf } from "./references";
import { analysisWindow, permittedScope } from "./portfolio-models";
import {
  currentOpenPlannedRisk,
  gapEventRisk,
  initialPlannedRisk,
  permittedRisk,
} from "./risk-records";
import {
  instant,
  magnitude,
  metricOf,
  policyRef,
  reasonCoded,
  recordValue,
  ref,
  safeId,
  series,
} from "./values";
import { informationProfile } from "./vocabularies";
import { isValueBearing } from "./validity";

/* ===================================================================== RiskSnapshot */

/**
 * §4.5 `RiskSnapshot`.
 *
 * The four risk quantities arrive here as `RecordValue`s, so **a missing assessment is
 * unavailable — never zero and never `NOT_APPLICABLE`** — and the portfolio aggregate is a
 * sum over **open exposure only, once per position**.
 */
export const riskSnapshotPayload = z.object({
  as_of: instant,
  /** The portfolio aggregate. PARTIAL where any component is stale or missing. */
  open_planned_risk: recordValue(currentOpenPlannedRisk),
  /** The immutable entry record of each open trade, listed rather than summed away. */
  /**
   * Every retained entry-time record on open exposure, one entry per STAGE.
   *
   * A pyramided trade retains one record per stage (§12.4), so it contributes more than one
   * entry and they share a `trade_ref`. `stage_ordinal` distinguishes them and is ADDITIVE:
   * it is absent on a trade that never added, where there is only the entry's record.
   *
   * Listing one record per TRADE would understate a pyramid's planned risk by everything its
   * adds contributed — on the demonstration book, 186.00 in place of 398.00 — and a risk
   * surface is the last place to report a smaller number than the records carry.
   */
  initial_planned_risk_open: z.array(
    z.object({
      trade_ref: refOf("RiskSnapshot.initial_planned_risk_open[].trade_ref"),
      stage_ordinal: z.number().int().nonnegative().optional(),
      value: recordValue(initialPlannedRisk),
    }),
  ),
  /**
   * Every permitted value carries its `PolicyRef`. Displayed, never computed.
   *
   * The scope is carried beside the wrapper for the reason `ExposureAggregate` does: a limit
   * whose policy reference is missing is an ABSENT record, and an absent record cannot name
   * which limit it was going to be.
   */
  permitted: z.array(
    z.object({ scope: permittedScope, value: recordValue(permittedRisk) }),
  ),
  concentration: metricOf("risk.concentration"),
  exposure_refs: refListFieldOf("RiskSnapshot.exposure_refs"),
  portfolio_volatility: metricOf("risk.portfolio_volatility"),
  /** A separate model where it applies. Never added into either planned-risk figure. */
  gap_event_risk: recordValue(gapEventRisk).optional(),
  /**
   * The recorded loss and drawdown thresholds.
   *
   * `policy_ref` is present **exactly when** the value is value-bearing: a threshold that is
   * merely named carries no approved number, and a number with no versioned reference is a
   * limit nobody approved at a version nobody can name. Naming the thresholds while reporting
   * every value as unavailable is the honest state of a project with no risk-limit policy —
   * and it is not the same as reporting no thresholds at all.
   */
  loss_thresholds: z.array(
    z
      .object({
        threshold: reasonCoded,
        value: metricOf("risk.loss_threshold"),
        policy_ref: policyRef.optional(),
      })
      .superRefine((candidate, ctx) => {
        const bearing = isValueBearing(candidate.value.availability);
        if (bearing !== (candidate.policy_ref !== undefined)) {
          ctx.addIssue({
            code: "custom",
            message:
              "a threshold states a value with its governing policy reference, or states " +
              "neither",
          });
        }
      }),
  ),
  risk_tier: reasonCoded,
  /** A recorded state. This application trips no breaker and resets none. */
  circuit_breaker_state: reasonCoded,
  new_entry_state: reasonCoded,
  decisions: z.array(
    z.object({ decision_ref: ref, at: instant, outcome: reasonCoded }),
  ),
});
export type RiskSnapshotPayload = z.infer<typeof riskSnapshotPayload>;

export const RISK_SNAPSHOT_SCHEMA = "cockpit.risk_snapshot.v2";
export const riskSnapshotEnvelope = envelope(riskSnapshotPayload, RISK_SNAPSHOT_SCHEMA);

/* ================================================================ ShortSideSnapshot */

/**
 * One security's borrow record.
 *
 * `availability` here is the BORROW availability — a closed vocabulary describing whether
 * shares can be borrowed — and it is **not** an `AvailabilityState`. The two are different
 * questions, so the borrow record carries a `ReasonCoded` and the surrounding `MetricValue`s
 * carry the data-availability axis independently.
 *
 * **Every figure carries `record_ref`**, the borrow record it was read from. A fee, a
 * quantity and a shortability answer are three separate observations, so each carries its
 * own as-of through its own `MetricValue`.
 */
export const borrowRecord = z.object({
  security_ref: refOf("ShortSideSnapshot.borrow[].security_ref"),
  security_label: z.string().min(1),
  availability: reasonCoded,
  fee: metricOf("borrow.fee"),
  quantity: metricOf("borrow.quantity"),
  deterioration: metricOf("borrow.deterioration"),
  record_ref: refOf("ShortSideSnapshot.borrow[].record_ref"),
});
export type BorrowRecord = z.infer<typeof borrowRecord>;

/**
 * §4.5 `ShortSideSnapshot`.
 *
 * Short-specific risk **has no long-side mirror**, which is why it has its own screen and
 * its own contract. **Gate G5 — historical borrow qualification — is OPEN**, and every
 * borrow statistic inherits that.
 */
export const shortSideSnapshotPayload = z.object({
  as_of: instant,
  short_positions: refListFieldOf("ShortSideSnapshot.short_positions"),
  borrow: z.array(borrowRecord),
  crowding: metricOf("short.crowding"),
  utilization: metricOf("short.utilization"),
  squeeze_state: reasonCoded,
  ssr_state: reasonCoded,
  recall_risk: reasonCoded,
  gross_short: magnitude,
  /** Scope `GROSS_SHORT`. A permitted limit is displayed and is never granted by showing it. */
  permitted_gross_short: recordValue(permittedRisk),
  /** The scope that limit would carry, so an absent one still names itself. */
  permitted_gross_short_scope: permittedScope,
  /**
   * Candidates the system declined for a borrow reason.
   *
   * A blocked short is a **decision that was taken**, not an opportunity that was measured:
   * no counterfactual outcome is carried here, because computing one needs a price path
   * nobody has and Missed Opportunities (Area 8, C6) owns that question.
   */
  blocked_shorts: z.array(z.object({ candidate_ref: ref, reason: reasonCoded })),
  /** What a borrow-related miss summary would need, and does not have. Named, not blank. */
  missed_opportunity_ref: refOf("ShortSideSnapshot.missed_opportunity_ref"),
});
export type ShortSideSnapshotPayload = z.infer<typeof shortSideSnapshotPayload>;

export const SHORT_SIDE_SNAPSHOT_SCHEMA = "cockpit.short_side_snapshot.v2";
export const shortSideSnapshotEnvelope = envelope(
  shortSideSnapshotPayload,
  SHORT_SIDE_SNAPSHOT_SCHEMA,
);

/* ====================================================================== MarketRegime */

/**
 * §4.5 `MarketRegime`.
 *
 * `context_version` is the identity: **the regime is displayed from a versioned context and
 * never recomputed by a view**, so two screens showing the same `context_version` are
 * showing the same recorded regime rather than two independent derivations of it.
 */
export const marketRegimePayload = z.object({
  context_version: safeId,
  as_of: instant,
  regime: reasonCoded,
  /** Trend, breadth, volatility, momentum-crash state, factor regime, event stress. */
  components: z.array(
    z.object({
      component: reasonCoded,
      value: metricOf("market.component_score"),
      /** The scale the score is read on, so a number is not read as a percentage. */
      scale: reasonCoded,
    }),
  ),
  stress: metricOf("market.stress"),
  /** The recorded regime history. A `Series`, so a gap is PARTIAL and never a zero. */
  history: series,
  /** DECLARED, never inferred. No default profile exists. */
  information_profile: informationProfile,
  /**
   * ADDITIVE: sector leadership and weakness, and the long and short context Area 11 names.
   * Each is a recorded, versioned observation rather than a computed ranking.
   */
  sector_context: z.array(
    z.object({
      sector: reasonCoded,
      standing: reasonCoded,
      value: metricOf("market.component_score"),
    }),
  ),
  side_context: z.array(z.object({ side: z.enum(["LONG", "SHORT"]), stance: reasonCoded })),
  /** The window the history covers, stated with its calendar and timezone. */
  window: analysisWindow,
});
export type MarketRegimePayload = z.infer<typeof marketRegimePayload>;

export const MARKET_REGIME_SCHEMA = "cockpit.market_regime.v2";
export const marketRegimeEnvelope = envelope(marketRegimePayload, MARKET_REGIME_SCHEMA);
