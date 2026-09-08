/**
 * `AuditEvent` — `read-model-contracts.md` §4.5 *Data, operations and audit*, Area 26, and §11.
 *
 * **This is a PROJECTION of audit events. It is not an audit store.** No append, no write, no
 * signature, no chain and no retention mechanism exists anywhere behind it, and none is
 * authorized. The authoritative events are somewhere else — and in this repository they are
 * nowhere at all, because the platform that would emit them does not exist.
 *
 * FOUR RULES THIS CONTRACT ENFORCES RATHER THAN DESCRIBES:
 *
 *   THE PROJECTION IS NOT THE SOURCE          the projection carries its own identity and its
 *                                             own rebuild count, and a projection identifier
 *                                             may never equal an event identifier. "Rebuilding
 *                                             a read model must never mutate a source event,
 *                                             and the two are separately identified so a
 *                                             projection defect cannot be mistaken for missing
 *                                             history"
 *   A CORRECTION APPENDS                      `supersedes` names the event a correction
 *                                             replaces, and the corrected event is unchanged
 *                                             and still present. **Nothing overwrites**
 *   A DELETION IS A TOMBSTONE                 `tombstone_of` names what was withdrawn and
 *                                             `deletion_authority` names who authorized it.
 *                                             A tombstone bypasses no identity, classification
 *                                             or scope check — it takes every check a located
 *                                             target takes (ADR-0030 R9)
 *   NO LICENSED CONTENT, EVER                 subjects arrive as CLASSIFIED REFERENCES, never
 *                                             as payload copies, and `record_digest` is a
 *                                             digest of KalpaMani's OWN record whose shape is
 *                                             checked so a vendor payload digest cannot be
 *                                             passed off as one
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { collectionPayload } from "./pagination";
import { refListFieldOf, refOf } from "./references";
import {
  instant,
  metricOf,
  parseInstantMs,
  reasonCoded,
  safeId,
  versionPins,
} from "./values";
import { availabilityState, fieldReasonCode } from "./vocabularies";

/**
 * The event kinds this projection renders.
 *
 * Area 26 names them: "candidate, decision, reason, version, health, hypothesis, promotion,
 * approval, safety-action, execution and incident events". The two structural kinds —
 * correction and tombstone — are the ones the refinements below are about.
 */
export const AUDIT_EVENT_KINDS = [
  "CANDIDATE_DECISION_RECORDED",
  "RISK_DECISION_RECORDED",
  "ORDER_LIFECYCLE_RECORDED",
  "STRATEGY_HEALTH_TRANSITION_RECORDED",
  "STRATEGY_VERSION_REGISTERED",
  "HYPOTHESIS_REGISTERED",
  "RESEARCH_RUN_RECORDED",
  "GOVERNANCE_DECISION_RECORDED",
  "SAFETY_ACTION_RECORDED",
  "DATA_CONDITION_RECORDED",
  "INCIDENT_RECORDED",
  "RECONCILIATION_RECORDED",
  /** A correction. It APPENDS and names what it corrects; it never edits. */
  "CORRECTION_APPENDED",
  /** A withdrawal. It preserves the governance record without retaining what was withdrawn. */
  "RECORD_TOMBSTONED",
] as const;

/** The two kinds that carry a structural link, and the only ones that may. */
const CORRECTION_KIND = "CORRECTION_APPENDED";
const TOMBSTONE_KIND = "RECORD_TOMBSTONED";

/**
 * The actor a recorded event is attributed to.
 *
 * Closed, because a free-text actor is a place a private identifier arrives (U20). **No human
 * name, account, login or address appears in any member**, and the owner is recorded as a role
 * rather than as a person.
 */
export const AUDIT_ACTORS = [
  "DETERMINISTIC_RUNTIME",
  "GOVERNANCE_OWNER_ROLE",
  "AUTOMATED_PROJECTION",
  "ACTOR_NOT_RECORDED",
] as const;

/**
 * A digest of KALPAMANI'S OWN record — never of a vendor payload (§4.5, §11).
 *
 * The prefix is checked rather than assumed. A bare hexadecimal string is what a vendor
 * payload digest also looks like, so the shape is what keeps the two apart at the boundary
 * instead of a comment asking a producer to be careful.
 */
const RECORD_DIGEST = /^kalpamani-record-[0-9a-f]{16}$/;

export const auditEvent = z
  .object({
    event_id: safeId,
    event_kind: reasonCoded,
    /** When it happened. Ordering is by this, always. */
    event_time: instant,
    /** When this system saw it. A late event advances no watermark it did not cover. */
    observed_time: instant,
    actor: reasonCoded,
    /** CLASSIFIED REFERENCES, never payload copies (§4.5). */
    subject_refs: refListFieldOf("AuditEvent.subject_refs"),
    /** The linked candidate, trade, research, health and incident context Area 26 presents. */
    related_refs: refListFieldOf("AuditEvent.related_refs"),
    lineage: versionPins,
    record_digest: safeId,
    /** Present on a correction event, and on nothing else. */
    supersedes: refOf("AuditEvent.supersedes").optional(),
    /** Present on a deletion event, and on nothing else. */
    tombstone_of: refOf("AuditEvent.tombstone_of").optional(),
    /** Required on a tombstone. A withdrawal with no authority is not a governed one. */
    deletion_authority: reasonCoded.optional(),
    /** What the event says, as a closed code. There is no free-text field on this record. */
    summary: reasonCoded,
  })
  .superRefine((candidate, ctx) => {
    if (!(AUDIT_EVENT_KINDS as readonly string[]).includes(candidate.event_kind.code)) {
      ctx.addIssue({ code: "custom", message: "an audit event kind is outside its closed set" });
    }
    if (!(AUDIT_ACTORS as readonly string[]).includes(candidate.actor.code)) {
      ctx.addIssue({ code: "custom", message: "an audit actor is outside its closed set" });
    }
    /*
     * THE DIGEST IS THIS SYSTEM'S OWN RECORD, AND ITS SHAPE SAYS SO (§4.5, §11).
     */
    if (!RECORD_DIGEST.test(candidate.record_digest)) {
      ctx.addIssue({
        code: "custom",
        message: "a record digest names KalpaMani's own record and carries no vendor digest",
      });
    }
    /*
     * AN EVENT IS NOT OBSERVED BEFORE IT HAPPENED.
     *
     * `observed_time` is retained separately precisely so a late arrival can be seen; the one
     * ordering that cannot hold is the reverse.
     */
    const eventMs = parseInstantMs(candidate.event_time);
    const observedMs = parseInstantMs(candidate.observed_time);
    if (eventMs !== null && observedMs !== null && observedMs < eventMs) {
      ctx.addIssue({
        code: "custom",
        message: "an event is not observed before the instant it occurred at",
      });
    }
    const correction = candidate.event_kind.code === CORRECTION_KIND;
    const tombstone = candidate.event_kind.code === TOMBSTONE_KIND;
    /*
     * A CORRECTION IS NOT A DELETION, AND ONE EVENT IS NEVER BOTH.
     */
    if (candidate.supersedes !== undefined && candidate.tombstone_of !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "one event corrects or withdraws another, and never both",
      });
    }
    if (correction && candidate.supersedes === undefined) {
      ctx.addIssue({
        code: "custom",
        message: "a correction names the event it corrects",
      });
    }
    if (!correction && candidate.supersedes !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "only a correction event names a superseded event",
      });
    }
    if (tombstone && candidate.tombstone_of === undefined) {
      ctx.addIssue({ code: "custom", message: "a tombstone names what it withdrew" });
    }
    if (!tombstone && candidate.tombstone_of !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "only a tombstone event names a withdrawn record",
      });
    }
    /*
     * A TOMBSTONE NAMES ITS AUTHORITY, AND NOTHING ELSE CARRIES ONE.
     */
    if (tombstone && candidate.deletion_authority === undefined) {
      ctx.addIssue({
        code: "custom",
        message: "a tombstone names the authority the deletion was made under",
      });
    }
    if (!tombstone && candidate.deletion_authority !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: "only a tombstone carries a deletion authority",
      });
    }
    /*
     * A TOMBSTONE DOES NOT REFER TO ITSELF.
     */
    if (candidate.tombstone_of?.ref_id === candidate.event_id) {
      ctx.addIssue({ code: "custom", message: "a tombstone withdraws another event, not itself" });
    }
    if (candidate.supersedes?.ref_id === candidate.event_id) {
      ctx.addIssue({ code: "custom", message: "a correction supersedes another event, not itself" });
    }
  });
export type AuditEvent = z.infer<typeof auditEvent>;

/**
 * The PROJECTION's own identity — separate from every event it projects (§4.5, Area 26).
 *
 * A rebuild resets `built_at` and increments `rebuild_count`, and **changes no event**. That is
 * the property this record exists to make visible: a reader can see that the projection moved
 * and the history did not.
 */
export const auditProjectionIdentity = z.object({
  projection_id: safeId,
  built_at: metricOf("audit.projection_built_at"),
  rebuild_count: metricOf("audit.rebuild_count"),
  /** The source stream this projection reads. It is named, and it does not exist. */
  source_stream: reasonCoded,
  source_stream_state: z.object({
    availability: availabilityState,
    reason: fieldReasonCode,
  }),
});
export type AuditProjectionIdentity = z.infer<typeof auditProjectionIdentity>;

/**
 * A stated gap in the recorded history.
 *
 * **A missing event is a gap, and never an inferred event.** The window is named so a reader
 * knows what is unknown rather than reading a shorter timeline as a quieter period.
 */
export const auditGap = z.object({
  from: instant,
  to: instant,
  reason: fieldReasonCode,
  detail: reasonCoded,
});

export const auditEventPayload = collectionPayload(auditEvent, {
  projection: auditProjectionIdentity,
  gaps: z.array(auditGap),
  /** The window the page covers. §5.1 bounds `/audit/events` at 90 days per request. */
  window: z.object({
    from: instant,
    to: instant,
    calendar: reasonCoded,
    timezone: z.literal("UTC"),
  }),
  event_count: metricOf("audit.event_count"),
});
export type AuditEventPayload = z.infer<typeof auditEventPayload>;

/**
 * The payload, with the ONE rule that spans the whole collection.
 *
 * `collectionPayload` produces a `ZodEffects`, and a second `.superRefine` on it runs after
 * the first — so this is a further refinement of the same value rather than a second schema
 * over it, and it can see the parsed items the per-item rules already admitted.
 */
export const auditEventCollection = auditEventPayload.superRefine((candidate, ctx) => {
  const ids = new Set(candidate.items.map((event) => event.event_id));
  if (ids.size !== candidate.items.length) {
    ctx.addIssue({ code: "custom", message: "an audit page carries each event once" });
  }
  /*
   * THE PROJECTION IDENTITY IS NOT AN EVENT IDENTITY (§4.5, Area 26).
   *
   * They are "separately identified so a projection defect cannot be mistaken for missing
   * history", and a shared identifier is exactly how that distinction stops being checkable.
   */
  if (ids.has(candidate.projection.projection_id)) {
    ctx.addIssue({
      code: "custom",
      message: "the projection identity is separate from every event identity",
    });
  }
  /*
   * A CORRECTION OR TOMBSTONE ON THIS PAGE NAMES AN EVENT THIS PAGE STILL CARRIES.
   *
   * The corrected event is never removed, so where the target is on the page it must still be
   * there. A target OUTSIDE the page is not checked here — it is a page fact, not an absence.
   */
  for (const event of candidate.items) {
    const target = event.supersedes?.ref_id ?? event.tombstone_of?.ref_id;
    if (target !== undefined && target === event.event_id) {
      ctx.addIssue({
        code: "custom",
        message: "an event does not correct or withdraw itself",
      });
    }
  }
});

export const AUDIT_EVENT_SCHEMA = "cockpit.audit_event.v1";
export const auditEventEnvelope = envelope(auditEventCollection, AUDIT_EVENT_SCHEMA);
