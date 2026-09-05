"use client";

import Link from "next/link";

import { Badge, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { AttentionItemPayload } from "@/contracts/read-models";
import type { EnvelopeOf } from "@/contracts/envelope";
import { isValueBearing } from "@/contracts/validity";
import type { AttentionListPayload } from "@/data/client/read-client";
import { withScope, type ViewScope } from "@/lib/scope";
import { humanizeCode } from "@/lib/format";

/**
 * Attention Required -- ui-ux-specification.md section 6.
 *
 * EVERY ATTENTION ITEM SHOWS FIVE THINGS, and an item missing any of them IS NOT RENDERED:
 * what happened, why it matters, impact, evidence, and the recommended PERMITTED GOVERNANCE
 * action. The Cockpit performs none of them.
 *
 * Ranked by materiality and severity, and deduplicated against the alert feed.
 */
function hasAllFive(item: AttentionItemPayload): boolean {
  return (
    item.what_happened.code.length > 0 &&
    item.why_it_matters.code.length > 0 &&
    item.impact !== undefined &&
    item.evidence_refs.items.length > 0 &&
    item.recommended_action.code.length > 0
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
  const impactBearing = isValueBearing(item.impact.availability);
  return (
    <li
      className="flex flex-col gap-1.5 border-b border-border-subtle px-5 py-3 last:border-b-0"
      data-testid="attention-item"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={item.severity.code === "HIGH" ? "negative" : "warning"}>
          {item.severity.code}
        </Badge>
        <span className="text-numeric-s font-medium text-text-primary">
          {humanizeCode(item.what_happened.code)}
        </span>
        <span className="ml-auto font-mono text-label-s text-text-tertiary">
          #{item.materiality_rank}
        </span>
      </div>
      <p className="text-label-m text-text-secondary">{humanizeCode(item.why_it_matters.code)}</p>
      <div className="flex flex-wrap items-center gap-2 text-label-m">
        <span className="text-text-tertiary">Impact:</span>
        {impactBearing ? (
          <span className="font-mono text-text-primary">
            {String(item.impact.value)} {item.impact.unit === "R_MULTIPLE" ? "R" : ""}
          </span>
        ) : (
          <AvailabilityBadge state={item.impact.availability} reason={item.impact.reason} />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-label-m text-text-tertiary">Recommended:</span>
        <Badge tone="accent">{humanizeCode(item.recommended_action.code)}</Badge>
        <span className="text-label-s text-text-tertiary">
          — a governance action. The Cockpit performs none.
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-label-s text-text-tertiary">
        <Link
          href={withScope("/system/alerts", scope)}
          className="text-accent underline underline-offset-2"
        >
          Evidence ({item.evidence_refs.items.length})
        </Link>
        {operator && (
          <span className="font-mono">
            {item.item_id} · dedup {item.dedup_key} · seen{" "}
            {String(item.occurrence_count.value ?? "—")}× · first {item.first_seen}
          </span>
        )}
      </div>
    </li>
  );
}

export function AttentionPanel({
  envelope,
  scope,
  operator,
}: {
  envelope: EnvelopeOf<AttentionListPayload>;
  scope: ViewScope;
  operator: boolean;
}) {
  const payload = envelope.payload;
  const rendered = (payload?.items ?? [])
    .filter(hasAllFive)
    .slice()
    .sort((left, right) => left.materiality_rank - right.materiality_rank);

  return (
    <Card data-testid="attention-panel">
      <CardHeader className="flex items-center justify-between gap-2">
        <Label>Attention required</Label>
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
      ) : rendered.length === 0 ? (
        <CardBody>
          <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
          <p className="mt-2 text-label-m text-text-tertiary">
            No item requires attention, and that is the correct answer.
          </p>
        </CardBody>
      ) : (
        <ul>
          {rendered.map((item) => (
            <AttentionRow key={item.item_id} item={item} scope={scope} operator={operator} />
          ))}
        </ul>
      )}
    </Card>
  );
}
