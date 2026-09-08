"use client";

import * as React from "react";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  EvaluationClassBadge,
  ReadOnlyNotice,
  ReasonList,
  ReferenceListPanel,
  ReferenceRow,
} from "@/components/cockpit/research";
import { useScope } from "@/components/shell/use-scope";
import type { HypothesisRegistration } from "@/contracts/research-models";
import { useHypotheses } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";

/**
 * Hypothesis Registry — Area 18.
 *
 * "Hold preregistrations immutably, so results cannot be reinterpreted after the fact."
 *
 *   A REGISTRATION IS IMMUTABLE            results attach as LINKED records and never edit it.
 *                                          A design change creates an amendment or a new
 *                                          registration, and the chain is displayed
 *   THE BUDGET IS READ ACROSS THE LINEAGE  granted, consumed and remaining are the LINEAGE's,
 *                                          and each row also shows what this identity spent on
 *                                          its own — so a rename cannot look like a reset
 *   EXPOSURE FOLLOWS THE DATA              the ledger is keyed by the LOCKED SET, spans
 *                                          registrations, and a confirmatory declaration over
 *                                          an already-exposed or unmeasurable set carries its
 *                                          refusal
 *   NO EDIT, REGISTER OR AMEND             no such control exists on this screen or anywhere
 *                                          in this application
 */

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const hypotheses = useHypotheses(scope);
  const [selected, setSelected] = React.useState<string | null>(null);

  const payload = hypotheses.data?.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);
  const chosen = items.find((entry) => entry.registration_id === selected) ?? items[0];
  const refused = items.filter((entry) => entry.exposure_ledger.refusal !== undefined);

  return (
    <>
      <PageHeader
        title="Hypothesis Registry"
        summary="Immutable preregistrations with their thesis, named baseline, variation, criteria, pins, trial budget and the exposure ledger of the locked set they name."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 18</Badge>
          <Badge tone="unavailable">Learning engine: NOT IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="immutable preregistrations"
          actions={["register", "amend", "edit", "supersede", "withdraw"]}
        />

        <ReadModelPanel
          title="Registrations"
          description="Every preregistration, with the trials its LINEAGE has spent beside the trials this identity spent on its own. A new registration identity resets neither."
          envelope={hypotheses.data}
          dependency="the hypothesis registry — no learning engine exists"
          operator={operator}
          testId="registration-table"
        >
          {() => (
            <div className="space-y-3">
              <ScrollRegion label="Hypothesis registrations">
                <table
                  className="w-full min-w-[58rem] border-collapse text-label-m"
                  data-testid="registration-rows"
                >
                  <caption className="sr-only">
                    Every preregistration with its module, declared evaluation class, the locked
                    set it names, its lineage trial budget, its own trial count and any refusal
                    the exposure ledger produces for it.
                  </caption>
                  <thead className="bg-surface-sunken">
                    <tr className="border-b border-border-subtle text-left text-text-tertiary">
                      <th scope="col" className="px-3 py-2 font-medium">
                        Registration
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Declared class
                      </th>
                      <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                        Locked set
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Lineage budget
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Its own trials
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Ledger
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Detail
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((entry) => (
                      <tr
                        key={entry.registration_id}
                        className="border-b border-border-subtle last:border-0"
                        data-registration={entry.registration_id}
                      >
                        <th
                          scope="row"
                          className="px-3 py-1.5 text-left font-normal text-text-secondary"
                        >
                          <span className="flex flex-col">
                            <span className="font-mono">{entry.registration_id}</span>
                            <span className="text-label-s text-text-tertiary">
                              {humanizeCode(entry.strategy_module.code)}
                            </span>
                          </span>
                        </th>
                        <td className="px-3 py-1.5">
                          <EvaluationClassBadge
                            evaluationClass={entry.declared_evaluation_class}
                          />
                        </td>
                        <td className="hidden px-3 py-1.5 font-mono text-label-s text-text-secondary lg:table-cell">
                          {entry.exposure_ledger.locked_set}
                        </td>
                        <td className="px-3 py-1.5">
                          <span className="flex flex-wrap items-baseline gap-1">
                            <MetricText metric={entry.trial_budget.consumed} neutral />
                            <span className="text-label-s text-text-tertiary">of</span>
                            <MetricText metric={entry.trial_budget.granted} neutral />
                            <span className="text-label-s text-text-tertiary">spent</span>
                          </span>
                        </td>
                        <td className="px-3 py-1.5">
                          <MetricText metric={entry.own_trial_count} neutral />
                        </td>
                        <td className="px-3 py-1.5">
                          {entry.exposure_ledger.refusal === undefined ? (
                            <Badge tone="neutral">
                              {humanizeCode(entry.exposure_ledger.completeness)}
                            </Badge>
                          ) : (
                            <Badge
                              tone="negative"
                              data-ledger-refusal={entry.exposure_ledger.refusal.code}
                            >
                              {humanizeCode(entry.exposure_ledger.refusal.code)}
                            </Badge>
                          )}
                        </td>
                        <td className="px-3 py-1.5">
                          <Button
                            size="sm"
                            variant={
                              entry.registration_id === chosen?.registration_id
                                ? "primary"
                                : "subtle"
                            }
                            aria-pressed={entry.registration_id === chosen?.registration_id}
                            onClick={() => setSelected(entry.registration_id)}
                          >
                            Ledger
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollRegion>
              <p
                className="max-w-3xl text-label-s leading-relaxed text-text-tertiary"
                data-testid="lineage-budget-note"
              >
                <strong className="text-text-secondary">
                  The budget columns are the LINEAGE&apos;s, not the row&apos;s.
                </strong>{" "}
                A registration whose own trial count is one and whose lineage consumption is
                five has not been given a fresh budget by being given a new name — and{" "}
                <strong className="text-text-secondary">
                  failed and abandoned runs count wherever they occurred.
                </strong>{" "}
                {refused.length > 0 && (
                  <>
                    {refused.length} registration{refused.length === 1 ? "" : "s"} carry a
                    ledger refusal, so their declared class cannot be read as fresh
                    out-of-sample evidence.
                  </>
                )}
              </p>
            </div>
          )}
        </ReadModelPanel>

        {chosen !== undefined && (
          <RegistrationDetail entry={chosen} operator={operator} scope={scope} />
        )}
      </div>
    </>
  );
}

function RegistrationDetail({
  entry,
  operator,
  scope,
}: {
  entry: HypothesisRegistration;
  operator: boolean;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  return (
    <Card data-testid="registration-detail" data-registration={entry.registration_id}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{humanizeCode(entry.strategy_module.code)}</Label>
          <p className="mt-0.5 font-mono text-label-m text-text-secondary">
            {entry.registration_id}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="info">Immutable</Badge>
          <EvaluationClassBadge evaluationClass={entry.declared_evaluation_class} />
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        <PanelSection
          title="The preregistration"
          note="Registered before any result was seen. Later records append; none of them edits this."
          testId="registration-body"
        >
          <dl className="grid gap-3 lg:grid-cols-2">
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Thesis
              </dt>
              <dd className="text-label-m text-text-secondary">
                {humanizeCode(entry.thesis.code)}
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Variation
              </dt>
              <dd className="text-label-m text-text-secondary">
                {humanizeCode(entry.variation.code)}
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Named baseline
              </dt>
              <dd>
                <ReferenceRow reference={entry.baseline_ref} label="Baseline" scope={scope} />
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Registered at
              </dt>
              <dd className="font-mono text-label-m text-text-secondary">
                {entry.registered_at}
              </dd>
            </div>
          </dl>
        </PanelSection>

        <PanelSection
          title="Criteria, stated before any result was seen"
          note="A hypothesis that cannot fail has not been stated, so the failure criteria are non-empty by contract."
          testId="registration-criteria"
        >
          <div className="grid gap-3 lg:grid-cols-2">
            <div>
              <Label>Success criteria</Label>
              <div className="mt-1">
                <ReasonList
                  codes={entry.success_criteria}
                  tone="positive"
                  empty="No success criterion is recorded."
                />
              </div>
            </div>
            <div>
              <Label>Failure criteria</Label>
              <div className="mt-1">
                <ReasonList
                  codes={entry.failure_criteria}
                  tone="negative"
                  empty="No failure criterion is recorded."
                  testId="failure-criteria"
                />
              </div>
            </div>
          </div>
        </PanelSection>

        <PanelSection
          title="Trial budget, across the lineage"
          note="Granted, consumed and remaining are read across the research lineage. This identity's own consumption is shown beside them so the difference is visible."
          testId="registration-budget"
        >
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(
              [
                ["Granted to the lineage", entry.trial_budget.granted],
                ["Consumed by the lineage", entry.trial_budget.consumed],
                ["Remaining to the lineage", entry.trial_budget.remaining],
                ["Spent by this registration", entry.own_trial_count],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="flex flex-col gap-0.5">
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  {label}
                </dt>
                <dd>
                  <MetricText metric={value} neutral operator={operator} />
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            <strong className="text-text-secondary">
              Renaming a registration or a Challenger resets neither the budget nor the
              exposure.
            </strong>{" "}
            The lineage is read through the parent registration, the amendment chain, the
            supersession links, a shared named baseline and a shared queue trigger.
          </p>
        </PanelSection>

        <PanelSection
          title="Exposure ledger"
          note="Attached to the LOCKED SET rather than to a registration, so most of these entries were written by something else. Overlap is measured, and an unmeasurable overlap fails closed."
          testId="registration-ledger"
        >
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-label-m text-text-secondary">
                {entry.exposure_ledger.locked_set}
              </span>
              <Badge tone="neutral">
                {humanizeCode(entry.exposure_ledger.completeness)} ledger
              </Badge>
              <MetricText metric={entry.exposure_ledger.entry_count} neutral />
              <span className="text-label-s text-text-tertiary">recorded entries</span>
            </div>

            {entry.exposure_ledger.refusal !== undefined && (
              <div
                className="flex flex-wrap items-center gap-2 rounded-sm border border-negative/40 bg-surface-sunken p-3"
                data-testid="ledger-refusal"
                data-refusal={entry.exposure_ledger.refusal.code}
              >
                <AvailabilityBadge state="NOT_AUTHORIZED" reason="PRODUCER_NOT_AUTHORIZED" />
                <span className="max-w-3xl text-label-m text-text-secondary">
                  <strong>{humanizeCode(entry.exposure_ledger.refusal.code)}.</strong> The
                  declared confirmatory class is <strong>refused rather than downgraded</strong>
                  , and this evidence is not admitted as fresh out-of-sample evidence under any
                  name. A new registration identity, a new Challenger identity and a new
                  research question leave the data exactly as exposed as it was.
                </span>
              </div>
            )}

            {entry.exposure_ledger.entries.length === 0 ? (
              <div className="flex flex-wrap items-center gap-2">
                <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
                <span className="text-label-m text-text-tertiary">
                  This locked set records no exposure entry. It has not been evaluated.
                </span>
              </div>
            ) : (
              <ScrollRegion
                label="Exposure ledger entries"
                className="rounded-sm border border-border-subtle"
              >
                <table
                  className="w-full min-w-[46rem] border-collapse text-label-m"
                  data-testid="ledger-entries"
                >
                  <caption className="sr-only">
                    Every recorded evaluation of this locked set, the registration that wrote
                    it, its declared class and its measured overlap with prior entries.
                  </caption>
                  <thead className="bg-surface-sunken">
                    <tr className="border-b border-border-subtle text-left text-text-tertiary">
                      <th scope="col" className="px-3 py-2 font-medium">
                        Entry
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Written by
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Class
                      </th>
                      <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                        Requested extent
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Measured overlap
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        At
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {entry.exposure_ledger.entries.map((ledgerEntry) => (
                      <tr
                        key={ledgerEntry.entry_id}
                        className="border-b border-border-subtle last:border-0"
                        data-ledger-entry={ledgerEntry.entry_id}
                      >
                        <th
                          scope="row"
                          className="px-3 py-1.5 text-left font-mono font-normal text-text-secondary"
                        >
                          {ledgerEntry.entry_id}
                        </th>
                        <td className="px-3 py-1.5">
                          <ReferenceRow
                            reference={ledgerEntry.registration_ref}
                            label="Registration"
                            scope={scope}
                          />
                        </td>
                        <td className="px-3 py-1.5">
                          <EvaluationClassBadge
                            evaluationClass={ledgerEntry.evaluation_class}
                          />
                        </td>
                        <td className="hidden px-3 py-1.5 text-text-secondary lg:table-cell">
                          {humanizeCode(ledgerEntry.requested_extent.code)}
                        </td>
                        <td className="px-3 py-1.5">
                          <MetricText metric={ledgerEntry.measured_overlap} neutral />
                        </td>
                        <td className="px-3 py-1.5 font-mono text-label-s text-text-tertiary">
                          {ledgerEntry.at}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollRegion>
            )}
            <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
              <strong className="text-text-secondary">Incomparable is not disjoint.</strong> An
              overlap that could not be measured renders as an unavailable value, never as a
              zero — and a ledger that cannot be shown complete refuses a confirmatory claim.
            </p>
          </div>
        </PanelSection>

        <PanelSection
          title="Lineage"
          note="Parent, amendments, related registrations and supersession. Exposure and budget are read across all of them."
          testId="registration-lineage"
        >
          <div className="space-y-2">
            {entry.lineage.parent_registration === undefined ? (
              <p className="text-label-m text-text-tertiary">
                This registration has no parent: it is the head of its own lineage.
              </p>
            ) : (
              <ReferenceRow
                reference={entry.lineage.parent_registration}
                label="Parent registration"
                scope={scope}
              />
            )}
            {entry.lineage.superseded_by !== undefined && (
              <ReferenceRow
                reference={entry.lineage.superseded_by}
                label="Superseded by"
                scope={scope}
              />
            )}
            <div className="grid gap-3 lg:grid-cols-2">
              <ReferenceListPanel
                list={entry.lineage.amendment_chain}
                label="Amendment chain"
                scope={scope}
                empty="No amendment has been recorded against this registration."
              />
              <ReferenceListPanel
                list={entry.lineage.related_registrations}
                label="Related registrations"
                scope={scope}
                empty="No related registration is recorded."
              />
            </div>
          </div>
        </PanelSection>

        <PanelSection
          title="Linked results"
          note="Results APPEND to a registration. None of them edits it."
          testId="registration-results"
        >
          <ReferenceListPanel
            list={entry.linked_results}
            label="Runs"
            scope={scope}
            empty="No run has been recorded against this registration."
          />
        </PanelSection>

        <PanelSection
          title="Pins and data requirements"
          note="The identities the registration was recorded against, and what it needs before it can run."
          testId="registration-pins"
        >
          <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {(
              [
                ["Manifest", entry.pins.manifest],
                ["Information profile", humanizeCode(entry.pins.profile.code)],
                ["Revision view", entry.pins.revision_view],
                ["Factor definitions", entry.pins.factor_definition_version],
                ["Research code identity", entry.pins.research_code_identity],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="flex flex-col gap-0.5">
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  {label}
                </dt>
                <dd className="font-mono text-label-m text-text-secondary">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-3">
            <Label>Data requirements</Label>
            <div className="mt-1">
              <ReasonList
                codes={entry.data_requirements}
                tone="unavailable"
                empty="No data requirement is recorded."
              />
            </div>
          </div>
        </PanelSection>
      </CardBody>
    </Card>
  );
}
