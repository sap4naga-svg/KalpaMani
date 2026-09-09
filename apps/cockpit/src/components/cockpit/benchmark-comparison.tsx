"use client";

import * as React from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import type { BenchmarkComparison } from "@/contracts/read-models";
import { formatDecimal, humanizeCode } from "@/lib/format";

/**
 * The portfolio benchmark comparison — Area 2, at explicitly synthetic scope.
 *
 * WHAT AREA 2 ASKS FOR, VERBATIM: "a comparison shows separately labelled series with their
 * comparability limits stated on the chart, not in a footnote nobody reads."
 *
 * FIVE THINGS THIS COMPONENT HOLDS.
 *
 *   TWO LINES, NEVER SPLICED         the portfolio and the benchmark are separate series in
 *                                    separate colours with separate names, rebased to a
 *                                    common 100 so they share an axis without sharing a line
 *   THE COMMON EXTENT IS THE EXTENT  only the instants BOTH arms observed. Nothing is
 *                                    extended, padded or carried forward to make the two
 *                                    reach the same edge of the chart
 *   THE LIMITS ARE ON THE CHART      not under a disclosure, not in operator mode only
 *   THE DIFFERENCE IS REFUSED        the arms differ in cost treatment, and §12.3 forbids
 *                                    comparing values that do. The refusal is shown with
 *                                    its reason instead of a number
 *   IT IS NOT ALPHA, AND NOT EVIDENCE the benchmark is a repository-owned invented curve.
 *                                    Nothing here is called alpha and nothing here validates
 *                                    a strategy
 */

interface ComparisonRow {
  readonly t: string;
  readonly portfolio: number | null;
  readonly benchmark: number | null;
  readonly portfolioDisplay: string | null;
  readonly benchmarkDisplay: string | null;
}

function plot(raw: unknown): number | null {
  if (typeof raw !== "string") {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildRows(comparison: BenchmarkComparison): readonly ComparisonRow[] {
  return comparison.portfolio_series.points.map((point, index) => {
    const other = comparison.benchmark_series.points[index];
    return {
      t: String(point.t),
      portfolio: plot(point.v.value),
      benchmark: plot(other?.v.value),
      portfolioDisplay: typeof point.v.value === "string" ? point.v.value : null,
      benchmarkDisplay: typeof other?.v.value === "string" ? other.v.value : null,
    };
  });
}

function ComparisonTooltip({
  active,
  payload,
  label,
  benchmarkLabel,
}: {
  active?: boolean;
  payload?: readonly { payload: ComparisonRow }[];
  label?: string | number;
  benchmarkLabel: string;
}) {
  if (active !== true || payload === undefined || payload.length === 0) {
    return null;
  }
  const row = payload[0].payload;
  const show = (value: string | null): string =>
    value === null
      ? "no observation"
      : (formatDecimal(value, { minimumFractionDigits: 2 }) ?? value);
  return (
    <div className="rounded-sm border border-border-subtle bg-surface-overlay px-3 py-2 shadow-elevation-2">
      <p className="font-mono text-label-s text-text-tertiary">{String(label)}</p>
      <p className="font-mono text-numeric-s text-text-primary">
        Portfolio {show(row.portfolioDisplay)}
      </p>
      <p className="font-mono text-label-s text-info">
        {benchmarkLabel} {show(row.benchmarkDisplay)}
      </p>
    </div>
  );
}

export function BenchmarkComparisonView({
  comparison,
  operator,
}: {
  comparison: BenchmarkComparison;
  operator: boolean;
}) {
  const [tableOpen, setTableOpen] = React.useState(false);
  const rows = React.useMemo(() => buildRows(comparison), [comparison]);
  const benchmarkLabel = humanizeCode(comparison.benchmark_label.code);

  return (
    <div className="space-y-3" data-testid="benchmark-comparison">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="synthetic">SYNTHETIC</Badge>
        <span className="text-label-m text-text-secondary">
          Portfolio against <strong>{benchmarkLabel}</strong>
        </span>
      </div>

      {/*
        * THE LIMITS COME FIRST, above the picture, because the picture is the persuasive
        * part. A limit under a chart is a limit most readers never reach.
        */}
      <ul
        className="space-y-1 rounded-sm border border-border-subtle bg-surface-sunken px-3 py-2 text-label-m text-text-secondary"
        data-testid="comparability-limits"
      >
        {comparison.comparability_limits.map((limit) => (
          <li key={limit.code} className="flex gap-2">
            <span aria-hidden="true" className="text-text-tertiary">
              ·
            </span>
            <span>{humanizeCode(limit.code)}</span>
          </li>
        ))}
      </ul>

      <div
        className="h-56 w-full sm:h-64"
        role="img"
        aria-label={`The portfolio and ${benchmarkLabel}, each rebased to 100 at the first of ${String(
          comparison.common_observations.value,
        )} common observations. A table of the same values follows.`}
        data-testid="comparison-chart"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={[...rows]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid
              stroke="var(--color-border-subtle)"
              strokeDasharray="2 4"
              vertical={false}
            />
            <XAxis
              dataKey="t"
              tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
              stroke="var(--color-border-subtle)"
              minTickGap={48}
            />
            <YAxis
              tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
              stroke="var(--color-border-subtle)"
              tickFormatter={(value: number) => value.toFixed(0)}
              width={48}
              domain={["auto", "auto"]}
            />
            <Tooltip
              content={<ComparisonTooltip benchmarkLabel={benchmarkLabel} />}
              cursor={{ stroke: "var(--color-border-strong)" }}
            />
            <ReferenceLine y={100} stroke="var(--color-border-strong)" />
            <Line
              type="monotone"
              dataKey="portfolio"
              name="Portfolio"
              stroke="var(--color-accent)"
              strokeWidth={1.75}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
            {/* ITS OWN LINE, its own colour, its own dash. Never spliced into the other. */}
            <Line
              type="monotone"
              dataKey="benchmark"
              name={benchmarkLabel}
              stroke="var(--color-info)"
              strokeWidth={1.25}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <dl
        className="grid gap-x-6 gap-y-1.5 text-label-s sm:grid-cols-2"
        data-testid="comparison-basis"
      >
        <div className="flex flex-wrap items-baseline gap-2">
          <dt className="text-text-tertiary">Portfolio movement</dt>
          <dd>
            <MetricText metric={comparison.portfolio_movement} operator={operator} />
          </dd>
        </div>
        <div className="flex flex-wrap items-baseline gap-2">
          <dt className="text-text-tertiary">Benchmark movement</dt>
          <dd>
            <MetricText metric={comparison.benchmark_movement} operator={operator} />
          </dd>
        </div>
        <div className="flex flex-wrap items-baseline gap-2">
          <dt className="text-text-tertiary">Common window</dt>
          <dd className="font-mono text-text-secondary" data-testid="comparison-window">
            {comparison.common_window.from.slice(0, 10)} →{" "}
            {comparison.common_window.to.slice(0, 10)}
          </dd>
        </div>
        <div className="flex flex-wrap items-baseline gap-2">
          <dt className="text-text-tertiary">Common observations</dt>
          <dd className="font-mono text-text-secondary">
            {String(comparison.common_observations.value)}
          </dd>
        </div>
        <div className="flex flex-wrap items-baseline gap-2">
          <dt className="text-text-tertiary">Portfolio basis</dt>
          <dd className="text-text-secondary">
            {humanizeCode(comparison.portfolio_basis)} ·{" "}
            {humanizeCode(comparison.portfolio_cost_treatment)}
          </dd>
        </div>
        <div className="flex flex-wrap items-baseline gap-2">
          <dt className="text-text-tertiary">Benchmark basis</dt>
          <dd className="text-text-secondary">
            {humanizeCode(comparison.benchmark_basis)} ·{" "}
            {humanizeCode(comparison.benchmark_cost_treatment)}
          </dd>
        </div>
      </dl>

      {/* THE DIFFERENCE, AND WHY THERE IS NONE. */}
      <div
        className="space-y-1.5 border-t border-border-subtle pt-3"
        data-testid="comparison-difference"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-label-m font-semibold text-text-primary">
            Return difference
          </span>
          <MetricText metric={comparison.difference} operator={operator} />
          {!comparison.comparable && comparison.refusal !== undefined && (
            <Badge tone="warning" data-testid="comparison-refusal">
              {humanizeCode(comparison.refusal.code)}
            </Badge>
          )}
        </div>
        <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          {comparison.comparable ? (
            <>
              Both arms carry the same return basis and the same cost treatment over the same
              boundaries, so the difference is defined. It is{" "}
              <strong className="text-text-secondary">a difference of two returns</strong> and
              nothing else — it is not alpha, and it establishes nothing about any strategy.
            </>
          ) : (
            <>
              <strong className="text-text-secondary">
                The two arms are not comparable as one figure.
              </strong>{" "}
              The portfolio is measured{" "}
              {humanizeCode(comparison.portfolio_cost_treatment).toLowerCase()} and the
              benchmark {humanizeCode(comparison.benchmark_cost_treatment).toLowerCase()}, and
              two values with different cost treatments are never compared, summed or placed
              in one series. Nothing in the arithmetic prevents the subtraction; what prevents
              it is that the result would mean nothing, and a screen that prints it teaches a
              reader that it does. It would not be alpha either way.
            </>
          )}
        </p>
      </div>

      {/* U10 — the same points, reachable by keyboard and readable by a screen reader. */}
      <details
        className="rounded-sm border border-border-subtle bg-surface-sunken"
        onToggle={(event) => setTableOpen(event.currentTarget.open)}
        data-testid="comparison-table-disclosure"
      >
        <summary className="cursor-pointer px-3 py-2 text-label-m text-text-secondary">
          Both arms as a table ({rows.length} common observations)
        </summary>
        <div className="px-3 pb-3">
          {tableOpen && (
            <ScrollRegion
              label="Rebased portfolio and benchmark by period"
              className="max-h-64 overflow-y-auto"
            >
              <table className="w-full min-w-[26rem] border-collapse text-label-m">
                <caption className="sr-only">
                  The portfolio and {benchmarkLabel}, each rebased to 100 at the first common
                  observation, for every period both arms observed.
                </caption>
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    <th scope="col" className="py-1.5 pr-3 font-medium text-text-tertiary">
                      Period
                    </th>
                    <th scope="col" className="py-1.5 pr-3 font-medium text-text-tertiary">
                      Portfolio
                    </th>
                    <th scope="col" className="py-1.5 font-medium text-text-tertiary">
                      {benchmarkLabel}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.t} className="border-b border-border-subtle last:border-0">
                      <th
                        scope="row"
                        className="py-1 pr-3 text-left font-mono font-normal text-text-tertiary"
                      >
                        {row.t}
                      </th>
                      <td className="py-1 pr-3 font-mono text-text-secondary">
                        {row.portfolioDisplay ?? "no observation"}
                      </td>
                      <td className="py-1 font-mono text-text-secondary">
                        {row.benchmarkDisplay ?? "no observation"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          )}
        </div>
      </details>
    </div>
  );
}

/** The state a comparison takes when the producer served none over this extent. */
export function BenchmarkComparisonUnavailable() {
  return (
    <div className="space-y-2" data-testid="benchmark-comparison-unavailable">
      <AvailabilityBadge state="INSUFFICIENT_OBSERVATIONS" reason="BELOW_MINIMUM_OBSERVATIONS" />
      <p className="max-w-3xl text-label-m leading-relaxed text-text-tertiary">
        A comparison needs at least two observations both arms carry, and this extent has
        fewer. Nothing is drawn from one point, and no comparison is extended to reach a
        second.
      </p>
    </div>
  );
}
