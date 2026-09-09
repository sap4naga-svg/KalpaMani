"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { PanelSection, ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import {
  GapEventRiskRecord,
  InitialPlannedRiskRecord,
  OpenPlannedRiskRecord,
  PermittedRiskRecord,
  RiskSeparationNote,
} from "@/components/cockpit/risk-records";
import { useScope } from "@/components/shell/use-scope";
import { useQualificationStatus, useRiskSnapshot } from "@/data/client/hooks";
import type { QualificationStatusPayload } from "@/contracts/read-models";
import { humanizeCode } from "@/lib/format";
import { withScope } from "@/lib/scope";

/**
 * Risk Dashboard — Area 12.
 *
 * **READ-ONLY, WITHOUT EXCEPTION.** This screen changes no threshold, trips no breaker,
 * reduces no exposure and computes no permitted exposure. There is no slider, no toggle and
 * no control of any kind on it, and there is no route behind one.
 *
 * TWO KINDS OF FACT SHARE THIS PAGE, AND EACH IS BADGED INDIVIDUALLY (§5).
 *
 *   THE RISK SNAPSHOT        SYNTHETIC. A demonstration book's recorded risk assessments
 *   THE RESEARCH PARAMETERS  REPOSITORY_TRACKED. The governed values of `CLAUDE.md` §6, read
 *                            from tracked authority at a recorded commit, **reproduced for
 *                            context, labelled as research parameters, and changed nowhere**
 *
 * **A RESEARCH PARAMETER IS NOT A PERMITTED LIMIT.** A permitted limit is a separately
 * governed policy value carried with its `PolicyRef`; no such policy version exists in this
 * project, so every permitted limit reports `POLICY_REFERENCE_MISSING`. **No headroom is
 * computed anywhere on this page**, because showing headroom is how an interface starts
 * implying that capital may be deployed.
 */
export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const risk = useRiskSnapshot(scope);
  const governance = useQualificationStatus(scope);

  return (
    <>
      <PageHeader
        title="Risk Dashboard"
        summary="The risk the book is carrying, the constraints that bound it, and the difference between a recorded assessment, a governed limit and a research parameter."
        pageState={risk.data?.completeness === "PARTIAL" ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 12</Badge>
          <Badge tone="neutral">Read-only — no control exists on this page</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadModelPanel
          title="Portfolio risk"
          description="The aggregate assessment, the concentration it carries and the volatility of the recorded equity path."
          envelope={risk.data}
          dependency="the risk engine — no risk engine exists"
          operator={operator}
          testId="risk-snapshot"
        >
          {(payload) => (
            <div className="space-y-4">
              <RiskSeparationNote />
              <div className="grid gap-4 lg:grid-cols-2">
                <PanelSection
                  title="Current open planned risk — portfolio aggregate"
                  note="Summed over open exposure only, once per position. An aggregate containing any stale or missing component is PARTIAL, and the components are named below."
                >
                  <OpenPlannedRiskRecord
                    wrapper={payload.open_planned_risk}
                    operator={operator}
                  />
                </PanelSection>
                <PanelSection
                  title="Gap and event risk — a separate model"
                  note="Modelled separately where it applies, and never added into either planned-risk figure."
                >
                  <GapEventRiskRecord
                    wrapper={
                      payload.gap_event_risk ?? {
                        availability: "NOT_APPLICABLE",
                        reason: "NOT_DEFINED_FOR_SUBJECT",
                      }
                    }
                  />
                </PanelSection>
              </div>

              <dl className="grid gap-3 border-t border-border-subtle pt-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="flex flex-col gap-0.5">
                  <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Concentration
                  </dt>
                  <dd>
                    <MetricText metric={payload.concentration} neutral />
                  </dd>
                </div>
                <div className="flex flex-col gap-0.5">
                  <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Portfolio volatility
                  </dt>
                  <dd>
                    <MetricText metric={payload.portfolio_volatility} neutral />
                  </dd>
                </div>
                <div className="flex flex-col gap-0.5">
                  <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Risk tier
                  </dt>
                  <dd className="text-label-m text-text-secondary">
                    {humanizeCode(payload.risk_tier.code)}
                  </dd>
                </div>
                <div className="flex flex-col gap-0.5">
                  <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Snapshot as of
                  </dt>
                  <dd className="font-mono text-label-m text-text-secondary">
                    {payload.as_of}
                  </dd>
                </div>
              </dl>

              <div className="grid gap-3 sm:grid-cols-2">
                <PanelSection
                  title="Circuit breaker"
                  note="A recorded state. This application trips no breaker and resets none."
                >
                  <Badge tone="neutral" data-breaker={payload.circuit_breaker_state.code}>
                    {humanizeCode(payload.circuit_breaker_state.code)}
                  </Badge>
                </PanelSection>
                <PanelSection
                  title="New entries"
                  note="A recorded state. Reducing and disabling new entries is automatic in the design; restoring them is not, and nothing here does either."
                >
                  <Badge tone="neutral" data-new-entry={payload.new_entry_state.code}>
                    {humanizeCode(payload.new_entry_state.code)}
                  </Badge>
                </PanelSection>
              </div>

              <PanelSection
                title="Permitted limits"
                note="A permitted value is a separately governed policy value and is never served under a default nobody approved."
              >
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {payload.permitted.map((entry) => (
                    <PermittedRiskRecord
                      key={entry.scope}
                      scope={entry.scope}
                      wrapper={entry.value}
                    />
                  ))}
                </div>
                <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                  <strong className="text-text-secondary">
                    No headroom is computed on this page.
                  </strong>{" "}
                  Showing a limit is not granting it, and subtracting a carried figure from a
                  limit would present an amount of capital as available to deploy. That is a
                  decision, and no interface takes it.
                </p>
              </PanelSection>

              <PanelSection
                title="Loss and drawdown thresholds"
                note="Named, and unapproved. A threshold carries its value with its governing policy reference, or it carries neither."
              >
                <ScrollRegion label="Loss and drawdown thresholds">
                  <table className="w-full min-w-[30rem] border-collapse text-label-m" data-testid="loss-thresholds">
                    <caption className="sr-only">
                      Each recorded loss or drawdown threshold, its value and the policy
                      reference that governs it.
                    </caption>
                    <thead>
                      <tr className="border-b border-border-subtle text-left text-text-tertiary">
                        <th scope="col" className="py-1.5 pr-4 font-medium">
                          Threshold
                        </th>
                        <th scope="col" className="py-1.5 pr-4 font-medium">
                          Value
                        </th>
                        <th scope="col" className="py-1.5 font-medium">
                          Policy
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {payload.loss_thresholds.map((threshold) => (
                        <tr
                          key={threshold.threshold.code}
                          className="border-b border-border-subtle last:border-0"
                          data-threshold={threshold.threshold.code}
                        >
                          <th
                            scope="row"
                            className="py-1.5 pr-4 text-left font-normal text-text-secondary"
                          >
                            {humanizeCode(threshold.threshold.code)}
                          </th>
                          <td className="py-1.5 pr-4">
                            <MetricText metric={threshold.value} neutral />
                          </td>
                          <td className="py-1.5 font-mono text-label-s text-text-tertiary">
                            {threshold.policy_ref === undefined
                              ? "no policy reference recorded"
                              : `${threshold.policy_ref.policy_id} · ${threshold.policy_ref.policy_version}`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollRegion>
              </PanelSection>

              <PanelSection
                title="Initial planned risk — every retained record on open exposure"
                note="Listed rather than summed away: each is an immutable entry-time record with its own reference price and its own recorded instant. A trade that added to its position retains one record per stage, and each is listed."
              >
                <div className="grid gap-3 lg:grid-cols-2">
                  {payload.initial_planned_risk_open.map((entry) => (
                    <div
                      key={`${entry.trade_ref.ref_id}-${entry.stage_ordinal ?? 0}`}
                      className="rounded-sm border border-border-subtle p-3"
                    >
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <ReferenceChip reference={entry.trade_ref} label={entry.trade_ref.ref_id} />
                        {entry.stage_ordinal !== undefined && (
                          <Badge tone="neutral">
                            {entry.stage_ordinal === 0 ? "Entry" : `Add ${entry.stage_ordinal}`}
                          </Badge>
                        )}
                      </div>
                      <InitialPlannedRiskRecord wrapper={entry.value} operator={operator} />
                    </div>
                  ))}
                </div>
              </PanelSection>

              <PanelSection
                title="Exposure and recorded decisions"
                note="The grouping axes this assessment was read against, and the risk decisions the book recorded."
              >
                <div className="flex flex-wrap gap-2">
                  {payload.exposure_refs.items.map((reference) => (
                    <ReferenceChip key={reference.ref_id} reference={reference} />
                  ))}
                </div>
                <ul className="mt-2 space-y-1">
                  {payload.decisions.map((decision) => (
                    <li
                      key={decision.decision_ref.ref_id}
                      className="flex flex-wrap items-baseline gap-2 text-label-s"
                    >
                      <span className="font-mono text-text-tertiary">
                        {decision.at.slice(0, 10)}
                      </span>
                      <span className="text-text-secondary">
                        {humanizeCode(decision.outcome.code)}
                      </span>
                      <ReferenceChip reference={decision.decision_ref} label="Risk decision" />
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-label-s text-text-tertiary">
                  <Link
                    href={withScope("/portfolio/positions", scope)}
                    className="text-accent underline underline-offset-2"
                  >
                    Positions &amp; Exposure
                  </Link>{" "}
                  holds the per-axis breakdown these references point at.
                </p>
              </PanelSection>
            </div>
          )}
        </ReadModelPanel>

        <ResearchParameters governance={governance.data} />
      </div>
    </>
  );
}

/**
 * The governed research values, as what they are.
 *
 * **They are REAL tracked facts and are badged as such**, on a page whose other panel is
 * synthetic — §5 requires a page carrying both kinds to badge each component individually
 * rather than choosing one badge for the page.
 *
 * **They are research parameters, not permitted limits and not performance expectations.**
 * `CLAUDE.md` §6 says so, this cycle changes none of them, and nothing on this page derives a
 * permission from one.
 */
function ResearchParameters({
  governance,
}: {
  governance: ReturnType<typeof useQualificationStatus>["data"];
}) {
  return (
    <Card data-testid="research-parameters">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label as="h2">Governed research parameters</Label>
          <p className="mt-0.5 max-w-3xl text-label-m leading-relaxed text-text-secondary">
            Read from tracked repository authority at a recorded commit.{" "}
            <strong className="text-text-primary">
              These are research parameters, not permitted limits and not performance
              expectations
            </strong>
            , and this application changes none of them.
          </p>
        </div>
        {governance?.payload !== undefined && (
          <ProvenanceBadge provenance={governance.provenance} />
        )}
      </CardHeader>
      <CardBody className="space-y-3">
        {governance === undefined ? (
          <>
            <div className="skeleton-shape h-24 w-full" data-testid="skeleton" />
            <span className="sr-only">Loading the governed research parameters</span>
          </>
        ) : governance.payload === undefined ? (
          <AvailabilityBadge
            state={governance.availability}
            reason={governance.availability_reason}
          />
        ) : (
          <ParameterTable payload={governance.payload} />
        )}
      </CardBody>
    </Card>
  );
}

function ParameterTable({ payload }: { payload: QualificationStatusPayload }) {
  return (
    <>
      <ScrollRegion label="Governed research parameters">
        <table className="w-full min-w-[36rem] border-collapse text-label-m" data-testid="parameter-table">
          <caption className="sr-only">
            Each governed research parameter, its value, the basis it is measured on and the
            tracked source it was read from.
          </caption>
          <thead className="bg-surface-sunken">
            <tr className="border-b border-border-subtle text-left text-text-tertiary">
              <th scope="col" className="px-3 py-2 font-medium">
                Parameter
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Value
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Basis
              </th>
              <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                Tracked source
              </th>
            </tr>
          </thead>
          <tbody>
            {payload.research_parameters.map((parameter, index) => (
              <tr
                key={`${parameter.parameter.code}-${parameter.value.unit}-${index}`}
                className="border-b border-border-subtle last:border-0"
                data-parameter={parameter.parameter.code}
              >
                <th
                  scope="row"
                  className="px-3 py-1.5 text-left font-normal text-text-secondary"
                >
                  {humanizeCode(parameter.parameter.code)}
                </th>
                <td className="px-3 py-1.5">
                  <MetricText metric={parameter.value} neutral />
                </td>
                <td className="px-3 py-1.5 text-text-tertiary">
                  {humanizeCode(parameter.basis.code)}
                </td>
                <td className="hidden px-3 py-1.5 font-mono text-label-s text-text-tertiary lg:table-cell">
                  {parameter.source.path} @ {parameter.source.commit.slice(0, 12)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        The maximum individual position is stated in tracked authority as a range of roughly
        8–10%. The row above carries the <strong>upper bound</strong> and says so in its basis,
        because a range rendered as one number without stating which end is a different claim.
      </p>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        Transcribed at commit{" "}
        <span className="font-mono text-text-secondary">
          {payload.read_at_commit.slice(0, 12)}
        </span>
        , from sources recording their state as of{" "}
        <span className="font-mono text-text-secondary">{payload.snapshot_extracted_on}</span>.
        These facts <strong>age</strong>: nothing in this application re-reads them, and a
        later cycle refreshes them under its own authorization.
      </p>
    </>
  );
}
