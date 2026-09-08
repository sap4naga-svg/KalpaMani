"use client";

import * as React from "react";

import { Badge, Label } from "@/components/ui/primitives";
import { DataTable, RowCount, columnsFor, type TableColumns } from "@/components/cockpit/data-table";
import { FilterBar, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import { ReasonList, ReferenceListPanel } from "@/components/cockpit/research";
import {
  Fact,
  FactGrid,
  OperationsReadOnlyNotice,
  SeverityBadge,
} from "@/components/cockpit/operations";
import { useScope } from "@/components/shell/use-scope";
import { usePageFilters } from "@/components/shell/use-page-filters";
import {
  ALERT_SEVERITIES,
  ALERT_STATES,
  SEVERITY_RANK,
  type Alert,
  type AlertSeverity,
} from "@/contracts/operations-models";
import { useAlerts } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import type { ViewScope } from "@/lib/scope";

/**
 * Alerts & Exceptions — Area 27.
 *
 * "Surface conditions that need a human eye, without becoming noise."
 *
 *   ONE CONDITION IS ONE ALERT               deduplication is a CONTRACT: the payload is
 *                                            refused at admission if two rows share a
 *                                            condition identity, because "a hundred copies of
 *                                            a true alert is an outage of the alerting system"
 *   SEVERITY IS RANKED, NEVER COMPARED       ordering comes from the accepted vocabulary's
 *                                            declared rank, never from comparing three words
 *   WHAT WAS FOLDED IS STATED                every row says how many duplicate observations it
 *                                            folded, and the page states the total, so nothing
 *                                            disappears silently
 *   AN ALERT IS NOT AN ATTENTION ITEM        they are separate records over the SAME condition
 *                                            identity, which is what lets the executive and
 *                                            operator views reconcile without double-counting
 *   NO NOTIFICATION INTEGRATION EXISTS       no email, SMS, push, chat webhook or paging
 *                                            integration is specified, built or authorized,
 *                                            and there is no acknowledge, resolve, snooze or
 *                                            dismiss control
 */

const FILTER_KEYS = ["severity", "state", "q"] as const;

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const alerts = useAlerts(scope);
  const payload = alerts.data?.payload;
  const { filters, setFilter, clearFilter, clearAll, activeKeys } =
    usePageFilters(FILTER_KEYS);

  const rows = React.useMemo(() => {
    if (payload === undefined) {
      return [];
    }
    return payload.items
      .filter((row) => filters.severity === "" || row.severity.code === filters.severity)
      .filter((row) => filters.state === "" || row.state === filters.state)
      .toSorted((left, right) => {
        const bySeverity =
          (SEVERITY_RANK[left.severity.code as AlertSeverity] ?? Number.MAX_SAFE_INTEGER) -
          (SEVERITY_RANK[right.severity.code as AlertSeverity] ?? Number.MAX_SAFE_INTEGER);
        if (bySeverity !== 0) {
          return bySeverity;
        }
        const byLastSeen = right.last_seen.localeCompare(left.last_seen);
        return byLastSeen !== 0 ? byLastSeen : left.dedup_key.localeCompare(right.dedup_key);
      });
  }, [payload, filters.severity, filters.state]);

  const hidden = (payload?.items.length ?? 0) - rows.length;

  return (
    <>
      <PageHeader
        title="Alerts & Exceptions"
        summary="One record per condition, with its occurrence count, its first and last sighting, its severity and its evidence. The attention list is a separate projection over the same condition identities."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 27</Badge>
          <Badge tone="unavailable">Platform alerts: NOT IMPLEMENTED</Badge>
          <Badge tone="neutral">No external notification integration exists</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <OperationsReadOnlyNotice
          subject="recorded alert conditions"
          actions={["acknowledge", "resolve", "snooze", "dismiss", "notify"]}
          producer="No alert pipeline exists and no notification integration is specified, built or authorized"
        />

        <ReadModelPanel
          title="Severity, deduplication and what is not here"
          description="Ordering comes from the accepted vocabulary's declared rank, and the notification integrations that do not exist are named rather than merely absent."
          envelope={alerts.data}
          dependency="a platform alert pipeline — none exists"
          operator={operator}
          testId="alert-boundary"
        >
          {(loaded) => (
            <div className="space-y-3">
              <div>
                <Label>Severity, in declared rank order</Label>
                <ul className="mt-1 flex flex-wrap gap-2" data-testid="severity-legend">
                  {loaded.severity_order.map((severity, index) => (
                    <li key={severity} className="inline-flex items-center gap-1">
                      <span className="font-mono text-label-s text-text-tertiary">
                        {index + 1}
                      </span>
                      <SeverityBadge
                        severity={{
                          code: severity,
                          vocabulary: "kalpamani.demo",
                          vocabulary_version: "v1",
                        }}
                      />
                    </li>
                  ))}
                </ul>
                <p className="mt-1 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                  Rank comes from the accepted vocabulary, not from comparing text. Two
                  severities are never ordered by how their names happen to sort.
                </p>
              </div>

              <FactGrid columns={2}>
                <Fact label="Duplicate observations folded away" testId="folded-total">
                  <MetricText metric={loaded.folded_total} neutral operator={operator} />
                </Fact>
                <Fact label="Conditions delivered">
                  <MetricText metric={loaded.page.total} neutral />
                </Fact>
              </FactGrid>

              <div>
                <Label>Notification integrations that do not exist</Label>
                <div className="mt-1">
                  <ReasonList
                    codes={loaded.absent_integrations}
                    tone="unavailable"
                    empty="This page records no absent integration."
                    testId="absent-integrations"
                  />
                </div>
              </div>

              <p
                className="max-w-3xl text-label-s leading-relaxed text-text-tertiary"
                data-testid="attention-reconciliation"
              >
                <strong className="text-text-secondary">
                  An alert record is not an attention item.
                </strong>{" "}
                The executive Attention Required list is a separate projection that ranks and
                deduplicates over the <strong>same condition identities</strong> these rows
                carry, so the two views reconcile against one another rather than counting one
                condition twice.
              </p>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded conditions"
          description="One row per condition, ordered by declared severity rank and then by when it was last seen."
          envelope={alerts.data}
          dependency="a platform alert pipeline — none exists"
          operator={operator}
          testId="alert-panel"
          always={
            <FilterBar
              chips={activeKeys.map((key) => ({
                key,
                label: key === "q" ? "Search" : key === "severity" ? "Severity" : "State",
                value: filters[key],
              }))}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
            >
              <SelectField
                id="alert-severity"
                label="Severity"
                value={filters.severity}
                options={ALERT_SEVERITIES.map((severity) => ({
                  value: severity,
                  label: humanizeCode(severity),
                }))}
                onChange={(next) => setFilter("severity", next)}
              />
              <SelectField
                id="alert-state"
                label="State"
                value={filters.state}
                options={ALERT_STATES.map((state) => ({
                  value: state,
                  label: humanizeCode(state),
                }))}
                onChange={(next) => setFilter("state", next)}
              />
              <SearchField
                id="alert-search"
                label="Search"
                value={filters.q}
                placeholder="Condition or identity"
                onChange={(next) => setFilter("q", next)}
              />
            </FilterBar>
          }
        >
          {(loaded) => (
            <div className="space-y-3">
              <AlertTable
                rows={rows}
                globalFilter={filters.q}
                scope={scope}
                operator={operator}
              />
              <RowCount shown={rows.length} total={loaded.items.length} noun="conditions" />
              {hidden > 0 && (
                <p className="text-label-s text-text-tertiary" data-testid="hidden-total">
                  <strong className="font-mono text-text-secondary">{hidden}</strong> recorded
                  conditions are hidden by the filter above. They are still part of the
                  population every count on this page was taken over.
                </p>
              )}
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

const helper = columnsFor<Alert>();

function AlertTable({
  rows,
  globalFilter,
  scope,
  operator,
}: {
  rows: readonly Alert[];
  globalFilter: string;
  scope: ViewScope;
  operator: boolean;
}) {
  const columns = React.useMemo<TableColumns<Alert>>(
    () =>
      helper.columns([
        helper.accessor((row) => row.condition.code, {
          id: "condition",
          header: () => "Condition",
          cell: ({ row }) => (
            <span className="flex flex-col">
              <span className="text-label-m text-text-primary">
                {humanizeCode(row.original.condition.code)}
              </span>
              <span
                className="font-mono text-label-s text-text-tertiary"
                data-dedup-key={row.original.dedup_key}
              >
                {row.original.dedup_key}
              </span>
            </span>
          ),
        }),
        helper.accessor(
          (row) => SEVERITY_RANK[row.severity.code as AlertSeverity] ?? Number.MAX_SAFE_INTEGER,
          {
            id: "severity",
            header: () => "Severity",
            cell: ({ row }) => <SeverityBadge severity={row.original.severity} />,
          },
        ),
        helper.accessor((row) => row.state, {
          id: "state",
          header: () => "State",
          cell: ({ row }) => (
            <Badge
              tone={row.original.state === "OPEN" ? "warning" : "neutral"}
              data-alert-state={row.original.state}
            >
              {humanizeCode(row.original.state)}
            </Badge>
          ),
        }),
        helper.accessor(
          (row) =>
            typeof row.occurrence_count.value === "number" ? row.occurrence_count.value : -1,
          {
            id: "occurrences",
            header: () => "Occurrences",
            cell: ({ row }) => (
              <span className="inline-flex flex-wrap items-baseline gap-1.5">
                <MetricText metric={row.original.occurrence_count} neutral />
                {typeof row.original.deduplicated_away.value === "number" &&
                  row.original.deduplicated_away.value > 0 && (
                    <span
                      className="text-label-s text-text-tertiary"
                      data-testid="folded-count"
                    >
                      (<MetricText metric={row.original.deduplicated_away} neutral /> folded)
                    </span>
                  )}
              </span>
            ),
          },
        ),
        helper.accessor((row) => row.last_seen, {
          id: "last-seen",
          header: () => "Last seen",
          cell: ({ row }) => (
            <span className="font-mono text-label-s">{row.original.last_seen}</span>
          ),
        }),
      ]),
    [],
  );

  return (
    <DataTable
      caption="Recorded alert conditions, one row per condition"
      columns={columns}
      data={rows}
      getRowId={(row) => row.alert_id}
      globalFilter={globalFilter}
      columnClasses={{
        "last-seen": "hidden lg:table-cell",
        occurrences: "hidden sm:table-cell",
      }}
      empty="No recorded condition matches this filter. Every condition this read delivered is still part of the population above."
      testId="alert-table"
      renderDetail={(row) => <AlertDetail alert={row} scope={scope} operator={operator} />}
    />
  );
}

function AlertDetail({
  alert,
  scope,
  operator,
}: {
  alert: Alert;
  scope: ViewScope;
  operator: boolean;
}) {
  return (
    <div className="space-y-3" data-testid={`alert-detail-${alert.alert_id}`}>
      <FactGrid columns={4}>
        <Fact label="First seen">
          <span className="font-mono text-label-s">{alert.first_seen}</span>
        </Fact>
        <Fact label="Last seen">
          <span className="font-mono text-label-s">{alert.last_seen}</span>
        </Fact>
        <Fact label="Resolved" testId={`resolved-${alert.alert_id}`}>
          <MetricText metric={alert.resolved_at} neutral />
        </Fact>
        <Fact label="Impact">
          <MetricText metric={alert.impact} />
        </Fact>
      </FactGrid>

      <PanelSection
        title="Two identities, kept apart"
        note="The alert record has its own identity; the condition it is about has another. The attention projection carries the same condition identity, which is how the two views reconcile."
      >
        <FactGrid columns={2}>
          <Fact label="Alert record">
            <span className="font-mono text-label-s" data-testid="alert-record-id">
              {alert.alert_id}
            </span>
          </Fact>
          <Fact label="Condition identity">
            <span className="font-mono text-label-s" data-testid="alert-condition-id">
              {alert.dedup_key}
            </span>
          </Fact>
        </FactGrid>
      </PanelSection>

      <ReferenceListPanel
        list={alert.evidence_refs}
        label="Evidence"
        scope={scope}
        empty="No evidence reference exists for this condition."
      />
      <ReferenceListPanel
        list={alert.incident_refs}
        label="Incidents linked to this condition"
        scope={scope}
        empty="This condition records no linked incident."
      />

      {operator && (
        <p className="font-mono text-label-s text-text-tertiary">
          alert_id={alert.alert_id} · dedup_key={alert.dedup_key} · severity=
          {alert.severity.code} · state={alert.state}
        </p>
      )}
    </div>
  );
}
