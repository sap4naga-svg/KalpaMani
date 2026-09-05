/**
 * Provenance presentation -- ui-ux-specification.md section 5 and section 9.4.
 *
 * SYNTHETIC is UNMISSABLE, not a tooltip, and it is labelled at PAGE level AND at
 * COMPONENT level, because screenshots travel (U3).
 *
 * A REAL FACT IS NEVER BADGED SYNTHETIC. Tracked repository governance facts carry the
 * REPOSITORY_TRACKED badge, visually distinct from SYNTHETIC, and a page carrying both
 * kinds badges EACH COMPONENT INDIVIDUALLY rather than choosing one badge for the page.
 *
 * The provenance badge is not the publication decision.
 */
import { Badge } from "@/components/ui/primitives";
import type { DataProvenance } from "@/contracts/vocabularies";

const PRESENTATION: Readonly<
  Record<DataProvenance, { label: string; tone: "synthetic" | "tracked" | "neutral"; note: string }>
> = {
  SYNTHETIC: {
    label: "SYNTHETIC",
    tone: "synthetic",
    note: "Repository-owned deterministic fixture. Not a result, and not evidence of anything.",
  },
  REPOSITORY_TRACKED: {
    label: "TRACKED FACT",
    tone: "tracked",
    note: "A real fact read from tracked repository authority, with its source and as-of.",
  },
  SYSTEM_RECORDED: {
    label: "SYSTEM RECORDED",
    tone: "neutral",
    note: "Produced by the deterministic runtime. Never admitted to an external deployment.",
  },
  BACKTEST_SIMULATED: {
    label: "BACKTEST SIMULATED",
    tone: "neutral",
    note: "Hypothetical, never realized. Never admitted to an external deployment.",
  },
  BROKER_REPORTED: {
    label: "BROKER REPORTED",
    tone: "neutral",
    note: "Observed from a brokerage. Never admitted to an external deployment.",
  },
};

export function ProvenanceBadge({
  provenance,
  className,
}: {
  provenance: DataProvenance;
  className?: string;
}) {
  const presentation = PRESENTATION[provenance];
  return (
    <Badge
      tone={presentation.tone}
      className={className}
      data-provenance={provenance}
      title={presentation.note}
    >
      {presentation.label}
    </Badge>
  );
}

export function provenanceNote(provenance: DataProvenance): string {
  return PRESENTATION[provenance].note;
}
