"use client";

import * as React from "react";

import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Label,
  ScrollRegion,
} from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { EnvelopeOf } from "@/contracts/envelope";
import type { Ref } from "@/contracts/values";
import { humanizeCode } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The wrapper every C5 panel is built from.
 *
 * ONE COMPONENT, because the same four things must happen around every read model and doing
 * them by hand eight times is eight chances to skip one:
 *
 *   A LOADING PANEL CARRIES NO DIGITS       shape-only, so a screenshot taken mid-load is not
 *                                           mistakable for data (U7)
 *   A PAYLOADLESS RESPONSE SAYS WHY         its availability state, its closed reason code and
 *                                           the dependency it waits on — never an empty panel
 *   PROVENANCE IS AT COMPONENT LEVEL        because screenshots travel (U3), and a page
 *                                           carrying both kinds badges each one individually
 *   A FAILING WIDGET DOES NOT FAIL THE PAGE the panel reports its own state and the page
 *                                           reports itself PARTIAL (U6)
 */

export interface ReadModelPanelProps<T> {
  readonly title: string;
  readonly description?: React.ReactNode;
  readonly envelope: EnvelopeOf<T> | undefined;
  /** What an unavailable response is waiting on. Named, never left to the reader. */
  readonly dependency: string;
  readonly children: (payload: T, envelope: EnvelopeOf<T>) => React.ReactNode;
  readonly actions?: React.ReactNode;
  readonly operator?: boolean;
  readonly testId?: string;
  readonly className?: string;
  /** Rendered under the header whether or not a payload arrived. */
  readonly always?: React.ReactNode;
}

export function ReadModelPanel<T>({
  title,
  description,
  envelope,
  dependency,
  children,
  actions,
  operator = false,
  testId,
  className,
  always,
}: ReadModelPanelProps<T>) {
  return (
    <Card className={className} data-testid={testId}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{title}</Label>
          {description !== undefined && (
            <p className="mt-0.5 max-w-3xl text-label-m leading-relaxed text-text-secondary">
              {description}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {envelope?.payload !== undefined && (
            <ProvenanceBadge provenance={envelope.provenance} />
          )}
          {envelope !== undefined && envelope.completeness === "PARTIAL" && (
            <Badge tone="warning" data-testid="panel-partial">
              <span aria-hidden="true">◧</span>
              <span>Partial</span>
            </Badge>
          )}
          {actions}
        </div>
      </CardHeader>
      <CardBody className="space-y-3">
        {always}
        {envelope === undefined ? (
          <>
            <div className="skeleton-shape h-24 w-full" data-testid="skeleton" />
            <span className="sr-only">Loading {title}</span>
          </>
        ) : envelope.payload === undefined ? (
          <UnavailableBody
            state={envelope.availability}
            reason={envelope.availability_reason}
            dependency={dependency}
          />
        ) : (
          <>
            {children(envelope.payload, envelope)}
            {operator && <EvidenceStrip envelope={envelope} />}
          </>
        )}
      </CardBody>
    </Card>
  );
}

/** The Operator-mode evidence every panel exposes: what this row is, and how far it read. */
export function EvidenceStrip<T>({ envelope }: { envelope: EnvelopeOf<T> }) {
  const fields: readonly (readonly [string, string])[] = [
    ["schema_version", envelope.schema_version],
    ["entity_id", envelope.entity_id],
    ["environment", envelope.environment],
    ["maturity_stage", envelope.maturity_stage ?? "absent"],
    ["provenance", envelope.provenance],
    ["classification", envelope.classification],
    ["access_scope", envelope.access_scope],
    ["availability", `${envelope.availability}/${envelope.availability_reason}`],
    ["completeness", envelope.completeness],
    ["as_of_time", envelope.as_of_time],
    ["watermark", envelope.watermark ?? "absent"],
    ["snapshot_version", envelope.snapshot_version],
    ["metric_definition_version", envelope.metric_definition_version],
  ];
  return (
    <ScrollRegion label="Read-model evidence fields" className="border-t border-border-subtle pt-3">
      <dl className="grid min-w-[34rem] grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-label-s sm:grid-cols-3">
        {fields.map(([key, value]) => (
          <div key={key} className="flex flex-col">
            <dt className="text-text-tertiary">{key}</dt>
            <dd className="truncate text-text-secondary" title={value}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </ScrollRegion>
  );
}

/**
 * A reference, rendered as what it is.
 *
 * §4.3: a reference that resolves to nothing is **carried, not omitted**, so a reader knows
 * the join exists and what it waits on. The resolution and the classification are shown, and
 * `UNRESOLVABLE_V1` is stated as the specified-but-absent producer it means.
 */
export function ReferenceChip({
  reference,
  label,
  className,
}: {
  reference: Ref;
  label?: string;
  className?: string;
}) {
  const unresolvable = reference.resolution === "UNRESOLVABLE_V1";
  return (
    <span
      className={cn(
        "inline-flex flex-wrap items-center gap-1.5 rounded-sm border px-2 py-0.5 text-label-s",
        "bg-surface-sunken",
        unresolvable ? "border-border-subtle" : "border-info/40",
        className,
      )}
      data-ref-kind={reference.ref_kind}
      data-resolution={reference.resolution}
      title={
        unresolvable
          ? "The join is specified and the producing subsystem does not exist, so this resolves to an availability state rather than to a payload."
          : `Resolves by ${reference.resolution.toLowerCase()}.`
      }
    >
      {/*
        * EVERY PART OF A CHIP MEETS THE CONTRAST REQUIREMENT.
        *
        * The resolution and the classification were dimmed with opacity, which is how a
        * secondary detail becomes an unreadable one: at 60% over a sunken surface they fell
        * to 2.8:1 against the 4.5:1 body-text requirement. Hierarchy here comes from the
        * TOKEN each part uses, not from fading it out.
        */}
      <span
        className={cn("font-medium", unresolvable ? "text-text-tertiary" : "text-info")}
      >
        {label ?? humanizeCode(reference.ref_kind)}
      </span>
      <span className="font-mono text-text-secondary">{reference.resolution}</span>
      <span className="font-mono text-text-tertiary">{reference.classification}</span>
    </span>
  );
}

/** A named section inside a panel, with its own heading level. */
export function PanelSection({
  title,
  children,
  note,
  state,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  note?: React.ReactNode;
  state?: { availability: React.ComponentProps<typeof AvailabilityBadge>["state"]; reason: React.ComponentProps<typeof AvailabilityBadge>["reason"] };
  testId?: string;
}) {
  return (
    <section className="space-y-2" data-testid={testId}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-label-m font-semibold text-text-primary">{title}</h3>
        {state !== undefined && (
          <AvailabilityBadge state={state.availability} reason={state.reason} />
        )}
      </div>
      {note !== undefined && (
        <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">{note}</p>
      )}
      {children}
    </section>
  );
}
