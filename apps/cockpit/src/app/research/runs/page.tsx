"use client";

import * as React from "react";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { FilterBar, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  ComparisonChart,
  EvaluationClassBadge,
  ExposureDisclosure,
  MeasureList,
  ReadOnlyNotice,
  ReasonList,
  ReferenceRow,
  SectionState,
} from "@/components/cockpit/research";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import type { ResearchRun, ResearchRunState } from "@/contracts/research-models";
import { isValueBearing } from "@/contracts/validity";
import { useResearchRuns } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";

/**
 * Research and Backtesting — Area 14.
 *
 * "Make research runs findable, comparable and reproducible."
 *
 *   A NAMED BASELINE COMES FIRST      a run whose baseline did not resolve renders INCOMPLETE
 *                                     and its comparison carries the state, never a zero
 *                                     difference
 *   EVERY TERMINAL RUN IS SHOWN       failed and abandoned runs are rows like any other, and
 *                                     each states that it still spent a trial
 *   THE TRIAL COUNT IS READ           the ordinal comes from the record. Nothing here counts
 *                                     rows and calls the answer a trial count
 *   NO RUN, RETRY, LAUNCH OR SCHEDULE no such control exists on this screen or anywhere in
 *                                     this application. **Backtesting has not started**
 */

const STATE_TONE: Readonly<Record<ResearchRunState, React.ComponentProps<typeof Badge>["tone"]>> = {
  PLANNED: "neutral",
  RUNNING: "info",
  COMPLETED: "positive",
  FAILED: "negative",
  ABANDONED: "warning",
};

const FILTER_KEYS = ["state", "class"] as const;

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const runs = useResearchRuns(scope);
  const { filters, setFilter, clearFilter, clearAll } = usePageFilters(FILTER_KEYS);
  const [selected, setSelected] = React.useState<string | null>(null);

  const payload = runs.data?.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);
  const visible = items.filter(
    (entry) =>
      (filters.state === "" || entry.state === filters.state) &&
      (filters.class === "" || entry.evaluation_class === filters.class),
  );
  const chosen = visible.find((entry) => entry.run_id === selected) ?? visible[0];

  const counting = items.filter((entry) => entry.counts_against_budget).length;
  const incomplete = items.filter(
    (entry) => !isValueBearing(entry.baseline_state.availability),
  ).length;

  return (
    <>
      <PageHeader
        title="Research & Backtesting"
        summary="The run registry: every authorized run with its registration, its named baseline, its declared evaluation class, its manifest pins and the trial it spent."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 14</Badge>
          <Badge tone="unavailable">Backtesting: NOT STARTED</Badge>
          <Badge tone="unavailable">G1 provider selection: OPEN</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="an immutable run registry"
          actions={["run", "retry", "launch", "schedule", "abandon"]}
        />

        <ReadModelPanel
          title="Run registry"
          description="Every recorded run, including the ones that failed and the ones that were abandoned. A terminal run spends a trial whether or not it produced a result."
          envelope={runs.data}
          dependency="the research runner and a qualified point-in-time provider — neither exists"
          operator={operator}
          testId="run-table"
          always={
            <FilterBar
              chips={[
                ...(filters.state === ""
                  ? []
                  : [{ key: "state", label: "State", value: filters.state }]),
                ...(filters.class === ""
                  ? []
                  : [{ key: "class", label: "Evaluation class", value: filters.class }]),
              ]}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
              basis="Filtering narrows the rows shown. The trial count below is read from the records and is not recomputed from what survives a filter."
            >
              <SelectField
                id="run-state"
                label="Run state"
                value={filters.state}
                options={(payload?.run_states ?? []).map((state) => ({
                  value: state,
                  label: humanizeCode(state),
                }))}
                onChange={(next) => setFilter("state", next)}
              />
              <SelectField
                id="run-class"
                label="Evaluation class"
                value={filters.class}
                options={(payload?.evaluation_classes ?? []).map((entry) => ({
                  value: entry,
                  label: humanizeCode(entry),
                }))}
                onChange={(next) => setFilter("class", next)}
              />
            </FilterBar>
          }
        >
          {(loaded) => (
            <div className="space-y-3">
              <ScrollRegion label="Research runs">
                <table
                  className="w-full min-w-[56rem] border-collapse text-label-m"
                  data-testid="run-rows"
                >
                  <caption className="sr-only">
                    Every recorded research run with its state, declared evaluation class, trial
                    ordinal, whether it counts against the trial budget and whether its named
                    baseline resolved.
                  </caption>
                  <thead className="bg-surface-sunken">
                    <tr className="border-b border-border-subtle text-left text-text-tertiary">
                      <th scope="col" className="px-3 py-2 font-medium">
                        Run
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        State
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Evaluation class
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Named baseline
                      </th>
                      <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                        Trial ordinal
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Spends a trial
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Detail
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-3 py-6 text-text-tertiary">
                          No run matches this filter. Every recorded run is still part of the
                          population the trial count is read against.
                        </td>
                      </tr>
                    )}
                    {visible.map((entry) => {
                      const resolved = isValueBearing(entry.baseline_state.availability);
                      return (
                        <tr
                          key={entry.run_id}
                          className="border-b border-border-subtle last:border-0"
                          data-run={entry.run_id}
                          data-run-state={entry.state}
                        >
                          <th
                            scope="row"
                            className="px-3 py-1.5 text-left font-normal text-text-secondary"
                          >
                            <span className="flex flex-col">
                              <span className="font-mono">{entry.run_id}</span>
                              <span className="font-mono text-label-s text-text-tertiary">
                                {entry.challenger_version}
                              </span>
                            </span>
                          </th>
                          <td className="px-3 py-1.5">
                            <Badge tone={STATE_TONE[entry.state]} data-state={entry.state}>
                              {humanizeCode(entry.state)}
                            </Badge>
                          </td>
                          <td className="px-3 py-1.5">
                            <EvaluationClassBadge evaluationClass={entry.evaluation_class} />
                          </td>
                          <td className="px-3 py-1.5">
                            {resolved ? (
                              <span className="font-mono text-label-s text-text-secondary">
                                {entry.baseline_ref.ref_id}
                              </span>
                            ) : (
                              <span
                                className="flex flex-col gap-1"
                                data-testid="run-baseline-unresolved"
                              >
                                <AvailabilityBadge
                                  state={entry.baseline_state.availability}
                                  reason={entry.baseline_state.reason}
                                />
                                <span className="text-label-s text-unavailable">
                                  incomplete — no complete comparison is possible
                                </span>
                              </span>
                            )}
                          </td>
                          <td className="hidden px-3 py-1.5 lg:table-cell">
                            <MetricText metric={entry.trial_ordinal} neutral />
                          </td>
                          <td className="px-3 py-1.5">
                            <Badge
                              tone={entry.counts_against_budget ? "warning" : "neutral"}
                              data-counts={String(entry.counts_against_budget)}
                            >
                              {entry.counts_against_budget ? "Yes" : "No"}
                            </Badge>
                          </td>
                          <td className="px-3 py-1.5">
                            <Button
                              size="sm"
                              variant={entry.run_id === chosen?.run_id ? "primary" : "subtle"}
                              aria-pressed={entry.run_id === chosen?.run_id}
                              onClick={() => setSelected(entry.run_id)}
                            >
                              Manifest
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </ScrollRegion>
              <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                <strong className="text-text-secondary">
                  {counting} of {loaded.items.length} recorded runs spend a trial.
                </strong>{" "}
                Failed and abandoned runs count; a deterministic reproduction does not, because
                it confirms reproducibility and tests no new hypothesis.{" "}
                {incomplete > 0 && (
                  <>
                    <strong className="text-text-secondary">
                      {incomplete} run{incomplete === 1 ? "" : "s"} named a baseline that did not
                      resolve
                    </strong>{" "}
                    and render incomplete rather than as a result.
                  </>
                )}
              </p>
            </div>
          )}
        </ReadModelPanel>

        {chosen !== undefined && <RunDetail run={chosen} operator={operator} scope={scope} />}
      </div>
    </>
  );
}

function RunDetail({
  run,
  operator,
  scope,
}: {
  run: ResearchRun;
  operator: boolean;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  const baselineResolved = isValueBearing(run.baseline_state.availability);
  const axes = [...new Set(run.decomposition.map((entry) => entry.axis.code))];
  const [axis, setAxis] = React.useState<string | null>(null);
  const activeAxis = axes.includes(axis ?? "") ? (axis as string) : axes[0];

  return (
    <Card data-testid="run-detail" data-run={run.run_id}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>Run</Label>
          <p className="mt-0.5 font-mono text-label-m text-text-secondary">{run.run_id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATE_TONE[run.state]}>{humanizeCode(run.state)}</Badge>
          <EvaluationClassBadge evaluationClass={run.evaluation_class} />
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        <PanelSection
          title="Registration, Challenger and locked set"
          note="A run is only meaningful against the registration that preregistered it and the locked set it touched."
          testId="run-identity"
        >
          <div className="space-y-1.5">
            <ReferenceRow reference={run.registration_ref} label="Registration" scope={scope} />
            <p className="text-label-m text-text-secondary">
              Challenger:{" "}
              <span className="font-mono">{run.challenger_version}</span>
            </p>
            <ReferenceRow reference={run.dataset_ref} label="Locked set" scope={scope} />
            <div className="flex flex-wrap items-center gap-2">
              <ReferenceRow reference={run.baseline_ref} label="Named baseline" scope={scope} />
              {!baselineResolved && (
                <AvailabilityBadge
                  state={run.baseline_state.availability}
                  reason={run.baseline_state.reason}
                />
              )}
            </div>
          </div>
        </PanelSection>

        <PanelSection
          title="Baseline comparison"
          note="A named baseline comes first. A run that could not resolve one has not been shown to add anything."
          testId="run-baseline-comparison"
        >
          {baselineResolved ? (
            <MeasureList
              entries={run.baseline_comparison.map((entry) => ({
                label: entry.measure.code,
                value: entry.value,
              }))}
              operator={operator}
            />
          ) : (
            <div className="space-y-2">
              <SectionState
                availability={run.baseline_state.availability}
                reason={run.baseline_state.reason}
                note="The record names a baseline and the registry holds no such version, so no comparison figure exists. Every measure below carries that state rather than a zero difference."
                testId="run-baseline-incomplete"
              />
              <MeasureList
                entries={run.baseline_comparison.map((entry) => ({
                  label: entry.measure.code,
                  value: entry.value,
                }))}
                operator={operator}
              />
            </div>
          )}
        </PanelSection>

        <PanelSection
          title="Recorded results"
          note="A synthetic illustration of the shape a recorded result arrives in. It is not a backtest, and no alpha is claimed."
          testId="run-results"
        >
          <ComparisonChart
            caption={`Recorded results for ${run.run_id}`}
            rows={run.results.map((entry) => ({
              label: entry.measure.code,
              value: entry.value,
            }))}
            unitLabel="their own declared units"
            testId="run-result-chart"
          />
        </PanelSection>

        {run.decomposition.length > 0 && activeAxis !== undefined && (
          <PanelSection
            title="Decomposition"
            note="Expectancy by regime, sector and factor bucket, as recorded on the run."
            testId="run-decomposition"
          >
            <div role="group" aria-label="Decomposition axis" className="mb-2 flex flex-wrap gap-1">
              {axes.map((candidate) => (
                <Button
                  key={candidate}
                  size="sm"
                  variant={candidate === activeAxis ? "primary" : "subtle"}
                  aria-pressed={candidate === activeAxis}
                  onClick={() => setAxis(candidate)}
                >
                  {humanizeCode(candidate)}
                </Button>
              ))}
            </div>
            <ComparisonChart
              caption={`${humanizeCode(activeAxis)} decomposition for ${run.run_id}`}
              rows={run.decomposition
                .filter((entry) => entry.axis.code === activeAxis)
                .map((entry) => ({ label: entry.bucket.code, value: entry.value }))}
              unitLabel="R"
              testId="run-decomposition-chart"
            />
          </PanelSection>
        )}

        <PanelSection
          title="Stress and capacity"
          note="Modelled scenario impacts, and the capacity figure that needs a provider nobody has selected."
          testId="run-stress"
        >
          <div className="space-y-3">
            {run.stress.length === 0 ? (
              <SectionState
                availability="NOT_YET_AVAILABLE"
                reason="UPSTREAM_INPUT_MISSING"
                note="This run produced no stress result, because it did not complete."
              />
            ) : (
              <MeasureList
                entries={run.stress.map((entry) => ({
                  label: entry.scenario.code,
                  value: entry.value,
                }))}
                operator={operator}
              />
            )}
            <MeasureList
              entries={[{ label: "CAPACITY", value: run.capacity }]}
              operator={operator}
              columns={2}
            />
          </div>
        </PanelSection>

        <PanelSection
          title="Reproducibility"
          note="Manifest, profile, revision view, code and configuration identity, seeds and environment — enough to reproduce the run without a network."
          testId="run-reproducibility"
        >
          <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {(
              [
                ["Manifest", run.reproducibility.manifest],
                ["Information profile", humanizeCode(run.reproducibility.profile.code)],
                ["Revision view", run.reproducibility.revision_view],
                ["Code identity", run.reproducibility.code_identity],
                ["Configuration identity", run.reproducibility.config_identity],
                ["Seeds", run.reproducibility.seeds.join(", ")],
                ["Environment", run.reproducibility.environment],
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
          <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            <strong className="text-text-secondary">
              Provider-derived price data never renders as public point-in-time.
            </strong>{" "}
            The profile is declared rather than inferred, <strong>no provider is
            selected</strong>, and G1 is open — so this screen names no vendor at all.
          </p>
        </PanelSection>

        <PanelSection title="Exposure and limitations" testId="run-exposure">
          <div className="space-y-3">
            <ExposureDisclosure disclosure={run.exposure_disclosure} />
            <div>
              <Label>What this run does not establish</Label>
              <div className="mt-1">
                <ReasonList
                  codes={run.limitations}
                  tone="unavailable"
                  empty="No limitation is recorded on this run."
                />
              </div>
            </div>
            <div>
              <Label>Why the run ended in this state</Label>
              <p className="mt-0.5 text-label-m text-text-secondary">
                {humanizeCode(run.state_reason.code)}
              </p>
            </div>
            {operator && (
              <div className="grid gap-2 sm:grid-cols-2">
                <div>
                  <Label>Started</Label>
                  <div className="mt-0.5">
                    <MetricText metric={run.started_at} neutral operator />
                  </div>
                </div>
                <div>
                  <Label>Completed</Label>
                  <div className="mt-0.5">
                    <MetricText metric={run.completed_at} neutral operator />
                  </div>
                </div>
              </div>
            )}
          </div>
        </PanelSection>
      </CardBody>
    </Card>
  );
}
