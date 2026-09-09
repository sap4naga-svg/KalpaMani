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

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { MetricText, UnavailableInline } from "@/components/cockpit/metric-text";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { EnvelopeOf } from "@/contracts/envelope";
import type { PerformanceSeriesPayload, RollingWindow } from "@/contracts/read-models";
import type { MetricValue, Series } from "@/contracts/values";
import type { AvailabilityState, FieldReasonCode } from "@/contracts/vocabularies";
import { isValueBearing } from "@/contracts/validity";
import { formatDecimal, humanizeCode } from "@/lib/format";
import { GRANULARITY_LABEL, PERIOD_LABEL, type ViewScope } from "@/lib/scope";
import { cn } from "@/lib/utils";

/**
 * Rolling-window performance — Area 2's "rolling returns", and the C5 completion follow-up's
 * half of it.
 *
 * FOUR THINGS THIS PANEL EXISTS SO A READER CANNOT GET WRONG.
 *
 *   A LOOKBACK IS NOT A PERIOD        the period is the extent the series covers; the
 *                                     lookback is how far each point looks back inside it.
 *                                     Both are stated, side by side, in every heading — a
 *                                     three-month extent under a 126-period lookback is a
 *                                     legitimate request whose every point is insufficient
 *   AN UNAVAILABLE POINT IS NOT ZERO  a point below the minimum, and a point whose window
 *                                     spans a session nobody observed, are two DIFFERENT
 *                                     absences and neither one is a number. The line breaks
 *                                     at both, and the table names which
 *   THE LOOKBACK COUNTS PERIODS       of the granularity actually served. It is never
 *                                     restated as a calendar duration, because twenty-one
 *                                     periods of a monthly series are twenty-one months
 *   THE CHART IS NOT THE ONLY ACCESS  a keyboard-reachable table carries the same points,
 *                                     with the same states (U10)
 */

const MEASURES = ["return", "drawdown"] as const;
type RollingMeasure = (typeof MEASURES)[number];

const MEASURE_LABEL: Readonly<Record<RollingMeasure, string>> = {
  return: "Rolling return",
  drawdown: "Rolling max drawdown",
};

interface RollingRow {
  readonly t: string;
  readonly value: number | null;
  readonly metric: MetricValue;
}

function seriesFor(window: RollingWindow, measure: RollingMeasure): Series {
  return measure === "return" ? window.return_series : window.drawdown_series;
}

/**
 * A number for the plot, and the decimal string for everything a reader sees.
 *
 * A point that carries no value plots as `null`, which Recharts draws as a BREAK. It is
 * never coerced to zero: "do not treat insufficient history as zero" is the whole reason
 * this panel carries three states rather than one.
 */
function plotValue(metric: MetricValue): number | null {
  if (!isValueBearing(metric.availability) || typeof metric.value !== "string") {
    return null;
  }
  const parsed = Number(metric.value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildRows(series: Series): readonly RollingRow[] {
  return series.points.map((point) => ({
    t: String(point.t),
    value: plotValue(point.v),
    metric: point.v,
  }));
}

/**
 * How many points carry a value, and how many carry each kind of absence.
 *
 * THE TWO ABSENCES ARE COUNTED SEPARATELY BECAUSE THEY MEAN DIFFERENT THINGS. One says the
 * extent has not reached back far enough yet; the other says a session inside the window was
 * never observed. Merging them into "unavailable" would let a reader conclude the first
 * where the second is true. The second bucket carries the state and reason it actually
 * arrived with rather than a label this component chose for it.
 */
function tally(series: Series): {
  readonly valued: number;
  readonly belowMinimum: number;
  readonly missing: number;
  readonly missingState: AvailabilityState | undefined;
  readonly missingReason: FieldReasonCode | undefined;
} {
  let valued = 0;
  let belowMinimum = 0;
  let missing = 0;
  let missingState: AvailabilityState | undefined;
  let missingReason: FieldReasonCode | undefined;
  for (const point of series.points) {
    if (isValueBearing(point.v.availability)) {
      valued += 1;
    } else if (point.v.reason === "BELOW_MINIMUM_OBSERVATIONS") {
      belowMinimum += 1;
    } else {
      missing += 1;
      missingState ??= point.v.availability;
      missingReason ??= point.v.reason;
    }
  }
  return { valued, belowMinimum, missing, missingState, missingReason };
}

function RollingTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: readonly { payload: RollingRow }[];
  label?: string | number;
}) {
  if (active !== true || payload === undefined || payload.length === 0) {
    return null;
  }
  const row = payload[0].payload;
  return (
    <div className="rounded-sm border border-border-subtle bg-surface-overlay px-3 py-2 shadow-elevation-2">
      <p className="font-mono text-label-s text-text-tertiary">{String(label)}</p>
      {row.value === null ? (
        <UnavailableInline metric={row.metric} />
      ) : (
        <p className="font-mono text-numeric-s text-text-primary">
          {formatDecimal(String(row.metric.value), {
            minimumFractionDigits: 2,
            signed: true,
          }) ?? String(row.metric.value)}{" "}
          %
        </p>
      )}
    </div>
  );
}

export interface RollingSeriesPanelProps {
  readonly envelope: EnvelopeOf<PerformanceSeriesPayload> | undefined;
  readonly scope: ViewScope;
  readonly operator: boolean;
}

export function RollingSeriesPanel({ envelope, scope, operator }: RollingSeriesPanelProps) {
  const [measure, setMeasure] = React.useState<RollingMeasure>("return");
  const [lookbackIndex, setLookbackIndex] = React.useState(0);
  const [tableOpen, setTableOpen] = React.useState(false);

  const payload = envelope?.payload;
  const windows = payload?.rolling_windows ?? [];
  const selected = windows[Math.min(lookbackIndex, Math.max(0, windows.length - 1))];
  const series = selected === undefined ? undefined : seriesFor(selected, measure);
  const rows = React.useMemo(() => (series === undefined ? [] : buildRows(series)), [series]);
  const counts = series === undefined ? undefined : tally(series);
  const granularityLabel = GRANULARITY_LABEL[scope.granularity].toLowerCase();

  return (
    <Card data-testid="rolling-windows">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label as="h2">Rolling-window performance</Label>
          <p className="mt-0.5 max-w-3xl text-label-m leading-relaxed text-text-secondary">
            Each point measures the trailing lookback ending at <strong>that</strong> point,
            using only observations up to it. A point with too little history behind it, and a
            point whose window spans a session nobody observed, are two different absences —
            and neither is a zero.
          </p>
        </div>
        {envelope !== undefined && payload !== undefined && (
          <ProvenanceBadge provenance={envelope.provenance} />
        )}
      </CardHeader>

      {envelope === undefined ? (
        <CardBody>
          <div className="skeleton-shape h-56 w-full" data-testid="skeleton" />
          <span className="sr-only">Loading the rolling-window series</span>
        </CardBody>
      ) : payload === undefined ? (
        <CardBody>
          <UnavailableBody
            state={envelope.availability}
            reason={envelope.availability_reason}
            dependency="the portfolio valuation projection and its recorded equity history"
          />
        </CardBody>
      ) : selected === undefined || series === undefined || counts === undefined ? (
        <CardBody>
          <AvailabilityBadge state="NOT_YET_AVAILABLE" reason="UPSTREAM_INPUT_MISSING" />
          <p className="mt-3 max-w-3xl text-label-m leading-relaxed text-text-tertiary">
            The producer served no rolling window over this extent. Nothing is derived here
            in its place: a screen that computes its own rolling metric is reporting a
            different metric under the same name.
          </p>
        </CardBody>
      ) : (
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div
              role="group"
              aria-label="Rolling lookback"
              className="flex flex-wrap gap-1"
              data-testid="lookback-selector"
            >
              {windows.map((window, index) => (
                <Button
                  key={String(window.lookback.value)}
                  size="sm"
                  variant={index === lookbackIndex ? "primary" : "subtle"}
                  aria-pressed={index === lookbackIndex}
                  onClick={() => setLookbackIndex(index)}
                  title={`A trailing window of ${String(window.lookback.value)} ${granularityLabel} periods`}
                >
                  {String(window.lookback.value)} periods
                </Button>
              ))}
            </div>
            <div role="group" aria-label="Rolling measure" className="flex flex-wrap gap-1">
              {MEASURES.map((candidate) => (
                <Button
                  key={candidate}
                  size="sm"
                  variant={candidate === measure ? "primary" : "subtle"}
                  aria-pressed={candidate === measure}
                  onClick={() => setMeasure(candidate)}
                >
                  {MEASURE_LABEL[candidate]}
                </Button>
              ))}
            </div>
          </div>

          {/*
            * THE TWO NUMBERS A READER MUST NEVER CONFUSE, printed beside each other rather
            * than in two different corners of the page.
            */}
          <dl
            className="flex flex-wrap gap-x-5 gap-y-1 text-label-s text-text-tertiary"
            data-testid="rolling-basis"
          >
            <div className="flex gap-1.5">
              <dt>Requested extent</dt>
              <dd className="text-text-secondary" data-testid="rolling-extent">
                {PERIOD_LABEL[scope.period]} · {series.coverage.requested} {granularityLabel}{" "}
                periods
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Rolling lookback</dt>
              <dd className="font-mono text-text-secondary" data-testid="rolling-lookback">
                {String(selected.lookback.value)} {granularityLabel} periods
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Minimum observations</dt>
              <dd className="font-mono text-text-secondary">
                {String(selected.minimum_observations.value)}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Observation unit</dt>
              <dd className="text-text-secondary">{humanizeCode(selected.observation_unit)}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>Population</dt>
              <dd className="text-text-secondary">{humanizeCode(selected.population.code)}</dd>
            </div>
          </dl>

          <div
            className="h-56 w-full sm:h-64"
            role="img"
            aria-label={`${MEASURE_LABEL[measure]} over a trailing ${String(
              selected.lookback.value,
            )}-period window, ${counts.valued} of ${series.points.length} points computed. A table of the same values follows.`}
            data-testid={`rolling-chart-${measure}`}
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
                  tickFormatter={(value: number) => `${value.toFixed(1)}%`}
                  width={56}
                  domain={["auto", "auto"]}
                />
                <Tooltip
                  content={<RollingTooltip />}
                  cursor={{ stroke: "var(--color-border-strong)" }}
                />
                <ReferenceLine y={0} stroke="var(--color-border-strong)" />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={
                    measure === "drawdown" ? "var(--color-negative)" : "var(--color-accent)"
                  }
                  strokeWidth={1.75}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* THE THREE OUTCOMES, COUNTED. A reader can see how much of the line is real. */}
          <div className="flex flex-wrap items-center gap-2" data-testid="rolling-tally">
            <Badge tone="neutral">{counts.valued} computed</Badge>
            {counts.belowMinimum > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <AvailabilityBadge
                  state="INSUFFICIENT_OBSERVATIONS"
                  reason="BELOW_MINIMUM_OBSERVATIONS"
                />
                <span className="text-label-m text-text-tertiary">
                  {counts.belowMinimum} points have fewer than{" "}
                  {String(selected.lookback.value)} earlier observations in this extent
                </span>
              </span>
            )}
            {counts.missing > 0 && counts.missingState !== undefined && (
              <span className="inline-flex items-center gap-1.5">
                <AvailabilityBadge
                  state={counts.missingState}
                  reason={counts.missingReason}
                />
                <span className="text-label-m text-text-tertiary">
                  {counts.missing} points span a session that carries no observation, so the
                  window they name was never fully observed
                </span>
              </span>
            )}
          </div>

          {counts.valued === 0 && (
            <p
              className="max-w-3xl text-label-m leading-relaxed text-text-tertiary"
              data-testid="rolling-none-computed"
            >
              <strong className="text-text-secondary">
                No point in this extent has a complete window behind it.
              </strong>{" "}
              The extent carries {series.coverage.requested} {granularityLabel} periods and
              the lookback needs {String(selected.lookback.value)} earlier ones plus the
              point itself. That is the correct answer to what was asked — a shorter window
              is not silently substituted, and nothing is drawn.
            </p>
          )}

          {/* U10 — the same points, the same states, reachable by keyboard. */}
          <details
            className="rounded-sm border border-border-subtle bg-surface-sunken"
            onToggle={(event) => setTableOpen(event.currentTarget.open)}
            data-testid="rolling-table-disclosure"
          >
            <summary className="cursor-pointer px-3 py-2 text-label-m text-text-secondary">
              {MEASURE_LABEL[measure]} as a table ({series.points.length} periods)
            </summary>
            <div className="px-3 pb-3">
              {tableOpen && (
                <ScrollRegion
                  label={`${MEASURE_LABEL[measure]} by period`}
                  className="max-h-64 overflow-y-auto"
                >
                  <table className="w-full min-w-[24rem] border-collapse text-label-m">
                    <caption className="sr-only">
                      {MEASURE_LABEL[measure]} over a trailing{" "}
                      {String(selected.lookback.value)}-period window, for each observed
                      period, in percent. A period with no value states why.
                    </caption>
                    <thead>
                      <tr className="border-b border-border-subtle text-left">
                        <th scope="col" className="py-1.5 pr-3 font-medium text-text-tertiary">
                          Period
                        </th>
                        <th scope="col" className="py-1.5 font-medium text-text-tertiary">
                          {MEASURE_LABEL[measure]} (%)
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
                          <td className={cn("py-1", row.value === null && "text-unavailable")}>
                            <MetricText metric={row.metric} operator={operator} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollRegion>
              )}
            </div>
          </details>

          <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            <strong className="text-text-secondary">
              A rolling window is not the period selector.
            </strong>{" "}
            Changing the period changes the extent the series is requested over; changing the
            lookback changes how far back each point inside it looks. The rolling return is{" "}
            <span className="font-mono">return.rolling</span> and the whole-window return is{" "}
            <span className="font-mono">return.time_weighted</span> — two identifiers, because
            they are two quantities.
          </p>
        </CardBody>
      )}
    </Card>
  );
}
