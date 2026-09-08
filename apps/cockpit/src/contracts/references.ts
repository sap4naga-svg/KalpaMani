/**
 * The reference boundary — `read-model-contracts.md` §4.2, §4.3 and §4.3.1, under ADR-0030.
 *
 * `values.ts` closes `Ref.ref_kind` at the twenty-seven members. That is the floor and not
 * the rule: WHICH kinds a field may carry, WHICH resolutions each kind admits, and WHETHER a
 * field may embed its target are all properties of the **host field**, so they are enforced
 * here, where the host field is known, and never inferred from the payload's contents.
 *
 * Four separations this module exists to keep:
 *
 *   PERMISSION vs TRUTH      a payload being present never authorizes `EMBEDDED` (R4). The
 *                            catalogue authorizes the host field, names the carrier, and
 *                            says whether it holds the complete target or a projection;
 *                            only then is the response checked for actually carrying it
 *   RELATION vs PAGE         `items`, `total` and `truncated` are three facts (R7). A
 *                            relation is never asserted satisfied from `items.length` while
 *                            `truncated` is true, and never from a total that is not
 *                            value-bearing
 *   TARGET vs CONTAINER      identity compares the target ENTITY's own identifier, never
 *                            the container it is retrieved through (R8)
 *   ABSENT RECORD vs         an implemented producer that lacks one record is
 *   ABSENT PRODUCER          `REFERENT_NOT_FOUND`, never `UNRESOLVABLE_V1` (R6, R9)
 *
 * **Nothing here resolves a reference over a network.** There is no fetcher, no proxy and no
 * generic resolver: this module validates declarations, and `lib/reference-navigation.ts`
 * maps a kind to an allowlisted internal route.
 */
import { z } from "zod";

import { ref, refList } from "./values";
import type { Ref, RefList } from "./values";
import { REF_KINDS } from "./vocabularies";
import type { Cardinality, RefKind, Resolution } from "./vocabularies";

/* ==================================================== the per-kind resolution sets (R3) */

/**
 * §4.3's Resolution column, transcribed as the PERMITTED SET each row names.
 *
 * The column is a set rather than a per-kind invariant — two accepted rows already carry two
 * members — and a reference declares ONE member of its row's set. `EMBEDDED` is deliberately
 * absent from every entry below: it is available to **every** row and is gated by catalogue
 * permission and truth instead of by enumeration (§4.3, R4), so it is checked against the
 * host field's `embeds` and never against this table.
 *
 * A kind whose row lists no `UNRESOLVABLE_V1` cannot declare one. That is the accepted text
 * rather than an omission: `UNRESOLVABLE_V1` says the PRODUCER does not exist, and for a kind
 * resolved by a catalogued GET or by an authorized read the absence of a TARGET is stated by
 * the value-bearing field it would have filled, or by a §5 error (R9).
 */
export const KIND_RESOLUTIONS: Readonly<Record<RefKind, readonly Resolution[]>> = {
  candidate: ["ENDPOINT", "UNRESOLVABLE_V1"],
  brain_decision: ["ENDPOINT", "UNRESOLVABLE_V1"],
  trade: ["ENDPOINT", "UNRESOLVABLE_V1"],
  risk_decision: ["AUTHORIZED_READ"],
  order: ["ENDPOINT"],
  fill: ["ENDPOINT"],
  protection: ["ENDPOINT"],
  add: ["ENDPOINT"],
  exit: ["ENDPOINT"],
  reconciliation: ["ENDPOINT"],
  execution_quality: ["ENDPOINT"],
  strategy_version: ["ENDPOINT"],
  health_transition: ["ENDPOINT"],
  research_run: ["ENDPOINT"],
  registration: ["ENDPOINT"],
  queue_item: ["ENDPOINT"],
  packet: ["ENDPOINT"],
  decision: ["ENDPOINT"],
  audit_event: ["AUTHORIZED_READ"],
  evidence: ["AUTHORIZED_READ"],
  chart_series: ["AUTHORIZED_READ", "UNRESOLVABLE_V1"],
  benchmark_series: ["AUTHORIZED_READ", "UNRESOLVABLE_V1"],
  regime_context: ["ENDPOINT"],
  data_quality: ["ENDPOINT"],
  incident: ["ENDPOINT"],
  alert: ["ENDPOINT"],
  source_fact: ["AUTHORIZED_READ"],
};

/**
 * The ACCESS SCOPE a read of each kind's target requires, transcribed from accepted text.
 *
 * **A required scope the caller may name is not a required scope.** `followReference` used to
 * take one as a parameter, so the authorization input was supplied by the thing being
 * authorized — and a caller free to name the requirement can name one it happens to hold.
 * The accepted contract states it, so the accepted contract is where it comes from.
 *
 * Two sources, in order of directness:
 *
 * ```text
 * §4.3's Resolution column   names the scope outright on the AUTHORIZED_READ rows --
 *                           risk_decision risk:read, audit_event audit:read, and both
 *                           chart_series and benchmark_series market:read
 * §4.5's read-model lines    name the scope of the read model §4.3's "Resolves to" column
 *                           points an ENDPOINT row at -- CandidateDetail signals:read,
 *                           TradeDetail portfolio:read, TradeLifecycle execution:read,
 *                           MarketRegime market:read, and so on for every row
 * ```
 *
 * **`evidence` and `source_fact` are `null`, and that is a stated limitation rather than an
 * omission.** Their rows read *"AUTHORIZED_READ — the scope named on the reference"*, and
 * §4.2 types `Ref` as `{ ref_id, ref_kind, resolution, classification }` — there is **no
 * scope field on a reference to name one in**. Adding one is a specification act reserved to
 * an ADR, so for those two kinds the caller's declared scope is the only available input and
 * is used as such, rather than a value invented here.
 */
export const KIND_READ_SCOPE: Readonly<Record<RefKind, string | null>> = {
  candidate: "signals:read",
  brain_decision: "signals:read",
  trade: "portfolio:read",
  risk_decision: "risk:read",
  order: "execution:read",
  fill: "execution:read",
  protection: "execution:read",
  add: "execution:read",
  exit: "execution:read",
  reconciliation: "execution:read",
  execution_quality: "execution:read",
  strategy_version: "strategy:read",
  health_transition: "strategy:read",
  research_run: "research:read",
  registration: "research:read",
  queue_item: "research:read",
  packet: "governance:read",
  decision: "governance:read",
  audit_event: "audit:read",
  evidence: null,
  chart_series: "market:read",
  benchmark_series: "market:read",
  regime_context: "market:read",
  data_quality: "system:read",
  incident: "system:read",
  alert: "system:read",
  source_fact: null,
};

/** The scope the accepted contract names for this kind, or `null` where it names none. */
export function contractReadScope(kind: RefKind): string | null {
  return KIND_READ_SCOPE[kind];
}

/**
 * §4.3's Cardinality column — the kind's GENERIC relation, recorded for traceability.
 *
 * **It is not the validation input** (R7). One kind is carried by both shapes: `source_fact`
 * is `ZERO_OR_MORE` here and is also carried by four required scalar `Ref` fields, none of
 * which can satisfy a list cardinality. What a validator checks is the HOST FIELD's own
 * declaration, below.
 */
export const KIND_RELATION: Readonly<Record<RefKind, Cardinality>> = {
  candidate: "ZERO_OR_ONE",
  brain_decision: "EXACTLY_ONE",
  trade: "ZERO_OR_ONE",
  risk_decision: "ZERO_OR_ONE",
  order: "ZERO_OR_MORE",
  fill: "ZERO_OR_MORE",
  protection: "ZERO_OR_MORE",
  add: "ZERO_OR_MORE",
  exit: "ZERO_OR_ONE",
  reconciliation: "ZERO_OR_MORE",
  execution_quality: "ZERO_OR_ONE",
  strategy_version: "EXACTLY_ONE",
  health_transition: "ZERO_OR_MORE",
  research_run: "ZERO_OR_MORE",
  registration: "ZERO_OR_ONE",
  queue_item: "ZERO_OR_MORE",
  packet: "ZERO_OR_ONE",
  decision: "ZERO_OR_MORE",
  audit_event: "ZERO_OR_MORE",
  evidence: "ZERO_OR_MORE",
  chart_series: "ZERO_OR_ONE",
  benchmark_series: "ZERO_OR_ONE",
  regime_context: "ZERO_OR_ONE",
  data_quality: "ZERO_OR_MORE",
  incident: "ZERO_OR_MORE",
  alert: "ZERO_OR_MORE",
  source_fact: "ZERO_OR_MORE",
};

/* ===================================================== identity correspondence (R4, R8) */

/**
 * How an embedded carrier's identity is compared with its reference's `ref_id`.
 *
 * A closed vocabulary rather than a free-form predicate, because "state identity
 * correspondence for every projection carrier" is a CONTRACT and a contract has to be
 * readable. Each member says what is compared, and every one of them compares the TARGET
 * entity rather than the container it arrived in (R8).
 */
export type IdentityCorrespondence =
  /** The carrier holds the target's own identifier, and it must equal `ref_id` exactly. */
  | { readonly rule: "TARGET_ID_FIELD"; readonly field: string }
  /** The carrier holds a `Ref` to itself, whose `ref_id` must equal `ref_id` exactly. */
  | { readonly rule: "TARGET_REF_FIELD"; readonly field: string }
  /**
   * The carrier holds a NATURAL KEY that a declared, deterministic rule canonicalizes into
   * the identifier. Used by the identifier-less `security` projection, where the comparand
   * is the `symbol` and NEVER the human-readable `display_name`.
   */
  | { readonly rule: "CANONICAL_KEY"; readonly field: string; readonly prefix: string }
  /**
   * The projection carries NO identifier of its own, so the reference identifier is derived
   * from the HOST entity's identifier by a declared suffix.
   *
   * **This establishes that the projection belongs to THIS host entity, and nothing more.**
   * It is not evidence that the carrier is the complete target — which is why every carrier
   * using it is declared a `DECLARED_PROJECTION`. It is still a real check: it refuses one
   * trade's detail carrying another trade's series reference.
   */
  | { readonly rule: "HOST_SCOPED_SUFFIX"; readonly hostIdField: string; readonly suffix: string };

/** Whether a named carrier holds the whole target, or a declared projection of it (R4). */
export type CarrierCompleteness = "COMPLETE_TARGET" | "DECLARED_PROJECTION";

export interface EmbedPermission {
  /** The target kind this host field may embed. */
  readonly kind: RefKind;
  /** The NAMED carrier field that holds it, on the object carrying the reference. */
  readonly carrier: string;
  readonly completeness: CarrierCompleteness;
  readonly identity: IdentityCorrespondence;
  /** What the carrier actually holds, so a projection is never read as the whole target. */
  readonly note: string;
}

/* ============================================================= the host-field catalogue */

export interface HostFieldDeclaration {
  readonly shape: "REF" | "REF_LIST";
  /**
   * The kind, or the stated SET of kinds, this field declares.
   *
   * A kind is a property of the FIELD and not of its NAME: the catalogue already gives
   * `evidence_refs` `source_fact` on three models and `evidence` on another.
   */
  readonly kinds: readonly RefKind[];
  readonly requiredness: "required" | "conditional" | "optional";
  /**
   * `REF_LIST` only, and present ONLY where the catalogue FIXES the field's relation.
   *
   * Most `RefList` fields state a kind and no cardinality, and for those §4.3.1 makes the
   * list's OWN `cardinality` the declaration: "its OWN `cardinality` governs; `items`,
   * `total` and `truncated` are checked against it". Forcing every list to the kind's generic
   * relation would be the per-kind validation input R7 refuses — and it would refuse a
   * producer that legitimately has exactly one target, which is a NARROWING the catalogue
   * permits. `AskAnswer.citations` is the one place the stronger relation is meant, and it is
   * the one place this is set.
   */
  readonly relation?: Cardinality;
  /** Every embed this host field is authorized to declare. Absent means: none. */
  readonly embeds?: readonly EmbedPermission[];
  /**
   * Whether this application implements the read model that carries the field.
   *
   * `false` is a SPECIFICATION-ONLY assignment: the field's kind is recorded so a later cycle
   * inherits an enforced contract rather than an open one, and **no model, producer, screen,
   * route or fixture is created by recording it**.
   */
  readonly implemented: boolean;
  /**
   * A nested target: the catalogue's container route and in-container selector (R8).
   *
   * Present only where the target lives INSIDE another read model's response. The reference
   * carries the nested entity's own identifier, so the container's id must come from the
   * host — which is why a nested kind gets no allowlisted route from `ref_id` alone.
   */
  readonly nested?: { readonly containerRoute: string; readonly selector: string };
}

const SECURITY_PROJECTION: EmbedPermission = {
  kind: "evidence",
  carrier: "security",
  completeness: "DECLARED_PROJECTION",
  identity: { rule: "CANONICAL_KEY", field: "symbol", prefix: "security-" },
  note:
    "a { symbol, display_name } display projection with no identifier of its own; the " +
    "comparand is the symbol, canonicalized, and never the display name",
};

/**
 * Every reference-valued field this contract knows of, and what it may carry.
 *
 * Sources, in order of authority: the §4.5 field lines that state a kind; §4.3.1's twenty-five
 * assignments; and — for fields this implementation added under ADR-0028's additive rule, and
 * which therefore have no §4.5 line — the kind the field's own contract text describes.
 */
export const REFERENCE_FIELDS = {
  /* ------------------------------------------------------------------ the envelope (§3) */
  /**
   * §3's plain list of source-fact references.
   *
   * **Its shape is not changed here** — no `cardinality`, `total` or `truncated` is added or
   * removed, and this entry only states what its items may be. With `source_fact` amended to
   * `ZERO_OR_MORE` (R7), an envelope whose producer references no source fact is conformant
   * rather than in breach of an inherited `ONE_OR_MORE`.
   */
  "Envelope.source_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },

  /* -------------------------------------------------------------------- C4 read models */
  "ExecutiveOverview.regime_ref": {
    shape: "REF",
    kinds: ["regime_context"],
    requiredness: "required",
    implemented: true,
  },
  "ExecutiveOverview.last_decision.ref": {
    shape: "REF",
    kinds: ["decision"],
    requiredness: "required",
    implemented: true,
  },
  "ExecutiveOverview.last_scout_run.ref": {
    shape: "REF",
    kinds: ["research_run"],
    requiredness: "required",
    implemented: true,
  },
  "ExecutiveOverview.what_changed": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "ExecutiveOverview.attention": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  /** §4.5 declares "kind `evidence` or `source_fact`" — a stated SET, and both are admitted. */
  "AttentionItem.evidence_refs": {
    shape: "REF_LIST",
    kinds: ["evidence", "source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "WhatChangedEntry.evidence_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "PerformanceSeries.benchmark_refs": {
    shape: "REF_LIST",
    kinds: ["benchmark_series"],
    requiredness: "required",
    implemented: true,
  },

  /* -------------------------------------------------------- the §4.4 risk record shapes */
  "InitialPlannedRisk.invalidation_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "CurrentOpenPlannedRisk.assessment_ref": {
    shape: "REF",
    kinds: ["risk_decision"],
    requiredness: "required",
    implemented: true,
  },
  "GapEventRisk.scenario_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },

  /* -------------------------------------------------------------------- C5 read models */
  "PositionSnapshot.security_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    embeds: [SECURITY_PROJECTION],
    implemented: true,
  },
  "PositionSnapshot.invalidation_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "PositionSnapshot.trade_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "ExposureAggregate.correlation_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "conditional",
    implemented: true,
  },
  "TradeSummary.security_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    embeds: [SECURITY_PROJECTION],
    implemented: true,
  },
  "TradeSummary.detail_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "TradeDetail.candidate_ref": {
    shape: "REF",
    kinds: ["candidate"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * R5: `ENDPOINT` from `TradeDetail`, resolving by the candidate route.
   *
   * **No brain-decision payload is added to `TradeDetail` to make `EMBEDDED` true** — that
   * would put a Brain payload inside a portfolio read model, which §4.3's "resolving a
   * reference is an authorized read, not a widening" forbids. There is no `embeds` entry
   * here, so an `EMBEDDED` declaration is refused whether or not a payload appears beside it.
   */
  "TradeDetail.brain_decision_ref": {
    shape: "REF",
    kinds: ["brain_decision"],
    requiredness: "required",
    implemented: true,
    nested: {
      containerRoute: "/signals/candidates/{candidate_id}",
      selector: "the journaled decision status inside CandidateDetail",
    },
  },
  "TradeDetail.risk_decision_ref": {
    shape: "REF",
    kinds: ["risk_decision"],
    requiredness: "required",
    implemented: true,
  },
  "TradeDetail.order_refs": {
    shape: "REF_LIST",
    kinds: ["order"],
    requiredness: "required",
    implemented: true,
  },
  "TradeDetail.fill_refs": {
    shape: "REF_LIST",
    kinds: ["fill"],
    requiredness: "required",
    implemented: true,
  },
  "TradeDetail.protection_refs": {
    shape: "REF_LIST",
    kinds: ["protection"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * The adds, as references into the lifecycle.
   *
   * **Not an authorized embed.** `add` resolves to `TradeLifecycle` add and pyramid EVENTS,
   * and `TradeDetail` carries none: `summary.add_planned_risk[]` is each add's retained RISK
   * RECORD, a different entity wearing an adjacent name. Naming it a carrier would be exactly
   * the "a field's name is not proof it contains the referenced entity" failure R4 exists to
   * refuse, so these resolve by the lifecycle endpoint instead.
   */
  "TradeDetail.add_refs": {
    shape: "REF_LIST",
    kinds: ["add"],
    requiredness: "required",
    implemented: true,
  },
  /** Required when CLOSED. Not an authorized embed, for the reason `add_refs` is not. */
  "TradeDetail.exit_ref": {
    shape: "REF",
    kinds: ["exit"],
    requiredness: "conditional",
    implemented: true,
  },
  "TradeDetail.reconciliation_refs": {
    shape: "REF_LIST",
    kinds: ["reconciliation"],
    requiredness: "required",
    implemented: true,
  },
  "TradeDetail.execution_quality_ref": {
    shape: "REF",
    kinds: ["execution_quality"],
    requiredness: "required",
    embeds: [
      {
        kind: "execution_quality",
        carrier: "execution_quality",
        completeness: "DECLARED_PROJECTION",
        identity: {
          rule: "HOST_SCOPED_SUFFIX",
          hostIdField: "trade_id",
          suffix: "-execution-quality",
        },
        note:
          "THIS trade's execution quality at AGGREGATE scope, not the Area 9 aggregate over " +
          "a window of fills; the record carries no identifier of its own",
      },
    ],
    implemented: true,
  },
  "TradeDetail.benchmark_series_ref": {
    shape: "REF",
    kinds: ["benchmark_series"],
    requiredness: "required",
    embeds: [
      {
        kind: "benchmark_series",
        carrier: "benchmark_series",
        completeness: "DECLARED_PROJECTION",
        identity: { rule: "HOST_SCOPED_SUFFIX", hostIdField: "trade_id", suffix: "-benchmark" },
        note:
          "a synthetic demonstration index aligned to this trade's holding-period " +
          "boundaries; a Series carries no identifier of its own",
      },
    ],
    implemented: true,
  },
  "TradeDetail.audit_refs": {
    shape: "REF_LIST",
    kinds: ["audit_event"],
    requiredness: "required",
    implemented: true,
  },
  "TradeDetail.chart_series_ref": {
    shape: "REF",
    kinds: ["chart_series"],
    requiredness: "required",
    embeds: [
      {
        kind: "chart_series",
        carrier: "chart_series",
        completeness: "DECLARED_PROJECTION",
        identity: { rule: "HOST_SCOPED_SUFFIX", hostIdField: "trade_id", suffix: "-marks" },
        note:
          "a MARK LINE and not OHLC: open, high, low and close need a market-data provider, " +
          "no provider is selected and G1 is OPEN",
      },
    ],
    implemented: true,
  },
  /**
   * The corrected event's kind, restricted to the lifecycle-event kinds §4.3 resolves into
   * `TradeLifecycle` — a stated FAMILY, exactly as §4.3.1 declares it.
   */
  "TradeLifecycle.events[].correction_of": {
    shape: "REF",
    kinds: ["order", "fill", "protection", "add", "exit"],
    requiredness: "conditional",
    implemented: true,
  },
  "TradeLifecycle.events[].source_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * The subject the quality was measured over — an ADR-0028 additive field with no §4.5 line.
   *
   * Its kind FOLLOWS `scope`, the way `correction_of`'s follows `event_kind`: an `ORDER`
   * record's subject is an order, a `FILL` record's is a fill, and an `AGGREGATE` record
   * inside `TradeDetail` is measured over the TRADE. It was emitted as `execution_quality` at
   * aggregate scope, which made the record its own subject.
   */
  "ExecutionQuality.subject_ref": {
    shape: "REF",
    kinds: ["order", "fill", "trade"],
    requiredness: "required",
    implemented: true,
  },
  "RiskDecision.candidate_ref": {
    shape: "REF",
    kinds: ["candidate"],
    requiredness: "required",
    implemented: true,
  },
  "RiskDecision.trade_ref": {
    shape: "REF",
    kinds: ["trade"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * The retained §4.4 initial-risk stage this decision is traceable to.
   *
   * **Not an authorized embed**, and it was declaring `EMBEDDED` while `RiskDecision` carried
   * no initial-risk record at all — an `EMBEDDED` that was not merely unpermitted but untrue.
   */
  "RiskDecision.initial_risk_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },

  /* ----------------------------------------------------------- C5 risk and market models */
  "RiskSnapshot.initial_planned_risk_open[].trade_ref": {
    shape: "REF",
    kinds: ["trade"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * The risk decisions this snapshot lists, each naming the decision record it points at.
   *
   * **`implemented` is `true`, and it read `false`.** This application serves `RiskSnapshot`
   * and its fixture emits this reference, so recording the producer as absent would make
   * `producerStateFor` answer `PRODUCER_NOT_IMPLEMENTED` for a producer that exists for
   * `SYNTHETIC` provenance — which R6 states asserts something false about the subsystem.
   * It sat among the specification-only C6 entries, which is how the flag came to disagree
   * with every other `RiskSnapshot.*` row, so it is recorded beside them instead.
   */
  "RiskSnapshot.decisions[].decision_ref": {
    shape: "REF",
    kinds: ["risk_decision"],
    requiredness: "required",
    implemented: true,
  },
  "RiskSnapshot.exposure_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "ShortSideSnapshot.short_positions": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * **Not an authorized embed**, and the reason is the one this audit exists to catch: the
   * only thing beside it is `security_label`, a human-readable display string. There is no
   * `symbol`, no identifier and nothing to canonicalize, so no identity correspondence can be
   * stated — and an embed whose identity rests on a display name is exactly the ambiguity R4
   * refuses. It resolves by authorized read instead.
   */
  "ShortSideSnapshot.borrow[].security_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "ShortSideSnapshot.borrow[].record_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "ShortSideSnapshot.blocked_shorts[].candidate_ref": {
    shape: "REF",
    kinds: ["candidate"],
    requiredness: "required",
    implemented: true,
  },
  /** Additive: what a borrow-related miss summary would need, named rather than left blank. */
  "ShortSideSnapshot.missed_opportunity_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },

  /* -------------------------------------------------------------------- C6 read models */
  "CandidateSummary.security_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    embeds: [SECURITY_PROJECTION],
    implemented: true,
  },
  "CandidateSummary.detail_ref": {
    shape: "REF",
    kinds: ["candidate"],
    requiredness: "required",
    implemented: true,
  },
  "CandidateDetail.security_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    embeds: [SECURITY_PROJECTION],
    implemented: true,
  },
  "CandidateDetail.regime_ref": {
    shape: "REF",
    kinds: ["regime_context"],
    requiredness: "required",
    implemented: true,
  },
  "CandidateDetail.ai_evidence_refs": {
    shape: "REF_LIST",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  /** The reference inside the parallel provenance structure §4.5 requires on each one. */
  "CandidateDetail.ai_evidence[].reference": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "CandidateDetail.challenger_objections": {
    shape: "REF_LIST",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "CandidateDetail.invalidation_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "CandidateDetail.short_context.borrow_evidence_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "conditional",
    implemented: true,
  },
  "CandidateDetail.downstream_refs.risk_decision": {
    shape: "REF",
    kinds: ["risk_decision"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * **The trade this candidate became** — kind `trade` under ADR-0030 R1 and R2.
   *
   * It was emitted as `source_fact` with an `ENDPOINT` that `source_fact`'s own row does not
   * list, because §4.3 had no `trade` row to assign it. A reader of that payload could not
   * tell the trade a candidate produced from a provenance record the projection was built
   * out of, and the two are different facts.
   */
  "CandidateDetail.downstream_refs.trade": {
    shape: "REF",
    kinds: ["trade"],
    requiredness: "required",
    implemented: true,
  },
  "MissedOpportunity.candidate_ref": {
    shape: "REF",
    kinds: ["candidate"],
    requiredness: "required",
    implemented: true,
  },
  /** Additive: the trade a taken candidate became, where one exists. */
  "MissedOpportunity.trade_ref": {
    shape: "REF",
    kinds: ["trade"],
    requiredness: "conditional",
    implemented: true,
  },
  /** Additive: the health transition behind a strategy row. */
  "StrategyPerformance.detail_ref": {
    shape: "REF",
    kinds: ["health_transition"],
    requiredness: "required",
    implemented: true,
  },

  /* -------------------------------------------------------------------- C7 read models
   *
   * The reference-valued fields of the Areas 5, 14, 15, 16, 17, 18, 19, 20 and 21 read models
   * this cycle actually serves. The §4.5 and §4.3.1 assignments already recorded below moved
   * up here with their producers; the entries in THIS block are the ADDITIVE fields those
   * payload contracts add under ADR-0028's additive rule, and each states the kind its own
   * contract text describes.
   *
   * **`implemented` is `true` here because a synthetic producer exists for `SYNTHETIC`
   * provenance and for nothing else** (R6). It is never a claim that a research engine, a
   * learning engine, a shadow runner, an AI agent or a governance runtime exists — none does,
   * and none is authorized.
   */
  /** The recorded position fact a pin is attached to. Not the trade, and not derived from it. */
  "StrategyVersion.open_positions[].position_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * The trade the pinned position belongs to.
   *
   * A DIFFERENT reference from `position_ref` beside it: one names a recorded position fact
   * and the other names the `TradeDetail` read model that owns the trade's story. They carry
   * different identifiers, and neither is derived from the other.
   */
  "StrategyVersion.open_positions[].trade_ref": {
    shape: "REF",
    kinds: ["trade"],
    requiredness: "required",
    implemented: true,
  },
  /** The registrations a version was produced by or evaluated under. */
  "StrategyVersion.registration_refs": {
    shape: "REF_LIST",
    kinds: ["registration"],
    requiredness: "required",
    implemented: true,
  },
  /** The recorded human decision that carried a version event, where one did. */
  "StrategyVersion.history[].decision_ref": {
    shape: "REF",
    kinds: ["decision"],
    requiredness: "conditional",
    implemented: true,
  },
  /** Area 17 presents supporting evidence beside the trigger. */
  "ResearchQueueItem.evidence_refs": {
    shape: "REF_LIST",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  /** Area 17 presents the associated Challenger, where one exists. */
  "ResearchQueueItem.challenger_ref": {
    shape: "REF",
    kinds: ["strategy_version"],
    requiredness: "conditional",
    implemented: true,
  },
  /** The registration a queue item became, once it reached `REGISTERED`. */
  "ResearchQueueItem.registration_ref": {
    shape: "REF",
    kinds: ["registration"],
    requiredness: "conditional",
    implemented: true,
  },
  /**
   * The registration that WROTE one exposure-ledger entry.
   *
   * The ledger is attached to the LOCKED SET rather than to a registration (§2.7.1), so most
   * of the entries a registration reads were written by something else — which is exactly why
   * each entry names its own author.
   */
  "HypothesisRegistration.exposure_ledger.entries[].registration_ref": {
    shape: "REF",
    kinds: ["registration"],
    requiredness: "required",
    implemented: true,
  },
  /** The authorized runs a Champion/Challenger comparison rests on. */
  "ChampionChallengerComparison.evidence_refs": {
    shape: "REF_LIST",
    kinds: ["research_run"],
    requiredness: "required",
    implemented: true,
  },
  /** The SHADOW evidence, kept in its own field so it is never read as a backtest result. */
  "ChampionChallengerComparison.shadow_refs": {
    shape: "REF_LIST",
    kinds: ["research_run"],
    requiredness: "required",
    implemented: true,
  },

  /* ========================================================================= added by C8 ===
   * The six C8 areas emit these payloads now, so their assignments move out of the
   * specification-only section below and are marked implemented.
   *
   * **`implemented` is scoped to what this application actually produces** — a read model
   * projected from repository-owned SYNTHETIC fixtures. It "exists for `SYNTHETIC` provenance
   * and for nothing else" (§4.3.1), and marking one true establishes nothing about an
   * execution runtime, a broker session, a provider feed, a scheduler, an alert pipeline or an
   * authoritative audit store. **None of those exists, and none is authorized.**
   */

  /* ---------------------------------------------------------------- Area 10 (§4.3.1) */
  "ReconciliationStatus.position_diffs[].security_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "ReconciliationStatus.order_diffs[].local_ref": {
    shape: "REF",
    kinds: ["order"],
    requiredness: "required",
    implemented: true,
  },
  "ReconciliationStatus.incident_refs": {
    shape: "REF_LIST",
    kinds: ["incident"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * ADDITIVE: the ownership finding's own local order reference.
   *
   * §4.5 gives `order_diffs[]` a `local_ref` and says nothing about ownership, which Area 10
   * "presents" as a separate fact. An ownership finding is about ONE local order, so it
   * carries its own reference rather than being positioned beside a diff — an association a
   * reader cannot see in the payload is one a producer can silently get wrong (§4.3.2).
   */
  "ReconciliationStatus.ownership_findings[].local_ref": {
    shape: "REF",
    kinds: ["order"],
    requiredness: "required",
    implemented: true,
  },
  /** ADDITIVE: the trades a recorded comparison covered, so its scope is visible. */
  "ReconciliationStatus.trade_refs": {
    shape: "REF_LIST",
    kinds: ["trade"],
    requiredness: "required",
    implemented: true,
  },

  /* ----------------------------------------------------------------------- Area 9 */
  /**
   * ADDITIVE: the trade and the order one execution-quality row belongs to.
   *
   * `ExecutionQuality.subject_ref` already names what the measurement was taken OVER, and its
   * kind follows `scope`. These two answer a different question — which trade, and which
   * order, this row sits under — and a screen that inferred either from the subject would be
   * guessing at an `AGGREGATE` row.
   */
  "ExecutionQualityRecord.trade_ref": {
    shape: "REF",
    kinds: ["trade"],
    requiredness: "required",
    implemented: true,
  },
  "ExecutionQualityRecord.order_ref": {
    shape: "REF",
    kinds: ["order"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * ADDITIVE: the protective orders recorded against this order's position.
   *
   * **A submitted protective order is not proof of active protection**, so the list is carried
   * beside a state that says what the record shows, and never in place of it.
   */
  "ExecutionQualityRecord.protective_order_refs": {
    shape: "REF_LIST",
    kinds: ["protection"],
    requiredness: "required",
    implemented: true,
  },

  /* ---------------------------------------------------------------- Area 22 (§4.5) */
  "DataQuality.lineage_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "DataQuality.incident_refs": {
    shape: "REF_LIST",
    kinds: ["incident"],
    requiredness: "required",
    implemented: true,
  },
  /** ADDITIVE: the alerts a recorded data condition raised, so the two views reconcile. */
  "DataQuality.alert_refs": {
    shape: "REF_LIST",
    kinds: ["alert"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * ADDITIVE: the exact version a recorded data condition affects.
   *
   * Area 22 presents "strategies blocked by a data condition". A strategy MODULE is a closed
   * code and a strategy VERSION is a record, so the affected row names the version it is about
   * rather than leaving a reader to match a label.
   */
  "DataQuality.affected_strategies[].version_ref": {
    shape: "REF",
    kinds: ["strategy_version"],
    requiredness: "required",
    implemented: true,
  },

  /* ---------------------------------------------------------------- Area 23 (§4.5) */
  "SystemIncident.evidence_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  /** ADDITIVE: the alerts a recorded incident is linked to. */
  "SystemIncident.alert_refs": {
    shape: "REF_LIST",
    kinds: ["alert"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * ADDITIVE: a job's recorded evidence and the incidents raised against it.
   *
   * `RefKind` is closed at twenty-seven members and holds no `job`, so a job's own recorded
   * facts are `source_fact` references — the kind §4.3 gives "the recorded fact a projection
   * was built from". **No kind is invented to obtain a link**, and none is relabelled.
   */
  "SystemJob.evidence_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "SystemJob.incident_refs": {
    shape: "REF_LIST",
    kinds: ["incident"],
    requiredness: "required",
    implemented: true,
  },

  /* ---------------------------------------------------------------- Area 27 (§4.5) */
  "Alert.evidence_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  /** ADDITIVE: the incidents a recorded condition was linked to. */
  "Alert.incident_refs": {
    shape: "REF_LIST",
    kinds: ["incident"],
    requiredness: "required",
    implemented: true,
  },

  /* ---------------------------------------------------------------- Area 26 (§4.5) */
  "AuditEvent.subject_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "AuditEvent.supersedes": {
    shape: "REF",
    kinds: ["audit_event"],
    requiredness: "conditional",
    implemented: true,
  },
  "AuditEvent.tombstone_of": {
    shape: "REF",
    kinds: ["audit_event"],
    requiredness: "conditional",
    implemented: true,
  },
  /**
   * ADDITIVE: the linked context Area 26 presents, as a STATED SET of kinds.
   *
   * "Linked candidate, trade, research, health and incident context" is five kinds on one
   * field, and §4.3.1 permits a field to declare "a stated SET of kinds" with the field's own
   * declaration governing. It is kept SEPARATE from `subject_refs`, which §4.3.1 assigns
   * `source_fact`: widening that field would have relabelled a subject to obtain a link, and
   * "a producer may NEVER change a reference's ref_kind to obtain a link" (§4.3.2).
   */
  "AuditEvent.related_refs": {
    shape: "REF_LIST",
    kinds: ["candidate", "trade", "research_run", "health_transition", "incident"],
    requiredness: "required",
    implemented: true,
  },

  /* ================================================================ specification-only ===
   * Assignments recorded so the cycle that FIRST emits one of these payloads inherits an
   * ENFORCED contract rather than an open one.
   *
   * **No model, producer, screen, route, fixture or C7 interface is created by any entry
   * below.** Each is §4.5's or §4.3.1's own assignment, transcribed. A field with no assigned
   * kind cannot be checked against anything — which is precisely how two trade references
   * came to be labelled `source_fact`.
   */
  "StrategyHealth.queue_item_ref": {
    shape: "REF",
    kinds: ["queue_item"],
    requiredness: "conditional",
    implemented: true,
  },
  "StrategyHealth.transitions[].input_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "StrategyHealth.failure_clusters[].evidence_refs": {
    shape: "REF_LIST",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "StrategyVersion.lineage_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "StrategyVersion.open_position_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "StrategyVersion.rollback_of": {
    shape: "REF",
    kinds: ["strategy_version"],
    requiredness: "conditional",
    implemented: true,
  },
  "MaturityStatus.decision_refs": {
    shape: "REF_LIST",
    kinds: ["decision"],
    requiredness: "required",
    implemented: false,
  },
  "ResearchRun.registration_ref": {
    shape: "REF",
    kinds: ["registration"],
    requiredness: "required",
    implemented: true,
  },
  "ResearchRun.baseline_ref": {
    shape: "REF",
    kinds: ["strategy_version"],
    requiredness: "required",
    implemented: true,
  },
  "ResearchRun.dataset_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "ResearchQueueItem.trigger_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "ResearchQueueItem.baseline_ref": {
    shape: "REF",
    kinds: ["strategy_version"],
    requiredness: "required",
    implemented: true,
  },
  "HypothesisRegistration.trigger_ref": {
    shape: "REF",
    kinds: ["queue_item"],
    requiredness: "required",
    implemented: true,
  },
  "HypothesisRegistration.baseline_ref": {
    shape: "REF",
    kinds: ["strategy_version"],
    requiredness: "required",
    implemented: true,
  },
  "HypothesisRegistration.exposure_ledger_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "HypothesisRegistration.linked_results": {
    shape: "REF_LIST",
    kinds: ["research_run"],
    requiredness: "required",
    implemented: true,
  },
  "HypothesisRegistration.lineage.parent_registration": {
    shape: "REF",
    kinds: ["registration"],
    requiredness: "conditional",
    implemented: true,
  },
  "HypothesisRegistration.lineage.superseded_by": {
    shape: "REF",
    kinds: ["registration"],
    requiredness: "conditional",
    implemented: true,
  },
  "HypothesisRegistration.lineage.related_registrations": {
    shape: "REF_LIST",
    kinds: ["registration"],
    requiredness: "required",
    implemented: true,
  },
  "HypothesisRegistration.lineage.amendment_chain": {
    shape: "REF_LIST",
    kinds: ["registration"],
    requiredness: "required",
    implemented: true,
  },
  "ChampionChallengerComparison.registration_ref": {
    shape: "REF",
    kinds: ["registration"],
    requiredness: "required",
    implemented: true,
  },
  "AiContribution.experiment_ref": {
    shape: "REF",
    kinds: ["registration"],
    requiredness: "required",
    implemented: true,
  },
  "AiContribution.ai_provenance.source_refs": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "FeedbackPipeline.stages[].item_refs": {
    shape: "REF_LIST",
    kinds: ["queue_item"],
    requiredness: "required",
    implemented: true,
  },
  "GovernancePacket.registration_ref": {
    shape: "REF",
    kinds: ["registration"],
    requiredness: "required",
    implemented: true,
  },
  "GovernancePacket.run_refs": {
    shape: "REF_LIST",
    kinds: ["research_run"],
    requiredness: "required",
    implemented: true,
  },
  "GovernancePacket.shadow_refs": {
    shape: "REF_LIST",
    kinds: ["research_run"],
    requiredness: "required",
    implemented: true,
  },
  "GovernancePacket.comparison_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: true,
  },
  "GovernancePacket.evidence_refs": {
    shape: "REF_LIST",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "GovernancePacket.decision_ref": {
    shape: "REF",
    kinds: ["decision"],
    requiredness: "conditional",
    implemented: true,
  },
  "DecisionRecord.packet_ref": {
    shape: "REF",
    kinds: ["packet"],
    requiredness: "required",
    implemented: true,
  },
  "DecisionRecord.reasoning_ref": {
    shape: "REF",
    kinds: ["evidence"],
    requiredness: "required",
    implemented: true,
  },
  "DecisionRecord.affected_versions": {
    shape: "REF_LIST",
    kinds: ["strategy_version"],
    requiredness: "required",
    implemented: true,
  },
  /**
   * §4.3.1: three separate `source_ref` fields, each reading a fact INDEPENDENTLY from
   * tracked repository authority. That is a catalogue-authorized CROSS-PROVENANCE reference
   * (R8) — see `CROSS_PROVENANCE_AUTHORIZED`.
   */
  "QualificationStatus.facts[].source_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: false,
  },
  "QualificationStatus.gates[].source_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: false,
  },
  "QualificationStatus.runs[].source_ref": {
    shape: "REF",
    kinds: ["source_fact"],
    requiredness: "required",
    implemented: false,
  },
  /**
   * §4.3.1: a search result names WHATEVER was found, so its kind is any `RefKind` and its
   * resolution is that kind's. Its rows carry their own environment, provenance and
   * classification, which is why it is cross-provenance authorized (R8).
   */
  "SearchResultPage.results[].ref": {
    shape: "REF",
    kinds: REF_KINDS,
    requiredness: "required",
    implemented: false,
  },
  /**
   * The ONE place the stronger relation is meant: "ONE_OR_MORE, or the answer is not
   * returned". The host field NARROWS the kind's `ZERO_OR_MORE` relation, which is exactly
   * what R7 makes the host declaration authoritative for.
   */
  "AskAnswer.citations": {
    shape: "REF_LIST",
    kinds: ["source_fact"],
    requiredness: "required",
    relation: "ONE_OR_MORE",
    implemented: false,
  },
} as const satisfies Record<string, HostFieldDeclaration>;

export type HostFieldKey = keyof typeof REFERENCE_FIELDS;

/**
 * The host fields a catalogue-authorized CROSS-PROVENANCE reference may appear on (R8).
 *
 * Environment must always match the resolving envelope. Provenance must match too, EXCEPT
 * here — and even here the target's own provenance label must be carried and displayed. A
 * blanket must-match rule would refuse `QualificationStatus`, whose whole purpose is reading
 * tracked repository authority, and `SearchResultPage`, whose rows already label themselves.
 * **Silent provenance mixing stays prohibited**: an unlabelled differing target is refused.
 */
export const CROSS_PROVENANCE_AUTHORIZED: readonly HostFieldKey[] = [
  "QualificationStatus.facts[].source_ref",
  "QualificationStatus.gates[].source_ref",
  "QualificationStatus.runs[].source_ref",
  "SearchResultPage.results[].ref",
];

export function declarationFor(key: HostFieldKey): HostFieldDeclaration {
  return REFERENCE_FIELDS[key];
}

/* =============================================================== validation, per reference */

/** Why a reference is refused, or `null` when the declaration is admissible. */
export function referenceFailure(key: HostFieldKey, candidate: Ref): string | null {
  const declaration: HostFieldDeclaration = REFERENCE_FIELDS[key];
  if (!(declaration.kinds as readonly string[]).includes(candidate.ref_kind)) {
    return `${key} declares kind ${declaration.kinds.join(" or ")}, and carries ${candidate.ref_kind}`;
  }
  /*
   * `AUDIT_TRAIL` IS DECLARED WHEN THE REFERENCE NAMES A RECORDED `AuditEvent` (§4.3.2).
   *
   * "An absent, unknown or undetermined owning area never resolves to it, and no rule may use
   * it as a fallback: *an Audit page owns every fact* is a false claim, and it is the one this
   * section exists to stop being made." Matrix A gives area 26 exactly one read model, and
   * §4.3 gives that read model exactly one kind -- so a reference naming anything else
   * declares the area that owns it, or, where accepted authority determines none, NONE.
   *
   * IT IS CHECKED HERE BECAUSE IT IS A PROPERTY OF ONE REFERENCE. The kind it carries and the
   * area it declares sit on the same object, which is the tightest boundary that can see both,
   * and this function is the one every declared reference field already passes through.
   * `owningAreaContradiction` answers a different question at a different scope -- two records
   * disagreeing inside one response -- and neither rule substitutes for the other: a single
   * mislabelled reference contradicts nothing and would pass it.
   */
  if (candidate.owning_area === "AUDIT_TRAIL" && candidate.ref_kind !== "audit_event") {
    return (
      `${key} declares owning_area AUDIT_TRAIL on a ${candidate.ref_kind} reference, and ` +
      `area 26 owns AuditEvent`
    );
  }
  if (candidate.resolution === "EMBEDDED") {
    const permitted = declaration.embeds?.some((entry) => entry.kind === candidate.ref_kind);
    if (permitted !== true) {
      /*
       * PRESENCE IS NOT PERMISSION.
       *
       * A rule satisfied by "the payload is there" is satisfied by PUTTING it there, so it
       * would authorize any widening a producer chose to perform and then ratify it. The
       * catalogue has to name this host field an authorized carrier first.
       */
      return `${key} is not an authorized carrier for an EMBEDDED ${candidate.ref_kind}`;
    }
    return null;
  }
  const permitted = KIND_RESOLUTIONS[candidate.ref_kind];
  if (!permitted.includes(candidate.resolution)) {
    return `${candidate.ref_kind} permits ${permitted.join(" or ")}, and ${key} declares ${candidate.resolution}`;
  }
  return null;
}

/**
 * Whether an `EMBEDDED` declaration is TRUE of the response, given the object carrying it.
 *
 * Permission is checked by `referenceFailure`; this is the second half of R4. A carrier that
 * is absent, or whose identity does not correspond to the reference under the declared rule,
 * refuses the response rather than rendering it.
 */
export function embeddedTruthFailure(
  key: HostFieldKey,
  candidate: Ref,
  host: Readonly<Record<string, unknown>>,
): string | null {
  if (candidate.resolution !== "EMBEDDED") {
    /*
     * Co-location neither compels EMBEDDED nor forbids another resolution (R4.1), so a
     * carrier present beside a non-embedded reference is not an error. `EMBEDDED` says "you
     * already have this"; `ENDPOINT` says "the authoritative record lives here". Both can be
     * true of one response, and refusing the second would destroy the route information.
     */
    return null;
  }
  const declaration: HostFieldDeclaration = REFERENCE_FIELDS[key];
  const permission = declaration.embeds?.find((entry) => entry.kind === candidate.ref_kind);
  if (permission === undefined) {
    return `${key} is not an authorized carrier for an EMBEDDED ${candidate.ref_kind}`;
  }
  const carrier = host[permission.carrier];
  if (carrier === undefined || carrier === null) {
    return `${key} declares EMBEDDED and the response carries no ${permission.carrier}`;
  }
  return identityFailure(key, permission, candidate, carrier, host);
}

function identityFailure(
  key: HostFieldKey,
  permission: EmbedPermission,
  candidate: Ref,
  carrier: unknown,
  host: Readonly<Record<string, unknown>>,
): string | null {
  const rule = permission.identity;
  const mismatch = (observed: unknown) =>
    `${key} embeds a ${permission.carrier} whose identity (${String(observed)}) is not the reference's`;
  switch (rule.rule) {
    case "TARGET_ID_FIELD": {
      const observed = readField(carrier, rule.field);
      return observed === candidate.ref_id ? null : mismatch(observed);
    }
    case "TARGET_REF_FIELD": {
      const nested = readField(carrier, rule.field);
      const observed = isRecord(nested) ? nested.ref_id : undefined;
      return observed === candidate.ref_id ? null : mismatch(observed);
    }
    case "CANONICAL_KEY": {
      const natural = readField(carrier, rule.field);
      if (typeof natural !== "string") {
        return `${key} embeds a ${permission.carrier} carrying no ${rule.field} to compare`;
      }
      const derived = `${rule.prefix}${natural.toLowerCase()}`;
      return derived === candidate.ref_id ? null : mismatch(derived);
    }
    case "HOST_SCOPED_SUFFIX": {
      const hostId = host[rule.hostIdField];
      if (typeof hostId !== "string") {
        return `${key} embeds a projection whose host carries no ${rule.hostIdField}`;
      }
      const derived = `${hostId}${rule.suffix}`;
      return derived === candidate.ref_id ? null : mismatch(derived);
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readField(carrier: unknown, field: string): unknown {
  return isRecord(carrier) ? carrier[field] : undefined;
}

/* ================================================================== cardinality, applied */

/** The value-bearing states of §4.1.1 — the only ones whose `total` can carry a number. */
const VALUE_BEARING: ReadonlySet<string> = new Set([
  "AVAILABLE",
  "STALE",
  "PARTIAL",
  "EMPTY_VERIFIED",
]);

function satisfiesRelation(relation: Cardinality, total: number): boolean {
  switch (relation) {
    case "EXACTLY_ONE":
      return total === 1;
    case "ZERO_OR_ONE":
      return total <= 1;
    case "ONE_OR_MORE":
      return total >= 1;
    case "ZERO_OR_MORE":
      return true;
  }
}

/**
 * The host field's own relation, checked against `items`, `total` and `truncated` — three
 * facts that are never collapsed into one (R7).
 */
export function refListFailure(key: HostFieldKey, candidate: RefList): string | null {
  const declaration: HostFieldDeclaration = REFERENCE_FIELDS[key];
  if (declaration.shape !== "REF_LIST") {
    return `${key} is not a RefList field`;
  }
  const fixed = declaration.relation;
  if (fixed !== undefined && candidate.cardinality !== fixed) {
    return `${key} declares relation ${fixed}, and the list states ${candidate.cardinality}`;
  }
  /*
   * THE LIST'S OWN CARDINALITY IS THE HOST FIELD'S DECLARATION.
   *
   * Where the catalogue fixes one it has just been checked; otherwise the emitted value IS
   * the declaration, and `items`, `total` and `truncated` are checked against it. A field may
   * NARROW its kind's generic relation -- `AskAnswer.citations` narrows `source_fact` to
   * ONE_OR_MORE -- so the per-kind column is deliberately not the comparand here (R7).
   */
  const relation = candidate.cardinality;
  for (const item of candidate.items) {
    const failure = referenceFailure(key, item);
    if (failure !== null) {
      return failure;
    }
  }
  const total = candidate.total;
  if (!VALUE_BEARING.has(total.availability) || typeof total.value !== "number") {
    /*
     * A COUNT NOBODY TOOK BOUNDS NOTHING.
     *
     * The relation is NOT asserted satisfied here, and no bound is inferred from
     * `items.length` — which is a page fact and not a population. The count's state and its
     * reason are the whole answer.
     */
    return null;
  }
  if (!satisfiesRelation(relation, total.value)) {
    return `${key} declares ${relation}, and states a total of ${total.value}`;
  }
  if (candidate.truncated && candidate.items.length > total.value) {
    return `${key} is truncated and carries more items than its total`;
  }
  if (!candidate.truncated && candidate.items.length !== total.value) {
    return `${key} is complete and carries ${candidate.items.length} of a total ${total.value}`;
  }
  return null;
}

/* ========================================================================= zod builders */

/** A single reference, validated against its host field's declaration. */
export function refOf(key: HostFieldKey) {
  return ref.superRefine((candidate, ctx) => {
    const failure = referenceFailure(key, candidate);
    if (failure !== null) {
      ctx.addIssue({ code: "custom", message: failure });
    }
  });
}

/** A reference list, validated against its host field's declaration and its own relation. */
export function refListFieldOf(key: HostFieldKey) {
  return refList.superRefine((candidate, ctx) => {
    const failure = refListFailure(key, candidate);
    if (failure !== null) {
      ctx.addIssue({ code: "custom", message: failure });
    }
  });
}

/**
 * Apply the R4 TRUTH half from inside the containing object's own refinement.
 *
 * It is checked on the CONTAINING object rather than on the reference, because a reference
 * cannot see the field beside it — which is why "presence is not permission" needs two checks
 * in two places rather than one clever one. `bindings` pairs each host-field key with the
 * property that holds its reference on this object.
 */
export function checkEmbeddedTruth(
  ctx: z.RefinementCtx,
  host: unknown,
  bindings: readonly (readonly [HostFieldKey, string])[],
): void {
  if (!isRecord(host)) {
    return;
  }
  for (const [key, field] of bindings) {
    const reference = host[field];
    if (!isRecord(reference) || typeof reference.resolution !== "string") {
      continue;
    }
    const failure = embeddedTruthFailure(key, reference as unknown as Ref, host);
    if (failure !== null) {
      ctx.addIssue({ code: "custom", message: failure });
    }
  }
}

/* ============================================ owning area, across the admission unit */

/**
 * The `owning_area` contradiction rule — §4.3.2, under ADR-0031 A1.
 *
 * **The comparison scope is the ADMISSION UNIT — one response payload — and not one
 * `RefList`.** The harm named is a renderer drawing two different area controls for one
 * record, and that harm does not arrive only inside a single list: the same record can appear
 * in two different `RefList` fields, or in a scalar `Ref` beside a list. Scoping the check to
 * a list would state a rule narrower than its own reason, so this walks the WHOLE parsed
 * response and compares every reference it finds against every other.
 *
 * **The scope is also exactly as wide as the comparison is sound.** ADR-0030 R8 requires the
 * environment to match the resolving envelope always, and §4.2 gives a `Ref` no provenance
 * field, so within one response a matched `ref_id` AND `ref_kind` name ONE target. Nothing
 * here widens that to a cross-response or global identity claim, and **no new identity model
 * is introduced** — this is R8's comparison, read at the scope R8 already fixes.
 *
 * **Absence is not a conflicting value.** A reference declaring an area beside one declaring
 * none is admitted and the declared area stands: an absence states nothing, so there is
 * nothing for it to disagree with. Only two DECLARED and DIFFERENT members conflict. Reading
 * an absence as a conflict would refuse conformant payloads at admission, which is the
 * opposite of the failure this rule exists to catch — and it would also quietly fill the
 * absence in, which A4 refuses.
 *
 * **Same-identity duplicates that AGREE are two references and stay two.** They are not
 * collapsed, and the shared area is not deduplicated away; this function only refuses, and it
 * never rewrites, merges or reorders anything.
 */
export function owningAreaContradiction(admissionUnit: unknown): string | null {
  const declared = new Map<string, string>();
  const seen = new Set<object>();
  const pending: unknown[] = [admissionUnit];
  while (pending.length > 0) {
    const node = pending.pop();
    if (!isRecord(node) || seen.has(node)) {
      continue;
    }
    seen.add(node);
    /*
     * A REFERENCE IS RECOGNISED BY ITS OWN FOUR REQUIRED FIELDS, and never by the name of the
     * property holding it. `evidence_refs`, `source_refs`, `security_ref` and every later host
     * field carry the same shape, and a rule keyed by field name would miss the next one.
     */
    const area = node.owning_area;
    if (
      typeof node.ref_id === "string" &&
      typeof node.ref_kind === "string" &&
      typeof node.resolution === "string" &&
      typeof node.classification === "string" &&
      typeof area === "string"
    ) {
      const identity = `${node.ref_kind} ${node.ref_id}`;
      const already = declared.get(identity);
      if (already !== undefined && already !== area) {
        return (
          `reference ${node.ref_kind} ${node.ref_id} declares owning_area ${already} and ` +
          `${area} in one response, and one record is not owned by two areas`
        );
      }
      declared.set(identity, area);
    }
    for (const value of Object.values(node)) {
      if (isRecord(value)) {
        pending.push(value);
      }
    }
  }
  return null;
}
