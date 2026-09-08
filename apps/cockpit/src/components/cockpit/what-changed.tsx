"use client";

import Link from "next/link";

import { Badge, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { formatDecimal, humanizeCode } from "@/lib/format";
import { ReferenceDestinations } from "@/components/cockpit/reference-links";
import { cn } from "@/lib/utils";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { EnvelopeOf } from "@/contracts/envelope";
import type { WhatChangedEntryPayload } from "@/contracts/read-models";
import type { MetricValue, Ref } from "@/contracts/values";
import type { Completeness } from "@/contracts/vocabularies";
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
 * AN UNAVAILABLE ENDPOINT IS NOT A CHANGE (§7, U17). Where either endpoint is `STALE`,
 * `PARTIAL` or not a value at all, the row reports WHICH endpoint it was and WHAT STATE it is
 * in, and presents NO delta: no arrow, no difference and no asserted materiality. Both
 * endpoint values are still shown, separately labelled, as diagnostic detail — evidence a
 * reader can use rather than a comparison they might trust.
 *
 * ABSENCE IS NOT PROOF OF APPEARANCE (§4.5: "a change is never synthesised from the absence
 * of a value"). A missing prior value is an appearance only where the prior population is
 * known to have been complete, which is what the envelope's `completeness` states. Where it
 * does not, the row reports the change as unevidenced instead of inferring one.
 *
 * AN EMPTY LIST IS THREE DIFFERENT ANSWERS, and they are never rendered the same way:
 *
 *   the comparison RAN COMPLETE and found nothing   EMPTY_VERIFIED -- a measurement
 *   the comparison ran but not over its extent      an incomplete answer, and not a nothing
 *   there was nothing to compare against            NOT_YET_AVAILABLE -- an absence, with its
 *                                                   reason and its named dependency
 */

/** How one endpoint of a comparison stands. */
type EndpointClass = "VALUE" | "DEGRADED" | "UNAVAILABLE" | "ABSENT";

/**
 * `EMPTY_VERIFIED` is NOT degraded. "The producer ran and the correct answer is nothing" is a
 * definitive measurement, and marking it uncertain would tell a reader the opposite of what
 * it means. Only `STALE` and `PARTIAL` qualify a value that exists.
 */
function classifyEndpoint(metric: MetricValue | undefined): EndpointClass {
  if (metric === undefined) {
    return "ABSENT";
  }
  if (metric.availability === "STALE" || metric.availability === "PARTIAL") {
    return "DEGRADED";
  }
  return isValueBearing(metric.availability) ? "VALUE" : "UNAVAILABLE";
}

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

/**
 * ONE ENDPOINT, LABELLED AS ITSELF, CARRYING ITS OWN STATE.
 *
 * The defect this replaces put the AFTER endpoint's availability badge on every qualified
 * row, so a stale BASELINE was reported behind the comparison endpoint's `AVAILABLE`. Each
 * endpoint now answers for itself and for nothing else.
 */
function EndpointDetail({
  role,
  label,
  metric,
}: {
  role: "baseline" | "comparison";
  label: string;
  metric: MetricValue | undefined;
}) {
  const classification = classifyEndpoint(metric);
  return (
    <div
      data-testid={`endpoint-${role}`}
      data-endpoint-state={metric?.availability ?? "ABSENT"}
      className="flex flex-wrap items-center gap-2 text-label-m"
    >
      <span className="text-label-s uppercase tracking-wide text-text-tertiary">{label}</span>
      {metric === undefined ? (
        <span className="text-label-s text-text-tertiary">no prior value recorded</span>
      ) : (
        <>
          <EndpointValue metric={metric} />
          {classification !== "VALUE" && (
            <AvailabilityBadge state={metric.availability} reason={metric.reason} />
          )}
          {metric.as_of !== undefined && (
            <span className="font-mono text-label-s text-text-tertiary">as of {metric.as_of}</span>
          )}
        </>
      )}
    </div>
  );
}

/**
 * The evidence drill-down for one change.
 *
 * A REFERENCE COUNT IS NOT A DRILL-DOWN. Each reference states its kind, its own resolution
 * and its classification, and links to the area that owns it where one exists — in BOTH
 * modes, because evidence is what makes a reported change checkable rather than asserted.
 * `UNRESOLVABLE_V1` is a STATED resolution and not a gap (§4.2): the join is specified, the
 * producing subsystem does not exist, and the reference resolves to an availability state
 * rather than to a payload. It is shown with that resolution and never silently dropped.
 */
function EvidenceDisclosure({
  references,
  total,
  truncated,
  scope,
}: {
  references: readonly Ref[];
  total: MetricValue;
  truncated: boolean;
  scope: ViewScope;
}) {
  const stated = typeof total.value === "number" ? total.value : null;
  return (
    <details className="mt-1 rounded-sm border border-border-subtle bg-surface-sunken">
      <summary className="cursor-pointer px-3 py-1.5 text-label-m text-accent">
        Evidence ({stated ?? references.length})
        {truncated && stated !== null && stated > references.length
          ? ` — showing ${references.length}`
          : ""}
      </summary>
      <div className="space-y-2 px-3 pb-3 pt-1">
        <ul className="space-y-1.5">
          {references.map((reference) => {
            return (
              <li
                key={reference.ref_id}
                data-testid="change-evidence-reference"
                data-resolution={reference.resolution}
                data-classification={reference.classification}
                data-owning-area={reference.owning_area ?? ""}
                className="flex flex-wrap items-center gap-2 text-label-s"
              >
                <Badge tone="neutral">{humanizeCode(reference.ref_kind.toUpperCase())}</Badge>
                <span className="font-mono text-text-tertiary">{reference.ref_id}</span>
                <Badge tone="unavailable">{reference.resolution}</Badge>
                <Badge tone="neutral">{reference.classification}</Badge>
                {/*
                 * THE SAME TWO AFFORDANCES AS THE ATTENTION DISCLOSURE, from the same closed
                 * tables (§4.3.2). A change's evidence reference declares the area that owns
                 * the recorded fact where one is catalogued, and declares none where none is --
                 * an absence stays an absence and is never pushed to the nearest page.
                 */}
                <ReferenceDestinations reference={reference} scope={scope} />
              </li>
            );
          })}
        </ul>
        {references.some((reference) => reference.resolution === "UNRESOLVABLE_V1") && (
          <p
            data-testid="change-evidence-unresolvable-note"
            className="text-label-s leading-relaxed text-text-tertiary"
          >
            <strong>UNRESOLVABLE_V1</strong> is a stated resolution, not a gap: the join is
            specified and the producing subsystem does not exist, so the reference resolves to
            an availability state rather than to a payload.
          </p>
        )}
      </div>
    </details>
  );
}

interface RowVerdict {
  readonly comparison: "VALID" | "UNAVAILABLE";
  readonly kind: "DELTA" | "APPEARANCE" | "DEGRADED_ENDPOINT" | "UNEVIDENCED_APPEARANCE";
}

/**
 * Whether this row may be presented as a change at all.
 *
 * `populationComplete` is the envelope's own `completeness`. An appearance is a claim about a
 * POPULATION — "the prior comparison covered this subject and did not contain it" — and a
 * comparison that did not cover the extent it was asked for cannot support one.
 */
function verdictFor(entry: WhatChangedEntryPayload, populationComplete: boolean): RowVerdict {
  const before = classifyEndpoint(entry.before);
  const after = classifyEndpoint(entry.after);
  if (after !== "VALUE" || before === "DEGRADED" || before === "UNAVAILABLE") {
    return { comparison: "UNAVAILABLE", kind: "DEGRADED_ENDPOINT" };
  }
  if (before === "ABSENT") {
    return populationComplete
      ? { comparison: "VALID", kind: "APPEARANCE" }
      : { comparison: "UNAVAILABLE", kind: "UNEVIDENCED_APPEARANCE" };
  }
  return { comparison: "VALID", kind: "DELTA" };
}

function ChangeRow({
  entry,
  operator,
  populationComplete,
  completeness,
  scope,
}: {
  entry: WhatChangedEntryPayload;
  operator: boolean;
  populationComplete: boolean;
  completeness: Completeness;
  scope: ViewScope;
}) {
  const verdict = verdictFor(entry, populationComplete);
  const valid = verdict.comparison === "VALID";

  return (
    <li
      data-testid="what-changed-item"
      data-comparison={verdict.comparison}
      data-change-kind={verdict.kind}
      className="flex flex-col gap-1.5 border-t border-border-subtle px-5 py-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-numeric-s font-medium text-text-primary">
          {humanizeCode(entry.subject.code)}
        </span>
        <Badge tone="unavailable">{humanizeCode(entry.change_kind.code)}</Badge>
        {/*
          * MATERIALITY IS ASSERTED ONLY OVER A SOUND COMPARISON. A judgement drawn from a
          * qualified or missing endpoint is a judgement about a number nobody can stand
          * behind, so the badge is ABSENT rather than downgraded to a quieter tone.
          */}
        {valid ? (
          <Badge
            data-testid="change-materiality"
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
        ) : (
          <Badge tone="unavailable" className="ml-auto">
            NOT COMPARABLE
          </Badge>
        )}
      </div>

      {valid && verdict.kind === "DELTA" && entry.before !== undefined ? (
        <div data-testid="change-delta" className="flex flex-wrap items-center gap-2 text-label-m">
          <EndpointValue metric={entry.before} />
          <span aria-hidden="true" className="text-text-tertiary">
            →
          </span>
          <EndpointValue metric={entry.after} />
        </div>
      ) : valid ? (
        /* An APPEARANCE, over a population this comparison covered completely. */
        <div data-testid="change-appearance" className="flex flex-wrap items-center gap-2 text-label-m">
          <span className="text-label-s text-text-tertiary">
            verified absent from the prior comparison population, and present now:
          </span>
          <EndpointValue metric={entry.after} />
        </div>
      ) : (
        /* U17: the row reports the endpoint STATES instead of a delta. */
        <div
          data-testid="change-endpoints"
          className="flex flex-col gap-1 rounded-sm border border-border-subtle bg-surface-sunken px-3 py-2"
        >
          <EndpointDetail role="baseline" label="baseline" metric={entry.before} />
          <EndpointDetail role="comparison" label="comparison" metric={entry.after} />
        </div>
      )}

      {verdict.kind === "DEGRADED_ENDPOINT" && (
        <p className="max-w-2xl text-label-s leading-relaxed text-text-tertiary">
          One endpoint of this comparison is <strong>not a sound value</strong>, so no
          difference between them is drawn and no materiality is asserted. Each endpoint is
          shown above with its own state, as evidence rather than as a comparison.
        </p>
      )}

      {verdict.kind === "UNEVIDENCED_APPEARANCE" && (
        <div
          data-testid="appearance-unevidenced"
          className="flex flex-col items-start gap-1 text-label-s text-text-tertiary"
        >
          <AvailabilityBadge
            state="NOT_YET_AVAILABLE"
            reason={
              completeness === "PARTIAL" ? "EXTENT_PARTIALLY_COVERED" : "EXTENT_NOT_DETERMINABLE"
            }
          />
          <p className="max-w-2xl leading-relaxed">
            There is no prior value for this subject, and{" "}
            <strong>the prior comparison population is not known to be complete</strong> — so
            a subject that was genuinely absent cannot be told apart from one the comparison
            never covered. A change read out of that is invented from missing data, and none
            is reported here.
          </p>
        </div>
      )}

      <EvidenceDisclosure
        references={entry.evidence_refs.items}
        total={entry.evidence_refs.total}
        truncated={entry.evidence_refs.truncated}
        scope={scope}
      />

      {operator && (
        <span className="font-mono text-label-s text-text-tertiary">
          {entry.change_id} · after {entry.after.metric_id} · after state{" "}
          {entry.after.availability}
          {entry.before !== undefined &&
            ` · before ${entry.before.availability} as-of ${entry.before.as_of ?? "absent"}`}
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

  /*
   * §4.5: "a change with no resolvable evidence reference is NOT RENDERED". A reference list
   * carrying no reference at all cannot make a change checkable, so the row is withheld --
   * and the count is STATED, because a silently shorter list reads as fewer changes.
   *
   * UNRESOLVABLE_V1 is not that case: it is a stated resolution to an availability state,
   * and a row carrying one is rendered WITH that resolution shown.
   */
  const renderable = (payload?.entries ?? []).filter(
    (entry) => entry.evidence_refs.items.length > 0,
  );
  const withheld = (payload?.entries.length ?? 0) - renderable.length;

  /*
   * THE POPULATION CLAIM COMES FROM THE ENVELOPE, not from a row's own optimism. COMPLETE is
   * the only value that says this comparison covered the extent it was asked for.
   */
  const populationComplete = envelope.completeness === "COMPLETE";
  const comparisonSound = populationComplete && envelope.availability === "AVAILABLE";

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
                <dd
                  className={
                    payload.baseline_as_of === undefined
                      ? "text-unavailable"
                      : "text-text-secondary"
                  }
                >
                  {payload.baseline_as_of ?? "absent"}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt>comparison as-of</dt>
                <dd className="text-text-secondary">{payload.comparison_as_of ?? "absent"}</dd>
              </div>
              <div className="flex gap-2">
                <dt>coverage</dt>
                <dd className="text-text-secondary">{envelope.completeness}</dd>
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
          ) : renderable.length === 0 ? (
            <CardBody className="border-t border-border-subtle pt-3">
              {comparisonSound ? (
                <div data-testid="what-changed-empty-verified">
                  <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
                  <p className="mt-2 max-w-2xl text-label-m leading-relaxed text-text-tertiary">
                    Both endpoints are sound, the comparison covered the whole extent it was
                    asked for, and <strong>nothing changed between them</strong>. That is a
                    measurement — a different answer from having had nothing to compare.
                  </p>
                </div>
              ) : (
                /*
                 * AN EMPTY LIST IS NOT BY ITSELF A VERIFIED NOTHING. A comparison that did not
                 * complete soundly over its whole extent has established nothing about the
                 * part it never covered.
                 */
                <div data-testid="what-changed-empty-unverified">
                  <AvailabilityBadge
                    state={
                      envelope.availability === "AVAILABLE" ? "PARTIAL" : envelope.availability
                    }
                    reason={
                      envelope.completeness === "PARTIAL"
                        ? "EXTENT_PARTIALLY_COVERED"
                        : envelope.completeness === "UNKNOWN"
                          ? "EXTENT_NOT_DETERMINABLE"
                          : envelope.availability_reason
                    }
                  />
                  <p className="mt-2 max-w-2xl text-label-m leading-relaxed text-text-tertiary">
                    No change is listed, and{" "}
                    <strong>that is not a measurement that nothing changed</strong>. This
                    comparison did not complete soundly over the whole extent it was asked
                    for, so the part it did not cover is unknown rather than unchanged.
                  </p>
                </div>
              )}
            </CardBody>
          ) : (
            <ul>
              {renderable.map((entry) => (
                <ChangeRow
                  key={entry.change_id}
                  entry={entry}
                  operator={operator}
                  populationComplete={populationComplete}
                  completeness={envelope.completeness}
                  scope={scope}
                />
              ))}
            </ul>
          )}

          {withheld > 0 && (
            <CardBody className="border-t border-border-subtle pt-3">
              <span
                data-testid="what-changed-withheld"
                className="text-label-s text-text-tertiary"
              >
                {withheld} change{withheld === 1 ? "" : "s"} withheld: a change with no
                resolvable evidence reference is not rendered.
              </span>
            </CardBody>
          )}

          {envelope.completeness === "PARTIAL" && renderable.length > 0 && (
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
