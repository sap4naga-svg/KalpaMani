"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { FilterBar, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import { useCandidateFunnel, useCandidates } from "@/data/client/hooks";
import type {
  CandidateFunnelPayload,
  CandidateSummaryPayload,
} from "@/contracts/signal-models";
import { BRAIN_DECISION_STATES } from "@/contracts/vocabularies";
import { isValueBearing } from "@/contracts/validity";
import { humanizeCode } from "@/lib/format";
import { withScope, type ViewScope } from "@/lib/scope";
import { cn } from "@/lib/utils";

/**
 * Signal & Candidate Funnel — Area 6.
 *
 * "Show where opportunities are lost, at every stage, with reasons."
 *
 * FOUR THINGS THIS SCREEN IS CAREFUL ABOUT, because each is a way a funnel misleads.
 *
 *   EVERY COUNT SAYS WHAT IT COUNTS       a stage counts securities, candidate decisions or
 *                                         candidates, and two stages counting different
 *                                         subjects are never subtracted. The generated stage
 *                                         is LARGER than the consolidated one, and that is a
 *                                         property of consolidation rather than a defect
 *   THE TWO AXES SIT SIDE BY SIDE         the eight Brain states and the nine downstream
 *                                         stages are two vocabularies on two axes, and this
 *                                         page never appends one to the other
 *   READY IS A HANDOFF, NOT AN APPROVAL   `READY_FOR_RISK_REVIEW` means the Brain has no
 *                                         deterministic objection. Portfolio and risk decide
 *                                         independently, and frequently refuse
 *   REASONS OVERLAP, AND SAY SO           one candidate may carry several blocking reasons,
 *                                         so a reason distribution can sum past the state's
 *                                         candidate count. It is labelled, never normalised
 */
export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const funnel = useCandidateFunnel(scope);
  const candidates = useCandidates(scope);
  const filters = usePageFilters(FILTER_KEYS);

  const rows = React.useMemo(
    () => filterRows(candidates.data?.payload, filters.filters),
    [candidates.data?.payload, filters.filters],
  );

  const degraded =
    funnel.data?.payload === undefined || candidates.data?.payload === undefined;

  return (
    <>
      <PageHeader
        title="Signal & Candidate Funnel"
        summary="Where opportunities went, at every stage, with the reasons recorded against them. Each count states the subject it counts, and the Brain's decision states are shown beside — never merged into — the separately owned downstream stages."
        pageState={degraded ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 6</Badge>
          <Badge tone="unavailable">No Brain runtime exists</Badge>
          <Badge tone="unavailable">Downstream stages: NOT_IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadModelPanel
          title="Stages, and what each one counts"
          description="Universe, eligible, generated and consolidated. Two of them count securities, one counts module decisions and one counts candidates."
          envelope={funnel.data}
          dependency="the Brain runtime and its journaled decisions — no Brain runtime exists"
          operator={operator}
          testId="funnel-stages-panel"
        >
          {(payload) => <Stages payload={payload} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Brain decision states"
          description="The eight states, rendered as a closed set. A state nothing reached shows a measured zero rather than disappearing."
          envelope={funnel.data}
          dependency="the Brain runtime and its journaled decisions"
          operator={operator}
          testId="funnel-brain-panel"
        >
          {(payload) => <BrainAxis payload={payload} scope={scope} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Downstream progression — a separate axis"
          description="Risk review, order and fill states are owned by the portfolio, risk and execution layers. They are shown here so the handoff is visible, and they are never appended to the Brain's vocabulary."
          envelope={funnel.data}
          dependency="the risk engine and the execution runtime — neither exists"
          testId="funnel-downstream-panel"
        >
          {(payload) => <DownstreamAxis payload={payload} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Conversion between stages"
          description="Each rate shows both of its counts and both of their subjects. A conversion between two stages counting different subjects carries no rate at all."
          envelope={funnel.data}
          dependency="the Brain runtime and its journaled decisions"
          testId="funnel-conversion-panel"
        >
          {(payload) => <Conversions payload={payload} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Per-strategy funnel"
          description="Each module's own decisions and its own decision states. The universe and eligible stages belong to the whole scan and are not split across modules."
          envelope={funnel.data}
          dependency="the Brain runtime and its journaled decisions"
          testId="funnel-strategy-panel"
        >
          {(payload) => <StrategyViews payload={payload} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="The candidates behind the counts"
          description="Every journaled decision on this page, with the state and the reason recorded against it. Filtering narrows what is shown and changes no count above."
          envelope={candidates.data}
          dependency="the Brain runtime and its journaled decisions"
          operator={operator}
          testId="funnel-candidates-panel"
          always={
            <FilterBar
              chips={chipsFor(filters.filters)}
              onRemove={(key) => filters.clearFilter(key as FilterKey)}
              onClearAll={filters.clearAll}
              basis="Decision instants are session closes on the named market calendar."
            >
              <SearchField
                id="candidate-search"
                label="Security or candidate"
                value={filters.filters.q}
                onChange={(next) => filters.setFilter("q", next)}
                placeholder="DEMO.ARB"
              />
              <SelectField
                id="candidate-state"
                label="Brain state"
                value={filters.filters.state}
                onChange={(next) => filters.setFilter("state", next)}
                options={BRAIN_DECISION_STATES.map((state) => ({
                  value: state,
                  label: humanizeCode(state),
                }))}
              />
            </FilterBar>
          }
        >
          {(payload) => <CandidateList payload={payload} rows={rows} scope={scope} />}
        </ReadModelPanel>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------- filtering */

const FILTER_KEYS = ["q", "state"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];

function chipsFor(filters: Readonly<Record<FilterKey, string>>) {
  const chips: { key: string; label: string; value: string }[] = [];
  if (filters.q !== "") {
    chips.push({ key: "q", label: "Search", value: filters.q });
  }
  if (filters.state !== "") {
    chips.push({ key: "state", label: "State", value: humanizeCode(filters.state) });
  }
  return chips;
}

function filterRows(
  payload: CandidateSummaryPayload | undefined,
  filters: Readonly<Record<FilterKey, string>>,
) {
  const items = payload?.items ?? [];
  const term = filters.q.trim().toLowerCase();
  return items.filter((item) => {
    if (filters.state !== "" && item.brain_state !== filters.state) {
      return false;
    }
    if (term === "") {
      return true;
    }
    return (
      item.security.symbol.toLowerCase().includes(term) ||
      item.security.display_name.toLowerCase().includes(term) ||
      item.candidate_id.toLowerCase().includes(term)
    );
  });
}

/* --------------------------------------------------------------------- stages */

/** The subject a stage counts, in words a reader can act on. */
const SUBJECT_LABEL: Readonly<Record<string, string>> = {
  SECURITIES: "securities",
  CANDIDATE_DECISIONS: "module decisions",
  CANDIDATES: "candidates",
};

function Stages({ payload }: { payload: CandidateFunnelPayload }) {
  return (
    <div className="space-y-3" data-testid="funnel-stages">
      <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {payload.stages.map((stage) => (
          <li
            key={stage.stage}
            className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
            data-stage={stage.stage}
            data-subject={stage.subject}
          >
            <p className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              {humanizeCode(stage.stage)}
            </p>
            <p className="mt-1">
              <MetricText metric={stage.count} neutral />
            </p>
            <p className="mt-1 text-label-s text-text-secondary">
              {SUBJECT_LABEL[stage.subject] ?? stage.subject}
            </p>
            <p className="mt-1.5 text-label-s leading-relaxed text-text-tertiary">
              {humanizeCode(stage.definition.code)}
            </p>
          </li>
        ))}
      </ol>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        <strong className="text-text-secondary">
          These four are not one decreasing population.
        </strong>{" "}
        A security that qualifies through several modules is one economic opportunity with
        several pieces of evidence, so the generated stage counts module decisions and is
        larger than the consolidated stage, which counts candidates. Subtracting one from the
        other would report opportunities lost that never existed.
      </p>
    </div>
  );
}

/* ----------------------------------------------------------------- brain axis */

function BrainAxis({
  payload,
  scope,
}: {
  payload: CandidateFunnelPayload;
  scope: ViewScope;
}) {
  const total = payload.brain_axis.reduce(
    (sum, entry) => sum + (typeof entry.count.value === "number" ? entry.count.value : 0),
    0,
  );
  return (
    <div className="space-y-3" data-testid="funnel-brain-axis">
      <ScrollRegion label="Brain decision states and their recorded reasons">
        <table className="w-full min-w-[36rem] border-collapse text-label-m">
          <caption className="sr-only">
            Each of the eight Brain decision states, how many candidates reached it, and the
            reason codes recorded against them.
          </caption>
          <thead>
            <tr className="border-b border-border-subtle text-left text-text-tertiary">
              <th scope="col" className="py-1.5 pr-4 font-medium">
                State
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Candidates
              </th>
              <th scope="col" className="py-1.5 font-medium">
                Recorded reasons
              </th>
            </tr>
          </thead>
          <tbody>
            {payload.brain_axis.map((entry) => (
              <tr
                key={entry.state}
                className="border-b border-border-subtle align-top last:border-0"
                data-brain-state={entry.state}
              >
                <th scope="row" className="py-2 pr-4 text-left font-normal">
                  <span
                    className={cn(
                      "font-medium",
                      entry.state === "READY_FOR_RISK_REVIEW"
                        ? "text-info"
                        : entry.state.startsWith("BLOCKED")
                          ? "text-warning"
                          : "text-text-secondary",
                    )}
                  >
                    {humanizeCode(entry.state)}
                  </span>
                </th>
                <td className="py-2 pr-4">
                  <MetricText metric={entry.count} neutral />
                </td>
                <td className="py-2">
                  <ul className="space-y-0.5">
                    {entry.reasons.map((reason) => (
                      <li
                        key={reason.code.code}
                        className="flex flex-wrap items-baseline gap-x-2 text-label-s"
                      >
                        <span className="font-mono text-text-tertiary">
                          {String(reason.count.value ?? "—")}
                        </span>
                        <span className="text-text-secondary">
                          {humanizeCode(reason.code.code)}
                        </span>
                        {reason.overlapping && <Badge tone="neutral">overlapping</Badge>}
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>

      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        The eight states partition the{" "}
        <span className="font-mono text-text-secondary">{total}</span> consolidated candidates
        exactly. <strong className="text-text-secondary">Reason counts do not.</strong> A
        candidate may carry several blocking reasons, so a distribution marked
        &ldquo;overlapping&rdquo; can sum past the state&rsquo;s candidate count — it is a
        tally of reason occurrences, not a second partition.
      </p>

      <div
        className="rounded-sm border border-info/40 bg-info/10 p-3"
        data-testid="ready-is-not-approval"
      >
        <p className="text-label-m leading-relaxed text-text-secondary">
          <strong className="text-info">
            READY FOR RISK REVIEW is a handoff, not an approval to trade.
          </strong>{" "}
          It records that the Brain has no deterministic objection. Portfolio and risk decide
          independently and frequently refuse, and this page shows no successful end state
          because there is none to show.{" "}
          <Link
            href={withScope("/signals/missed", scope)}
            className="text-accent underline underline-offset-2"
          >
            One candidate on this page was ready and was declined downstream.
          </Link>
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- downstream axis */

function DownstreamAxis({ payload }: { payload: CandidateFunnelPayload }) {
  return (
    <div className="space-y-2" data-testid="funnel-downstream-axis">
      <ul className="flex flex-wrap gap-2">
        {payload.downstream_axis.map((entry) => (
          <li key={entry.stage}>
            <span className="inline-flex items-center gap-2 rounded-sm border border-border-subtle bg-surface-sunken px-2 py-1">
              <span className="text-label-s text-text-secondary">
                {humanizeCode(entry.stage)}
              </span>
              <AvailabilityBadge state={entry.availability} reason={entry.reason} />
            </span>
          </li>
        ))}
      </ul>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        Every one of these is{" "}
        <strong className="text-text-secondary">NOT_IMPLEMENTED</strong>: no risk engine, order
        router or execution runtime exists. The axis is rendered in full so a reader can see the
        vocabulary the handoff lands in, and it carries no count anywhere — a count here would
        be the first step of merging two axes that must stay apart.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------- conversions */

function Conversions({ payload }: { payload: CandidateFunnelPayload }) {
  return (
    <ScrollRegion label="Conversion rates between funnel stages">
      <table
        className="w-full min-w-[42rem] border-collapse text-label-m"
        data-testid="funnel-conversions"
      >
        <caption className="sr-only">
          Each conversion between two funnel stages, with its numerator, its denominator, the
          subject each stage counts, and the rate where the two are comparable.
        </caption>
        <thead>
          <tr className="border-b border-border-subtle text-left text-text-tertiary">
            <th scope="col" className="py-1.5 pr-4 font-medium">
              From
            </th>
            <th scope="col" className="py-1.5 pr-4 font-medium">
              To
            </th>
            <th scope="col" className="py-1.5 pr-4 font-medium">
              Numerator
            </th>
            <th scope="col" className="py-1.5 pr-4 font-medium">
              Denominator
            </th>
            <th scope="col" className="py-1.5 font-medium">
              Rate
            </th>
          </tr>
        </thead>
        <tbody>
          {payload.conversion.map((entry) => (
            <tr
              key={`${entry.from.code}-${entry.to.code}`}
              className="border-b border-border-subtle align-top last:border-0"
              data-comparable={String(entry.comparable)}
            >
              <th scope="row" className="py-2 pr-4 text-left font-normal text-text-secondary">
                {humanizeCode(entry.from.code)}
                <span className="mt-0.5 block text-label-s text-text-tertiary">
                  {SUBJECT_LABEL[entry.from_subject] ?? entry.from_subject}
                </span>
              </th>
              <td className="py-2 pr-4 text-text-secondary">
                {humanizeCode(entry.to.code)}
                <span className="mt-0.5 block text-label-s text-text-tertiary">
                  {SUBJECT_LABEL[entry.to_subject] ?? entry.to_subject}
                </span>
              </td>
              <td className="py-2 pr-4">
                <MetricText metric={entry.numerator} neutral />
              </td>
              <td className="py-2 pr-4">
                <MetricText metric={entry.denominator} neutral />
              </td>
              <td className="py-2">
                {entry.comparable ? (
                  <MetricText metric={entry.rate} neutral />
                ) : (
                  <span className="flex flex-col gap-1">
                    <AvailabilityBadge
                      state={entry.rate.availability}
                      reason={entry.rate.reason}
                    />
                    <span className="text-label-s text-text-tertiary">
                      two different subjects do not divide
                    </span>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/* ---------------------------------------------------------- per-strategy views */

function StrategyViews({ payload }: { payload: CandidateFunnelPayload }) {
  return (
    <div className="space-y-3" data-testid="funnel-strategy-views">
      {payload.strategy_views.map((view) => {
        const reached = view.brain_axis.filter(
          (entry) => typeof entry.count.value === "number" && entry.count.value > 0,
        );
        return (
          <PanelSection
            key={view.strategy_version}
            title={humanizeCode(view.strategy_module.code)}
            note={`Attributed to the exact version ${view.strategy_version}.`}
          >
            <div className="flex flex-wrap gap-2">
              {view.stages.map((stage) => (
                <span
                  key={stage.stage}
                  className="inline-flex items-baseline gap-2 rounded-sm border border-border-subtle bg-surface-sunken px-2 py-1 text-label-s"
                >
                  <span className="text-text-tertiary">{humanizeCode(stage.stage)}</span>
                  <span className="font-mono text-text-primary">
                    {String(stage.count.value ?? "—")}
                  </span>
                  <span className="text-text-tertiary">
                    {SUBJECT_LABEL[stage.subject] ?? stage.subject}
                  </span>
                </span>
              ))}
            </div>
            <ul className="mt-2 flex flex-wrap gap-2">
              {reached.map((entry) => (
                <li
                  key={entry.state}
                  className="inline-flex items-baseline gap-2 rounded-sm border border-border-subtle px-2 py-0.5 text-label-s"
                >
                  <span className="text-text-secondary">{humanizeCode(entry.state)}</span>
                  <span className="font-mono text-text-primary">
                    {String(entry.count.value)}
                  </span>
                </li>
              ))}
            </ul>
          </PanelSection>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------- candidate list */

function CandidateList({
  payload,
  rows,
  scope,
}: {
  payload: CandidateSummaryPayload;
  rows: CandidateSummaryPayload["items"];
  scope: ViewScope;
}) {
  return (
    <div className="space-y-2">
      <p className="text-label-s text-text-tertiary" data-testid="candidate-row-count">
        Showing <span className="font-mono text-text-secondary">{rows.length}</span> of{" "}
        <span className="font-mono text-text-secondary">{payload.items.length}</span> delivered
        rows, drawn from {humanizeCode(payload.population.code).toLowerCase()}.
      </p>
      <ScrollRegion label="Journaled candidate decisions">
        <table
          className="w-full min-w-[44rem] border-collapse text-label-m"
          data-testid="candidate-table"
        >
          <caption className="sr-only">
            Every journaled candidate decision, with its security, its Brain state, the primary
            reason recorded against it and its downstream stage.
          </caption>
          <thead>
            <tr className="border-b border-border-subtle text-left text-text-tertiary">
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Security
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Direction
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Brain state
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Primary reason
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Downstream
              </th>
              <th scope="col" className="py-1.5 font-medium">
                Decided
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr
                key={item.candidate_id}
                className="border-b border-border-subtle last:border-0"
                data-candidate-id={item.candidate_id}
                data-brain-state={item.brain_state}
              >
                <th scope="row" className="py-2 pr-4 text-left font-normal">
                  <Link
                    href={withScope(`/signals/candidates/${item.candidate_id}`, scope)}
                    className="text-accent underline underline-offset-2"
                  >
                    {item.security.symbol}
                  </Link>
                  <span className="mt-0.5 block text-label-s text-text-tertiary">
                    {item.security.display_name}
                  </span>
                </th>
                <td className="py-2 pr-4">
                  <Badge tone={item.direction === "LONG" ? "info" : "warning"}>
                    <span aria-hidden="true">{item.direction === "LONG" ? "▲" : "▼"}</span>
                    <span>{item.direction}</span>
                  </Badge>
                </td>
                <td className="py-2 pr-4 text-text-secondary">
                  {humanizeCode(item.brain_state)}
                </td>
                <td className="py-2 pr-4 text-label-s text-text-tertiary">
                  {humanizeCode(item.primary_reason.code)}
                </td>
                <td className="py-2 pr-4">
                  {isValueBearing(item.downstream_stage.availability) ? (
                    <span className="text-label-s text-text-secondary">
                      {humanizeCode(String(item.downstream_stage.value))}
                    </span>
                  ) : (
                    <AvailabilityBadge
                      state={item.downstream_stage.availability}
                      reason={item.downstream_stage.reason}
                    />
                  )}
                </td>
                <td className="py-2 font-mono text-label-s text-text-tertiary">
                  {item.decided_at.slice(0, 10)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      {rows.length === 0 && (
        <p className="text-label-m text-text-secondary" data-testid="candidate-empty">
          No delivered row matches this filter. The counts above are unchanged: filtering
          narrows what is shown and computes nothing.
        </p>
      )}
    </div>
  );
}
