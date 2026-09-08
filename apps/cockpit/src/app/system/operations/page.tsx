"use client";

import * as React from "react";

import { Badge, Label } from "@/components/ui/primitives";
import { DataTable, RowCount, columnsFor, type TableColumns } from "@/components/cockpit/data-table";
import { FilterBar, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import { ReferenceListPanel, SectionState } from "@/components/cockpit/research";
import {
  AbsentControls,
  Fact,
  FactGrid,
  HistoricalFact,
  OperationsReadOnlyNotice,
  SeverityBadge,
  StateBadge,
  Timeline,
} from "@/components/cockpit/operations";
import { useScope } from "@/components/shell/use-scope";
import { usePageFilters } from "@/components/shell/use-page-filters";
import {
  INCIDENT_STATES,
  JOB_STATES,
  type SystemIncident,
  type SystemJob,
} from "@/contracts/operations-models";
import { useSystemIncidents, useSystemJobs } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import type { ViewScope } from "@/lib/scope";

/**
 * System Operations — Area 23.
 *
 * "Show whether the machinery is running."
 *
 *   DISPLAYING JOBS DOES NOT RUN THEM        there is no start, stop, retry, trigger, restart,
 *                                            schedule or repair control, and no such handler
 *                                            or route exists anywhere in this application
 *   A LAST SUCCESS IS NOT CURRENT HEALTH     two separate fields, rendered separately. A claim
 *                                            of present health requires a PRESENT observation,
 *                                            and the contract refuses one without it
 *   A ROW IS NOT A SERVICE                   every row declares that no runtime service exists,
 *                                            so a synthetic row naming a scheduler is not
 *                                            evidence that a scheduler exists
 *   AN OPEN INCIDENT HAS NO CLOSE TIME       and a closed one has one. Neither is inferred
 *                                            from the other, and an open count is a measured
 *                                            count rather than a zero standing in for one
 */

const JOB_FILTER_KEYS = ["state", "q"] as const;
const INCIDENT_FILTER_KEYS = ["incident_state"] as const;

const JOB_STATE_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  OPERATING_NORMALLY: "positive",
  DEGRADED: "warning",
  FAILING: "negative",
  NOT_OBSERVED: "unavailable",
  NEVER_OBSERVED: "unavailable",
};

const OUTCOME_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  SUCCEEDED: "positive",
  FAILED: "negative",
  PARTIALLY_COMPLETED: "warning",
  NOT_RUN: "unavailable",
};

const INCIDENT_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  OPEN: "negative",
  MITIGATED: "warning",
  CLOSED: "neutral",
};

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const jobs = useSystemJobs(scope);
  const incidents = useSystemIncidents(scope);
  const jobPayload = jobs.data?.payload;
  const incidentPayload = incidents.data?.payload;

  const jobFilters = usePageFilters(JOB_FILTER_KEYS);
  const incidentFilters = usePageFilters(INCIDENT_FILTER_KEYS);

  const jobRows = React.useMemo(() => {
    if (jobPayload === undefined) {
      return [];
    }
    return jobPayload.items.filter(
      (job) =>
        jobFilters.filters.state === "" ||
        job.current_state.code === jobFilters.filters.state,
    );
  }, [jobPayload, jobFilters.filters.state]);

  const incidentRows = React.useMemo(() => {
    if (incidentPayload === undefined) {
      return [];
    }
    return incidentPayload.items.filter(
      (incident) =>
        incidentFilters.filters.incident_state === "" ||
        incident.state.code === incidentFilters.filters.incident_state,
    );
  }, [incidentPayload, incidentFilters.filters.incident_state]);

  const degraded = jobPayload === undefined || incidentPayload === undefined;

  return (
    <>
      <PageHeader
        title="System Operations"
        summary="Recorded job runs and incidents for the deterministic core. A last successful run and the current state are two separate facts, and nothing here starts, stops, retries or schedules anything."
        pageState={degraded ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 23</Badge>
          <Badge tone="unavailable">Scheduler and service runtime: NOT IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <OperationsReadOnlyNotice
          subject="recorded job runs and incidents"
          actions={["start", "stop", "retry", "trigger", "restart", "schedule", "repair"]}
          producer="No scheduler, service runtime or process supervisor exists, and nothing observes a running service"
        />

        <ReadModelPanel
          title="What this screen is not"
          description="The scheduler these rows describe does not exist, and the controls a reader might expect are named rather than merely absent."
          envelope={jobs.data}
          dependency="a scheduler or service runtime — neither exists"
          operator={operator}
          testId="operations-boundary"
        >
          {(loaded) => (
            <div className="space-y-3">
              <SectionState
                availability={loaded.scheduler_state.availability}
                reason={loaded.scheduler_state.reason}
                note={humanizeCode(loaded.scheduler_state.note.code)}
                testId="scheduler-state"
              />
              <AbsentControls
                controls={loaded.absent_controls}
                label="Controls this screen does not have"
              />
              <p
                className="max-w-3xl text-label-s leading-relaxed text-text-tertiary"
                data-testid="service-existence-note"
              >
                <strong className="text-text-secondary">
                  A row naming a service is not evidence that the service exists.
                </strong>{" "}
                Every row below declares that no runtime service exists, which is why none of
                them carries a present observation — and why none of them can claim present
                health.
              </p>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded jobs"
          description="Last run, last success with its own as-of, and the current state — which the last run does not determine."
          envelope={jobs.data}
          dependency="a scheduler or service runtime — neither exists"
          operator={operator}
          testId="job-panel"
          always={
            <FilterBar
              chips={jobFilters.activeKeys.map((key) => ({
                key,
                label: key === "q" ? "Search" : "Current state",
                value: jobFilters.filters[key],
              }))}
              onRemove={(key) =>
                jobFilters.clearFilter(key as (typeof JOB_FILTER_KEYS)[number])
              }
              onClearAll={jobFilters.clearAll}
            >
              <SelectField
                id="job-state"
                label="Current state"
                value={jobFilters.filters.state}
                options={JOB_STATES.map((state) => ({
                  value: state,
                  label: humanizeCode(state),
                }))}
                onChange={(next) => jobFilters.setFilter("state", next)}
              />
              <SearchField
                id="job-search"
                label="Search"
                value={jobFilters.filters.q}
                placeholder="Job or subsystem"
                onChange={(next) => jobFilters.setFilter("q", next)}
              />
            </FilterBar>
          }
        >
          {(loaded) => (
            <div className="space-y-3">
              <JobTable
                rows={jobRows}
                globalFilter={jobFilters.filters.q}
                scope={scope}
                operator={operator}
              />
              <RowCount shown={jobRows.length} total={loaded.items.length} noun="jobs" />
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded incidents"
          description="Each with its own timeline. An open incident carries no close time; a closed one carries exactly when."
          envelope={incidents.data}
          dependency="an incident recorder — no service runtime exists"
          operator={operator}
          testId="incident-panel"
          always={
            <FilterBar
              chips={incidentFilters.activeKeys.map((key) => ({
                key,
                label: "State",
                value: incidentFilters.filters[key],
              }))}
              onRemove={(key) =>
                incidentFilters.clearFilter(key as (typeof INCIDENT_FILTER_KEYS)[number])
              }
              onClearAll={incidentFilters.clearAll}
            >
              <SelectField
                id="incident-state"
                label="State"
                value={incidentFilters.filters.incident_state}
                options={INCIDENT_STATES.map((state) => ({
                  value: state,
                  label: humanizeCode(state),
                }))}
                onChange={(next) => incidentFilters.setFilter("incident_state", next)}
              />
            </FilterBar>
          }
        >
          {(loaded) => (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2" data-testid="open-incidents">
                <Label>Incidents not closed</Label>
                <MetricText metric={loaded.open_count} neutral operator={operator} />
              </div>
              {incidentRows.length === 0 ? (
                <p className="text-label-m text-text-tertiary" data-testid="no-incidents">
                  No recorded incident is in this state. Every incident this read delivered is
                  still part of the count above.
                </p>
              ) : (
                <ul className="space-y-3" data-testid="incident-list">
                  {incidentRows.map((incident) => (
                    <li key={incident.incident_id}>
                      <IncidentCard incident={incident} scope={scope} operator={operator} />
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-label-s text-text-tertiary" data-testid="incident-count">
                Showing{" "}
                <strong className="font-mono text-text-secondary">
                  {incidentRows.length}
                </strong>{" "}
                of{" "}
                <strong className="font-mono text-text-secondary">
                  {loaded.items.length}
                </strong>{" "}
                recorded incidents delivered by this read.
              </p>
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

const helper = columnsFor<SystemJob>();

function JobTable({
  rows,
  globalFilter,
  scope,
  operator,
}: {
  rows: readonly SystemJob[];
  globalFilter: string;
  scope: ViewScope;
  operator: boolean;
}) {
  const columns = React.useMemo<TableColumns<SystemJob>>(
    () =>
      helper.columns([
        helper.accessor((row) => row.kind.code, {
          id: "job",
          header: () => "Job",
          cell: ({ row }) => (
            <span className="flex flex-col">
              <span className="text-label-m text-text-primary">
                {humanizeCode(row.original.kind.code)}
              </span>
              <span className="font-mono text-label-s text-text-tertiary">
                {row.original.job_id}
              </span>
            </span>
          ),
        }),
        helper.accessor((row) => row.current_state.code, {
          id: "current",
          header: () => "Current state",
          cell: ({ row }) => (
            <StateBadge
              state={row.original.current_state}
              tone={JOB_STATE_TONE[row.original.current_state.code] ?? "neutral"}
              attribute="job-state"
            />
          ),
        }),
        helper.accessor((row) => row.last_run.outcome.code, {
          id: "last-run",
          header: () => "Last run",
          cell: ({ row }) => (
            <span className="flex flex-col gap-0.5">
              <StateBadge
                state={row.original.last_run.outcome}
                tone={OUTCOME_TONE[row.original.last_run.outcome.code] ?? "neutral"}
                attribute="run-outcome"
                className="self-start"
              />
              <span className="font-mono text-label-s text-text-tertiary">
                {row.original.last_run.at}
              </span>
            </span>
          ),
        }),
        helper.accessor(
          (row) =>
            typeof row.last_success.value === "string" ? row.last_success.value : "",
          {
            id: "last-success",
            header: () => "Last success",
            cell: ({ row }) => (
              <MetricText metric={row.original.last_success} neutral />
            ),
          },
        ),
        helper.accessor(
          (row) => (typeof row.queue_depth.value === "number" ? row.queue_depth.value : -1),
          {
            id: "queue",
            header: () => "Queue depth",
            cell: ({ row }) => <MetricText metric={row.original.queue_depth} neutral />,
          },
        ),
        helper.accessor((row) => row.subsystem_role.code, {
          id: "role",
          header: () => "Subsystem",
          cell: ({ row }) => humanizeCode(row.original.subsystem_role.code),
        }),
      ]),
    [],
  );

  return (
    <DataTable
      caption="Recorded job runs for the deterministic core"
      columns={columns}
      data={rows}
      getRowId={(row) => row.job_id}
      globalFilter={globalFilter}
      initialSorting={[{ id: "last-run", desc: false }]}
      columnClasses={{
        queue: "hidden md:table-cell",
        role: "hidden lg:table-cell",
        "last-success": "hidden sm:table-cell",
      }}
      empty="No recorded job is in this state. Every job this read delivered is still part of the population."
      testId="job-table"
      renderDetail={(row) => <JobDetail job={row} scope={scope} operator={operator} />}
    />
  );
}

function JobDetail({
  job,
  scope,
  operator,
}: {
  job: SystemJob;
  scope: ViewScope;
  operator: boolean;
}) {
  return (
    <div className="space-y-3" data-testid={`job-detail-${job.job_id}`}>
      <div className="grid gap-4 lg:grid-cols-2">
        <HistoricalFact
          label="Last successful run"
          metric={job.last_success}
          operator={operator}
          testId={`last-success-${job.job_id}`}
        />
        <div className="flex flex-col gap-1" data-testid={`current-state-${job.job_id}`}>
          <Label>Current state</Label>
          <StateBadge
            state={job.current_state}
            tone={JOB_STATE_TONE[job.current_state.code] ?? "neutral"}
            attribute="job-state"
            className="self-start"
          />
          <span className="max-w-md text-label-s leading-relaxed text-text-tertiary">
            A present statement, and it is <strong>not</strong> derived from the last run. A
            claim of present health requires a present observation, and this row carries none.
          </span>
        </div>
      </div>

      <FactGrid columns={4}>
        <Fact label="Present observation">
          <MetricText metric={job.current_observation} neutral />
        </Fact>
        <Fact label="Availability">
          <MetricText metric={job.availability} neutral />
        </Fact>
        <Fact label="Last duration">
          <MetricText metric={job.duration} neutral />
        </Fact>
        <Fact label="Restarts">
          <MetricText metric={job.restarts} neutral />
        </Fact>
        <Fact label="Queue depth">
          <MetricText metric={job.queue_depth} neutral />
        </Fact>
        <Fact label="Next scheduled">
          <MetricText metric={job.next_scheduled} neutral />
        </Fact>
        <Fact label="Service existence" testId={`existence-${job.job_id}`}>
          <StateBadge
            state={job.service_existence}
            tone="unavailable"
            attribute="service-existence"
          />
        </Fact>
        <Fact label="Subsystem">{humanizeCode(job.subsystem_role.code)}</Fact>
      </FactGrid>

      <ReferenceListPanel
        list={job.evidence_refs}
        label="Recorded evidence"
        scope={scope}
        empty="This job records no evidence reference."
      />
      <ReferenceListPanel
        list={job.incident_refs}
        label="Incidents raised against this job"
        scope={scope}
        empty="This job records no incident."
      />
    </div>
  );
}

function IncidentCard({
  incident,
  scope,
  operator,
}: {
  incident: SystemIncident;
  scope: ViewScope;
  operator: boolean;
}) {
  return (
    <div
      className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
      data-incident={incident.incident_id}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-label-m font-semibold text-text-primary">
            {humanizeCode(incident.subject.code)}
          </h3>
          <SeverityBadge severity={incident.severity} />
          <StateBadge
            state={incident.state}
            tone={INCIDENT_TONE[incident.state.code] ?? "neutral"}
            attribute="incident-state"
          />
        </div>
        <span className="font-mono text-label-s text-text-tertiary">
          {incident.incident_id}
        </span>
      </div>

      <FactGrid className="mt-3" columns={3}>
        <Fact label="Opened">
          <span className="font-mono text-label-s">{incident.opened_at}</span>
        </Fact>
        <Fact label="Closed" testId={`closed-${incident.incident_id}`}>
          <MetricText metric={incident.closed_at} neutral />
        </Fact>
        <Fact label="Open for">
          <MetricText metric={incident.open_duration} neutral />
        </Fact>
      </FactGrid>

      <div className="mt-3">
        <Label>Recorded timeline</Label>
        <div className="mt-1">
          <Timeline
            entries={incident.timeline.map((entry, index) => ({
              key: `${incident.incident_id}-${index}`,
              at: entry.at,
              title: humanizeCode(entry.event.code),
              detail: humanizeCode(entry.detail.code),
            }))}
            empty="This incident records no timeline entry."
            testId={`timeline-${incident.incident_id}`}
          />
        </div>
      </div>

      <details className="mt-3">
        <summary className="cursor-pointer text-label-s text-text-secondary">
          Evidence and linked alerts
        </summary>
        <div className="mt-2 space-y-3">
          <PanelSection title="Evidence">
            <ReferenceListPanel
              list={incident.evidence_refs}
              label="Recorded evidence"
              scope={scope}
              empty="This incident records no evidence reference."
            />
          </PanelSection>
          <ReferenceListPanel
            list={incident.alert_refs}
            label="Alerts linked to this incident"
            scope={scope}
            empty="This incident records no linked alert."
          />
          {operator && (
            <p className="font-mono text-label-s text-text-tertiary">
              incident_id={incident.incident_id} · state={incident.state.code} · severity=
              {incident.severity.code}
            </p>
          )}
        </div>
      </details>
    </div>
  );
}
