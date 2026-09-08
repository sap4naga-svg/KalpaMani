"use client";

import * as React from "react";

import { Badge, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  ComparisonChart,
  ReadOnlyNotice,
  ReasonList,
  ReferenceListPanel,
  ReferenceRow,
  SectionState,
} from "@/components/cockpit/research";
import { useScope } from "@/components/shell/use-scope";
import type { AiContribution } from "@/contracts/research-models";
import { useAiContribution } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";

/**
 * AI Contribution Analytics — Area 21.
 *
 * "Measure what AI actually contributed, without inventing a causal claim."
 *
 *   MATCHED COMPARISONS AND STATED UNCERTAINTY   an unmatched arm set reports no difference at
 *                                                all, because the difference would measure the
 *                                                populations rather than the arms
 *   A SMALL POPULATION REPORTS ITS RULE          `INSUFFICIENT_OBSERVATIONS`, with the count
 *                                                and the minimum, and NO ratio
 *   NO CAUSAL ALPHA CLAIM                        a descriptive difference between two arms is
 *                                                not attribution, and the field states which
 *                                                gate owns the question
 *   EXPERIMENT E HAS NOT BEEN RUN                no AI agent exists, no model is called by this
 *                                                screen, and every figure is a recorded fixture
 */

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const contribution = useAiContribution(scope);
  const payload = contribution.data?.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);

  return (
    <>
      <PageHeader
        title="AI Contribution Analytics"
        summary="Matched-arm comparisons with their populations, their stated uncertainty, their provenance and the outages that shortened them."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 21</Badge>
          <Badge tone="unavailable">AI agents: NOT IMPLEMENTED</Badge>
          <Badge tone="unavailable">Experiment E: NOT RUN</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="recorded matched-arm comparisons"
          actions={["run an experiment", "call a model", "assign an arm", "publish a finding"]}
        />

        <Card data-testid="ai-boundary">
          <CardBody className="space-y-2 pt-4">
            <Label>What AI may and may not do</Label>
            <p className="max-w-3xl text-label-m leading-relaxed text-text-secondary">
              <strong>AI may REMOVE a candidate. It may never RESTORE one.</strong> A
              deterministic failure cannot be rescued by an AI opinion, and AI receives no
              money and no order authority anywhere in this system.
            </p>
            <p className="max-w-3xl text-label-m leading-relaxed text-text-secondary">
              <strong>This view is measurement, not justification.</strong> Experiment E of the
              Brain specification has not been run; no Research Agent and no Challenger Agent
              exists; and <strong>no model is invoked by this screen</strong>.
            </p>
          </CardBody>
        </Card>

        <ReadModelPanel
          title="Matched-arm comparisons"
          description="Deterministic-only against structured evidence against structured evidence plus LLM interpretation, over one shortlist and one window."
          envelope={contribution.data}
          dependency="the AI Research and Challenger agents — neither exists, and experiment E has not been run"
          operator={operator}
          testId="ai-comparisons"
        >
          {() => (
            <div className="space-y-4">
              {items.map((entry, index) => (
                <ContributionCard
                  key={`${entry.experiment.code}-${index}`}
                  entry={entry}
                  scope={scope}
                  operator={operator}
                />
              ))}
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

function ContributionCard({
  entry,
  scope,
  operator,
}: {
  entry: AiContribution;
  scope: ReturnType<typeof useScope>["scope"];
  operator: boolean;
}) {
  const reportable = entry.matched && entry.minimum_observations_met;
  const smallest = entry.arms.reduce<number | null>((lowest, arm) => {
    const value = typeof arm.population.value === "number" ? arm.population.value : null;
    if (value === null) return lowest;
    return lowest === null ? value : Math.min(lowest, value);
  }, null);

  return (
    <Card
      className="border-border-subtle"
      data-testid="ai-comparison"
      data-experiment={entry.experiment.code}
      data-matched={String(entry.matched)}
      data-minimum-met={String(entry.minimum_observations_met)}
    >
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{humanizeCode(entry.experiment.code)}</Label>
          <p className="mt-0.5 text-label-s text-text-tertiary">
            Matched on {humanizeCode(entry.matching_basis.code)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={entry.matched ? "info" : "warning"}>
            {entry.matched ? "Matched arms" : "Unmatched arms"}
          </Badge>
          {!entry.minimum_observations_met && (
            <AvailabilityBadge
              state="INSUFFICIENT_OBSERVATIONS"
              reason="BELOW_MINIMUM_OBSERVATIONS"
            />
          )}
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        {!reportable && (
          <SectionState
            availability={
              entry.minimum_observations_met ? "NOT_APPLICABLE" : "INSUFFICIENT_OBSERVATIONS"
            }
            reason={
              entry.minimum_observations_met
                ? "NOT_DEFINED_FOR_SUBJECT"
                : "BELOW_MINIMUM_OBSERVATIONS"
            }
            note={
              entry.minimum_observations_met
                ? "The arms were drawn from different populations, so a difference between them would measure the populations rather than the arms. No outcome is reported."
                : `The smallest matched arm holds ${smallest ?? "an unknown number of"} observations against a declared minimum of ${
                    typeof entry.minimum_observations.value === "number"
                      ? entry.minimum_observations.value
                      : "an unrecorded figure"
                  }. The rule is reported, and no ratio is.`
            }
            testId="ai-not-reportable"
          />
        )}

        <PanelSection
          title="Arms"
          note="Each arm carries its own population and, where one may be reported, its outcome with the half-width of its stated interval in the same unit."
          testId="ai-arms"
        >
          <ComparisonChart
            caption={`Arm outcomes for ${humanizeCode(entry.experiment.code)}`}
            rows={entry.arms.map((arm) => ({
              label: arm.arm.code,
              value: arm.outcome,
              uncertainty: arm.uncertainty,
              context: arm.population,
            }))}
            unitLabel="R"
            contextLabel="Matched population"
            testId="ai-arm-chart"
          />
        </PanelSection>

        <PanelSection
          title="What this comparison does not claim"
          note="A descriptive difference is not an attribution."
          testId="ai-causal"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Label>Causal attribution</Label>
            <AvailabilityBadge
              state={entry.causal_attribution.availability}
              reason={entry.causal_attribution.reason}
            />
            <span className="max-w-2xl text-label-s text-text-tertiary">
              Owned by{" "}
              <strong className="text-text-secondary">
                {humanizeCode(entry.causal_attribution.gate.code)}
              </strong>
              . <strong>No causal alpha claim is made here</strong>, and none is derivable from
              these figures.
            </span>
          </div>
          <div className="mt-2">
            <Label>Stated assumptions</Label>
            <div className="mt-1">
              <ReasonList
                codes={entry.assumptions}
                tone="warning"
                empty="No assumption is recorded on this comparison."
              />
            </div>
          </div>
        </PanelSection>

        <PanelSection
          title="Provenance"
          note="Every AI output carries its model version, its prompt version and timestamped source provenance."
          testId="ai-provenance"
        >
          <dl className="grid gap-2 sm:grid-cols-2">
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Model version
              </dt>
              <dd className="font-mono text-label-m text-text-secondary">
                {entry.ai_provenance.model_version}
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Prompt version
              </dt>
              <dd className="font-mono text-label-m text-text-secondary">
                {entry.ai_provenance.prompt_version}
              </dd>
            </div>
          </dl>
          <div className="mt-2 grid gap-3 lg:grid-cols-2">
            <ReferenceListPanel
              list={entry.ai_provenance.source_refs}
              label="Source provenance"
              scope={scope}
              empty="This comparison records no source reference, so nothing supports its arm assignment."
            />
            <div>
              <ReferenceRow reference={entry.experiment_ref} label="Experiment" scope={scope} />
            </div>
          </div>
        </PanelSection>

        <PanelSection
          title="Outages and coverage"
          note="An AI outage shortens a window. The handling is recorded rather than inferred, and coverage is stated."
          testId="ai-outages"
        >
          {entry.outages.length === 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              <span className="text-label-m text-text-tertiary">
                No outage is recorded over this window.
              </span>
            </div>
          ) : (
            <ul className="space-y-1">
              {entry.outages.map((outage) => (
                <li
                  key={`${outage.from}-${outage.to}`}
                  className="flex flex-wrap items-center gap-2 rounded-sm border border-border-subtle p-2"
                  data-outage={outage.handling.code}
                >
                  <span className="font-mono text-label-s text-text-tertiary">
                    {outage.from} → {outage.to}
                  </span>
                  <span className="text-label-s text-text-secondary">
                    {humanizeCode(outage.handling.code)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-label-s text-text-tertiary">
            {humanizeCode(entry.coverage_note.code)}
          </p>
          {operator && (
            <p className="mt-1 font-mono text-label-s text-text-tertiary">
              minimum_observations=
              <MetricText metric={entry.minimum_observations} neutral />
            </p>
          )}
        </PanelSection>
      </CardBody>
    </Card>
  );
}
