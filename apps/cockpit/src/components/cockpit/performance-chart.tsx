"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { EnvelopeOf } from "@/contracts/envelope";
import type { PerformanceSeriesPayload } from "@/contracts/read-models";
import type { Series } from "@/contracts/values";
import { formatDecimal, humanizeCode } from "@/lib/format";
import {
  GRANULARITY_LABEL,
  PERFORMANCE_PERIODS,
  PERIOD_LABEL,
  SERIES_GRANULARITIES,
  type PerformancePeriod,
  type ScopeGranularity,
  type ViewScope,
} from "@/lib/scope";
import { cn } from "@/lib/utils";

/**
 * The executive performance overview.
 *
 * IT IS AN OVERVIEW, NOT THE PORTFOLIO PERFORMANCE PAGE. Three views over one validated
 * `PerformanceSeries`, a period selector and an optional benchmark — the full analytics
 * surface (attribution, trade population, expectancy, cost decomposition) is C5's, and this
 * makes no claim to it.
 *
 * FOUR RULES THIS COMPONENT EXISTS TO OBEY:
 *
 *   A GAP IS A BREAK, NEVER A ZERO       missing sessions are inserted as NULL rows so the
 *                                        line breaks. Recharts would otherwise draw straight
 *                                        through the hole, which reads as a flat period that
 *                                        was never observed
 *   MIXED PROVENANCE IS NEVER ONE LINE   the benchmark is its own line, its own colour and
 *                                        its own label (§13). Nothing is spliced
 *   THE CHART IS NOT THE ONLY ACCESS     a keyboard-reachable, screen-reader-readable table
 *                                        carries the SAME points (U10)
 *   EVERY NUMBER KEEPS ITS UNIT          and its as-of, its calendar and its cost treatment
 *                                        (U19). A curve with no basis is not a measurement
 */

const VIEWS = ["equity", "return", "drawdown"] as const;
type ChartView = (typeof VIEWS)[number];

const VIEW_LABEL: Readonly<Record<ChartView, string>> = {
  equity: "Equity",
  return: "Return",
  drawdown: "Drawdown",
};

const VIEW_UNIT: Readonly<Record<ChartView, string>> = {
  equity: "USD",
  return: "%",
  drawdown: "%",
};

interface ChartRow {
  readonly t: string;
  readonly value: number | null;
  readonly benchmark: number | null;
  /** The decimal string the value came from, so a tooltip never re-derives it. */
  readonly display: string | null;
  readonly benchmarkDisplay: string | null;
}

/** The next weekday after a `YYYY-MM-DD`, on the UTC calendar the series is stated in. */
function nextWeekday(date: string): string {
  const cursor = new Date(`${date}T00:00:00.000Z`);
  do {
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  } while (cursor.getUTCDay() === 0 || cursor.getUTCDay() === 6);
  return cursor.toISOString().slice(0, 10);
}

/**
 * A number for the plot, and the decimal string for everything a reader sees.
 *
 * The plot needs a `number` — a pixel position cannot be computed from a string — and that is
 * the ONLY place the decimal is converted. Every rendered figure comes from the decimal
 * string itself, so the value shown is the value the producer measured (§4.2).
 */
function plotValue(raw: unknown): number | null {
  if (typeof raw !== "string") {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function seriesFor(payload: PerformanceSeriesPayload, view: ChartView): Series {
  if (view === "equity") return payload.equity;
  if (view === "return") return payload.return_series;
  return payload.drawdown_series;
}

/**
 * Builds the plot rows, inserting an explicit break wherever a session is missing.
 *
 * The breaks are DERIVED from the dates actually present, not invented: where two consecutive
 * points are more than one weekday apart, the weekdays between them carry no observation and
 * are emitted as `null`. Nothing is interpolated and nothing is filled with zero.
 */
function buildRows(
  payload: PerformanceSeriesPayload,
  view: ChartView,
  withBenchmark: boolean,
): readonly ChartRow[] {
  const series = seriesFor(payload, view);
  const benchmark = withBenchmark ? payload.benchmark_series : undefined;
  const benchmarkByDate = new Map<string, unknown>(
    (benchmark?.points ?? []).map((point) => [point.t, point.v.value]),
  );

  const rows: ChartRow[] = [];
  series.points.forEach((point, index) => {
    /*
     * A BREAK IS ONLY DERIVABLE AT DAILY GRANULARITY.
     *
     * The rule below is "the weekdays between two consecutive points carry no observation",
     * and that is true of a daily series. A weekly or monthly series is SUPPOSED to skip
     * weekdays, so applying it there would draw a break through every period.
     */
    if (index > 0 && series.granularity === "DAILY") {
      const previous = series.points[index - 1].t;
      if (/^\d{4}-\d{2}-\d{2}$/.test(previous) && /^\d{4}-\d{2}-\d{2}$/.test(point.t)) {
        let cursor = nextWeekday(previous);
        while (cursor < point.t) {
          rows.push({
            t: cursor,
            value: null,
            benchmark: null,
            display: null,
            benchmarkDisplay: null,
          });
          cursor = nextWeekday(cursor);
        }
      }
    }
    const benchmarkRaw = benchmarkByDate.get(point.t);
    rows.push({
      t: point.t,
      value: plotValue(point.v.value),
      benchmark: plotValue(benchmarkRaw),
      display: typeof point.v.value === "string" ? point.v.value : null,
      benchmarkDisplay: typeof benchmarkRaw === "string" ? benchmarkRaw : null,
    });
  });
  return rows;
}

function formatAxis(value: number, view: ChartView): string {
  if (view === "equity") {
    return `${Math.round(value / 1000)}k`;
  }
  return `${value.toFixed(1)}%`;
}

function formatDisplay(decimal: string | null, view: ChartView): string {
  if (decimal === null) {
    return "no observation";
  }
  const formatted = formatDecimal(decimal, {
    minimumFractionDigits: 2,
    signed: view !== "equity",
  });
  return `${formatted ?? decimal} ${VIEW_UNIT[view]}`;
}

function ChartTooltip({
  active,
  payload,
  label,
  view,
  benchmarkLabel,
}: {
  active?: boolean;
  payload?: readonly { payload: ChartRow }[];
  label?: string | number;
  view: ChartView;
  benchmarkLabel: string | null;
}) {
  if (active !== true || payload === undefined || payload.length === 0) {
    return null;
  }
  const row = payload[0].payload;
  return (
    <div className="rounded-sm border border-border-subtle bg-surface-overlay px-3 py-2 shadow-elevation-2">
      <p className="font-mono text-label-s text-text-tertiary">{String(label)}</p>
      <p className="font-mono text-numeric-s text-text-primary">
        {formatDisplay(row.display, view)}
      </p>
      {benchmarkLabel !== null && row.benchmarkDisplay !== null && (
        <p className="font-mono text-label-s text-info">
          {benchmarkLabel}: {formatDisplay(row.benchmarkDisplay, "return")}
        </p>
      )}
    </div>
  );
}

/** The period selector. A period is a request parameter, so it lives in the URL (U13). */
function PeriodSelector({
  period,
  onSelect,
}: {
  period: PerformancePeriod;
  onSelect: (next: PerformancePeriod) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Comparison period"
      className="flex flex-wrap gap-1"
      data-testid="period-selector"
    >
      {PERFORMANCE_PERIODS.map((candidate) => (
        <Button
          key={candidate}
          size="sm"
          variant={candidate === period ? "primary" : "subtle"}
          aria-pressed={candidate === period}
          onClick={() => onSelect(candidate)}
          title={PERIOD_LABEL[candidate]}
        >
          {candidate}
        </Button>
      ))}
    </div>
  );
}

/** The granularity selector. Like the period, it is a request parameter and lives in the URL. */
function GranularitySelector({
  granularity,
  onSelect,
}: {
  granularity: ScopeGranularity;
  onSelect: (next: ScopeGranularity) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Series granularity"
      className="flex flex-wrap gap-1"
      data-testid="granularity-selector"
    >
      {SERIES_GRANULARITIES.map((candidate) => (
        <Button
          key={candidate}
          size="sm"
          variant={candidate === granularity ? "primary" : "subtle"}
          aria-pressed={candidate === granularity}
          onClick={() => onSelect(candidate)}
          title={`${GRANULARITY_LABEL[candidate]} periods`}
        >
          {GRANULARITY_LABEL[candidate]}
        </Button>
      ))}
    </div>
  );
}

export interface PerformanceOverviewProps {
  readonly envelope: EnvelopeOf<PerformanceSeriesPayload> | undefined;
  readonly scope: ViewScope;
  readonly operator: boolean;
  readonly onPeriodChange: (next: PerformancePeriod) => void;
  /**
   * Present on the portfolio performance page and absent on the executive overview.
   *
   * The overview is an OVERVIEW: one granularity, one question. The performance page asks a
   * different question at each granularity, so it owns the control.
   */
  readonly onGranularityChange?: (next: ScopeGranularity) => void;
  readonly heading?: string;
  readonly summary?: string;
  readonly testId?: string;
}

export function PerformanceOverview({
  envelope,
  scope,
  operator,
  onPeriodChange,
  onGranularityChange,
  heading = "Performance overview",
  summary = "Equity, return and drawdown over one stated window. An overview — not the full portfolio performance analysis.",
  testId = "performance-overview",
}: PerformanceOverviewProps) {
  const [view, setView] = React.useState<ChartView>("equity");
  const [showBenchmark, setShowBenchmark] = React.useState(false);
  const [tableOpen, setTableOpen] = React.useState(false);

  const payload = envelope?.payload;
  const benchmarkAvailable = payload?.benchmark_series !== undefined;
  const withBenchmark = showBenchmark && benchmarkAvailable && view === "return";
  const benchmarkLabel =
    withBenchmark && payload?.benchmark_label !== undefined
      ? humanizeCode(payload.benchmark_label.code)
      : null;

  const rows = React.useMemo(
    () => (payload === undefined ? [] : buildRows(payload, view, withBenchmark)),
    [payload, view, withBenchmark],
  );

  const series = payload === undefined ? undefined : seriesFor(payload, view);
  const partial = series !== undefined && series.completeness !== "COMPLETE";

  return (
    <Card data-testid={testId}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{heading}</Label>
          <p className="mt-0.5 max-w-xl text-label-m text-text-secondary">{summary}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {envelope !== undefined && payload !== undefined && (
            <ProvenanceBadge provenance={envelope.provenance} />
          )}
          {onGranularityChange !== undefined && (
            <GranularitySelector
              granularity={scope.granularity}
              onSelect={onGranularityChange}
            />
          )}
          <PeriodSelector period={scope.period} onSelect={onPeriodChange} />
        </div>
      </CardHeader>

      {envelope === undefined ? (
        <CardBody>
          <div className="skeleton-shape h-64 w-full" data-testid="skeleton" />
          <span className="sr-only">Loading the performance series</span>
        </CardBody>
      ) : payload === undefined ? (
        <CardBody>
          <UnavailableBody
            state={envelope.availability}
            reason={envelope.availability_reason}
            dependency="the portfolio valuation projection and its recorded equity history"
          />
          <p className="mt-3 max-w-2xl text-label-m leading-relaxed text-text-tertiary">
            No equity history exists, so no curve is drawn. A flat line at strategy capital
            would read as a portfolio that traded and returned nothing, which is a different
            claim from <strong>no portfolio has ever traded</strong>.
          </p>
        </CardBody>
      ) : (
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div role="group" aria-label="Chart view" className="flex flex-wrap gap-1">
              {VIEWS.map((candidate) => (
                <Button
                  key={candidate}
                  size="sm"
                  variant={candidate === view ? "primary" : "subtle"}
                  aria-pressed={candidate === view}
                  onClick={() => setView(candidate)}
                >
                  {VIEW_LABEL[candidate]}
                </Button>
              ))}
            </div>
            {benchmarkAvailable && (
              <Button
                size="sm"
                variant={withBenchmark ? "primary" : "subtle"}
                aria-pressed={withBenchmark}
                disabled={view !== "return"}
                onClick={() => setShowBenchmark((current) => !current)}
                title={
                  view === "return"
                    ? "Draw the benchmark as its own line"
                    : "A benchmark comparison is only meaningful against return"
                }
              >
                Benchmark
              </Button>
            )}
          </div>

          {/*
            * The plot is decorative to a screen reader: the table below carries the same
            * points, and duplicating hundreds of them into an aria tree would be worse than
            * useless. The chart is explicitly labelled and the alternative is named.
            */}
          <div
            className="h-56 w-full sm:h-64"
            role="img"
            aria-label={`${VIEW_LABEL[view]} over ${PERIOD_LABEL[scope.period]}, ${
              series?.points.length ?? 0
            } observed sessions. A table of the same values follows.`}
            data-testid={`chart-${view}`}
          >
            <ResponsiveContainer width="100%" height="100%">
              {view === "drawdown" ? (
                <AreaChart data={[...rows]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--color-border-subtle)" strokeDasharray="2 4" vertical={false} />
                  <XAxis
                    dataKey="t"
                    tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
                    stroke="var(--color-border-subtle)"
                    minTickGap={48}
                  />
                  <YAxis
                    tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
                    stroke="var(--color-border-subtle)"
                    tickFormatter={(value: number) => formatAxis(value, view)}
                    width={52}
                  />
                  <Tooltip
                    content={<ChartTooltip view={view} benchmarkLabel={null} />}
                    cursor={{ stroke: "var(--color-border-strong)" }}
                  />
                  <ReferenceLine y={0} stroke="var(--color-border-strong)" />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="var(--color-negative)"
                    fill="var(--color-negative)"
                    fillOpacity={0.16}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                </AreaChart>
              ) : (
                <LineChart data={[...rows]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--color-border-subtle)" strokeDasharray="2 4" vertical={false} />
                  <XAxis
                    dataKey="t"
                    tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
                    stroke="var(--color-border-subtle)"
                    minTickGap={48}
                  />
                  <YAxis
                    tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
                    stroke="var(--color-border-subtle)"
                    tickFormatter={(value: number) => formatAxis(value, view)}
                    width={52}
                    domain={["auto", "auto"]}
                  />
                  <Tooltip
                    content={<ChartTooltip view={view} benchmarkLabel={benchmarkLabel} />}
                    cursor={{ stroke: "var(--color-border-strong)" }}
                  />
                  {view === "return" && (
                    <ReferenceLine y={0} stroke="var(--color-border-strong)" />
                  )}
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke="var(--color-accent)"
                    strokeWidth={1.75}
                    dot={false}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                  {/* ITS OWN LINE. A benchmark is never spliced into the portfolio's. */}
                  {withBenchmark && (
                    <Line
                      type="monotone"
                      dataKey="benchmark"
                      stroke="var(--color-info)"
                      strokeWidth={1.25}
                      strokeDasharray="4 3"
                      dot={false}
                      isAnimationActive={false}
                      connectNulls={false}
                    />
                  )}
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>

          {/* THE BASIS. A curve without one is a picture, not a measurement. */}
          <dl className="flex flex-wrap gap-x-5 gap-y-1 text-label-s text-text-tertiary">
            <div className="flex gap-1.5">
              <dt>Window</dt>
              <dd className="font-mono text-text-secondary">
                {payload.window.from.slice(0, 10)} → {payload.window.to.slice(0, 10)}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Calendar</dt>
              <dd className="text-text-secondary">{humanizeCode(payload.calendar.code)}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Timezone</dt>
              <dd className="font-mono text-text-secondary">{payload.window.timezone}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Costs</dt>
              <dd className="text-text-secondary">{humanizeCode(payload.cost_treatment)}</dd>
            </div>
            {view === "drawdown" && (
              <div className="flex gap-1.5">
                <dt>Basis</dt>
                <dd className="text-text-secondary">{humanizeCode(payload.drawdown_basis)}</dd>
              </div>
            )}
            <div className="flex gap-1.5">
              <dt>Sessions</dt>
              <dd className="font-mono text-text-secondary">
                {series?.coverage.present} of {series?.coverage.requested}
              </dd>
            </div>
          </dl>

          {/* A GAP IS STATED, not smoothed. The line breaks and the coverage says why. */}
          {partial && series !== undefined && (
            <div className="flex flex-wrap items-center gap-2" data-testid="series-partial">
              <AvailabilityBadge state="PARTIAL" reason="EXTENT_PARTIALLY_COVERED" />
              <span className="text-label-m text-text-tertiary">
                {series.coverage.requested - series.coverage.present} sessions in this window
                carry no observation. The line breaks where they are missing; nothing is
                interpolated and no gap is filled with a zero.
              </span>
            </div>
          )}

          {payload.cash_flows.length > 0 && (
            <p className="text-label-s leading-relaxed text-text-tertiary">
              <strong>{payload.cash_flows.length}</strong> external cash flow
              {payload.cash_flows.length === 1 ? "" : "s"} in this window. It moves{" "}
              <strong>equity</strong> and appears in neither the return nor the drawdown
              series: a deposit is not a profit, and the drawdown is computed on the
              cash-flow-adjusted index so an external flow creates no new peak.
            </p>
          )}

          {/* U10 -- the same information, reachable by keyboard and readable by a screen reader. */}
          <details
            className="rounded-sm border border-border-subtle bg-surface-sunken"
            onToggle={(event) => setTableOpen(event.currentTarget.open)}
            data-testid="series-table-disclosure"
          >
            <summary className="cursor-pointer px-3 py-2 text-label-m text-text-secondary">
              {VIEW_LABEL[view]} as a table ({series?.points.length ?? 0} observed sessions)
            </summary>
            <div className="px-3 pb-3">
              {tableOpen && series !== undefined && (
                <ScrollRegion
                  label={`${VIEW_LABEL[view]} values by session`}
                  className="max-h-64 overflow-y-auto"
                >
                  <table className="w-full min-w-[20rem] border-collapse text-label-m">
                    <caption className="sr-only">
                      {VIEW_LABEL[view]} for each observed session, in {VIEW_UNIT[view]}, on
                      the {humanizeCode(payload.calendar.code)} calendar in{" "}
                      {payload.window.timezone}.
                    </caption>
                    <thead>
                      <tr className="border-b border-border-subtle text-left">
                        <th scope="col" className="py-1.5 pr-3 font-medium text-text-tertiary">
                          Session
                        </th>
                        <th scope="col" className="py-1.5 font-medium text-text-tertiary">
                          {VIEW_LABEL[view]} ({VIEW_UNIT[view]})
                        </th>
                        {withBenchmark && (
                          <th scope="col" className="py-1.5 font-medium text-text-tertiary">
                            {benchmarkLabel} (%)
                          </th>
                        )}
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
                          <td
                            className={cn(
                              "py-1 font-mono",
                              row.display === null ? "text-unavailable" : "text-text-secondary",
                            )}
                          >
                            {formatDisplay(row.display, view)}
                          </td>
                          {withBenchmark && (
                            <td className="py-1 font-mono text-text-secondary">
                              {formatDisplay(row.benchmarkDisplay, "return")}
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollRegion>
              )}
            </div>
          </details>

          {operator && (
            <ScrollRegion label="Series evidence fields">
              <dl className="grid min-w-[34rem] grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-label-s sm:grid-cols-3">
                {(
                  [
                    ["series_id", payload.series_id],
                    ["granularity", payload.granularity],
                    ["cost_treatment", payload.cost_treatment],
                    ["drawdown_basis", payload.drawdown_basis],
                    ["metric_id", seriesFor(payload, view).points[0]?.v.metric_id ?? "absent"],
                    ["completeness", seriesFor(payload, view).completeness],
                    ["benchmark_refs.total", String(payload.benchmark_refs.total.value ?? "—")],
                    ["cash_flows", String(payload.cash_flows.length)],
                    ["watermark", envelope.watermark ?? "absent"],
                    ["snapshot_version", envelope.snapshot_version],
                  ] as const
                ).map(([key, value]) => (
                  <div key={key} className="flex flex-col">
                    <dt className="text-text-tertiary">{key}</dt>
                    <dd className="truncate text-text-secondary">{value}</dd>
                  </div>
                ))}
              </dl>
            </ScrollRegion>
          )}

          {envelope.provenance === "SYNTHETIC" && (
            <p className="flex flex-wrap items-center gap-2 border-t border-border-subtle pt-3 text-label-s text-text-tertiary">
              <Badge tone="synthetic">SYNTHETIC</Badge>
              <span>
                A repository-owned deterministic fixture. <strong>Not a result</strong>, not a
                backtest, and not evidence that any strategy or portfolio exists.
              </span>
            </p>
          )}
        </CardBody>
      )}
    </Card>
  );
}
