"use client";

import { Badge, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { humanizeCode } from "@/lib/format";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { EnvelopeOf } from "@/contracts/envelope";
import { isValueBearing } from "@/contracts/validity";
import type { WhatChangedPayload } from "@/data/client/read-client";

/**
 * What Changed -- ui-ux-specification.md section 7.
 *
 * A comparison needs a STATED BASELINE, and this one says it on the screen: the comparison
 * window is explicit and both endpoints carry their as-of times.
 *
 * AN UNAVAILABLE ENDPOINT IS NOT A CHANGE (U17). When either side is unavailable the item
 * reports THAT STATE instead of a delta, because A DELTA COMPUTED AGAINST A MISSING
 * BASELINE IS A FABRICATED CHANGE. Two provenances never form one delta.
 */
export function WhatChangedPanel({
  envelope,
  operator,
}: {
  envelope: EnvelopeOf<WhatChangedPayload>;
  operator: boolean;
}) {
  const payload = envelope.payload;
  return (
    <Card data-testid="what-changed-panel">
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Label>What changed</Label>
          {payload !== undefined && (
            <p className="mt-0.5 text-label-m text-text-secondary">{payload.baseline_label}</p>
          )}
        </div>
        {payload !== undefined && <ProvenanceBadge provenance={envelope.provenance} />}
      </CardHeader>

      {payload === undefined ? (
        <CardBody>
          <UnavailableBody
            state={envelope.availability}
            reason={envelope.availability_reason}
            dependency="a baseline endpoint and a comparison endpoint, consistently scoped"
          />
          <p className="mt-2 text-label-s text-text-tertiary">
            A comparison needs two valid, consistently scoped endpoints. Without both, the
            correct answer is this state — never an invented delta.
          </p>
        </CardBody>
      ) : (
        <>
          <CardBody className="pb-2">
            <dl className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-label-s text-text-tertiary">
              <div className="flex gap-2">
                <dt>baseline as-of</dt>
                <dd className="text-text-secondary">{payload.baseline_as_of ?? "absent"}</dd>
              </div>
              <div className="flex gap-2">
                <dt>comparison as-of</dt>
                <dd className="text-text-secondary">{payload.comparison_as_of ?? "absent"}</dd>
              </div>
            </dl>
          </CardBody>
          <ul>
            {payload.entries.map((entry) => {
              const beforeKnown = entry.before !== undefined && isValueBearing(entry.before.availability);
              const afterKnown = isValueBearing(entry.after.availability);
              return (
                <li
                  key={entry.change_id}
                  data-testid="what-changed-item"
                  className="flex flex-col gap-1 border-t border-border-subtle px-5 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-numeric-s font-medium text-text-primary">
                      {humanizeCode(entry.subject.code)}
                    </span>
                    <Badge tone="unavailable">{humanizeCode(entry.change_kind.code)}</Badge>
                    <Badge
                      tone={entry.materiality.code === "MATERIAL" ? "warning" : "neutral"}
                      className="ml-auto"
                    >
                      {entry.materiality.code}
                    </Badge>
                  </div>
                  {afterKnown ? (
                    <div className="flex flex-wrap items-center gap-2 font-mono text-label-m">
                      {beforeKnown ? (
                        <>
                          <span className="text-text-tertiary">
                            {String(entry.before?.value)}
                          </span>
                          <span aria-hidden="true" className="text-text-tertiary">
                            →
                          </span>
                        </>
                      ) : (
                        <span className="text-label-s text-text-tertiary">
                          no prior value — reported as an appearance, not a delta
                        </span>
                      )}
                      <span className="text-text-primary">{String(entry.after.value)}</span>
                      {entry.after.availability !== "AVAILABLE" && (
                        <AvailabilityBadge
                          state={entry.after.availability}
                          reason={entry.after.reason}
                        />
                      )}
                    </div>
                  ) : (
                    <AvailabilityBadge
                      state={entry.after.availability}
                      reason={entry.after.reason}
                    />
                  )}
                  {operator && (
                    <span className="font-mono text-label-s text-text-tertiary">
                      {entry.change_id} · evidence {entry.evidence_refs.items.length} ·{" "}
                      {entry.evidence_refs.items[0]?.resolution}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Card>
  );
}
