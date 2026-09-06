"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import {
  PerformanceSummaryPanel,
  RMultipleDistribution,
} from "@/components/cockpit/performance-summary";
import { PanelSection, ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import { useScope } from "@/components/shell/use-scope";
import { useStrategyPerformance } from "@/data/client/hooks";
import type { AlphaFamilyRollup, StrategyPerformance } from "@/contracts/strategy-models";
import { humanizeCode } from "@/lib/format";
import { withScope } from "@/lib/scope";

/**
 * Strategy Performance — Area 4.
 *
 * "Measure each strategy module separately, and its family jointly."
 *
 *   EVERY RESULT IS ATTRIBUTED TO AN EXACT VERSION   Breakout Long appears twice, at two
 *                                                    versions, and their trades, counts and
 *                                                    ratios stay apart. A superseded
 *                                                    version's record is not folded into its
 *                                                    successor's
 *   MODULES KEEP SEPARATE ATTRIBUTION                Breakout and Pullback share a family
 *                                                    context and are never merged into one
 *                                                    result
 *   NO DIVERSIFICATION OR ALPHA CLAIM                two modules in one family are one
 *                                                    exposure with two names until measured
 *                                                    otherwise. **G7 is OPEN**, and the family
 *                                                    roll-up says so in a field
 *   HEALTH IS CONTEXT, NOT A HEALTH SCREEN           a recorded state and its reason travel
 *                                                    with the results. The transitions, the
 *                                                    drift and the research queue are Area 5,
 *                                                    and this cycle implements none of them
 */
export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const strategy = useStrategyPerformance(scope);
  const [selectedVersion, setSelectedVersion] = React.useState<string | null>(null);

  const items = strategy.data?.payload?.items ?? [];
  const selected =
    items.find((entry) => entry.strategy_version === selectedVersion) ?? items[0];

  return (
    <>
      <PageHeader
        title="Strategy Performance"
        summary="Each module measured separately, at the exact version that produced the result, with its family context beside it and no claim about the two together."
        pageState={strategy.data?.payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 4</Badge>
          <Badge tone="unavailable">G7 strategy-taxonomy evidence: OPEN</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadModelPanel
          title="Modules and versions"
          description="One row per exact strategy version. A version with too few closed trades reports its rule rather than a ratio."
          envelope={strategy.data}
          dependency="the strategy runtime — no strategy module exists and none has ever run"
          operator={operator}
          testId="strategy-modules"
        >
          {(payload) => (
            <div className="space-y-3">
              <ScrollRegion label="Strategy modules and versions">
                <table className="w-full min-w-[52rem] border-collapse text-label-m" data-testid="strategy-table">
                  <caption className="sr-only">
                    Each strategy module at each exact version, with its recorded health state,
                    its closed-trade count and the ratios its population supports.
                  </caption>
                  <thead className="bg-surface-sunken">
                    <tr className="border-b border-border-subtle text-left text-text-tertiary">
                      <th scope="col" className="px-3 py-2 font-medium">
                        Module and version
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Family
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Recorded health
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Realized
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Expectancy
                      </th>
                      <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                        Profit factor
                      </th>
                      <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                        Win rate
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Closed trades
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Detail
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {payload.items.map((entry) => (
                      <tr
                        key={entry.strategy_version}
                        className="border-b border-border-subtle last:border-0"
                        data-strategy-version={entry.strategy_version}
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
                        <td className="px-3 py-1.5 text-text-secondary">
                          {humanizeCode(entry.alpha_family.code)}
                        </td>
                        <td className="px-3 py-1.5">
                          <HealthChip entry={entry} />
                        </td>
                        <td className="px-3 py-1.5">
                          <MetricText metric={entry.module_metrics.realized_pnl} />
                        </td>
                        <td className="px-3 py-1.5">
                          <MetricText metric={entry.summary.expectancy} />
                        </td>
                        <td className="hidden px-3 py-1.5 lg:table-cell">
                          <MetricText metric={entry.summary.profit_factor} neutral />
                        </td>
                        <td className="hidden px-3 py-1.5 lg:table-cell">
                          <MetricText
                            metric={entry.summary.win_rate}
                            denominator="defined population"
                            neutral
                          />
                        </td>
                        <td className="px-3 py-1.5">
                          <MetricText metric={entry.summary.observation_count} neutral />
                        </td>
                        <td className="px-3 py-1.5">
                          <Button
                            size="sm"
                            variant={
                              entry.strategy_version === selected?.strategy_version
                                ? "primary"
                                : "subtle"
                            }
                            aria-pressed={entry.strategy_version === selected?.strategy_version}
                            onClick={() => setSelectedVersion(entry.strategy_version)}
                          >
                            Slices
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollRegion>
              <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                <strong className="text-text-secondary">
                  Breakout Long appears at two versions, and they are two rows.
                </strong>{" "}
                A superseded version keeps its own trades, its own observation counts and its
                own ratios; nothing is folded forward into its successor, and the two are never
                summed.
              </p>
            </div>
          )}
        </ReadModelPanel>

        {selected !== undefined && (
          <VersionDetail entry={selected} operator={operator} scope={scope} />
        )}

        <ReadModelPanel
          title="Alpha families"
          description="The family roll-up, with the claim it deliberately does not make."
          envelope={strategy.data}
          dependency="the strategy runtime"
          testId="alpha-families"
        >
          {(payload) => (
            <div className="space-y-4">
              {payload.families.map((family) => (
                <FamilyPanel key={family.alpha_family.code} family={family} />
              ))}
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

function HealthChip({ entry }: { entry: StrategyPerformance }) {
  const state = entry.health_context.state;
  const value = typeof state.value === "string" ? state.value : null;
  if (value === null) {
    return <MetricText metric={state} neutral />;
  }
  const tone =
    value === "HEALTHY"
      ? "positive"
      : value === "WATCH"
        ? "info"
        : value === "RETIRED"
          ? "unavailable"
          : "warning";
  return (
    <span className="flex flex-col gap-1">
      <Badge tone={tone} data-health-state={value}>
        <span aria-hidden="true">●</span>
        <span>{humanizeCode(value)}</span>
      </Badge>
      <span className="text-label-s text-text-tertiary">
        {humanizeCode(entry.health_context.reason.code)}
      </span>
    </span>
  );
}

/** One version: its full summary, its slices, its module metrics and its health context. */
function VersionDetail({
  entry,
  operator,
  scope,
}: {
  entry: StrategyPerformance;
  operator: boolean;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  const axes = React.useMemo(
    () => [...new Set(entry.slices.map((slice) => slice.axis.code))],
    [entry],
  );
  const [axis, setAxis] = React.useState<string | null>(null);
  const activeAxis = axes.includes(axis ?? "") ? (axis as string) : axes[0];
  const slices = entry.slices.filter((slice) => slice.axis.code === activeAxis);

  return (
    <Card data-testid="strategy-version-detail">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{humanizeCode(entry.strategy_module.code)}</Label>
          <p className="mt-0.5 font-mono text-label-m text-text-secondary">
            {entry.strategy_version}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">{humanizeCode(entry.alpha_family.code)}</Badge>
          <HealthChip entry={entry} />
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        <PerformanceSummaryPanel summary={entry.summary} operator={operator} />

        <PanelSection
          title="Module measures"
          note="Holding time, opportunities, turnover, capacity, excursions and execution cost, over this version's own trades."
        >
          <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {(
              [
                ["Realized", entry.module_metrics.realized_pnl, undefined],
                ["Unrealized", entry.module_metrics.unrealized_pnl, undefined],
                [
                  "Average hold",
                  entry.module_metrics.average_holding_period,
                  undefined,
                ],
                ["Entries taken", entry.module_metrics.opportunity_count, undefined],
                [
                  "Turnover",
                  entry.module_metrics.turnover,
                  "strategy capital",
                ],
                ["Capacity", entry.module_metrics.capacity, undefined],
                ["Maximum favourable", entry.module_metrics.mfe, undefined],
                ["Maximum adverse", entry.module_metrics.mae, undefined],
                [
                  "Capture ratio",
                  entry.module_metrics.capture_ratio,
                  "maximum favourable",
                ],
                ["Slippage", entry.module_metrics.slippage, "reference price"],
              ] as const
            ).map(([term, metric, denominator]) => (
              <div key={term} className="flex flex-col gap-0.5">
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  {term}
                </dt>
                <dd>
                  <MetricText metric={metric} denominator={denominator} operator={operator} />
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            <strong className="text-text-secondary">Entries taken is not opportunities
            that existed.</strong>{" "}
            Counting the second needs a candidate stream, the Brain runtime does not exist, and
            Missed Opportunities owns that question.
          </p>
        </PanelSection>

        <PanelSection
          title="R-multiple distribution"
          note="Each closed trade's outcome divided by its own initial planned risk."
        >
          <RMultipleDistribution summary={entry.summary} />
        </PanelSection>

        <PanelSection
          title="Slices"
          note="One summary per bucket. A narrow slice is a small population, and it reports its rule rather than a ratio."
        >
          <div role="group" aria-label="Slice axis" className="mb-2 flex flex-wrap gap-1">
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
          <ScrollRegion
            label={`${humanizeCode(entry.strategy_module.code)} results by ${humanizeCode(activeAxis ?? "")}`}
            className="rounded-sm border border-border-subtle"
          >
            <table className="w-full min-w-[40rem] border-collapse text-label-m" data-testid="slice-table">
              <caption className="sr-only">
                Results for {humanizeCode(entry.strategy_module.code)} at version{" "}
                {entry.strategy_version}, sliced by {humanizeCode(activeAxis ?? "")}.
              </caption>
              <thead className="bg-surface-sunken">
                <tr className="border-b border-border-subtle text-left text-text-tertiary">
                  <th scope="col" className="px-3 py-2 font-medium">
                    {humanizeCode(activeAxis ?? "")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Expectancy
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Profit factor
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Win rate
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Closed trades
                  </th>
                </tr>
              </thead>
              <tbody>
                {slices.map((slice) => (
                  <tr
                    key={`${slice.axis.code}-${slice.bucket.code}`}
                    className="border-b border-border-subtle last:border-0"
                    data-slice-bucket={slice.bucket.code}
                  >
                    <th
                      scope="row"
                      className="px-3 py-1.5 text-left font-normal text-text-secondary"
                    >
                      {humanizeCode(slice.bucket.code)}
                    </th>
                    <td className="px-3 py-1.5">
                      <MetricText metric={slice.summary.expectancy} />
                    </td>
                    <td className="px-3 py-1.5">
                      <MetricText metric={slice.summary.profit_factor} neutral />
                    </td>
                    <td className="px-3 py-1.5">
                      <MetricText metric={slice.summary.win_rate} neutral />
                    </td>
                    <td className="px-3 py-1.5">
                      <MetricText metric={slice.summary.observation_count} neutral />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        </PanelSection>

        <PanelSection
          title="Health context"
          note="A recorded state and its reason, so results are not read as a healthy module's when the record says otherwise."
        >
          <div className="flex flex-wrap items-center gap-2">
            <HealthChip entry={entry} />
            <ReferenceChip
              reference={entry.health_context.detail_ref}
              label="Health transitions"
            />
            <Link
              href={withScope("/strategy/health", scope)}
              className="text-label-m text-accent underline underline-offset-2"
            >
              Strategy Health
            </Link>
          </div>
          <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            <strong className="text-text-secondary">
              This is context, not the health subsystem.
            </strong>{" "}
            Transitions, drift, failure clusters, the recovery authority and the research-queue
            entry a degradation creates belong to Area 5 and are implemented in a later cycle.
            Nothing on this page causes a transition.
          </p>
          <ul className="mt-2 flex flex-wrap gap-2" data-testid="health-omissions">
            {entry.health_context.omitted.map((omitted) => (
              <li key={omitted.subject.code}>
                <span className="inline-flex items-center gap-2 rounded-sm border border-border-subtle bg-surface-sunken px-2 py-1">
                  <span className="text-label-s text-text-secondary">
                    {humanizeCode(omitted.subject.code)}
                  </span>
                  <AvailabilityBadge state={omitted.availability} reason={omitted.reason} />
                </span>
              </li>
            ))}
          </ul>
        </PanelSection>
      </CardBody>
    </Card>
  );
}

/**
 * A family roll-up, and the claim it does not make.
 *
 * **Two modules in one family are one exposure with two names until measured otherwise.** The
 * roll-up carries no diversification figure at all: reporting one would be exactly the claim
 * G7 exists to withhold.
 */
function FamilyPanel({ family }: { family: AlphaFamilyRollup }) {
  return (
    <div
      className="rounded-sm border border-border-subtle p-3"
      data-testid="family-rollup"
      data-family={family.alpha_family.code}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-label-m font-semibold text-text-primary">
          {humanizeCode(family.alpha_family.code)}
        </h3>
        {family.member_versions.map((version) => (
          <Badge key={version} tone="neutral">
            {version}
          </Badge>
        ))}
      </div>
      <PerformanceSummaryPanel summary={family.summary} compact />
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border-subtle pt-2.5">
        <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
          Diversification benefit
        </span>
        <AvailabilityBadge
          state={family.diversification_claim.availability}
          reason={family.diversification_claim.reason}
        />
        <span className="text-label-s text-text-tertiary">
          Owned by{" "}
          <strong className="text-text-secondary">
            {humanizeCode(family.diversification_claim.gate.code)}
          </strong>
          . <strong>No diversification or alpha claim is made here</strong>, and none is
          derivable from these figures.
        </span>
      </div>
    </div>
  );
}
