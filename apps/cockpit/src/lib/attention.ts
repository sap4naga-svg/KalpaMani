/**
 * Attention ranking, deduplication and filtering — `ui-ux-specification.md` §6.
 *
 * ONE MODULE, SO ONE ANSWER. The executive summary and the dedicated `/attention` page read
 * the same read model and rank it here; two sort implementations are two orderings that
 * disagree the first time a tie appears, and a reader who follows "3 items need attention"
 * to a list of four has been told two different things by one system.
 *
 * "Ranked by materiality and severity, and deduplicated against the alert feed."
 *
 * WHAT IS NOT DONE HERE, deliberately:
 *
 *   NO IMPACT-BASED RANKING       an item whose impact is NOT_APPLICABLE or NOT_IMPLEMENTED
 *                                 has no number, and sorting it as zero would rank an
 *                                 unmeasured item as harmless. Impact is DISPLAYED with its
 *                                 availability and never folded into the order
 *   NO SCORE                      no weighted total, no percentage, no composite "priority".
 *                                 Materiality and severity are recorded facts; a number
 *                                 blended out of them is an invention
 *   NO SUPPRESSION                a filter hides rows and SAYS SO; nothing is dropped for
 *                                 being inconvenient, and the unfiltered total stays visible
 */
import type { AttentionItemPayload } from "@/contracts/read-models";
import { isValueBearing } from "@/contracts/validity";

/**
 * The severity ordering, for the one vocabulary this application owns.
 *
 * Severity is a `ReasonCoded` — a code plus the vocabulary it belongs to — and the contracts
 * do not fix an ordering over any particular vocabulary's members. So this orders the codes
 * of the vocabulary defined here, and treats anything else as UNRANKED rather than guessing:
 * an unknown severity sorts after every known one and is labelled, instead of being silently
 * assigned a rank it never had.
 */
export const SEVERITY_ORDER: Readonly<Record<string, number>> = {
  HIGH: 0,
  MEDIUM: 1,
  LOW: 2,
};

export const SEVERITY_CODES = ["HIGH", "MEDIUM", "LOW"] as const;
export type SeverityCode = (typeof SEVERITY_CODES)[number];

export function severityRank(code: string): number {
  return SEVERITY_ORDER[code] ?? Number.MAX_SAFE_INTEGER;
}

export function isKnownSeverity(code: string): code is SeverityCode {
  return code in SEVERITY_ORDER;
}

/**
 * An item shows FIVE things, and one missing any of them is NOT RENDERED (§6, §4.5).
 *
 * `impact` counts as present when the field exists — an impact that is `NOT_APPLICABLE` is an
 * ANSWER about impact, and the item still shows it. What is missing is a field that is not
 * there at all.
 */
export function hasAllFivePresented(item: AttentionItemPayload): boolean {
  return (
    item.what_happened.code.length > 0 &&
    item.why_it_matters.code.length > 0 &&
    item.impact !== undefined &&
    item.evidence_refs.items.length > 0 &&
    item.recommended_action.code.length > 0
  );
}

/**
 * Deduplication against the alert feed, by `dedup_key`.
 *
 * §4.5: `item_id` is "stable across occurrences" and `dedup_key` is what the alert feed is
 * deduplicated against. Where two rows share a key they are ONE thing seen twice, and the
 * survivor is chosen deterministically — the most recently seen, then the most frequently
 * seen, then the lexicographically first identifier. Never "the first one in the array":
 * that makes the surviving row depend on the order a producer happened to emit them in.
 */
export function deduplicate(
  items: readonly AttentionItemPayload[],
): readonly AttentionItemPayload[] {
  const byKey = new Map<string, AttentionItemPayload>();
  for (const item of items) {
    const held = byKey.get(item.dedup_key);
    if (held === undefined || preferOver(item, held)) {
      byKey.set(item.dedup_key, item);
    }
  }
  return [...byKey.values()];
}

function occurrenceOf(item: AttentionItemPayload): number | null {
  return isValueBearing(item.occurrence_count.availability) &&
    typeof item.occurrence_count.value === "number"
    ? item.occurrence_count.value
    : null;
}

function preferOver(candidate: AttentionItemPayload, held: AttentionItemPayload): boolean {
  if (candidate.last_seen !== held.last_seen) {
    return candidate.last_seen > held.last_seen;
  }
  const candidateCount = occurrenceOf(candidate);
  const heldCount = occurrenceOf(held);
  // An UNKNOWN occurrence count never wins on count -- it is not a larger number, and it is
  // not a smaller one either. The comparison falls through to the identifier instead.
  if (candidateCount !== null && heldCount !== null && candidateCount !== heldCount) {
    return candidateCount > heldCount;
  }
  return candidate.item_id < held.item_id;
}

/**
 * The ranking: materiality, then severity, then a STABLE tie-break on the identifier.
 *
 * The identifier tie-break is what makes the order total. Two items of equal materiality and
 * equal severity are otherwise ordered by whatever the sort implementation happens to do with
 * them, and a list that reorders itself between renders is a list a reader cannot trust.
 */
export function rankAttention(
  items: readonly AttentionItemPayload[],
): readonly AttentionItemPayload[] {
  return [...items].sort((left, right) => {
    if (left.materiality_rank !== right.materiality_rank) {
      return left.materiality_rank - right.materiality_rank;
    }
    const severity = severityRank(left.severity.code) - severityRank(right.severity.code);
    if (severity !== 0) {
      return severity;
    }
    return left.item_id < right.item_id ? -1 : left.item_id > right.item_id ? 1 : 0;
  });
}

export interface AttentionFilter {
  /** Empty means "every severity", and the interface says so rather than showing nothing. */
  readonly severities: readonly string[];
  /** §4.3 evidence kinds. Empty means "every kind". */
  readonly evidenceKinds: readonly string[];
}

export const NO_FILTER: AttentionFilter = { severities: [], evidenceKinds: [] };

export function evidenceKindsOf(item: AttentionItemPayload): readonly string[] {
  return [...new Set(item.evidence_refs.items.map((ref) => ref.ref_kind))].sort();
}

export function matchesFilter(item: AttentionItemPayload, filter: AttentionFilter): boolean {
  if (filter.severities.length > 0 && !filter.severities.includes(item.severity.code)) {
    return false;
  }
  if (filter.evidenceKinds.length > 0) {
    const kinds = evidenceKindsOf(item);
    if (!filter.evidenceKinds.some((kind) => kinds.includes(kind))) {
      return false;
    }
  }
  return true;
}

export interface RankedAttention {
  /** What is shown, in order. */
  readonly visible: readonly AttentionItemPayload[];
  /** Every renderable item, before filtering. A filter hides rows and states how many. */
  readonly rankedTotal: number;
  /** Items the producer sent that are NOT renderable, because §4.5 requires all five. */
  readonly withheldIncomplete: number;
  /** Rows folded into another by `dedup_key`. */
  readonly deduplicated: number;
}

/**
 * The one pipeline: complete → deduplicated → ranked → filtered.
 *
 * Every count it discards is REPORTED rather than absorbed, so a reader is never shown a
 * shorter list than the producer sent without being told why it is shorter.
 */
export function prepareAttention(
  items: readonly AttentionItemPayload[],
  filter: AttentionFilter = NO_FILTER,
): RankedAttention {
  const complete = items.filter(hasAllFivePresented);
  const deduplicated = deduplicate(complete);
  const ranked = rankAttention(deduplicated);
  return {
    visible: ranked.filter((item) => matchesFilter(item, filter)),
    rankedTotal: ranked.length,
    withheldIncomplete: items.length - complete.length,
    deduplicated: complete.length - deduplicated.length,
  };
}
