/**
 * Closed vocabularies, transcribed from `docs/cockpit/read-model-contracts.md` §2 and §4.1.
 *
 * Every vocabulary here is CLOSED. A value outside it is rejected at the boundary rather
 * than rendered, and a new member is added by an ADR rather than by an implementation
 * (read-model-contracts.md §2). These arrays are the single source of truth for the Zod
 * enums below; nothing re-spells a member.
 */
import { z } from "zod";

/** read-model-contracts.md §2.1 — exactly eleven members. */
export const AVAILABILITY_STATES = [
  "AVAILABLE",
  "NOT_YET_AVAILABLE",
  "NOT_IMPLEMENTED",
  "NOT_AUTHORIZED",
  "UNEVALUATED",
  "STALE",
  "PARTIAL",
  "ERROR",
  "NOT_APPLICABLE",
  "EMPTY_VERIFIED",
  "INSUFFICIENT_OBSERVATIONS",
] as const;
export const availabilityState = z.enum(AVAILABILITY_STATES);
export type AvailabilityState = z.infer<typeof availabilityState>;

/** read-model-contracts.md §4.1 — closed, extended only by an ADR. */
export const FIELD_REASON_CODES = [
  "NONE",
  "EMPTY_RESULT_VERIFIED",
  "EXTENT_PARTIALLY_COVERED",
  "EXTENT_NOT_DETERMINABLE",
  "NOT_YET_ASSESSED",
  "PRODUCER_NOT_IMPLEMENTED",
  "PRODUCER_NOT_AUTHORIZED",
  "UPSTREAM_INPUT_MISSING",
  "UPSTREAM_INPUT_STALE",
  "SOURCE_TIMESTAMP_MISSING",
  "CLOCK_UNSYNCHRONIZED",
  "PRICE_PATH_INCOMPLETE",
  "CORPORATE_ACTION_UNRESOLVED",
  "BELOW_MINIMUM_OBSERVATIONS",
  "DENOMINATOR_ZERO",
  "NOT_DEFINED_FOR_SUBJECT",
  "POLICY_REFERENCE_MISSING",
  "CLASSIFICATION_WITHHELD",
  /**
   * ADR-0030 R9 — a reference is well formed and its identifier names NOTHING in the
   * producing read model.
   *
   * It is an ABSENCE of a target and never an INAPPLICABILITY, so §4.1.1 reaches it from
   * `NOT_YET_AVAILABLE` alone and `NOT_APPLICABLE` keeps its two ADR-0028 routes. It is
   * never a producer that does not exist, never a scope the caller lacks, and never a
   * target withheld by classification. It is carried by the VALUE-BEARING field the target
   * would have filled — never by a bare `Ref`, which has no availability field.
   */
  "REFERENT_NOT_FOUND",
  "PROJECTION_ERROR",
] as const;
export const fieldReasonCode = z.enum(FIELD_REASON_CODES);
export type FieldReasonCode = z.infer<typeof fieldReasonCode>;

/**
 * read-model-contracts.md §5.2 — the closed error vocabulary, and NO FREE TEXT.
 *
 * `REFERENT_NOT_FOUND` is ADR-0030 R9's second landing place: the §5 error returned by an
 * attempt to FOLLOW a reference. It is never a substitute for an unimplemented producer or
 * a withheld target, and scope denial stays separate from classification withholding.
 */
export const ERROR_CODES = [
  "UNKNOWN_SCHEMA_VERSION",
  "UNKNOWN_API_VERSION",
  "UNKNOWN_FILTER",
  "UNKNOWN_SORT",
  "PAGE_SIZE_EXCEEDED",
  "EXTENT_EXCEEDED",
  "CURSOR_INVALID",
  "CURSOR_SNAPSHOT_SUPERSEDED",
  "SCOPE_MISSING",
  "SCOPE_INSUFFICIENT",
  "CLASSIFICATION_WITHHELD",
  "POLICY_REFERENCE_MISSING",
  "REFERENT_NOT_FOUND",
  "PROJECTION_ERROR",
] as const;
export const errorCode = z.enum(ERROR_CODES);
export type ErrorCode = z.infer<typeof errorCode>;

/** read-model-contracts.md §2.2. `REPOSITORY_TRACKED` is REAL and never relabelled SYNTHETIC. */
export const DATA_PROVENANCES = [
  "SYNTHETIC",
  "REPOSITORY_TRACKED",
  "SYSTEM_RECORDED",
  "BACKTEST_SIMULATED",
  "BROKER_REPORTED",
] as const;
export const dataProvenance = z.enum(DATA_PROVENANCES);
export type DataProvenance = z.infer<typeof dataProvenance>;

/** read-model-contracts.md §2.3. `UNCLASSIFIED` goes nowhere; `CONTROL` is refused at admission. */
export const DATA_CLASSIFICATIONS = [
  "PUBLIC_SAFE",
  "PRIVATE_OPERATIONAL",
  "LICENSED_DERIVED",
  "UNCLASSIFIED",
  "CONTROL",
] as const;
export const dataClassification = z.enum(DATA_CLASSIFICATIONS);
export type DataClassification = z.infer<typeof dataClassification>;

/** read-model-contracts.md §2.4. */
export const HOSTING_BOUNDARIES = ["PUBLIC_EDGE", "PRIVATE_BOUNDARY"] as const;
export const hostingBoundary = z.enum(HOSTING_BOUNDARIES);
export type HostingBoundary = z.infer<typeof hostingBoundary>;

/**
 * read-model-contracts.md §2.5 — presentation stages. Distinct from the runtime
 * `Environment` enum, which is unchanged (COCKPIT_FEEDBACK_EXTENSION.md §4.1).
 */
export const MATURITY_STAGES = [
  "RESEARCH",
  "SHADOW",
  "AUTOMATED_PAPER",
  "MICRO_LIVE",
  "SCALED_LIVE",
] as const;
export const maturityStage = z.enum(MATURITY_STAGES);
export type MaturityStage = z.infer<typeof maturityStage>;

/** The runtime environment enum, consumed unchanged from `src/kalpamani/common/environment.py`. */
export const ENVIRONMENTS = ["RESEARCH", "PAPER", "LIVE"] as const;
export const environment = z.enum(ENVIRONMENTS);
export type Environment = z.infer<typeof environment>;

/** read-model-contracts.md §4.2 closed `Unit` helper vocabulary. */
export const UNITS = [
  "USD",
  "RATIO",
  "PERCENT",
  "BPS",
  "SHARES",
  "SECONDS",
  "TRADING_DAYS",
  "CALENDAR_DAYS",
  "COUNT",
  "R_MULTIPLE",
  "DIMENSIONLESS",
] as const;
export const unit = z.enum(UNITS);
export type Unit = z.infer<typeof unit>;

/** Envelope `completeness`. `UNKNOWN` belongs here and is NOT an availability value. */
export const COMPLETENESS_VALUES = ["COMPLETE", "PARTIAL", "UNKNOWN"] as const;
export const completeness = z.enum(COMPLETENESS_VALUES);
export type Completeness = z.infer<typeof completeness>;

/** read-model-contracts.md §4.2 closed `Cardinality` and `Resolution` helpers. */
export const CARDINALITIES = ["EXACTLY_ONE", "ZERO_OR_ONE", "ZERO_OR_MORE", "ONE_OR_MORE"] as const;
export const cardinality = z.enum(CARDINALITIES);

export const RESOLUTIONS = [
  "ENDPOINT",
  "EMBEDDED",
  "AUTHORIZED_READ",
  "UNRESOLVABLE_V1",
] as const;
export const resolution = z.enum(RESOLUTIONS);
export type Resolution = z.infer<typeof resolution>;
export type Cardinality = z.infer<typeof cardinality>;

/**
 * `RefKind` — read-model-contracts.md §4.2, CLOSED at the TWENTY-SEVEN rows of the §4.3
 * table (ADR-0030 R1).
 *
 * `trade` is the twenty-seventh, added by ADR-0030 R1 because
 * `CandidateDetail.downstream_refs.trade` and
 * `RiskSnapshot.initial_planned_risk_open[].trade_ref` each require a reference to a trade
 * and no earlier row supplied one. Both were emitted as `source_fact` before this cycle,
 * which made *the trade a candidate became* indistinguishable from *a provenance record a
 * projection was built out of*.
 *
 * A value outside this set is REFUSED at the boundary, never rendered and never coerced.
 * A new member is added by an ADR, never by an implementation (§2).
 */
export const REF_KINDS = [
  "candidate",
  "brain_decision",
  "trade",
  "risk_decision",
  "order",
  "fill",
  "protection",
  "add",
  "exit",
  "reconciliation",
  "execution_quality",
  "strategy_version",
  "health_transition",
  "research_run",
  "registration",
  "queue_item",
  "packet",
  "decision",
  "audit_event",
  "evidence",
  "chart_series",
  "benchmark_series",
  "regime_context",
  "data_quality",
  "incident",
  "alert",
  "source_fact",
] as const;
export const refKind = z.enum(REF_KINDS);
export type RefKind = z.infer<typeof refKind>;

/**
 * `OwningArea` — read-model-contracts.md §4.2 and §4.3.2, CLOSED at the SEVEN rows of the
 * §4.3.2 table (ADR-0031 A2).
 *
 * **A SECOND, SEPARATE axis from `RefKind`, and never a substitute for one.** `ref_kind`
 * answers *what is this a reference to*; `owning_area` answers *which area is responsible for
 * the record it names*. Expressing the second through the first is what produced the
 * non-conformant kinds ADR-0030 R2 corrected, and this vocabulary exists so that mislabelling
 * is unnecessary rather than merely forbidden.
 *
 * **`AUDIT_TRAIL` is a member and is NEVER a default.** It is declared when the reference
 * names a recorded `AuditEvent`. An absent, unknown or undetermined owning area never
 * resolves to it, and no rule anywhere may use it as a fallback.
 *
 * **No member is added because a route exists.** The navigation registry carries far more
 * routes than seven; a member is added by an accepted decision, never by an implementation
 * noticing a spare page (§2).
 */
export const OWNING_AREAS = [
  "DATA_QUALITY",
  "STRATEGY_HEALTH",
  "RECONCILIATION",
  "SHORT_SIDE",
  "ALERTS",
  "SYSTEM_OPERATIONS",
  "AUDIT_TRAIL",
] as const;
export const owningArea = z.enum(OWNING_AREAS);
export type OwningArea = z.infer<typeof owningArea>;

/** ADR-0026 Brain decision states — consumed, never extended (read-model-contracts.md §2.6). */
export const BRAIN_DECISION_STATES = [
  "READY_FOR_RISK_REVIEW",
  "WATCHLIST",
  "REJECTED",
  "BLOCKED_DATA",
  "BLOCKED_EVENT",
  "BLOCKED_AI",
  "BLOCKED_CONTRADICTION",
  "BLOCKED_BORROW",
] as const;

/** read-model-contracts.md §2.7 — a SEPARATE axis, never merged into the Brain vocabulary. */
export const DOWNSTREAM_STAGES = [
  "RISK_REVIEW_PENDING",
  "RISK_APPROVED",
  "RISK_REJECTED",
  "ORDER_SUBMITTED",
  "ORDER_ACKNOWLEDGED",
  "ORDER_PARTIALLY_FILLED",
  "ORDER_FILLED",
  "ORDER_REJECTED",
  "ORDER_CANCELLED",
] as const;

/**
 * read-model-contracts.md 2.8 -- ADR-0026's Brain specification 13 owns this vocabulary,
 * and this application CONSUMES it. Seven members, never extended here.
 *
 * Reducing and disabling new entries is automatic; RESTORING them is not, and recovery past
 * a governed suspension is never automatic. Nothing in this application causes a transition.
 */
export const STRATEGY_HEALTH_STATES = [
  "HEALTHY",
  "WATCH",
  "DEGRADED",
  "NEW_ENTRIES_REDUCED",
  "NEW_ENTRIES_DISABLED",
  "SUSPENDED",
  "RETIRED",
] as const;
export const strategyHealthState = z.enum(STRATEGY_HEALTH_STATES);
export type StrategyHealthState = z.infer<typeof strategyHealthState>;

/**
 * read-model-contracts.md 2.9 -- consumed exactly as ADR-0005 and the point-in-time contract
 * define them. NO DEFAULT PROFILE IS INVENTED: a profile is DECLARED, never inferred, and
 * Sharadar price data never renders as PUBLIC_PIT.
 */
export const INFORMATION_PROFILES = [
  "PUBLIC_PIT",
  "PROVIDER_REALISTIC_PIT",
  "FORWARD_SYSTEM",
] as const;
export const informationProfile = z.enum(INFORMATION_PROFILES);
export type InformationProfile = z.infer<typeof informationProfile>;
