/**
 * Following a reference — `read-model-contracts.md` §4.3.1, under ADR-0030 R6, R8 and R9.
 *
 * Validating a reference's DECLARATION is `references.ts`. This module answers the separate
 * question a consumer asks when it tries to FOLLOW one, and its whole purpose is that the
 * five ways a target can be unavailable are **five different answers**:
 *
 *   the identifier names nothing            REFERENT_NOT_FOUND
 *   the producer does not exist here        PRODUCER_NOT_IMPLEMENTED
 *   the caller lacks the scope              SCOPE_MISSING / SCOPE_INSUFFICIENT
 *   classification withholds the target     CLASSIFICATION_WITHHELD
 *   the reference is malformed              refused at admission, and never reached here
 *
 * **Scope denial is not classification withholding.** A caller lacking `risk:read` receives a
 * scope error; a caller holding it whose classification bars the target receives
 * `CLASSIFICATION_WITHHELD`. Collapsing them reports a policy decision as a data-sensitivity
 * one, which is why §5 has separated them since before this cycle.
 *
 * **`Ref.classification` is a LABEL and not access or publication authorization** (R10), and a
 * reference the caller may not follow stays VISIBLE (R9), so the reader knows something
 * exists that they may not see. **The label is a producer-controlled claim**, so it is never
 * what a read is authorized against: the required scope comes from the accepted §4.3 table,
 * and the located target's OWN classification is what withholds it.
 *
 * **Absent metadata never proves conformance.** A located target arrives with its own kind,
 * its own identifier and its own environment, provenance and classification labels, or it is
 * not located. There is no shape in which "the caller supplied nothing" reads as "everything
 * checked out" — which is what an optional label bag produces.
 */
import { CROSS_PROVENANCE_AUTHORIZED, contractReadScope, declarationFor } from "./references";
import type { HostFieldKey } from "./references";
import type { Ref } from "./values";
import type {
  AvailabilityState,
  DataClassification,
  DataProvenance,
  ErrorCode,
  FieldReasonCode,
  RefKind,
} from "./vocabularies";

/** The resolving response's own labels — what the caller already holds. */
export interface ResolvingContext {
  readonly environment: string;
  readonly provenance: DataProvenance;
  /** Every access scope this caller holds. */
  readonly heldScopes: readonly string[];
  /**
   * The scope the CALLER believes the read requires.
   *
   * It is consulted **only** where §4.3 names none for the kind — `evidence` and
   * `source_fact`, whose rows read *"the scope named on the reference"* and whose scope a
   * `Ref` has no field to carry (§4.2). Where the table DOES name one, the table governs and
   * a contradicting declaration is REFUSED: a caller free to name the requirement could name
   * one it happens to hold.
   */
  readonly declaredScope?: string;
  /** Classifications this caller may read. */
  readonly readableClassifications: readonly DataClassification[];
}

/**
 * The labels a located target carries ITSELF.
 *
 * Every field is required. `provenance` is the target's, never the resolving envelope's
 * copied onto it — copying is exactly the silent provenance mixing R8 prohibits — and
 * `classification` is the target's own, never the reference's label restated.
 */
export interface TargetLabels {
  readonly environment: string;
  readonly provenance: DataProvenance;
  readonly classification: DataClassification;
}

/**
 * A target the producer actually holds, carrying its own identity (R8).
 *
 * The kind and the identifier are the TARGET ENTITY's, never the container it was retrieved
 * through: `brain_decision` is retrieved by the candidate route and is not the candidate.
 */
export interface LocatedTarget {
  readonly kind: RefKind;
  readonly id: string;
  readonly labels: TargetLabels;
}

/**
 * A RECORDED tombstone, and not a flag saying one exists (R9).
 *
 * §4.3.1 keeps a withdrawn record addressable through `AuditEvent.tombstone_of` and
 * `supersedes`, so a tombstone is an `audit_event` that NAMES the entity it withdrew. A bare
 * boolean establishes no such relationship: it turns *this target is gone* into something the
 * caller asserts rather than something the record shows, and any caller could assert it about
 * any identifier.
 */
export interface RecordedTombstone {
  /** The withdrawing audit event's own identifier. */
  readonly auditEventId: string;
  /** The entity it withdrew. It must be the one the reference names. */
  readonly tombstoneOf: string;
  readonly labels: TargetLabels;
}

/** What a producer for this reference's kind is, in the requested scope. */
export type ProducerState =
  /** Implemented for the requested environment, provenance and read-model scope. */
  | "IMPLEMENTED"
  /**
   * No producing subsystem exists for the requested scope.
   *
   * A producer implemented against repository-owned SYNTHETIC fixtures exists for `SYNTHETIC`
   * provenance **and for nothing else**, and never establishes that the real subsystem —
   * the Brain, a scanner, a risk or execution runtime — has been built.
   */
  | "NOT_IMPLEMENTED_FOR_SCOPE";

export type ReferenceOutcome =
  /** The target was located, validated and is readable. */
  | { readonly status: "RESOLVED" }
  /** A §5 error on the attempt to follow it. The reference itself stays visible. */
  | { readonly status: "REFUSED"; readonly code: ErrorCode }
  /**
   * An availability answer for the VALUE-BEARING field the target would have filled.
   *
   * Never for the bare `Ref`, which has no `availability` and no `reason` field (R9).
   */
  | {
      readonly status: "UNAVAILABLE";
      readonly availability: AvailabilityState;
      readonly reason: FieldReasonCode;
    };

/** The absence answer a read model reports, and the ONE place the R6/R9 rule is written. */
export interface TargetAbsence {
  readonly availability: AvailabilityState;
  readonly reason: FieldReasonCode;
}

/**
 * What a read model reports for a REQUESTED TARGET IDENTITY it could not serve (R6, R9).
 *
 * This is the rule an ordinary read runs into, not only a helper a test can call: an unknown
 * identifier reaches it through `tradeDetail`, `tradeLifecycle` and `candidateDetail`, and
 * `followReference` reaches it through this same function so the two cannot drift apart.
 *
 * **An implemented producer that lacks one record is NOT producer nonexistence.** Saying
 * `PRODUCER_NOT_IMPLEMENTED` there asserts something false about the subsystem, and saying
 * `NOT_APPLICABLE` says the question does not apply to the subject — which ADR-0028 reserves
 * for a property of the subject or of the arithmetic, and which R9 explicitly refuses here:
 * *"a reference whose identifier names nothing is exactly we do not have it — the question
 * still applies, and the target is absent."*
 */
export function targetAvailability(producer: ProducerState, located: boolean): TargetAbsence {
  if (producer === "NOT_IMPLEMENTED_FOR_SCOPE") {
    return { availability: "NOT_IMPLEMENTED", reason: "PRODUCER_NOT_IMPLEMENTED" };
  }
  if (located) {
    /* A located target is not an absence, and asking this about one is a caller defect. */
    throw new Error("targetAvailability describes an ABSENT target, and this one was located");
  }
  return { availability: "NOT_YET_AVAILABLE", reason: "REFERENT_NOT_FOUND" };
}

/**
 * Follow one reference, and say exactly which of the five outcomes applies.
 *
 * `target` carries what the producer actually holds. A located target brings its own kind,
 * identifier and labels; a recorded tombstone brings the audit event that withdrew it and the
 * entity it withdrew. Neither can be asserted by a bare flag, and neither is validated by
 * omission.
 */
export function followReference(
  key: HostFieldKey,
  reference: Ref,
  context: ResolvingContext,
  target: {
    readonly producer: ProducerState;
    readonly located?: LocatedTarget;
    readonly tombstone?: RecordedTombstone;
  },
): ReferenceOutcome {
  /*
   * THE REQUIRED SCOPE COMES FROM THE ACCEPTED TABLE, NOT FROM THE CALLER.
   *
   * §4.3 names the scope for every kind but `evidence` and `source_fact`, whose rows say
   * "the scope named on the reference" -- and §4.2 gives `Ref` no field to name it in, so for
   * those two the caller's declaration is the only available input and is used as such.
   * Everywhere else a declaration that DISAGREES with the table is refused rather than
   * honoured.
   */
  const contracted = contractReadScope(reference.ref_kind);
  if (contracted !== null && context.declaredScope !== undefined) {
    if (context.declaredScope !== contracted) {
      return { status: "REFUSED", code: "PROJECTION_ERROR" };
    }
  }
  const required = contracted ?? context.declaredScope;
  if (required === undefined) {
    /* Nothing names what this read requires, so nothing authorizes it. */
    return { status: "REFUSED", code: "SCOPE_MISSING" };
  }
  /*
   * SCOPE FIRST, AND BEFORE ANY TARGET FACT IS CONSULTED.
   *
   * A caller who may not perform the read must not learn from the answer whether the record
   * exists -- so the denial is decided from the caller's authorization alone, and no denied
   * target payload is reached, rendered or cached.
   */
  if (!context.heldScopes.includes(required)) {
    return {
      status: "REFUSED",
      code: context.heldScopes.length === 0 ? "SCOPE_MISSING" : "SCOPE_INSUFFICIENT",
    };
  }
  if (!context.readableClassifications.includes(reference.classification)) {
    /*
     * The caller HAS the scope, and the classification withholds the target. This is a
     * different answer from the scope denial above, and the reference stays VISIBLE.
     *
     * This is the REFERENCE's label, which is a producer claim: it can only WITHHOLD, never
     * admit. What the caller may actually read is decided again below, from the target's own
     * classification, so a reference under-labelled `PUBLIC_SAFE` cannot open a private
     * target.
     */
    return {
      status: "UNAVAILABLE",
      availability: "NOT_AUTHORIZED",
      reason: "CLASSIFICATION_WITHHELD",
    };
  }
  if (target.producer === "NOT_IMPLEMENTED_FOR_SCOPE") {
    const absence = targetAvailability(target.producer, false);
    return { status: "UNAVAILABLE", availability: absence.availability, reason: absence.reason };
  }
  const tombstone = target.tombstone;
  if (tombstone !== undefined) {
    /*
     * A RECORDED TOMBSTONE IS NOT AN UNKNOWN TARGET, AND IT IS NOT EXEMPT EITHER.
     *
     * The reference resolves TO the tombstone, so the tombstone IS a located target and takes
     * every check a located target takes. Returning RESOLVED the moment a tombstone flag
     * appeared skipped environment, provenance and classification entirely, which would have
     * admitted one environment's withdrawal as another's.
     */
    if (tombstone.tombstoneOf !== reference.ref_id) {
      return { status: "REFUSED", code: "PROJECTION_ERROR" };
    }
    return locatedOutcome(key, context, reference, tombstone.labels);
  }
  const located = target.located;
  if (located === undefined) {
    /*
     * AN IMPLEMENTED PRODUCER THAT LACKS ONE RECORD IS NOT PRODUCER NONEXISTENCE.
     *
     * Declaring UNRESOLVABLE_V1 or PRODUCER_NOT_IMPLEMENTED here would assert something false
     * about the subsystem, and a bare 404 is the outcome UNRESOLVABLE_V1 exists to prevent.
     * It is an ABSENCE and never an INAPPLICABILITY, so it carries NOT_YET_AVAILABLE and
     * never NOT_APPLICABLE.
     */
    const absence = targetAvailability(target.producer, false);
    return { status: "UNAVAILABLE", availability: absence.availability, reason: absence.reason };
  }
  /*
   * A REFERENCE RESOLVES TO ITS OWN TARGET (R8).
   *
   * The kind and the identifier compared here are the TARGET ENTITY's own, and never the
   * container it was retrieved through. Nothing substitutes: no nearest match, no default and
   * no first row.
   */
  if (located.kind !== reference.ref_kind || located.id !== reference.ref_id) {
    return { status: "REFUSED", code: "PROJECTION_ERROR" };
  }
  return locatedOutcome(key, context, reference, located.labels);
}

/** Environment, provenance and classification, checked against a located target's OWN labels. */
function locatedOutcome(
  key: HostFieldKey,
  context: ResolvingContext,
  reference: Ref,
  labels: TargetLabels,
): ReferenceOutcome {
  const failure = targetLabelFailure(key, context, labels);
  if (failure !== null) {
    return { status: "REFUSED", code: failure };
  }
  if (!context.readableClassifications.includes(labels.classification)) {
    /* The TARGET's own classification withholds it, whatever the reference claimed. */
    return {
      status: "UNAVAILABLE",
      availability: "NOT_AUTHORIZED",
      reason: "CLASSIFICATION_WITHHELD",
    };
  }
  if (labels.classification !== reference.classification) {
    /*
     * A MISMATCH NEVER GRANTS ACCESS.
     *
     * The reference labels one classification and the located target carries another, so one
     * of the two is wrong and neither is authority. It is refused rather than resolved under
     * whichever of the two happens to be the permissive one.
     */
    return { status: "REFUSED", code: "PROJECTION_ERROR" };
  }
  return { status: "RESOLVED" };
}

/**
 * R8's environment and provenance rule, checked against the target's OWN labels.
 *
 * Environment must match the resolving envelope, always. Provenance must match too, except
 * where the catalogue explicitly authorizes a cross-provenance reference AND the target
 * carries its own provenance label — in which case the label governs and is displayed.
 */
export function targetLabelFailure(
  key: HostFieldKey,
  context: ResolvingContext,
  labels: TargetLabels,
): ErrorCode | null {
  if (labels.environment !== context.environment) {
    return "PROJECTION_ERROR";
  }
  if (labels.provenance === context.provenance) {
    return null;
  }
  return CROSS_PROVENANCE_AUTHORIZED.includes(key) ? null : "PROJECTION_ERROR";
}

/** Whether this host field may carry a labelled target of a different provenance (R8). */
export function permitsCrossProvenance(key: HostFieldKey): boolean {
  return CROSS_PROVENANCE_AUTHORIZED.includes(key);
}

/** Whether the catalogue implements the read model that produces this field's targets. */
export function producerStateFor(key: HostFieldKey): ProducerState {
  return declarationFor(key).implemented ? "IMPLEMENTED" : "NOT_IMPLEMENTED_FOR_SCOPE";
}
