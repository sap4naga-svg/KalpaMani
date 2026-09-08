"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { FilterBar, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  MeasureList,
  ReadOnlyNotice,
  ReasonList,
  ReferenceListPanel,
  ReferenceRow,
} from "@/components/cockpit/research";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import type { StrategyHealth } from "@/contracts/strategy-models";
import type { StrategyHealthState } from "@/contracts/vocabularies";
import { useStrategyHealth } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import { withScope } from "@/lib/scope";

/**
 * Strategy Health — Area 5.
 *
 * "Show whether a strategy is behaving as researched, and what the system did about it."
 *
 *   ONLY THE SEVEN STATES RENDER          the closed ADR-0026 §13 vocabulary arrives IN THE
 *                                         RESPONSE, so this screen keeps no second copy of it
 *                                         and a state with no record renders as a verified
 *                                         zero rather than being omitted
 *   THE VIEW CAUSES NO TRANSITION         there is no control here that raises, lowers,
 *                                         suspends, retires, restores or acknowledges
 *                                         anything, and none exists in the application
 *   A DEGRADATION SHOWS ITS QUEUE ENTRY   and the link goes to the entry the degradation
 *                                         CREATED, not to a form that creates one
 *   HEALTH IS NOT LIFECYCLE, ENVIRONMENT  four axes, four panels, four labels. A `RESEARCH`
 *   OR AVAILABILITY                       environment says where a version runs; a
 *                                         `NOT_IMPLEMENTED` input says a producer is missing;
 *                                         neither is a health state
 */

const STATE_TONE: Readonly<
  Record<StrategyHealthState, React.ComponentProps<typeof Badge>["tone"]>
> = {
  HEALTHY: "positive",
  WATCH: "info",
  DEGRADED: "warning",
  NEW_ENTRIES_REDUCED: "warning",
  NEW_ENTRIES_DISABLED: "negative",
  SUSPENDED: "negative",
  RETIRED: "unavailable",
};

const STATE_MEANING: Readonly<Record<StrategyHealthState, string>> = {
  HEALTHY: "Behaving inside the researched band. No safety action is in force.",
  WATCH: "Under closer monitoring. No entry reduction has been applied.",
  DEGRADED: "Outside the researched band. A research queue entry has been created.",
  NEW_ENTRIES_REDUCED:
    "New entries reduced by a preapproved safety rule. Reduction is automatic; RESTORATION IS NOT.",
  NEW_ENTRIES_DISABLED:
    "New entries disabled by a preapproved safety rule. Restoring them requires human authority.",
  SUSPENDED: "A governed stop. Recovery past a governed suspension is NEVER automatic.",
  RETIRED: "Terminal for this version. A new version is required; retirement is not reversible.",
};

function HealthStateBadge({ state }: { state: StrategyHealthState }) {
  return (
    <Badge tone={STATE_TONE[state]} data-health-state={state} title={STATE_MEANING[state]}>
      <span aria-hidden="true">●</span>
      <span>{humanizeCode(state)}</span>
    </Badge>
  );
}

const FILTER_KEYS = ["state", "module"] as const;

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const health = useStrategyHealth(scope);
  const { filters, setFilter, clearFilter, clearAll } = usePageFilters(FILTER_KEYS);
  const [selected, setSelected] = React.useState<string | null>(null);

  const payload = health.data?.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);
  const states = payload?.health_states ?? [];

  const visible = items.filter(
    (entry) =>
      (filters.state === "" || entry.state === filters.state) &&
      (filters.module === "" || entry.strategy_module.code === filters.module),
  );
  const chosen = visible.find((entry) => entry.strategy_version === selected) ?? visible[0];
  const modules = [...new Set(items.map((entry) => entry.strategy_module.code))].sort();

  return (
    <>
      <PageHeader
        title="Strategy Health"
        summary="The recorded health state of every strategy version, its transition history, the drift and failure clusters behind it, and the research queue entry a degradation created."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 5</Badge>
          <Badge tone="unavailable">Strategy runtime: NOT IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="recorded health transitions"
          actions={["raise", "reduce", "disable", "suspend", "retire", "restore", "acknowledge"]}
        />

        <ReadModelPanel
          title="The seven health states"
          description="The closed ADR-0026 vocabulary, delivered in the response. A state with no record is a verified zero, not an omission."
          envelope={health.data}
          dependency="the strategy runtime and its health monitor — neither exists"
          testId="health-vocabulary"
        >
          {(loaded) => (
            <ul className="flex flex-wrap gap-2" data-testid="health-state-legend">
              {loaded.health_states.map((state) => {
                const population = loaded.items.filter((entry) => entry.state === state).length;
                return (
                  <li
                    key={state}
                    className="inline-flex items-center gap-2 rounded-sm border border-border-subtle bg-surface-sunken px-2 py-1"
                    data-legend-state={state}
                  >
                    <HealthStateBadge state={state} />
                    <span className="font-mono text-label-s text-text-secondary">
                      {population}
                    </span>
                    <span className="text-label-s text-text-tertiary">
                      {population === 1 ? "version" : "versions"}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded health by version"
          description="One row per exact strategy version, with the safety action taken and the human action required stated separately."
          envelope={health.data}
          dependency="the strategy runtime — no strategy module exists and none has ever run"
          operator={operator}
          testId="health-table"
          always={
            <FilterBar
              chips={[
                ...(filters.state === ""
                  ? []
                  : [{ key: "state", label: "State", value: filters.state }]),
                ...(filters.module === ""
                  ? []
                  : [{ key: "module", label: "Module", value: filters.module }]),
              ]}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
              basis="Health states are recorded facts; filtering narrows what is shown and changes no record."
            >
              <SelectField
                id="health-state"
                label="Health state"
                value={filters.state}
                options={states.map((state) => ({ value: state, label: humanizeCode(state) }))}
                onChange={(next) => setFilter("state", next)}
              />
              <SelectField
                id="health-module"
                label="Module"
                value={filters.module}
                options={modules.map((code) => ({ value: code, label: humanizeCode(code) }))}
                onChange={(next) => setFilter("module", next)}
              />
            </FilterBar>
          }
        >
          {() => (
            <ScrollRegion label="Recorded strategy health by version">
              <table
                className="w-full min-w-[52rem] border-collapse text-label-m"
                data-testid="health-rows"
              >
                <caption className="sr-only">
                  Every strategy version with its recorded health state, when it entered that
                  state, the safety action taken, the human action required and its observation
                  count against the declared minimum.
                </caption>
                <thead className="bg-surface-sunken">
                  <tr className="border-b border-border-subtle text-left text-text-tertiary">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Module and version
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Health state
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Since
                    </th>
                    <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                      Safety action taken
                    </th>
                    <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                      Human action required
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Observations
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
                        No version matches this filter. Every recorded version is still part of
                        the population the legend above counts.
                      </td>
                    </tr>
                  )}
                  {visible.map((entry) => (
                    <tr
                      key={entry.strategy_version}
                      className="border-b border-border-subtle last:border-0"
                      data-health-version={entry.strategy_version}
                    >
                      <th
                        scope="row"
                        className="px-3 py-1.5 text-left font-normal text-text-secondary"
                      >
                        <span className="flex flex-col">
                          <span>{humanizeCode(entry.strategy_module.code)}</span>
                          <span className="font-mono text-label-s text-text-tertiary">
                            {entry.strategy_version}
                          </span>
                        </span>
                      </th>
                      <td className="px-3 py-1.5">
                        <HealthStateBadge state={entry.state} />
                      </td>
                      <td className="px-3 py-1.5 font-mono text-label-s text-text-tertiary">
                        {entry.since}
                      </td>
                      <td className="hidden px-3 py-1.5 text-text-secondary lg:table-cell">
                        {humanizeCode(entry.safety_action.code)}
                      </td>
                      <td className="hidden px-3 py-1.5 text-text-secondary lg:table-cell">
                        {humanizeCode(entry.human_action_required.code)}
                      </td>
                      <td className="px-3 py-1.5">
                        <span className="flex flex-col gap-0.5">
                          <MetricText metric={entry.observation_count} neutral />
                          {!entry.minimum_observations_met && (
                            <span className="text-label-s text-unavailable">
                              below the declared minimum of{" "}
                              <MetricText metric={entry.minimum_observations} neutral />
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="px-3 py-1.5">
                        <Button
                          size="sm"
                          variant={
                            entry.strategy_version === chosen?.strategy_version
                              ? "primary"
                              : "subtle"
                          }
                          aria-pressed={entry.strategy_version === chosen?.strategy_version}
                          onClick={() => setSelected(entry.strategy_version)}
                        >
                          History
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          )}
        </ReadModelPanel>

        {chosen !== undefined && (
          <HealthDetail entry={chosen} operator={operator} scope={scope} />
        )}
      </div>
    </>
  );
}

function HealthDetail({
  entry,
  operator,
  scope,
}: {
  entry: StrategyHealth;
  operator: boolean;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  return (
    <Card data-testid="health-detail" data-health-version={entry.strategy_version}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{humanizeCode(entry.strategy_module.code)}</Label>
          <p className="mt-0.5 font-mono text-label-m text-text-secondary">
            {entry.strategy_version}
          </p>
        </div>
        <HealthStateBadge state={entry.state} />
      </CardHeader>
      <CardBody className="space-y-4">
        <PanelSection
          title="Transition history"
          note="Every transition records the rule that fired, whose authority it carried and the inputs the rule read. Nothing on this screen causes one."
          testId="health-transitions"
        >
          {entry.transitions.length === 0 ? (
            <p className="text-label-m text-text-tertiary">
              No transition has been recorded for this version. It has held its current state
              since <span className="font-mono">{entry.since}</span>, and an absence of
              transitions is not an absence of monitoring.
            </p>
          ) : (
            <ol className="space-y-2" data-testid="transition-list">
              {entry.transitions.map((transition) => (
                <li
                  key={`${transition.at}-${transition.to}`}
                  className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
                  data-transition-to={transition.to}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <HealthStateBadge state={transition.from} />
                    <span aria-hidden="true" className="text-text-tertiary">
                      →
                    </span>
                    <HealthStateBadge state={transition.to} />
                    <span className="font-mono text-label-s text-text-tertiary">
                      {transition.at}
                    </span>
                  </div>
                  <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                    <div>
                      <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                        Rule
                      </dt>
                      <dd className="text-label-m text-text-secondary">
                        {humanizeCode(transition.rule.code)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                        Authority
                      </dt>
                      <dd className="text-label-m text-text-secondary">
                        {humanizeCode(transition.authority.code)}
                      </dd>
                    </div>
                  </dl>
                  <div className="mt-2">
                    <ReferenceListPanel
                      list={transition.input_refs}
                      label="Inputs the rule read"
                      scope={scope}
                      empty="This transition records no contributing input reference."
                    />
                  </div>
                </li>
              ))}
            </ol>
          )}
        </PanelSection>

        <PanelSection
          title="The research queue entry this degradation created"
          note="A degradation creates a research queue entry. It does NOT mutate a strategy parameter, and nothing here creates, prioritizes or advances one."
          testId="health-queue-link"
        >
          {entry.queue_item_ref === undefined ? (
            <p className="text-label-m text-text-tertiary">
              No research queue entry is recorded against this version. Its state is not a
              recorded degradation, so none was created — an absence, and not a missing link.
            </p>
          ) : (
            /*
             * ONE CONTROL, AND IT IS THE REFERENCE'S OWN.
             *
             * The reference already carries an allowlisted target destination into the queue
             * (§4.3.1, R10). A second hand-written link beside it would be two controls to one
             * destination, and the second one would not be the allowlist's.
             */
            <ReferenceRow
              reference={entry.queue_item_ref}
              label="Research queue entry"
              scope={scope}
              testId="health-queue-reference"
            />
          )}
        </PanelSection>

        <PanelSection
          title="Recovery"
          note="Reducing and disabling new entries is automatic. RESTORING them is not, and recovery past a governed suspension is never automatic."
          testId="health-recovery"
        >
          <div className="space-y-2">
            <div>
              <Label>Recorded recovery authority</Label>
              <p className="mt-0.5 text-label-m text-text-secondary">
                {humanizeCode(entry.recovery_authority.code)}
              </p>
            </div>
            <div>
              <Label>Recorded recovery requirements</Label>
              <div className="mt-1">
                <ReasonList
                  codes={entry.recovery_requirements}
                  tone="unavailable"
                  empty="No recovery requirement is recorded, because no recovery is required."
                  testId="recovery-requirements"
                />
              </div>
            </div>
            <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
              <strong className="text-text-secondary">
                Displaying a requirement is not satisfying one.
              </strong>{" "}
              This screen offers no way to restore an entry, request a restoration or record
              that a requirement was met.
            </p>
          </div>
        </PanelSection>

        <PanelSection
          title="Drift"
          note="Recorded drift measures. A version below its declared minimum observations reports its rule rather than a number."
          testId="health-drift"
        >
          <MeasureList
            entries={entry.drift.map((measure) => ({
              label: measure.measure.code,
              value: measure.value,
            }))}
            operator={operator}
          />
        </PanelSection>

        <PanelSection
          title="Failure clusters"
          note="Losses sharing a CAUSE rather than a period. A month of losses is not a cluster."
          testId="health-clusters"
        >
          {entry.failure_clusters.length === 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              <span className="text-label-m text-text-tertiary">
                No failure cluster is recorded for this version, and that is the correct answer
                rather than an absence of analysis.
              </span>
            </div>
          ) : (
            <ul className="space-y-2">
              {entry.failure_clusters.map((cluster) => (
                <li
                  key={cluster.cluster.code}
                  className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
                  data-cluster={cluster.cluster.code}
                >
                  <div className="flex flex-wrap items-baseline gap-2">
                    <strong className="text-label-m text-text-primary">
                      {humanizeCode(cluster.cluster.code)}
                    </strong>
                    <MetricText metric={cluster.count} neutral />
                    <span className="text-label-s text-text-tertiary">losses</span>
                  </div>
                  <div className="mt-2">
                    <ReferenceListPanel
                      list={cluster.evidence_refs}
                      label="Cluster evidence"
                      scope={scope}
                      empty="This cluster records no evidence reference."
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </PanelSection>

        <PanelSection
          title="Health inputs"
          note="The ADR-0026 §13 inputs, each with its own availability. An input whose producer does not exist says so rather than reporting a zero."
          testId="health-inputs"
        >
          <MeasureList
            entries={entry.health_inputs.map((input) => ({
              label: input.input.code,
              value: input.value,
            }))}
            operator={operator}
            columns={4}
          />
        </PanelSection>

        <PanelSection
          title="Health is not lifecycle, environment or availability"
          note="Four axes that are never one axis."
          testId="health-axes"
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-sm border border-border-subtle p-3">
              <Label>Health</Label>
              <div className="mt-1">
                <HealthStateBadge state={entry.state} />
              </div>
              <p className="mt-1 text-label-s text-text-tertiary">
                How the version is behaving against its research.
              </p>
            </div>
            <div className="rounded-sm border border-border-subtle p-3">
              <Label>Lifecycle and maturity</Label>
              <p className="mt-1 text-label-m">
                <Link
                  href={withScope("/strategy/versions", scope)}
                  className="text-accent underline underline-offset-2"
                >
                  Strategy Version Registry →
                </Link>
              </p>
              <p className="mt-1 text-label-s text-text-tertiary">
                Where the version sits on the ladder.{" "}
                <strong>Watch, suspended and retired are statuses, not maturity stages.</strong>
              </p>
            </div>
            <div className="rounded-sm border border-border-subtle p-3">
              <Label>Runtime environment</Label>
              <p className="mt-1 font-mono text-label-m text-text-secondary">
                {scope.environment}
              </p>
              <p className="mt-1 text-label-s text-text-tertiary">
                Where it runs. It says nothing about how it is behaving.
              </p>
            </div>
            <div className="rounded-sm border border-border-subtle p-3">
              <Label>Data availability</Label>
              <div className="mt-1">
                <AvailabilityBadge state="NOT_IMPLEMENTED" reason="PRODUCER_NOT_IMPLEMENTED" />
              </div>
              <p className="mt-1 text-label-s text-text-tertiary">
                Whether a producer exists. A version with no recorded health is not a healthy
                one.
              </p>
            </div>
          </div>
        </PanelSection>
      </CardBody>
    </Card>
  );
}
