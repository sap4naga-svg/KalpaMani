"use client";

import * as React from "react";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { FilterBar, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  ReadOnlyNotice,
  ReasonList,
  ReferenceListPanel,
  ReferenceRow,
} from "@/components/cockpit/research";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import type { ResearchQueueItem, ResearchQueueState } from "@/contracts/research-models";
import { useResearchQueue } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";

/**
 * Research Queue — Area 17.
 *
 * "Show what the system thinks should be investigated, and why."
 *
 *   A QUEUE ENTRY IS NOT AN AUTHORIZATION   every open item names the authorization it is
 *                                           waiting on, and the contract refuses an open item
 *                                           that names none
 *   THE TRIGGER IS A REFERENCE              it carries its own owning area, so a health-raised
 *                                           item reaches Strategy Health through the
 *                                           reference's declared area rather than through a
 *                                           relabelled kind
 *   A NAMED BASELINE IS REQUIRED            an item with none is refused at the boundary, so
 *                                           there is no row here without one
 *   NO CREATE, PRIORITIZE, PROMOTE OR       no such control exists on this screen or anywhere
 *   WITHDRAW                                in this application
 */

const STATE_TONE: Readonly<
  Record<ResearchQueueState, React.ComponentProps<typeof Badge>["tone"]>
> = {
  QUEUED: "neutral",
  PREREGISTRATION_DRAFTED: "info",
  REGISTERED: "positive",
  WITHDRAWN: "unavailable",
};

const PRIORITY_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  HIGH: "warning",
  MEDIUM: "info",
  LOW: "neutral",
};

const FILTER_KEYS = ["state", "priority"] as const;

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const queue = useResearchQueue(scope);
  const { filters, setFilter, clearFilter, clearAll } = usePageFilters(FILTER_KEYS);
  const [selected, setSelected] = React.useState<string | null>(null);

  const payload = queue.data?.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);
  const visible = items.filter(
    (entry) =>
      (filters.state === "" || entry.state === filters.state) &&
      (filters.priority === "" || entry.priority.code === filters.priority),
  );
  const chosen = visible.find((entry) => entry.item_id === selected) ?? visible[0];
  const priorities = [...new Set(items.map((entry) => entry.priority.code))];

  return (
    <>
      <PageHeader
        title="Research Queue"
        summary="What the recorded triggers say should be investigated, each with its issue, its proposed experiment, its named baseline and the authorization it is waiting on."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 17</Badge>
          <Badge tone="unavailable">Learning engine: NOT IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="a recorded research queue"
          actions={["create", "prioritize", "register", "withdraw", "authorize"]}
        />

        <ReadModelPanel
          title="Queued research"
          description="A queue entry records what should be investigated. It is not permission to investigate it, and every open item names what it is waiting on."
          envelope={queue.data}
          dependency="the learning engine — no learning engine exists"
          operator={operator}
          testId="queue-table"
          always={
            <FilterBar
              chips={[
                ...(filters.state === ""
                  ? []
                  : [{ key: "state", label: "State", value: filters.state }]),
                ...(filters.priority === ""
                  ? []
                  : [{ key: "priority", label: "Priority", value: filters.priority }]),
              ]}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
              basis="Filtering narrows what is shown. A hidden item is still queued, and is still waiting on the same authorization."
            >
              <SelectField
                id="queue-state"
                label="State"
                value={filters.state}
                options={(payload?.queue_states ?? []).map((state) => ({
                  value: state,
                  label: humanizeCode(state),
                }))}
                onChange={(next) => setFilter("state", next)}
              />
              <SelectField
                id="queue-priority"
                label="Priority"
                value={filters.priority}
                options={priorities.map((code) => ({ value: code, label: humanizeCode(code) }))}
                onChange={(next) => setFilter("priority", next)}
              />
            </FilterBar>
          }
        >
          {() => (
            <ScrollRegion label="Research queue items">
              <table
                className="w-full min-w-[56rem] border-collapse text-label-m"
                data-testid="queue-rows"
              >
                <caption className="sr-only">
                  Every research queue item with its issue, its proposed experiment, its named
                  baseline, its state, its priority and the authorizations it is waiting on.
                </caption>
                <thead className="bg-surface-sunken">
                  <tr className="border-b border-border-subtle text-left text-text-tertiary">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Item
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Issue
                    </th>
                    <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                      Proposed experiment
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Named baseline
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      State
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Priority
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
                        No queue item matches this filter, and that is a true answer about the
                        filter rather than an empty queue.
                      </td>
                    </tr>
                  )}
                  {visible.map((entry) => (
                    <tr
                      key={entry.item_id}
                      className="border-b border-border-subtle last:border-0"
                      data-queue-item={entry.item_id}
                      data-queue-state={entry.state}
                    >
                      <th
                        scope="row"
                        className="px-3 py-1.5 text-left font-normal text-text-secondary"
                      >
                        <span className="flex flex-col">
                          <span className="font-mono">{entry.item_id}</span>
                          <span className="text-label-s text-text-tertiary">
                            {humanizeCode(entry.strategy_module.code)}
                          </span>
                        </span>
                      </th>
                      <td className="px-3 py-1.5 text-text-secondary">
                        {humanizeCode(entry.issue.code)}
                      </td>
                      <td className="hidden px-3 py-1.5 text-text-secondary lg:table-cell">
                        {humanizeCode(entry.proposed_experiment.code)}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-label-s text-text-secondary">
                        {entry.baseline_ref.ref_id}
                      </td>
                      <td className="px-3 py-1.5">
                        <Badge tone={STATE_TONE[entry.state]}>{humanizeCode(entry.state)}</Badge>
                      </td>
                      <td className="px-3 py-1.5">
                        <Badge tone={PRIORITY_TONE[entry.priority.code] ?? "neutral"}>
                          {humanizeCode(entry.priority.code)}
                        </Badge>
                      </td>
                      <td className="px-3 py-1.5">
                        <Button
                          size="sm"
                          variant={entry.item_id === chosen?.item_id ? "primary" : "subtle"}
                          aria-pressed={entry.item_id === chosen?.item_id}
                          onClick={() => setSelected(entry.item_id)}
                        >
                          Evidence
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          )}
        </ReadModelPanel>

        {chosen !== undefined && <QueueDetail item={chosen} operator={operator} scope={scope} />}
      </div>
    </>
  );
}

function QueueDetail({
  item,
  operator,
  scope,
}: {
  item: ResearchQueueItem;
  operator: boolean;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  return (
    <Card data-testid="queue-detail" data-queue-item={item.item_id}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{humanizeCode(item.issue.code)}</Label>
          <p className="mt-0.5 font-mono text-label-m text-text-secondary">{item.item_id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATE_TONE[item.state]}>{humanizeCode(item.state)}</Badge>
          <Badge tone={PRIORITY_TONE[item.priority.code] ?? "neutral"}>
            {humanizeCode(item.priority.code)}
          </Badge>
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        <PanelSection
          title="Trigger"
          note="The recorded fact that raised this item. Its owning area is declared on the reference, so it reaches the area responsible for the record rather than a nearest catalogued page."
          testId="queue-trigger"
        >
          <ReferenceRow
            reference={item.trigger_ref}
            label="Trigger"
            scope={scope}
            testId="queue-trigger-reference"
          />
          {item.trigger_ref.owning_area === undefined && (
            <p className="mt-1 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
              This reference declares no owning area, so it gets no area control.{" "}
              <strong className="text-text-secondary">
                That is not a claim that no area owns the record.
              </strong>
            </p>
          )}
        </PanelSection>

        <PanelSection
          title="What it proposes, and against what"
          note="A named baseline comes first. An item with none is refused at the boundary."
          testId="queue-proposal"
        >
          <dl className="grid gap-2 sm:grid-cols-2">
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Proposed experiment
              </dt>
              <dd className="text-label-m text-text-secondary">
                {humanizeCode(item.proposed_experiment.code)}
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Named baseline
              </dt>
              <dd>
                <ReferenceRow reference={item.baseline_ref} label="Baseline" scope={scope} />
              </dd>
            </div>
          </dl>
          <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            <strong className="text-text-secondary">
              A queue entry is not permission to execute its proposal.
            </strong>{" "}
            Generating and prioritizing research is inside the automation&apos;s approved
            bounds; running it against real data is a separate gate that has not been opened.
          </p>
        </PanelSection>

        <PanelSection
          title="Authorizations this item is waiting on"
          note="Every open item names at least one. A withdrawn item awaits nothing."
          testId="queue-authorizations"
        >
          <ReasonList
            codes={item.awaiting_authorizations}
            tone="unavailable"
            empty="This item awaits nothing, because it was withdrawn."
            testId="queue-awaiting"
          />
          {item.withdrawal_reason !== undefined && (
            <p className="mt-2 text-label-m text-text-secondary">
              Withdrawn: <MetricText metric={item.withdrawal_reason} neutral />
            </p>
          )}
        </PanelSection>

        <PanelSection title="Dependencies and evidence" testId="queue-dependencies">
          <div className="grid gap-3 lg:grid-cols-2">
            <div>
              <Label>Dependencies</Label>
              <div className="mt-1">
                <ReasonList
                  codes={item.dependencies}
                  empty="This item records no dependency."
                />
              </div>
            </div>
            <ReferenceListPanel
              list={item.evidence_refs}
              label="Supporting evidence"
              scope={scope}
              empty="This item records no supporting evidence reference."
            />
          </div>
        </PanelSection>

        <PanelSection
          title="Where it went"
          note="The associated Challenger and the registration this item became, where each exists."
          testId="queue-outcome"
        >
          <div className="space-y-1.5">
            {item.challenger_ref === undefined ? (
              <p className="text-label-m text-text-tertiary">
                No Challenger is associated with this item yet.
              </p>
            ) : (
              <ReferenceRow reference={item.challenger_ref} label="Challenger" scope={scope} />
            )}
            {item.registration_ref === undefined ? (
              <p className="text-label-m text-text-tertiary">
                This item has not become a preregistration.
              </p>
            ) : (
              <ReferenceRow
                reference={item.registration_ref}
                label="Registration"
                scope={scope}
              />
            )}
          </div>
        </PanelSection>

        <PanelSection
          title="History"
          note="What the record says happened. Navigation may follow an item; it never advances one."
          testId="queue-history"
        >
          <ol className="space-y-1">
            {item.history.map((event) => (
              <li
                key={`${event.at}-${event.state}`}
                className="flex flex-wrap items-center gap-2 rounded-sm border border-border-subtle p-2"
              >
                <Badge tone={STATE_TONE[event.state]}>{humanizeCode(event.state)}</Badge>
                <span className="font-mono text-label-s text-text-tertiary">{event.at}</span>
                <span className="text-label-s text-text-secondary">
                  {humanizeCode(event.note.code)}
                </span>
              </li>
            ))}
          </ol>
          {operator && (
            <p className="mt-2 text-label-s text-text-tertiary">
              Queued at <MetricText metric={item.queued_at} neutral operator />
            </p>
          )}
        </PanelSection>
      </CardBody>
    </Card>
  );
}
