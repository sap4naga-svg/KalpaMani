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
 * **`Ref.classification` is a LABEL and not access or publication authorization**, and a
 * reference the caller may not follow stays VISIBLE (R9), so the reader knows something
 * exists that they may not see.
 */
import { CROSS_PROVENANCE_AUTHORIZED, declarationFor } from "./references";
import type { HostFieldKey } from "./references";
import type { Ref } from "./values";
import type {
  AvailabilityState,
  DataClassification,
  DataProvenance,
  ErrorCode,
  FieldReasonCode,
} from "./vocabularies";

/** The resolving response's own labels — what the caller already holds. */
export interface ResolvingContext {
  readonly environment: string;
  readonly provenance: DataProvenance;
  /** Every access scope this caller holds. */
  readonly heldScopes: readonly string[];
  /** The scope the target read requires. */
  readonly requiredScope: string;
  /** Classifications this caller may read. */
  readonly readableClassifications: readonly DataClassification[];
}

/**
 * The target's OWN labels, where a target was located.
 *
 * `provenance` is the target's, never the resolving envelope's copied onto it — copying is
 * exactly the silent provenance mixing R8 prohibits.
 */
export interface TargetLabels {
  readonly environment: string;
  readonly provenance: DataProvenance;
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
  /** The target was located and is readable. */
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

/**
 * Follow one reference, and say exactly which of the five outcomes applies.
 *
 * `found` is whether the producer holds a record for this identifier, and is meaningful only
 * when the producer is implemented. `tombstone` records the case §4.3.1 keeps separate: where
 * `AuditEvent.tombstone_of` or `supersedes` records a withdrawn target the reference resolves
 * TO IT, and only where nothing is recorded is the outcome `REFERENT_NOT_FOUND`.
 */
export function followReference(
  key: HostFieldKey,
  reference: Ref,
  context: ResolvingContext,
  target: {
    readonly producer: ProducerState;
    readonly found: boolean;
    readonly tombstone?: boolean;
    readonly labels?: TargetLabels;
  },
): ReferenceOutcome {
  /*
   * SCOPE FIRST, AND BEFORE ANY TARGET FACT IS CONSULTED.
   *
   * A caller who may not perform the read must not learn from the answer whether the record
   * exists -- so the denial is decided from the caller's authorization alone, and no denied
   * target payload is reached, rendered or cached.
   */
  if (!context.heldScopes.includes(context.requiredScope)) {
    return {
      status: "REFUSED",
      code: context.heldScopes.length === 0 ? "SCOPE_MISSING" : "SCOPE_INSUFFICIENT",
    };
  }
  if (!context.readableClassifications.includes(reference.classification)) {
    /*
     * The caller HAS the scope, and the classification withholds the target. This is a
     * different answer from the scope denial above, and the reference stays VISIBLE.
     */
    return {
      status: "UNAVAILABLE",
      availability: "NOT_AUTHORIZED",
      reason: "CLASSIFICATION_WITHHELD",
    };
  }
  if (target.producer === "NOT_IMPLEMENTED_FOR_SCOPE") {
    return {
      status: "UNAVAILABLE",
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
    };
  }
  if (!target.found) {
    if (target.tombstone === true) {
      /* A recorded tombstone is not an unknown target: the reference resolves to it. */
      return { status: "RESOLVED" };
    }
    /*
     * AN IMPLEMENTED PRODUCER THAT LACKS ONE RECORD IS NOT PRODUCER NONEXISTENCE.
     *
     * Declaring UNRESOLVABLE_V1 or PRODUCER_NOT_IMPLEMENTED here would assert something
     * false about the subsystem, and a bare 404 is the outcome UNRESOLVABLE_V1 exists to
     * prevent. It is an ABSENCE and never an INAPPLICABILITY, so it carries
     * NOT_YET_AVAILABLE and never NOT_APPLICABLE.
     */
    return {
      status: "UNAVAILABLE",
      availability: "NOT_YET_AVAILABLE",
      reason: "REFERENT_NOT_FOUND",
    };
  }
  const labels = target.labels;
  if (labels !== undefined) {
    const failure = targetLabelFailure(key, context, labels);
    if (failure !== null) {
      return { status: "REFUSED", code: failure };
    }
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
