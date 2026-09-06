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
 *   NO INVENTED WINNER            where authority does not determine which of two conflicting
 *                                 records is current, none is declared current
 */
import type { AttentionItemPayload } from "@/contracts/read-models";
import type { ReasonCoded } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";

/**
 * The severity ordering, and THE VOCABULARY IT IS DEFINED OVER.
 *
 * Severity is a `ReasonCoded` — a code, the vocabulary it belongs to, and that vocabulary's
 * version — and a code string means nothing without the other two. `HIGH` in some other
 * vocabulary is not this vocabulary's `HIGH`, and ranking it as one orders a screen by a
 * coincidence of spelling. So the ordering is declared over exactly one (vocabulary,
 * version) pair, and everything else is UNRANKED rather than guessed at: an unknown severity
 * sorts after every known one and is LABELLED, instead of being silently assigned a rank it
 * never had.
 *
 * The pair below is the one the only current producer emits. A second producer, or a version
 * bump, is a deliberate change here — not something that quietly starts ranking.
 */
export const SEVERITY_VOCABULARY = "kalpamani.demo";
export const SEVERITY_VOCABULARY_VERSION = "v1";

export const SEVERITY_ORDER: Readonly<Record<string, number>> = {
  HIGH: 0,
  MEDIUM: 1,
  LOW: 2,
};

export const SEVERITY_CODES = ["HIGH", "MEDIUM", "LOW"] as const;
export type SeverityCode = (typeof SEVERITY_CODES)[number];

/** The rank an unrecognised severity takes: after every ranked one, and never ahead of it. */
export const UNRANKED_SEVERITY = Number.MAX_SAFE_INTEGER;

/** Whether a `ReasonCoded` belongs to the vocabulary this ordering is defined over. */
export function isRankedSeverityVocabulary(severity: ReasonCoded): boolean {
  return (
    severity.vocabulary === SEVERITY_VOCABULARY &&
    severity.vocabulary_version === SEVERITY_VOCABULARY_VERSION
  );
}

export function severityRank(severity: ReasonCoded): number {
  if (!isRankedSeverityVocabulary(severity)) {
    return UNRANKED_SEVERITY;
  }
  return SEVERITY_ORDER[severity.code] ?? UNRANKED_SEVERITY;
}

export function isKnownSeverity(severity: ReasonCoded): boolean {
  return isRankedSeverityVocabulary(severity) && severity.code in SEVERITY_ORDER;
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
 * A canonical, key-ordered rendering of one record, used ONLY to tell records apart.
 *
 * Two records with the same signature are the SAME record seen twice, and collapsing them
 * loses nothing. Two with different signatures are two different claims, and this string
 * never decides which of them is true — §4.5 fixes no ordering over content, so nothing here
 * invents one.
 */
function contentSignature(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value ?? null);
  }
  if (Array.isArray(value)) {
    return `[${value.map(contentSignature).join(",")}]`;
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, held]) => held !== undefined)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
  const rendered = entries.map(
    ([key, held]) => `${JSON.stringify(key)}:${contentSignature(held)}`,
  );
  return `{${rendered.join(",")}}`;
}

function occurrenceOf(item: AttentionItemPayload): number | null {
  return isValueBearing(item.occurrence_count.availability) &&
    typeof item.occurrence_count.value === "number"
    ? item.occurrence_count.value
    : null;
}

export interface DeduplicationResult {
  /** One record per `dedup_key`, ordered by that key. */
  readonly items: readonly AttentionItemPayload[];
  /** Rows folded into another. Exact duplicates and superseded versions both count here. */
  readonly folded: number;
  /** Keys where authority did NOT determine a unique current version. */
  readonly conflicted: ReadonlySet<string>;
}

/**
 * Deduplication against the alert feed, by `dedup_key`, GROUPED rather than folded pairwise.
 *
 * §4.5: `item_id` is "stable across occurrences" and `dedup_key` is what the alert feed is
 * deduplicated against. Where rows share a key they are ONE thing seen several times.
 *
 * THE PAIRWISE FOLD THIS REPLACES WAS ORDER-DEPENDENT. It compared each arriving record with
 * whichever one it happened to be holding, using `last_seen`, then the occurrence count where
 * both were known, then the identifier. With three records at one `last_seen` and one unknown
 * count the preference is not transitive — c beats a on count, a beats b on identifier and b
 * beats c on identifier — so the survivor depended on the order a producer emitted them in,
 * and all three could win. It also kept whichever record arrived FIRST when two records
 * agreed on identity, time and count but disagreed on content.
 *
 * The group is narrowed only by rules that actually establish a winner:
 *
 *   1. the newest `last_seen` supersedes older observations of the same thing
 *   2. among those, a strictly larger occurrence count wins ONLY when every remaining
 *      record states one -- an unknown count is not a larger number and not a smaller one,
 *      so it cannot order anything
 *   3. records identical after that are the same record, and collapse
 *
 * WHAT SURVIVES STEP 3 IS A GENUINE CONFLICT, and no rule in accepted authority resolves it.
 * It is not silently resolved here: the group is reported as conflicting, and ONE record is
 * still shown so the underlying issue does not disappear from the list. Which one is shown is
 * a stated, deterministic choice — the least `item_id`, then the least content signature —
 * and the row renders as an UNRESOLVED CONFLICT rather than as the current version.
 */
export function deduplicateWithDiagnostics(
  items: readonly AttentionItemPayload[],
): DeduplicationResult {
  const groups = new Map<string, AttentionItemPayload[]>();
  for (const item of items) {
    const held = groups.get(item.dedup_key);
    if (held === undefined) {
      groups.set(item.dedup_key, [item]);
    } else {
      held.push(item);
    }
  }

  const conflicted = new Set<string>();
  const chosen: AttentionItemPayload[] = [];
  const keys = [...groups.keys()].sort((left, right) =>
    left < right ? -1 : left > right ? 1 : 0,
  );

  for (const key of keys) {
    const records = groups.get(key)!;
    // 1. The newest observation supersedes the older ones.
    const newest = records.reduce(
      (latest, record) => (record.last_seen > latest ? record.last_seen : latest),
      records[0]!.last_seen,
    );
    let candidates = records.filter((record) => record.last_seen === newest);

    // 2. A count orders the group only when EVERY remaining record states one.
    const counts = candidates.map(occurrenceOf);
    if (counts.every((count): count is number => count !== null)) {
      const highest = Math.max(...counts);
      candidates = candidates.filter((record) => occurrenceOf(record) === highest);
    }

    // 3. Identical records are one record.
    const distinct = new Map<string, AttentionItemPayload>();
    for (const record of candidates) {
      const signature = contentSignature(record);
      if (!distinct.has(signature)) {
        distinct.set(signature, record);
      }
    }

    if (distinct.size > 1) {
      conflicted.add(key);
    }
    const ordered = [...distinct.entries()].sort(
      ([leftSignature, left], [rightSignature, right]) => {
        if (left.item_id !== right.item_id) {
          return left.item_id < right.item_id ? -1 : 1;
        }
        return leftSignature < rightSignature ? -1 : leftSignature > rightSignature ? 1 : 0;
      },
    );
    chosen.push(ordered[0]![1]);
  }

  return { items: chosen, folded: items.length - chosen.length, conflicted };
}

/** The surviving record per `dedup_key`. Diagnostics are in `deduplicateWithDiagnostics`. */
export function deduplicate(
  items: readonly AttentionItemPayload[],
): readonly AttentionItemPayload[] {
  return deduplicateWithDiagnostics(items).items;
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
    const severity = severityRank(left.severity) - severityRank(right.severity);
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
  /** Deduplication keys whose conflicting versions authority does not resolve. */
  readonly conflicting: number;
  /** Which keys those are, so a row can say it is one of them. */
  readonly conflictedKeys: ReadonlySet<string>;
}

/**
 * The one pipeline: complete → deduplicated → ranked → filtered.
 *
 * Every count it discards is REPORTED rather than absorbed, so a reader is never shown a
 * shorter list than the producer sent without being told why it is shorter. The counts answer
 * different questions and are never added together or conflated: how many the producer sent
 * that could not be rendered, how many rows folded, how many keys are in conflict, and how
 * many survived to be ranked.
 */
export function prepareAttention(
  items: readonly AttentionItemPayload[],
  filter: AttentionFilter = NO_FILTER,
): RankedAttention {
  const complete = items.filter(hasAllFivePresented);
  const deduplicated = deduplicateWithDiagnostics(complete);
  const ranked = rankAttention(deduplicated.items);
  return {
    visible: ranked.filter((item) => matchesFilter(item, filter)),
    rankedTotal: ranked.length,
    withheldIncomplete: items.length - complete.length,
    deduplicated: deduplicated.folded,
    conflicting: deduplicated.conflicted.size,
    conflictedKeys: deduplicated.conflicted,
  };
}
