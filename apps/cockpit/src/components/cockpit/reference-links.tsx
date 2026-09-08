"use client";

import Link from "next/link";

import { referenceDestination, owningAreaDestination } from "@/lib/reference-navigation";
import { withScope, type ViewScope } from "@/lib/scope";

/**
 * The two navigation affordances a disclosed reference may offer — `read-model-contracts.md`
 * §4.3.1 (R10) and §4.3.2 (ADR-0031 A3), rendered once so both disclosures agree.
 *
 * ```text
 * TARGET       keyed by RefKind          names the RECORD, and reads as opening it
 * OWNING AREA  keyed by Ref.owning_area  names the AREA, and says so
 * ```
 *
 * **They are distinct controls and are never merged.** A reference may offer both, one, or
 * neither, and **neither is a fallback for the other**: an unmapped kind yields no target link
 * and the declared area does not stand in for it; an absent area yields no area link and the
 * R10 allowlist does not supply one.
 *
 * **The area label may never read as retrieval.** §4.3.2 forbids phrasing it as resolving,
 * opening, retrieving, viewing or showing the reference, the evidence or the artefact — a
 * control labelled *"View evidence"* that lands on an area page has told the reader it
 * retrieved something it did not. The labels come from the closed table and end in *area*.
 *
 * **An area link asserts nothing about the destination.** Six of the seven routes are
 * placeholders, so the affordance carries the destination's own status rather than implying a
 * built screen, and navigating asserts nothing about whether the producing subsystem exists.
 *
 * This component decides nothing. Both destinations are resolved by the closed allowlists in
 * `reference-navigation.ts`; a second copy of either table living in a component is how the
 * two duplicated destination literals this cycle deleted came to exist.
 */
export function ReferenceDestinations({
  reference,
  scope,
}: {
  readonly reference: {
    readonly ref_kind: string;
    readonly ref_id: string;
    readonly owning_area?: string | undefined;
  };
  readonly scope: ViewScope;
}) {
  const target = referenceDestination(reference);
  const area = owningAreaDestination(reference);
  return (
    <>
      {target !== null ? (
        <Link
          href={withScope(target.href, scope)}
          data-testid="reference-target-link"
          className="text-accent underline underline-offset-2"
        >
          {target.label} →
        </Link>
      ) : (
        /*
         * NO TARGET DESTINATION IS STATED, AND NOT LEFT BLANK.
         *
         * The R10 allowlist maps no route for this kind, and R10 is explicit that an unmapped
         * kind yields NO LINK -- "never a guess". Rendering nothing at all left a reader unable
         * to tell a reference they COULD have followed from one this version cannot resolve, so
         * the absence is said out loud. An owning area, where one is declared, is rendered
         * BESIDE this and never INSTEAD of it.
         */
        <span
          className="text-text-tertiary"
          data-testid="evidence-no-destination"
          title="No V1 destination is catalogued for this reference kind."
        >
          no V1 destination
        </span>
      )}
      {area !== null && (
        <span className="inline-flex items-center gap-1" data-testid="reference-area">
          <Link
            href={withScope(area.href, scope)}
            data-testid="reference-area-link"
            data-owning-area={reference.owning_area}
            data-area-status={area.status}
            className="text-accent underline underline-offset-2"
          >
            {area.label} →
          </Link>
          {area.status !== "implemented" && (
            <span
              className="text-text-tertiary"
              data-testid="reference-area-placeholder"
              title="The area screen is not built yet, and its producing subsystem does not exist."
            >
              (not yet implemented)
            </span>
          )}
        </span>
      )}
    </>
  );
}
