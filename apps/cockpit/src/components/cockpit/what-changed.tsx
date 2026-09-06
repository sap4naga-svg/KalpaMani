"use client";

import Link from "next/link";

import { Badge, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { formatDecimal, humanizeCode } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { EnvelopeOf } from "@/contracts/envelope";
import type { WhatChangedEntryPayload } from "@/contracts/read-models";
import type { MetricValue } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";
import type { WhatChangedPayload } from "@/data/client/read-client";
import {
  CHANGE_VARIANTS,
  CHANGE_VARIANT_LABEL,
  withScope,
  type ChangeVariant,
  type ViewScope,
} from "@/lib/scope";

/**
 * What Changed — `ui-ux-specification.md` §7.
 *
 * A COMPARISON NEEDS A STATED BASELINE, AND THIS ONE SAYS IT ON THE SCREEN. The window is
 * explicit, both endpoints carry their as-of, and the environment and provenance of the
 * comparison are shown beside them — because two provenances never form one delta.
 *
 * AN UNAVAILABLE ENDPOINT IS NOT A CHANGE (U17). Where either side is `NOT_YET_AVAILABLE`,
 * `STALE` or `PARTIAL`, the item reports THAT STATE alongside its values instead of
 * presenting a clean delta, and where there is no baseline at all there are no items —
 * A DELTA COMPUTED AGAINST A MISSING BASELINE IS A FABRICATED CHANGE.
 *
 * AN EMPTY LIST IS TWO DIFFERENT ANSWERS, and they are never rendered the same way:
 *
 *   the comparison RAN and found nothing        EMPTY_VERIFIED -- a measurement
 *   there was nothing to compare against        NOT_YET_AVAILABLE -- an absence, with its
 *                                               reason and its named dependency
 */

/** The rendered figure for one endpoint, with its qualification kept. */
function EndpointValue({ metric }: { metric: MetricValue }) {
  if (!isValueBearing(metric.availability)) {
    return <AvailabilityBadge state={metric.availability} reason={metric.reason} />;
  }
  const decimal =
    typeof metric.value === "string"
      ? formatDecimal(metric.value, {
          minimumFractionDigits: metric.unit === "USD" ? 2 : metric.unit === "PERCENT" ? 2 : 0,
        })
      : null;
  return (
    <span className="font-mono text-text-primary">
      {decimal ?? String(metric.value)}
      {metric.unit === "USD" ? " USD" : metric.unit === "PERCENT" ? "%" : ""}
    </span>
  );
}

function ChangeRow({ entry, operator }: { entry: WhatChangedEntryPayload; operator: boolean }) {
  const beforeKnown = entry.before !== undefined && isValueBearing(entry.before.availability);
  const afterKnown = isValueBearing(entry.after.availability);
  /*
   * A DEGRADED ENDPOINT IS REPORTED, NOT ABSORBED. A delta drawn between two qualified
   * numbers is only as sound as they are, so the badge stays on the row.
   *
   * `EMPTY_VERIFIED` is NOT degraded. "The producer ran and the correct answer is nothing" is
   * a definitive measurement, and marking it uncertain would tell a reader the opposite of
   * what it means. Only STALE and PARTIAL qualify a value, and an absence is handled above.
   */
  const qualifies = (state: MetricValue["availability"]): boolean =>
    state === "STALE" || state === "PARTIAL";
  const degraded =
    (entry.before !== undefined && qualifies(entry.before.availability)) ||
    qualifies(entry.after.availability);

  return (
    <li
      key={entry.change_id}
      data-testid="what-changed-item"
      data-degraded={degraded ? "true" : "false"}
      className="flex flex-col gap-1 border-t border-border-subtle px-5 py-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-numeric-s font-medium text-text-primary">
          {humanizeCode(entry.subject.code)}
        </span>
        <Badge tone="unavailable">{humanizeCode(entry.change_kind.code)}</Badge>
        <Badge
          tone={
            entry.materiality.code === "MATERIAL"
              ? "warning"
              : entry.materiality.code === "INDETERMINATE"
                ? "unavailable"
                : "neutral"
          }
          className="ml-auto"
        >
          {entry.materiality.code}
        </Badge>
      </div>

      {afterKnown ? (
        <div className="flex flex-wrap items-center gap-2 text-label-m">
          {beforeKnown && entry.before !== undefined ? (
            <>
              <EndpointValue metric={entry.before} />
              <span aria-hidden="true" className="text-text-tertiary">
                →
              </span>
            </>
          ) : (
            <span className="text-label-s text-text-tertiary">
              no prior value for this subject — reported as an appearance, not a delta
            </span>
          )}
          <EndpointValue metric={entry.after} />
          {degraded && (
            <AvailabilityBadge
              state={entry.after.availability}
              reason={entry.after.reason}
            />
          )}
        </div>
      ) : (
        /* U17: an unavailable endpoint reports THAT STATE instead of a delta. */
        <AvailabilityBadge state={entry.after.availability} reason={entry.after.reason} />
      )}

      {degraded && (
        <p className="text-label-s text-text-tertiary">
          One endpoint of this comparison is qualified, so the difference between them is
          reported <strong>with that qualification</strong> and its materiality is not
          asserted.
        </p>
      )}

      {operator && (
        <span className="font-mono text-label-s text-text-tertiary">
          {entry.change_id} · evidence {String(entry.evidence_refs.total.value ?? "—")} ·{" "}
          {entry.evidence_refs.items[0]?.resolution ?? "no reference"} · after{" "}
          {entry.after.metric_id}
          {entry.before !== undefined && ` · before as-of ${entry.before.as_of ?? "absent"}`}
        </span>
      )}
    </li>
  );
}

/**
 * The demonstration-variant selector.
 *
 * Only rendered inside the SYNTHETIC scenario, where everything is already labelled. Three of
 * §7's four behaviours are only reachable when an endpoint is broken, and a reviewer cannot
 * break a fixture from the interface — so the variants are selectable, deterministic, and
 * carried in the URL like every other scope field.
 */
function VariantSelector({ scope }: { scope: ViewScope }) {
  return (
    <div
      role="group"
      aria-label="Demonstration comparison variant"
      className="flex flex-wrap items-center gap-1.5"
      data-testid="change-variant-selector"
    >
      <span className="text-label-s uppercase tracking-wide text-text-tertiary">
        Demonstration variant
      </span>
      {/*
        * Links, not buttons. A variant is part of the view's identity and lives in the URL,
        * so selecting one is a NAVIGATION -- shareable, reproducible and back-navigable --
        * rather than local state a shared link would lose.
        */}
      {CHANGE_VARIANTS.map((variant: ChangeVariant) => {
        const active = scope.changes === variant;
        return (
          <Link
            key={variant}
            href={withScope("/", { ...scope, changes: variant })}
            aria-current={active ? "true" : undefined}
            className={cn(
              "inline-flex h-7 items-center rounded-sm px-2.5 text-label-m font-medium transition-colors",
              active
                ? "bg-accent text-text-inverse"
                : "border border-border-subtle bg-surface-sunken text-text-secondary hover:border-border-strong hover:text-text-primary",
            )}
          >
            {CHANGE_VARIANT_LABEL[variant]}
          </Link>
        );
      })}
    </div>
  );
}

export function WhatChangedPanel({
  envelope,
  scope,
  operator,
  withVariants = false,
}: {
  envelope: EnvelopeOf<WhatChangedPayload>;
  scope: ViewScope;
  operator: boolean;
  withVariants?: boolean;
}) {
  const payload = envelope.payload;
  const noBaseline = payload !== undefined && payload.baseline_state !== undefined;

  return (
    <Card data-testid="what-changed-panel">
      <CardHeader className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
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
          <CardBody className="space-y-2 pb-2">
            {/* BOTH ENDPOINTS, and the environment they were compared in. */}
            <dl className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-label-s text-text-tertiary">
              <div className="flex gap-2">
                <dt>baseline as-of</dt>
                <dd className={payload.baseline_as_of === undefined ? "text-unavailable" : "text-text-secondary"}>
                  {payload.baseline_as_of ?? "absent"}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt>comparison as-of</dt>
                <dd className="text-text-secondary">{payload.comparison_as_of ?? "absent"}</dd>
              </div>
              <div className="flex gap-2">
                <dt>environment</dt>
                <dd className="text-text-secondary">{envelope.environment}</dd>
              </div>
              <div className="flex gap-2">
                <dt>provenance</dt>
                <dd className="text-text-secondary">{envelope.provenance}</dd>
              </div>
            </dl>
            {withVariants && <VariantSelector scope={scope} />}
          </CardBody>

          {noBaseline && payload.baseline_state !== undefined ? (
            <CardBody className="border-t border-border-subtle pt-3">
              <UnavailableBody
                state={payload.baseline_state.availability}
                reason={payload.baseline_state.reason}
                dependency="a prior snapshot of the same subjects, in the same environment"
              />
              <p className="mt-2 max-w-2xl text-label-m leading-relaxed text-text-tertiary">
                <strong>No change is listed, and none is inferred.</strong> A delta computed
                against a missing baseline is a fabricated change, and an appearance cannot be
                read out of a population that was never observed.
              </p>
            </CardBody>
          ) : payload.entries.length === 0 ? (
            <CardBody className="border-t border-border-subtle pt-3">
              <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              <p className="mt-2 max-w-2xl text-label-m leading-relaxed text-text-tertiary">
                Both endpoints are sound and <strong>nothing changed between them</strong>.
                That is a measurement over a complete comparison — a different answer from
                having had nothing to compare.
              </p>
            </CardBody>
          ) : (
            <ul>
              {payload.entries.map((entry) => (
                <ChangeRow key={entry.change_id} entry={entry} operator={operator} />
              ))}
            </ul>
          )}

          {envelope.completeness === "PARTIAL" && (
            <CardBody className="border-t border-border-subtle pt-3">
              <div className="flex flex-wrap items-center gap-2">
                <AvailabilityBadge state="PARTIAL" reason="EXTENT_PARTIALLY_COVERED" />
                <span className="text-label-m text-text-tertiary">
                  This comparison did not cover the whole extent it was asked for.
                </span>
              </div>
            </CardBody>
          )}
        </>
      )}
    </Card>
  );
}
