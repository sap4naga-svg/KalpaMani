/**
 * Availability presentation -- ui-ux-specification.md section 9.2.
 *
 * Every one of the eleven availability states renders DISTINCTLY, and NONE renders as
 * zero, healthy, passed or no incidents (U4). Three distinctions are acceptance criteria:
 *
 *   EMPTY_VERIFIED  is not  NOT_YET_AVAILABLE
 *   NOT_IMPLEMENTED is not  NOT_AUTHORIZED
 *   STALE           is not  AVAILABLE
 *
 * Colour is never the only carrier of meaning (U11): every state carries a short glyph and
 * a label in addition to its tone.
 */
import { Badge } from "@/components/ui/primitives";
import { isValueBearing } from "@/contracts/validity";
import type { AvailabilityState, FieldReasonCode } from "@/contracts/vocabularies";

type Tone = "positive" | "warning" | "negative" | "unavailable" | "neutral" | "info";

interface StatePresentation {
  readonly label: string;
  readonly glyph: string;
  readonly tone: Tone;
  /** How the state reads to an executive, in the specification's own words. */
  readonly meaning: string;
}

export const STATE_PRESENTATION: Readonly<Record<AvailabilityState, StatePresentation>> = {
  AVAILABLE: {
    label: "Available",
    glyph: "●",
    tone: "positive",
    meaning: "A real value, with its as-of time.",
  },
  STALE: {
    label: "Stale",
    glyph: "◑",
    tone: "warning",
    meaning: "The value, with its age and its freshness contract. Not available.",
  },
  PARTIAL: {
    label: "Partial",
    glyph: "◧",
    tone: "warning",
    meaning: "The available extent, with the missing extent stated.",
  },
  EMPTY_VERIFIED: {
    label: "Empty (verified)",
    glyph: "○",
    tone: "neutral",
    meaning: "No rows, and that is the correct answer.",
  },
  NOT_YET_AVAILABLE: {
    label: "Not yet available",
    glyph: "◌",
    tone: "unavailable",
    meaning: "Specified, not yet fed. The dependency is named.",
  },
  NOT_IMPLEMENTED: {
    label: "Not implemented",
    glyph: "◍",
    tone: "unavailable",
    meaning: "The producing subsystem does not exist.",
  },
  NOT_AUTHORIZED: {
    label: "Not authorized",
    glyph: "⊘",
    tone: "unavailable",
    meaning: "Exists, may not run. The authorization is named.",
  },
  UNEVALUATED: {
    label: "Unevaluated",
    glyph: "◇",
    tone: "unavailable",
    meaning: "Not assessed. Never pending, never blank, never zero.",
  },
  INSUFFICIENT_OBSERVATIONS: {
    label: "Insufficient observations",
    glyph: "◔",
    tone: "unavailable",
    meaning: "Computable, and would not be meaningful. No ratio is shown.",
  },
  NOT_APPLICABLE: {
    label: "Not applicable",
    glyph: "—",
    tone: "unavailable",
    meaning: "The question does not apply to this subject, or the arithmetic is undefined.",
  },
  ERROR: {
    label: "Error",
    glyph: "✕",
    tone: "negative",
    meaning: "Production failed, with a closed reason code and no fabricated payload.",
  },
};

export function AvailabilityBadge({
  state,
  reason,
  className,
}: {
  state: AvailabilityState;
  reason?: FieldReasonCode;
  className?: string;
}) {
  const presentation = STATE_PRESENTATION[state];
  return (
    <Badge
      tone={presentation.tone}
      className={className}
      data-availability={state}
      data-reason={reason}
      title={reason === undefined ? presentation.meaning : `${presentation.meaning} (${reason})`}
    >
      <span aria-hidden="true">{presentation.glyph}</span>
      <span>{presentation.label}</span>
    </Badge>
  );
}

/**
 * The body of an unavailable field.
 *
 * Renders the state, its closed reason code and its named dependency. It NEVER renders a
 * zero, a dash standing in for a number, or a plausible placeholder.
 */
export function UnavailableBody({
  state,
  reason,
  dependency,
}: {
  state: AvailabilityState;
  reason: FieldReasonCode;
  dependency?: string;
}) {
  const presentation = STATE_PRESENTATION[state];
  return (
    <div className="space-y-1.5" data-testid="unavailable-body" data-availability={state}>
      <AvailabilityBadge state={state} reason={reason} />
      <p className="text-label-m text-text-tertiary">{presentation.meaning}</p>
      <p className="font-mono text-label-s text-unavailable">{reason}</p>
      {dependency !== undefined && (
        <p className="text-label-s text-text-tertiary">Waiting on: {dependency}</p>
      )}
    </div>
  );
}

export { isValueBearing };
