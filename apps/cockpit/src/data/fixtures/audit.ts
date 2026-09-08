/**
 * The C8 audit-trail projection — Area 26.
 *
 * **A PROJECTION, and not an audit store.** These events are repository-owned fixtures; there
 * is no append path, no signature, no chain, no retention mechanism and no source stream. The
 * projection carries its own identity and its own rebuild count so a reader can see that
 * rebuilding it moves the PROJECTION and leaves every event exactly where it was.
 *
 * The timeline follows the same operational narrative the other C8 areas record — the data
 * condition, the job failure behind it, the incident it opened, the health transition it
 * affected and the reconciliation sweep that found an orphan — and it reaches them by
 * REFERENCE. **No licensed content, vendor row, payload copy or reconstructable derivative
 * appears in any event**, and every subject is a classified reference to a record held
 * elsewhere.
 *
 * Two structural events are included because they are the ones the contract is about:
 *
 *   A CORRECTION APPENDS      it names the event it corrects, the corrected event is still on
 *                             the page, and nothing was edited
 *   A TOMBSTONE WITHDRAWS     it names what it withdrew and the authority it was made under,
 *                             and the withdrawn event's own record stays addressable
 */
import { instantOf, pinsOf } from "@/contracts/factories";
import type { AuditEvent, AuditEventPayload } from "@/contracts/audit-models";
import type { Ref } from "@/contracts/values";

import {
  CALENDAR,
  count,
  demoRef,
  demoReason,
  instantValue,
  refListOf,
} from "./common";
import {
  MARK_FEED_INCIDENT,
  RECONCILIATION_INCIDENT,
} from "./operations";
import { RECONCILIATION_MISMATCH_RUN } from "./quality";

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/** §5.1: `/audit/events` serves 100 rows by default, bounded at 90 days per request. */
const AUDIT_PAGE_SIZE = 100;
const AUDIT_WINDOW_DAYS = 90;

/** The event a correction later restated, and the one a tombstone later withdrew. */
export const CORRECTED_EVENT = "demo-audit-0003";
export const WITHDRAWN_EVENT = "demo-audit-0002";

function subjects(ids: readonly string[], asOf: string) {
  const refs: Ref[] = ids.map((id) =>
    demoRef(id, "source_fact", "AUTHORIZED_READ", "AUDIT_TRAIL"),
  );
  return refListOf(refs, "ZERO_OR_MORE", asOf);
}

function related(refs: readonly Ref[], asOf: string) {
  return refListOf(refs, "ZERO_OR_MORE", asOf);
}

/**
 * A digest of KALPAMANI'S OWN record.
 *
 * Sixteen hexadecimal characters behind an unmistakable prefix, derived deterministically from
 * the event identifier — **never from a vendor payload**, which is the confusion the contract's
 * shape check exists to refuse.
 */
function recordDigest(eventId: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < eventId.length; index += 1) {
    hash ^= eventId.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  const low = hash.toString(16).padStart(8, "0");
  const high = Math.imul(hash ^ eventId.length, 0x85ebca6b) >>> 0;
  return `kalpamani-record-${high.toString(16).padStart(8, "0")}${low}`;
}

interface EventSpec {
  readonly id: string;
  readonly kind: string;
  readonly offsetMs: number;
  /** Seconds between the event and this system seeing it. Zero where it arrived at once. */
  readonly observedLagSeconds?: number;
  readonly actor: string;
  readonly summary: string;
  readonly subjectIds: readonly string[];
  readonly relatedRefs?: readonly Ref[];
  readonly supersedes?: string;
  readonly tombstoneOf?: string;
  readonly deletionAuthority?: string;
}

function buildEvent(spec: EventSpec, asOf: string, originMs: number): AuditEvent {
  const eventMs = originMs - spec.offsetMs;
  const observedMs = eventMs + (spec.observedLagSeconds ?? 0) * 1000;
  return {
    event_id: spec.id,
    event_kind: demoReason(spec.kind),
    event_time: instantOf(eventMs),
    observed_time: instantOf(observedMs),
    actor: demoReason(spec.actor),
    subject_refs: subjects(spec.subjectIds, asOf),
    related_refs: related(spec.relatedRefs ?? [], asOf),
    /**
     * NOTHING IS PINNED, AND THE RECORD SAYS SO RATHER THAN OMITTING IT.
     *
     * No strategy version, factor definition, risk policy, model or prompt exists to pin,
     * because none of those subsystems exists. §4.2 asks for that to be stated.
     */
    lineage: pinsOf({
      code_identity: "cockpit-audit-event-v1",
      config_identity: "fixture-research",
    }),
    record_digest: recordDigest(spec.id),
    ...(spec.supersedes === undefined
      ? {}
      : { supersedes: demoRef(spec.supersedes, "audit_event", "AUTHORIZED_READ", "AUDIT_TRAIL") }),
    ...(spec.tombstoneOf === undefined
      ? {}
      : { tombstone_of: demoRef(spec.tombstoneOf, "audit_event", "AUTHORIZED_READ", "AUDIT_TRAIL") }),
    ...(spec.deletionAuthority === undefined
      ? {}
      : { deletion_authority: demoReason(spec.deletionAuthority) }),
    summary: demoReason(spec.summary),
  };
}

/**
 * Which recorded events name which trade.
 *
 * `TradeDetail.audit_refs` has been an empty list since C6, because no audit producer existed
 * for any scope. One exists now, so the join is **bound to actual matching records** rather
 * than left empty — and a trade this timeline never mentions still carries an empty list,
 * which is a true answer rather than a manufactured one.
 */
export const AUDIT_EVENTS_BY_TRADE: Readonly<Record<string, readonly string[]>> = {
  "demo-trade-arb-0001": [WITHDRAWN_EVENT],
  "demo-trade-sol-0006": [CORRECTED_EVENT, "demo-audit-0010"],
};

export function syntheticAuditEvents(asOf: string, originMs: number): AuditEventPayload {
  const specs: readonly EventSpec[] = [
    {
      id: "demo-audit-0001",
      kind: "CANDIDATE_DECISION_RECORDED",
      offsetMs: 30 * HOUR_MS,
      actor: "DETERMINISTIC_RUNTIME",
      summary: "CANDIDATE_REACHED_READY_FOR_RISK_REVIEW",
      subjectIds: ["demo-source-candidate-journal"],
      relatedRefs: [demoRef("demo-candidate-0001", "candidate", "ENDPOINT")],
    },
    {
      id: WITHDRAWN_EVENT,
      kind: "RISK_DECISION_RECORDED",
      offsetMs: 29 * HOUR_MS,
      actor: "DETERMINISTIC_RUNTIME",
      summary: "RISK_DECISION_RECORDED_AGAINST_A_CANDIDATE",
      subjectIds: ["demo-source-risk-journal"],
      relatedRefs: [demoRef("demo-trade-arb-0001", "trade", "ENDPOINT")],
    },
    {
      id: CORRECTED_EVENT,
      kind: "ORDER_LIFECYCLE_RECORDED",
      offsetMs: 28 * HOUR_MS,
      /** Observed three hours after it happened. Ordering stays by `event_time`. */
      observedLagSeconds: 3 * 3600,
      actor: "DETERMINISTIC_RUNTIME",
      summary: "PROTECTIVE_ORDER_LEVEL_RECORDED",
      subjectIds: ["demo-source-order-journal"],
      relatedRefs: [demoRef("demo-trade-sol-0006", "trade", "ENDPOINT")],
    },
    {
      id: "demo-audit-0004",
      kind: "DATA_CONDITION_RECORDED",
      offsetMs: 26 * HOUR_MS,
      actor: "AUTOMATED_PROJECTION",
      summary: "MARK_DATA_OLDER_THAN_CONTRACT",
      subjectIds: ["demo-source-marks-manifest", "demo-source-mark-refresh-log"],
      relatedRefs: [
        demoRef(MARK_FEED_INCIDENT, "incident", "ENDPOINT", "SYSTEM_OPERATIONS"),
      ],
    },
    {
      id: "demo-audit-0005",
      kind: "INCIDENT_RECORDED",
      offsetMs: 26 * HOUR_MS - MINUTE_MS,
      actor: "AUTOMATED_PROJECTION",
      summary: "INCIDENT_OPENED_AGAINST_A_DATA_SUBJECT",
      subjectIds: ["demo-source-mark-refresh-log"],
      relatedRefs: [
        demoRef(MARK_FEED_INCIDENT, "incident", "ENDPOINT", "SYSTEM_OPERATIONS"),
      ],
    },
    {
      id: "demo-audit-0006",
      kind: "STRATEGY_HEALTH_TRANSITION_RECORDED",
      offsetMs: 25 * HOUR_MS,
      actor: "DETERMINISTIC_RUNTIME",
      summary: "STRATEGY_ENTERED_DEGRADED",
      subjectIds: ["demo-evidence-health"],
      relatedRefs: [
        demoRef("demo-health-transition-0001", "health_transition", "ENDPOINT", "STRATEGY_HEALTH"),
      ],
    },
    {
      id: "demo-audit-0007",
      kind: "SAFETY_ACTION_RECORDED",
      offsetMs: 24 * HOUR_MS,
      actor: "DETERMINISTIC_RUNTIME",
      summary: "NEW_ENTRIES_REDUCED_UNDER_A_PREAPPROVED_RULE",
      subjectIds: ["demo-evidence-health"],
      relatedRefs: [],
    },
    {
      id: "demo-audit-0008",
      kind: "RESEARCH_RUN_RECORDED",
      offsetMs: 12 * HOUR_MS,
      actor: "AUTOMATED_PROJECTION",
      summary: "RESEARCH_RUN_QUEUED_AND_NOT_EXECUTED",
      subjectIds: ["demo-source-research-queue"],
      relatedRefs: [demoRef("demo-run-0001", "research_run", "ENDPOINT")],
    },
    {
      id: "demo-audit-0009",
      kind: "RECONCILIATION_RECORDED",
      offsetMs: HOUR_MS,
      actor: "DETERMINISTIC_RUNTIME",
      summary: "RECONCILIATION_ORPHAN_OBSERVED",
      subjectIds: [`demo-source-${RECONCILIATION_MISMATCH_RUN}`],
      relatedRefs: [
        demoRef(RECONCILIATION_INCIDENT, "incident", "ENDPOINT", "SYSTEM_OPERATIONS"),
      ],
    },
    {
      /**
       * THE CORRECTION. It APPENDS, names what it corrects, and edits nothing.
       *
       * `demo-audit-0003` is still on this page, unchanged, exactly as it was recorded.
       */
      id: "demo-audit-0010",
      kind: "CORRECTION_APPENDED",
      offsetMs: 45 * MINUTE_MS,
      actor: "DETERMINISTIC_RUNTIME",
      summary: "PROTECTIVE_ORDER_LEVEL_CORRECTED",
      subjectIds: ["demo-source-order-journal"],
      relatedRefs: [demoRef("demo-trade-sol-0006", "trade", "ENDPOINT")],
      supersedes: CORRECTED_EVENT,
    },
    {
      /**
       * THE TOMBSTONE. It withdraws a record and names the authority it was made under.
       *
       * The governance record survives: the withdrawn event stays addressable, its own row is
       * unchanged, and nothing about the withdrawal bypasses an identity, classification or
       * scope check.
       */
      id: "demo-audit-0011",
      kind: "RECORD_TOMBSTONED",
      offsetMs: 30 * MINUTE_MS,
      actor: "GOVERNANCE_OWNER_ROLE",
      summary: "RECORD_WITHDRAWN_UNDER_A_RECORDED_AUTHORITY",
      subjectIds: ["demo-source-risk-journal"],
      relatedRefs: [],
      tombstoneOf: WITHDRAWN_EVENT,
      deletionAuthority: "GOVERNANCE_OWNER_DELETION_AUTHORITY",
    },
    {
      id: "demo-audit-0012",
      kind: "GOVERNANCE_DECISION_RECORDED",
      offsetMs: 15 * MINUTE_MS,
      actor: "GOVERNANCE_OWNER_ROLE",
      summary: "MORE_EVIDENCE_REQUESTED_ON_A_PACKET",
      subjectIds: ["demo-source-governance-journal"],
      relatedRefs: [],
    },
  ];

  const items = specs.map((spec) => buildEvent(spec, asOf, originMs));

  return {
    items,
    page: {
      page_size: AUDIT_PAGE_SIZE,
      total: count("reference.total", items.length, asOf),
      truncated: false,
      sort: demoReason("EVENT_TIME_DESCENDING"),
      tiebreak: demoReason("EVENT_ID_ASCENDING"),
    },
    projection: {
      /** SEPARATE from every event identity, and the contract refuses a shared one. */
      projection_id: "demo-audit-projection-0001",
      built_at: instantValue(
        "audit.projection_built_at",
        instantOf(originMs - 15 * MINUTE_MS),
        asOf,
      ),
      /** A rebuild moves THIS number and mutates no event. */
      rebuild_count: count("audit.rebuild_count", 4, asOf),
      source_stream: demoReason("PLATFORM_AUDIT_EVENT_STREAM"),
      source_stream_state: {
        availability: "NOT_IMPLEMENTED",
        reason: "PRODUCER_NOT_IMPLEMENTED",
      },
    },
    gaps: [
      {
        /**
         * A STATED GAP. A missing event is a gap, and never an inferred event.
         *
         * The projection consumed nothing over this window, so the page says what it does not
         * know rather than letting a quiet stretch read as an uneventful one.
         */
        from: instantOf(originMs - 20 * HOUR_MS),
        to: instantOf(originMs - 13 * HOUR_MS),
        reason: "UPSTREAM_INPUT_MISSING",
        detail: demoReason("NO_SOURCE_EVENTS_WERE_CONSUMED_OVER_THIS_WINDOW"),
      },
    ],
    window: {
      from: instantOf(originMs - AUDIT_WINDOW_DAYS * DAY_MS),
      to: asOf,
      calendar: CALENDAR,
      timezone: "UTC",
    },
    event_count: count("audit.event_count", items.length, asOf),
  };
}
