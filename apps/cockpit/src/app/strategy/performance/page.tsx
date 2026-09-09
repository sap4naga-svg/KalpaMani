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
import type {
  AlphaFamilyRollup,
  RollingExpectancy,
  StrategyPerformance,
} from "@/contracts/strategy-models";
import type { MetricValue } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";
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
          <CapacityDependencies metric={entry.module_metrics.capacity} />
        </PanelSection>

        <PanelSection
          title="Rolling expectancy"
          note="Expectancy over the trailing thirty closed trades of this exact version, one point per closed trade."
        >
          {entry.rolling_expectancy === undefined ? (
            <AvailabilityBadge state="NOT_YET_AVAILABLE" reason="UPSTREAM_INPUT_MISSING" />
          ) : (
            <RollingExpectancyView
              rolling={entry.rolling_expectancy}
              operator={operator}
              versionId={entry.strategy_version}
            />
          )}
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

/**
 * Rolling expectancy over one version's trailing closed trades.
 *
 * THE AXIS IS THE TRADE, NOT THE SESSION, and the table says so in its own header. Two
 * trades of one version routinely close on the same day, so a time axis would have to drop
 * one of them; the ordinal is what an observation unit of `CLOSED_TRADE` actually means, and
 * each point carries the exit it was taken at beside its ordinal rather than instead of it.
 *
 * A POINT BELOW THE MINIMUM IS NOT A SMALLER SAMPLE. §12.3 declares thirty trades for
 * `expectancy.currency`; a point with twenty-nine behind it reports
 * `INSUFFICIENT_OBSERVATIONS` rather than an expectancy over twenty-nine wearing a
 * thirty-trade label.
 */
function RollingExpectancyView({
  rolling,
  operator,
  versionId,
}: {
  rolling: RollingExpectancy;
  operator: boolean;
  versionId: string;
}) {
  const computed = rolling.points.filter((point) =>
    isValueBearing(point.value.availability),
  ).length;
  return (
    <div className="space-y-2" data-testid={`rolling-expectancy-${versionId}`}>
      <dl className="flex flex-wrap gap-x-5 gap-y-1 text-label-s text-text-tertiary">
        <div className="flex gap-1.5">
          <dt>Lookback</dt>
          <dd className="font-mono text-text-secondary" data-testid="expectancy-lookback">
            {String(rolling.lookback.value)} closed trades
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Minimum observations</dt>
          <dd className="font-mono text-text-secondary">
            {String(rolling.minimum_observations.value)}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Observation unit</dt>
          <dd className="text-text-secondary">{humanizeCode(rolling.observation_unit)}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Closed trades</dt>
          <dd className="font-mono text-text-secondary" data-testid="expectancy-observed">
            {String(rolling.observed.value)}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Points computed</dt>
          <dd className="font-mono text-text-secondary" data-testid="expectancy-computed">
            {computed}
          </dd>
        </div>
      </dl>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        Population: {humanizeCode(rolling.population.code)}. A trade with no retained
        entry-time risk record is <strong>excluded</strong> here exactly as the summary above
        excludes it, and the window is then short by that many rather than averaged over
        fewer.
      </p>
      {computed === 0 ? (
        <p
          className="max-w-3xl text-label-m leading-relaxed text-text-tertiary"
          data-testid="expectancy-none-computed"
        >
          <strong className="text-text-secondary">
            No point on this version has a complete window behind it.
          </strong>{" "}
          It carries {String(rolling.observed.value)} closed trades and the window needs{" "}
          {String(rolling.lookback.value)}. That is the answer, and a shorter window is not
          substituted for it.
        </p>
      ) : (
        <ScrollRegion
          label={`Rolling expectancy by closed trade for ${versionId}`}
          className="max-h-64 overflow-y-auto"
        >
          <table className="w-full min-w-[26rem] border-collapse text-label-m">
            <caption className="sr-only">
              Expectancy over the trailing {String(rolling.lookback.value)} closed trades of{" "}
              {versionId}, in USD, indexed by the trade&rsquo;s position in exit order.
            </caption>
            <thead>
              <tr className="border-b border-border-subtle text-left">
                <th scope="col" className="py-1.5 pr-3 font-medium text-text-tertiary">
                  Trade
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium text-text-tertiary">
                  Exit
                </th>
                <th scope="col" className="py-1.5 font-medium text-text-tertiary">
                  Rolling expectancy (USD)
                </th>
              </tr>
            </thead>
            <tbody>
              {rolling.points.map((point) => (
                <tr
                  key={String(point.ordinal.value)}
                  className="border-b border-border-subtle last:border-0"
                >
                  <th
                    scope="row"
                    className="py-1 pr-3 text-left font-mono font-normal text-text-tertiary"
                  >
                    #{String(point.ordinal.value)}
                  </th>
                  <td className="py-1 pr-3 font-mono text-text-tertiary">
                    {String(point.at.value).slice(0, 10)}
                  </td>
                  <td className="py-1">
                    <MetricText metric={point.value} operator={operator} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      )}
    </div>
  );
}

/**
 * What capacity is waiting on, named exactly.
 *
 * AREA 4 NAMES CAPACITY, AND THIS APPLICATION DOES NOT COMPUTE ONE. The metric beside it
 * renders unavailable; this states WHY, because "unavailable" on its own sends a reader to
 * look for a broken producer rather than at a dependency that does not exist.
 *
 * NOTHING HERE IS AN ESTIMATE. No participation rate, no average daily volume, no impact
 * model, no borrow constraint and no recommended allocation appears — inventing any one of
 * them is how a demonstration becomes a number somebody sizes a position from.
 *
 * AND CAPACITY IS NOT ANY OF THE THINGS IT IS ROUTINELY CONFUSED WITH. Strategy capital,
 * available cash, buying power and a position or risk limit are four other quantities, three
 * of which this application already displays elsewhere; none of them is how much this
 * strategy could deploy before its own execution moved the price against it.
 */
function CapacityDependencies({ metric }: { metric: MetricValue }) {
  if (isValueBearing(metric.availability)) {
    return null;
  }
  return (
    <div
      className="mt-3 space-y-1.5 rounded-sm border border-border-subtle bg-surface-sunken px-3 py-2"
      data-testid="capacity-dependencies"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-label-m font-semibold text-text-primary">Capacity</span>
        <AvailabilityBadge state={metric.availability} reason={metric.reason} />
      </div>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        Capacity is <strong>how much this strategy could deploy before its own execution
        moved the price against it</strong>. It is not strategy capital, not available cash,
        not buying power and not a position or risk limit — those are four other quantities,
        and substituting any of them would answer a different question under this name.
      </p>
      <ul className="space-y-1 text-label-s text-text-secondary">
        <li className="flex gap-2">
          <span aria-hidden="true" className="text-text-tertiary">
            ·
          </span>
          <span>
            <strong>No liquidity or market-impact model exists</strong> in this repository.
            There is no participation assumption, no impact function and no execution
            simulator to run one through.
          </span>
        </li>
        <li className="flex gap-2">
          <span aria-hidden="true" className="text-text-tertiary">
            ·
          </span>
          <span>
            <strong>No volume or liquidity history is held.</strong> A capacity figure needs
            per-security traded volume over the evaluated window, and this application holds
            none — <strong>G1 is OPEN</strong> and no market-data provider is selected.
          </span>
        </li>
        <li className="flex gap-2">
          <span aria-hidden="true" className="text-text-tertiary">
            ·
          </span>
          <span>
            <strong>No borrow or short-availability history is held</strong> for the
            short-side limb — <strong>G5 is OPEN</strong>.
          </span>
        </li>
        <li className="flex gap-2">
          <span aria-hidden="true" className="text-text-tertiary">
            ·
          </span>
          <span>
            <strong>No accepted definition exists</strong> to compute one against. The metric
            dictionary registers <span className="font-mono">strategy.capacity</span> with its
            unit and carries <strong>no formula, denominator, participation assumption or
            minimum-observation rule</strong> for it, so the quantity is not yet specified
            well enough to compute — and choosing those here would be inventing a policy on a
            screen.
          </span>
        </li>
      </ul>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        The requirement stays <strong>open</strong>. It is not satisfied by this disclosure,
        and it is not deferred out of scope — it is named, with what it waits on.
      </p>
    </div>
  );
}

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
