"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, Button, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { AttentionItemPayload } from "@/contracts/read-models";
import type { EnvelopeOf } from "@/contracts/envelope";
import { isValueBearing } from "@/contracts/validity";
import type { AttentionListPayload } from "@/data/client/read-client";
import {
  SEVERITY_CODES,
  isKnownSeverity,
  prepareAttention,
  type AttentionFilter,
} from "@/lib/attention";
import { formatDecimal, humanizeCode } from "@/lib/format";
import { withScope, type ViewScope } from "@/lib/scope";
import { REFERENCE_FIELDS } from "@/contracts/references";
import { referenceDestination } from "@/lib/reference-navigation";
import { cn } from "@/lib/utils";

/**
 * Attention Required — `ui-ux-specification.md` §6.
 *
 * ONE READ MODEL, ONE RANKING. The executive summary and `/attention` render the same items
 * through the same pipeline in `lib/attention.ts`, so the count on the landing page and the
 * list on the page cannot disagree.
 *
 * EVERY ITEM SHOWS FIVE THINGS, and one missing any of them IS NOT RENDERED. When that
 * happens the panel SAYS how many it withheld: a silently shorter list tells a reader there
 * is less to worry about than there is.
 *
 * A RECOMMENDED ACTION IS A PERMITTED GOVERNANCE ACTION, and the Cockpit performs none of
 * them. Nothing on this surface acknowledges, dismisses, resolves, approves, suppresses or
 * snoozes anything: those verbs change state in systems this application only reads.
 */

const SEVERITY_TONE: Readonly<Record<string, "negative" | "warning" | "neutral">> = {
  HIGH: "negative",
  MEDIUM: "warning",
  LOW: "neutral",
};

const SEVERITY_GLYPH: Readonly<Record<string, string>> = {
  HIGH: "▲",
  MEDIUM: "◆",
  LOW: "▪",
};

function ImpactValue({ item }: { item: AttentionItemPayload }) {
  const impact = item.impact;
  if (!isValueBearing(impact.availability)) {
    /*
     * An impact nobody measured is NOT an impact of zero, and it is never ranked as one. The
     * state and its reason are the whole answer.
     */
    return <AvailabilityBadge state={impact.availability} reason={impact.reason} />;
  }
  const decimal =
    typeof impact.value === "string"
      ? formatDecimal(impact.value, {
          minimumFractionDigits: impact.unit === "USD" ? 2 : 0,
          signed: true,
        })
      : null;
  return (
    <span className="font-mono text-numeric-s text-text-primary">
      {decimal ?? String(impact.value)}
      {impact.unit === "R_MULTIPLE" ? " R" : impact.unit === "USD" ? " USD" : ""}
    </span>
  );
}

/**
 * The evidence drill-down.
 *
 * A LOCAL, READ-ONLY DISCLOSURE rather than a navigation, because the screens that will own
 * this evidence are later-cycle placeholders — sending a reader to a page that says "not
 * implemented" loses the evidence they were following. Each reference states its kind, how it
 * resolves and its classification, and links to the owning area where one exists.
 */
function EvidenceDisclosure({
  item,
  scope,
  dense = false,
}: {
  item: AttentionItemPayload;
  scope: ViewScope;
  dense?: boolean;
}) {
  const total = item.evidence_refs.total.value;
  return (
    <details
      data-testid="attention-evidence"
      className={cn(
        "rounded-sm border border-border-subtle bg-surface-sunken",
        dense ? "inline-block" : "mt-1 block",
      )}
    >
      <summary
        className={cn(
          "cursor-pointer px-3 text-label-m text-accent",
          dense ? "py-1" : "py-1.5",
        )}
      >
        Evidence ({typeof total === "number" ? total : item.evidence_refs.items.length})
      </summary>
      <div className="space-y-2 px-3 pb-3 pt-1">
        <ul className="space-y-1.5">
          {item.evidence_refs.items.map((reference) => {
            const destination = referenceDestination(reference);
            return (
              <li
                key={reference.ref_id}
                className="flex flex-wrap items-center gap-2 text-label-s"
                data-testid="evidence-reference"
              >
                <Badge tone="neutral">{humanizeCode(reference.ref_kind.toUpperCase())}</Badge>
                <span className="font-mono text-text-tertiary">{reference.ref_id}</span>
                <Badge tone="unavailable">{reference.resolution}</Badge>
                <Badge tone="neutral">{reference.classification}</Badge>
                {destination !== null ? (
                  <Link
                    href={withScope(destination.href, scope)}
                    className="text-accent underline underline-offset-2"
                  >
                    {destination.label} →
                  </Link>
                ) : (
                  /*
                   * NO DESTINATION IS STATED, AND NOT LEFT BLANK.
                   *
                   * The R10 allowlist maps no route for this kind, and R10 is explicit that an
                   * unmapped kind yields NO LINK -- "never a guess". Rendering nothing at all
                   * left a reader unable to tell an evidence reference they COULD have followed
                   * from one this version cannot resolve, so the absence is said out loud.
                   */
                  <span
                    className="text-text-tertiary"
                    data-testid="evidence-no-destination"
                    title="No V1 destination is catalogued for this reference kind."
                  >
                    no V1 destination
                  </span>
                )}
              </li>
            );
          })}
        </ul>
        {item.evidence_refs.items.some(
          (reference) => reference.resolution === "UNRESOLVABLE_V1",
        ) && (
          <p className="text-label-s leading-relaxed text-text-tertiary">
            <strong>UNRESOLVABLE_V1</strong> is a stated resolution, not a gap: the join is
            specified and the producing subsystem does not exist, so the reference resolves to
            an availability state rather than to a payload.
          </p>
        )}
        <dl className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-label-s text-text-tertiary">
          <div className="flex gap-1.5">
            <dt>first seen</dt>
            <dd className="text-text-secondary">{item.first_seen}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt>last seen</dt>
            <dd className="text-text-secondary">{item.last_seen}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt>occurrences</dt>
            <dd className="text-text-secondary">
              {isValueBearing(item.occurrence_count.availability)
                ? String(item.occurrence_count.value)
                : item.occurrence_count.availability}
            </dd>
          </div>
        </dl>
      </div>
    </details>
  );
}

/**
 * ONE ATTENTION ITEM.
 *
 * `dense` is the EXECUTIVE-SUMMARY presentation, and it is a layout choice and nothing more:
 * ALL FIVE PRESENTED THINGS are still rendered, at the same type sizes, and none is dropped,
 * truncated or hidden. It exists because 6 requires the ranked list to sit in the FIRST
 * VIEWPORT at 1440 x 900 -- and an item whose impact, recommended action and evidence fall
 * below the fold has not been presented to a reader who does not scroll. The rows are
 * combined; the content is not reduced.
 */
function AttentionRow({
  item,
  scope,
  operator,
  conflicted,
  dense = false,
}: {
  item: AttentionItemPayload;
  scope: ViewScope;
  operator: boolean;
  /** This item's deduplication key holds versions authority does not order (4.5). */
  conflicted: boolean;
  dense?: boolean;
}) {
  /*
   * A SEVERITY IS A CODE PLUS ITS VOCABULARY. `HIGH` in some other vocabulary is not this
   * vocabulary's HIGH, so it takes neither its rank, nor its tone, nor its glyph -- it is
   * labelled UNRANKED, which is what it is.
   */
  const ranked = isKnownSeverity(item.severity);
  return (
    <li
      className={cn(
        "flex flex-col border-b border-border-subtle px-5 last:border-b-0",
        dense ? "gap-0.5 py-1.5" : "gap-1.5 py-3",
      )}
      data-testid="attention-item"
      data-dense={dense ? "true" : "false"}
      data-severity={ranked ? item.severity.code : "UNRANKED"}
      data-conflicted={conflicted ? "true" : "false"}
    >
      <div className="flex flex-wrap items-center gap-2">
        {/* Colour is never the only carrier of meaning (U11): a glyph and a word carry it too. */}
        <Badge tone={ranked ? (SEVERITY_TONE[item.severity.code] ?? "neutral") : "neutral"}>
          <span aria-hidden="true">
            {ranked ? (SEVERITY_GLYPH[item.severity.code] ?? "◇") : "◇"}
          </span>
          <span>{ranked ? item.severity.code : "UNRANKED"}</span>
        </Badge>
        <span className="text-numeric-s font-medium text-text-primary">
          {humanizeCode(item.what_happened.code)}
        </span>
        <span
          className="ml-auto font-mono text-label-s text-text-tertiary"
          title="Materiality rank, as recorded by the producer"
        >
          #{item.materiality_rank}
        </span>
      </div>

      <p className="text-label-m text-text-secondary" data-testid="attention-why">
        <span className="text-text-tertiary">Why it matters: </span>
        {humanizeCode(item.why_it_matters.code)}
      </p>

      {/*
        * IMPACT AND THE RECOMMENDED ACTION. Two separate facts, each labelled, sharing a row
        * in the dense presentation and taking one each otherwise. The action is a PERMITTED
        * GOVERNANCE action, and the sentence saying so travels with it either way -- in the
        * dense row as the badge's title, so the claim is never dropped to save a line.
        */}
      <div
        className={cn(
          "flex flex-wrap items-center gap-2 text-label-m",
          dense ? "gap-x-4" : "",
        )}
      >
        <span className="text-text-tertiary">Impact:</span>
        <ImpactValue item={item} />
        {dense && (
          <>
            <span className="text-text-tertiary">Recommended:</span>
            <Badge
              tone="accent"
              data-testid="attention-recommended"
              title="A governance action for a person. The Cockpit performs none of them."
            >
              {humanizeCode(item.recommended_action.code)}
            </Badge>
            <EvidenceDisclosure item={item} scope={scope} dense />
          </>
        )}
      </div>

      {!dense && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-label-m text-text-tertiary">Recommended:</span>
          <Badge tone="accent" data-testid="attention-recommended">
            {humanizeCode(item.recommended_action.code)}
          </Badge>
          <span className="text-label-s text-text-tertiary">
            — a governance action for a person. The Cockpit performs none.
          </span>
        </div>
      )}

      {/*
        * AN UNRESOLVED CONFLICT IS SHOWN, NOT SETTLED. Several records share this
        * deduplication key, they are not the same record, and no rule in accepted authority
        * orders them -- so the row states that rather than presenting one of them as current.
        */}
      {conflicted && (
        <div
          data-testid="attention-conflict"
          className="flex flex-wrap items-center gap-2 rounded-sm border border-border-strong bg-surface-sunken px-3 py-1.5"
        >
          <AvailabilityBadge state="PARTIAL" reason="EXTENT_NOT_DETERMINABLE" />
          <span className="text-label-s text-text-tertiary">
            Several differing records share this deduplication key and authority does not
            order them. <strong>One is shown so the issue stays visible</strong>; it is not
            asserted to be the current version.
          </span>
        </div>
      )}

      {!dense && <EvidenceDisclosure item={item} scope={scope} />}

      {operator && (
        <span className="font-mono text-label-s text-text-tertiary">
          {item.item_id} · dedup {item.dedup_key} · severity {item.severity.vocabulary}@
          {item.severity.vocabulary_version} · impact {item.impact.metric_id}
        </span>
      )}
    </li>
  );
}

/** The filter chips. An applied filter is VISIBLE, or a subset reads as the whole (§8). */
function FilterChips({
  filter,
  onChange,
  kinds,
}: {
  filter: AttentionFilter;
  onChange: (next: AttentionFilter) => void;
  kinds: readonly string[];
}) {
  const toggle = (list: readonly string[], value: string): string[] =>
    list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];

  return (
    <div className="space-y-2" data-testid="attention-filters">
      <div
        role="group"
        aria-label="Filter by severity"
        className="flex flex-wrap items-center gap-1.5"
      >
        <span className="text-label-s uppercase tracking-wide text-text-tertiary">Severity</span>
        {SEVERITY_CODES.map((code) => (
          <Button
            key={code}
            size="sm"
            variant={filter.severities.includes(code) ? "primary" : "subtle"}
            aria-pressed={filter.severities.includes(code)}
            onClick={() => onChange({ ...filter, severities: toggle(filter.severities, code) })}
          >
            {code}
          </Button>
        ))}
      </div>
      <div
        role="group"
        aria-label="Filter by evidence kind"
        className="flex flex-wrap items-center gap-1.5"
      >
        <span className="text-label-s uppercase tracking-wide text-text-tertiary">Evidence</span>
        {kinds.map((kind) => (
          <Button
            key={kind}
            size="sm"
            variant={filter.evidenceKinds.includes(kind) ? "primary" : "subtle"}
            aria-pressed={filter.evidenceKinds.includes(kind)}
            onClick={() =>
              onChange({ ...filter, evidenceKinds: toggle(filter.evidenceKinds, kind) })
            }
          >
            {humanizeCode(kind.toUpperCase())}
          </Button>
        ))}
      </div>
    </div>
  );
}

export interface AttentionPanelProps {
  readonly envelope: EnvelopeOf<AttentionListPayload>;
  readonly scope: ViewScope;
  readonly operator: boolean;
  /** The full page adds filters; the executive summary shows the top items and links on. */
  readonly withFilters?: boolean;
  /** The summary caps the list, and SAYS it capped it. */
  readonly limit?: number;
}

export function AttentionPanel({
  envelope,
  scope,
  operator,
  withFilters = false,
  limit,
}: AttentionPanelProps) {
  const [filter, setFilter] = React.useState<AttentionFilter>({
    severities: [],
    evidenceKinds: [],
  });

  const payload = envelope.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);
  const prepared = prepareAttention(
    items,
    withFilters ? filter : { severities: [], evidenceKinds: [] },
  );
  /*
   * THE CHIPS ARE THE KINDS THE CONTRACT PERMITS, AND THEY USED TO BE THE KINDS PRESENT.
   *
   * Deriving them from `items` describes THIS SAMPLE: a category with no rows today has no
   * chip, so a reader cannot tell "none of these" from "no such category", and the filter
   * silently changes shape as the data does. section 4.5 declares what this field may carry --
   * "kind evidence or source_fact" -- so the categories are a property of the CONTRACT, and
   * a chip that selects zero rows is a true answer rather than a missing control.
   *
   * It is the same rule as everywhere else in this cycle: the contract, and not the sample.
   */
  const kinds = React.useMemo(
    () => [...REFERENCE_FIELDS["AttentionItem.evidence_refs"].kinds].sort(),
    [],
  );
  const shown = limit === undefined ? prepared.visible : prepared.visible.slice(0, limit);
  const filtersActive = filter.severities.length > 0 || filter.evidenceKinds.length > 0;
  const notes =
    shown.length < prepared.visible.length ||
    prepared.deduplicated > 0 ||
    prepared.withheldIncomplete > 0 ||
    prepared.conflicting > 0 ||
    limit !== undefined;

  return (
    <Card data-testid="attention-panel">
      <CardHeader
        className={cn(
          "flex flex-wrap items-start justify-between gap-2",
          limit !== undefined ? "pt-3" : "",
        )}
      >
        <div>
          <Label>Attention required</Label>
          {payload !== undefined && (
            <p className="mt-0.5 text-label-m text-text-secondary">
              {prepared.rankedTotal === 0
                ? "Nothing requires attention."
                : `${prepared.rankedTotal} item${
                    prepared.rankedTotal === 1 ? "" : "s"
                  }, ranked by materiality then severity.`}
            </p>
          )}
        </div>
        {payload !== undefined && <ProvenanceBadge provenance={envelope.provenance} />}
      </CardHeader>

      {payload === undefined ? (
        <CardBody>
          <UnavailableBody
            state={envelope.availability}
            reason={envelope.availability_reason}
            dependency="the attention projection and the alert feed"
          />
        </CardBody>
      ) : (
        <>
          {withFilters && (
            <CardBody className="pb-3">
              <FilterChips filter={filter} onChange={setFilter} kinds={kinds} />
            </CardBody>
          )}

          {shown.length === 0 ? (
            <CardBody>
              <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              <p className="mt-2 text-label-m text-text-tertiary">
                {filtersActive ? (
                  <>
                    No item matches the active filters. <strong>{prepared.rankedTotal}</strong>{" "}
                    item{prepared.rankedTotal === 1 ? " is" : "s are"} hidden by them.
                  </>
                ) : (
                  <>
                    No item requires attention, and that is the correct answer — the producer
                    ran and found nothing.
                  </>
                )}
              </p>
            </CardBody>
          ) : (
            <ul>
              {shown.map((item) => (
                <AttentionRow
                  key={item.item_id}
                  item={item}
                  scope={scope}
                  operator={operator}
                  conflicted={prepared.conflictedKeys.has(item.dedup_key)}
                  dense={limit !== undefined}
                />
              ))}
            </ul>
          )}

          {/*
            * WHAT WAS NOT SHOWN, and why. Deduplication, the five-things rule and the summary
            * cap each remove rows, and a reader who is not told is looking at a shorter list
            * than the producer sent with no way to know it.
            */}
          {notes && (
            <CardBody className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-subtle pt-3 text-label-s text-text-tertiary">
              {shown.length < prepared.visible.length && (
                <span data-testid="attention-capped">
                  Showing {shown.length} of {prepared.visible.length}.
                </span>
              )}
              {prepared.deduplicated > 0 && (
                <span data-testid="attention-deduplicated">
                  {prepared.deduplicated} folded into another by deduplication key.
                </span>
              )}
              {prepared.conflicting > 0 && (
                <span data-testid="attention-conflicting">
                  {prepared.conflicting} deduplication key
                  {prepared.conflicting === 1 ? "" : "s"} hold differing records that authority
                  does not order.
                </span>
              )}
              {prepared.withheldIncomplete > 0 && (
                <span data-testid="attention-withheld">
                  {prepared.withheldIncomplete} withheld: an item missing any of the five
                  presented things is not rendered.
                </span>
              )}
              {limit !== undefined && (
                <Link
                  href={withScope("/attention", scope)}
                  className="text-accent underline underline-offset-2"
                >
                  All attention items →
                </Link>
              )}
            </CardBody>
          )}
        </>
      )}
    </Card>
  );
}
