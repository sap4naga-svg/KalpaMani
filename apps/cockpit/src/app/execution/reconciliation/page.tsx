"use client";

import * as React from "react";

import { Badge, Label } from "@/components/ui/primitives";
import { FilterBar, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import { ReasonList, ReferenceListPanel, ReferenceRow } from "@/components/cockpit/research";
import {
  AbsentControls,
  Fact,
  FactGrid,
  OperationsReadOnlyNotice,
  PresentState,
  StateBadge,
  Timeline,
} from "@/components/cockpit/operations";
import { useScope } from "@/components/shell/use-scope";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { RECONCILIATION_RESULTS } from "@/contracts/execution-quality-page";
import type { ReconciliationStatus } from "@/contracts/execution-quality-page";
import { useReconciliation } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import type { ViewScope } from "@/lib/scope";

/**
 * Broker & Reconciliation — Area 10.
 *
 * "Show whether the system's view of the world matches the broker's."
 *
 *   THESE ARE RECORDS, NOT A SESSION         the Cockpit holds no brokerage credential and
 *                                            opens no brokerage session. There is no connect,
 *                                            reconnect, authenticate, refresh or repair
 *                                            control, and no path to one exists
 *   A PAST SUCCESS IS NOT PRESENT HEALTH     every run shows its own as-of, and present health
 *                                            is a separate statement with its own availability
 *   A MISSING INPUT IS NOT A MATCH           a run that could not read one side reports the
 *                                            input it was missing, and its counts stay ABSENT
 *                                            rather than becoming zeros
 *   SCOPE AND AS-OF ARE COMPARED             the two as-of times are separate fields and the
 *                                            alignment between them is stated, not assumed
 *   BROKER EQUITY IS INFORMATIONAL           it is observed for reconciliation and is NEVER
 *                                            sizing authority. Strategy capital is separate
 *                                            and authoritative
 */

const FILTER_KEYS = ["result"] as const;

const RESULT_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  RECONCILED: "positive",
  MISMATCH_RECORDED: "negative",
  COMPARISON_INPUT_MISSING: "warning",
  NOT_ATTEMPTED: "unavailable",
};

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const reconciliation = useReconciliation(scope);
  const payload = reconciliation.data?.payload;
  const { filters, setFilter, clearFilter, clearAll, activeKeys } =
    usePageFilters(FILTER_KEYS);

  const runs = React.useMemo(() => {
    if (payload === undefined) {
      return [];
    }
    return payload.items.filter(
      (run) => filters.result === "" || run.result.code === filters.result,
    );
  }, [payload, filters.result]);

  return (
    <>
      <PageHeader
        title="Broker & Reconciliation"
        summary="Recorded comparisons of internal state against a broker's, each with the scope it compared, the two as-of times it compared across, and what it could not read. A historical success is shown as history."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 10</Badge>
          <Badge tone="unavailable">Broker session: NOT IMPLEMENTED</Badge>
          <Badge tone="neutral">No broker-native identifier is rendered</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <OperationsReadOnlyNotice
          subject="recorded reconciliation results"
          actions={["connect", "reconnect", "authenticate", "refresh-from-broker", "repair"]}
          producer="The Cockpit holds no brokerage credential and opens no brokerage session, and the broker is flat"
        />

        <ReadModelPanel
          title="What is true now, and what was true then"
          description="Present health is a separate question from the newest recorded result, and it is answered separately."
          envelope={reconciliation.data}
          dependency="a broker session — none exists, and none is authorized"
          operator={operator}
          testId="reconciliation-health"
        >
          {(loaded) => {
            const latest = loaded.items.find((run) => run.run_id === loaded.latest_run_id);
            return (
              <div className="space-y-4">
                <div className="grid gap-4 lg:grid-cols-2">
                  <PresentState
                    label="Present reconciliation health"
                    availability={loaded.current_health.availability}
                    reason={loaded.current_health.reason}
                    note={loaded.current_health.note}
                    testId="present-health"
                  />
                  <PresentState
                    label="Broker session"
                    availability={loaded.broker_session.availability}
                    reason={loaded.broker_session.reason}
                    note={loaded.broker_session.note}
                    testId="broker-session"
                  />
                </div>

                {latest !== undefined && (
                  <PanelSection
                    title="The newest recorded run"
                    note="It is the newest RECORD, and a record is a statement about the instant it was taken at."
                    testId="latest-run"
                  >
                    <FactGrid columns={4}>
                      <Fact label="Result">
                        <StateBadge
                          state={latest.result}
                          tone={RESULT_TONE[latest.result.code] ?? "neutral"}
                          attribute="result"
                        />
                      </Fact>
                      <Fact label="Recorded as of" testId="latest-as-of">
                        <span className="font-mono text-label-s">{latest.as_of}</span>
                      </Fact>
                      <Fact label="Age of that record">
                        <MetricText metric={latest.age} neutral />
                      </Fact>
                      <Fact label="Orphans">
                        <MetricText metric={latest.orphans} neutral />
                      </Fact>
                    </FactGrid>
                  </PanelSection>
                )}

                <AbsentControls
                  controls={loaded.absent_controls}
                  label="Controls this screen does not have"
                />
              </div>
            );
          }}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded reconciliation runs"
          description="Each run states what it compared, the two as-of times it compared across, what disagreed and what it could not read."
          envelope={reconciliation.data}
          dependency="a broker session — none exists, and none is authorized"
          operator={operator}
          testId="reconciliation-runs"
          always={
            <FilterBar
              chips={activeKeys.map((key) => ({
                key,
                label: "Result",
                value: filters[key],
              }))}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
            >
              <SelectField
                id="reconciliation-result"
                label="Result"
                value={filters.result}
                options={RECONCILIATION_RESULTS.map((result) => ({
                  value: result,
                  label: humanizeCode(result),
                }))}
                onChange={(next) => setFilter("result", next)}
              />
            </FilterBar>
          }
        >
          {(loaded) => (
            <div className="space-y-3">
              {runs.length === 0 ? (
                <p className="text-label-m text-text-tertiary" data-testid="no-runs">
                  No recorded run matches this filter. Every run this read delivered is still
                  part of the population above.
                </p>
              ) : (
                <ul className="space-y-3" data-testid="run-list">
                  {runs.map((run) => (
                    <li key={run.run_id}>
                      <RunCard run={run} scope={scope} operator={operator} />
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-label-s text-text-tertiary" data-testid="run-count">
                Showing{" "}
                <strong className="font-mono text-text-secondary">{runs.length}</strong> of{" "}
                <strong className="font-mono text-text-secondary">
                  {loaded.items.length}
                </strong>{" "}
                recorded runs delivered by this read.
              </p>
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

function RunCard({
  run,
  scope,
  operator,
}: {
  run: ReconciliationStatus;
  scope: ViewScope;
  operator: boolean;
}) {
  return (
    <div
      className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
      data-run={run.run_id}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-label-s text-text-tertiary">{run.run_id}</span>
          <StateBadge
            state={run.result}
            tone={RESULT_TONE[run.result.code] ?? "neutral"}
            attribute="result"
          />
          <StateBadge state={run.session_state} attribute="session-state" />
        </div>
        <span className="font-mono text-label-s text-text-tertiary" data-testid="run-as-of">
          as of {run.as_of}
        </span>
      </div>

      <FactGrid className="mt-3" columns={4}>
        <Fact label="Compared">{humanizeCode(run.comparison_scope.code)}</Fact>
        <Fact label="Internal as of">
          <span className="font-mono text-label-s">{run.internal_as_of}</span>
        </Fact>
        <Fact label="Broker as of">
          <MetricText metric={run.broker_as_of} neutral />
        </Fact>
        <Fact label="As-of alignment" testId={`alignment-${run.run_id}`}>
          <StateBadge
            state={run.as_of_alignment}
            tone={run.as_of_alignment.code === "AS_OF_TIMES_ALIGNED" ? "positive" : "warning"}
            attribute="alignment"
          />
        </Fact>
      </FactGrid>

      {run.missing_inputs.length > 0 && (
        <div className="mt-3" data-testid={`missing-${run.run_id}`}>
          <Label>Inputs this comparison did not have</Label>
          <div className="mt-1">
            <ReasonList codes={run.missing_inputs} tone="warning" empty="" />
          </div>
          <p className="mt-1 max-w-2xl text-label-s leading-relaxed text-text-tertiary">
            A missing comparison input is <strong>not zero and not a match</strong>. The counts
            this run could not compute are shown as absences rather than as agreement.
          </p>
        </div>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-label-s text-text-secondary">
          Differences, ownership, balances, session events and evidence
        </summary>
        <div className="mt-2 space-y-3">
          <PanelSection title="Position differences">
            {run.position_diffs.length === 0 ? (
              <p className="text-label-s text-text-tertiary">
                This run records no position difference.
              </p>
            ) : (
              <ul className="space-y-2" data-testid={`position-diffs-${run.run_id}`}>
                {run.position_diffs.map((diff) => (
                  <li key={diff.security_ref.ref_id} className="space-y-1">
                    <ReferenceRow reference={diff.security_ref} label="Security" scope={scope} />
                    <FactGrid columns={4}>
                      <Fact label="Internal">
                        <MetricText metric={diff.expected} neutral />
                      </Fact>
                      <Fact label="Broker-side">
                        <MetricText metric={diff.observed} neutral />
                      </Fact>
                      <Fact label="Difference">
                        <MetricText metric={diff.difference} neutral />
                      </Fact>
                      <Fact label="Finding">{humanizeCode(diff.finding.code)}</Fact>
                    </FactGrid>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <PanelSection title="Order differences">
            {run.order_diffs.length === 0 ? (
              <p className="text-label-s text-text-tertiary">
                This run records no order difference.
              </p>
            ) : (
              <ul className="space-y-1" data-testid={`order-diffs-${run.run_id}`}>
                {run.order_diffs.map((diff) => (
                  <li key={diff.local_ref.ref_id} className="flex flex-wrap items-center gap-2">
                    <ReferenceRow reference={diff.local_ref} label="Local order" scope={scope} />
                    <span className="text-label-s text-text-tertiary">
                      {humanizeCode(diff.disposition.code)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <PanelSection
            title="Ownership"
            note="Ownership is a separate question from quantity: an order can exist on both sides and belong to neither record."
          >
            {run.ownership_findings.length === 0 ? (
              <p className="text-label-s text-text-tertiary">
                This run records no ownership finding.
              </p>
            ) : (
              <ul className="space-y-1" data-testid={`ownership-${run.run_id}`}>
                {run.ownership_findings.map((finding) => (
                  <li
                    key={finding.local_ref.ref_id}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <ReferenceRow
                      reference={finding.local_ref}
                      label="Local order"
                      scope={scope}
                    />
                    <Badge tone="warning">{humanizeCode(finding.finding.code)}</Badge>
                    <span className="text-label-s text-text-tertiary">
                      {humanizeCode(finding.disposition.code)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <PanelSection
            title="Balances"
            note="Broker-reported equity is OBSERVED and informational. It is never sizing authority, and KalpaMani strategy capital is a separate, authoritative figure."
            testId={`balances-${run.run_id}`}
          >
            {run.balances.length === 0 ? (
              <p className="text-label-s text-text-tertiary">
                This run records no balance comparison.
              </p>
            ) : (
              <ul className="space-y-2">
                {run.balances.map((entry) => (
                  <li key={entry.measure.code} className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-label-m font-medium text-text-primary">
                        {humanizeCode(entry.measure.code)}
                      </span>
                      <Badge tone="neutral" data-testid="informational-only">
                        Informational only
                      </Badge>
                    </div>
                    <FactGrid columns={3}>
                      <Fact label="Internal">
                        <MetricText metric={entry.internal} neutral />
                      </Fact>
                      <Fact label="Broker-reported">
                        <MetricText metric={entry.broker_reported} neutral />
                      </Fact>
                      <Fact label="Difference">
                        <MetricText metric={entry.difference} neutral />
                      </Fact>
                    </FactGrid>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <PanelSection
            title="Recorded session conditions"
            note="Reconnects, restarts and authentication conditions as they were RECORDED. Nothing here opens, refreshes or repairs a session."
          >
            <Timeline
              entries={run.session_events.map((event, index) => ({
                key: `${run.run_id}-session-${index}`,
                at: event.at,
                title: humanizeCode(event.event.code),
              }))}
              empty="This run records no session event."
              testId={`session-events-${run.run_id}`}
            />
          </PanelSection>

          <ReferenceListPanel
            list={run.incident_refs}
            label="Incidents linked to this run"
            scope={scope}
            empty="This run records no linked incident."
            testId={`incidents-${run.run_id}`}
          />
          <ReferenceListPanel
            list={run.trade_refs}
            label="Trades this comparison covered"
            scope={scope}
            empty="This run records no covered trade."
            testId={`trades-${run.run_id}`}
          />

          {operator && (
            <p className="font-mono text-label-s text-text-tertiary">
              run_id={run.run_id} · result={run.result.code} · session={run.session_state.code}
            </p>
          )}
        </div>
      </details>
    </div>
  );
}
