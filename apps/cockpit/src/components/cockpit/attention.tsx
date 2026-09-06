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
  evidenceKindsOf,
  isKnownSeverity,
  prepareAttention,
  type AttentionFilter,
} from "@/lib/attention";
import { formatDecimal, humanizeCode } from "@/lib/format";
import { withScope, type ViewScope } from "@/lib/scope";

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

/** The area that OWNS each evidence kind, so a drill-down goes somewhere real. */
const EVIDENCE_DESTINATION: Readonly<Record<string, { href: string; label: string }>> = {
  data_quality: { href: "/system/data-quality", label: "Data quality" },
  health_transition: { href: "/strategy/health", label: "Strategy health" },
  reconciliation: { href: "/execution/reconciliation", label: "Reconciliation" },
  alert: { href: "/system/alerts", label: "Alerts" },
  incident: { href: "/system/operations", label: "Operations" },
  source_fact: { href: "/governance/audit", label: "Audit trail" },
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
function EvidenceDisclosure({ item, scope }: { item: AttentionItemPayload; scope: ViewScope }) {
  const total = item.evidence_refs.total.value;
  return (
    <details className="mt-1 rounded-sm border border-border-subtle bg-surface-sunken">
      <summary className="cursor-pointer px-3 py-1.5 text-label-m text-accent">
        Evidence ({typeof total === "number" ? total : item.evidence_refs.items.length})
      </summary>
      <div className="space-y-2 px-3 pb-3 pt-1">
        <ul className="space-y-1.5">
          {item.evidence_refs.items.map((reference) => {
            const destination = EVIDENCE_DESTINATION[reference.ref_kind];
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
                {destination !== undefined && (
                  <Link
                    href={withScope(destination.href, scope)}
                    className="text-accent underline underline-offset-2"
                  >
                    {destination.label} →
                  </Link>
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

function AttentionRow({
  item,
  scope,
  operator,
}: {
  item: AttentionItemPayload;
  scope: ViewScope;
  operator: boolean;
}) {
  return (
    <li
      className="flex flex-col gap-1.5 border-b border-border-subtle px-5 py-3 last:border-b-0"
      data-testid="attention-item"
      data-severity={item.severity.code}
    >
      <div className="flex flex-wrap items-center gap-2">
        {/* Colour is never the only carrier of meaning (U11): a glyph and a word carry it too. */}
        <Badge tone={SEVERITY_TONE[item.severity.code] ?? "neutral"}>
          <span aria-hidden="true">{SEVERITY_GLYPH[item.severity.code] ?? "◇"}</span>
          <span>{isKnownSeverity(item.severity.code) ? item.severity.code : "UNRANKED"}</span>
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

      <p className="text-label-m text-text-secondary">
        <span className="text-text-tertiary">Why it matters: </span>
        {humanizeCode(item.why_it_matters.code)}
      </p>

      <div className="flex flex-wrap items-center gap-2 text-label-m">
        <span className="text-text-tertiary">Impact:</span>
        <ImpactValue item={item} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-label-m text-text-tertiary">Recommended:</span>
        <Badge tone="accent">{humanizeCode(item.recommended_action.code)}</Badge>
        <span className="text-label-s text-text-tertiary">
          — a governance action for a person. The Cockpit performs none.
        </span>
      </div>

      <EvidenceDisclosure item={item} scope={scope} />

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
  const kinds = React.useMemo(
    () => [...new Set(items.flatMap(evidenceKindsOf))].sort(),
    [items],
  );
  const shown = limit === undefined ? prepared.visible : prepared.visible.slice(0, limit);
  const filtersActive = filter.severities.length > 0 || filter.evidenceKinds.length > 0;
  const notes =
    shown.length < prepared.visible.length ||
    prepared.deduplicated > 0 ||
    prepared.withheldIncomplete > 0 ||
    limit !== undefined;

  return (
    <Card data-testid="attention-panel">
      <CardHeader className="flex flex-wrap items-start justify-between gap-2">
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
                <AttentionRow key={item.item_id} item={item} scope={scope} operator={operator} />
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
