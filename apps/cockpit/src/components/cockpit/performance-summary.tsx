"use client";

import * as React from "react";

import { Badge, ScrollRegion } from "@/components/ui/primitives";
import { MetricText } from "@/components/cockpit/metric-text";
import type { PerformanceSummaryPayload } from "@/contracts/portfolio-models";
import { humanizeCode } from "@/lib/format";

/**
 * A `PerformanceSummary`, rendered with the rules it was computed under.
 *
 * §12.5 is the whole reason this component shows so much beside each number:
 *
 *   DISPLAY SUFFICIENCY   the number has a definition, a unit, a denominator, a basis, a cost
 *                         treatment, a minimum-observation rule and a stated unavailable
 *                         outcome. That is what a summary provides
 *   EVIDENCE OF VALIDITY  preregistration, a named baseline, a locked out-of-sample
 *                         evaluation, tracked trials, multiple-testing control and a human
 *                         governance decision. **None of it has been run**
 *
 * **A metric that passes every rule here is still not a finding.** The panel says so, and the
 * observation rules are displayed rather than trusted, so a reader can check the sample rather
 * than accept the ratio.
 */

const RATIO_LABELS: readonly (readonly [
  keyof PerformanceSummaryPayload,
  string,
  string | undefined,
])[] = [
  ["total_return", "Time-weighted return", "chained sub-period beginning values"],
  ["max_drawdown", "Maximum drawdown", "running peak"],
  ["expectancy", "Expectancy", "trade count"],
  ["profit_factor", "Profit factor", "gross loss"],
  ["win_rate", "Win rate", "defined population"],
  ["sharpe", "Sharpe", "standard deviation of period returns"],
  ["average_winner", "Average winner", undefined],
  ["average_loser", "Average loser", undefined],
];

export function PerformanceSummaryPanel({
  summary,
  operator = false,
  testId,
  compact = false,
}: {
  summary: PerformanceSummaryPayload;
  operator?: boolean;
  testId?: string;
  compact?: boolean;
}) {
  return (
    <div className="space-y-3" data-testid={testId}>
      <dl
        className={
          compact
            ? "grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4"
            : "grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4"
        }
      >
        {RATIO_LABELS.map(([key, label, denominator]) => {
          const metric = summary[key];
          if (typeof metric !== "object" || metric === null || !("availability" in metric)) {
            return null;
          }
          return (
            <div key={String(key)} className="flex flex-col gap-0.5">
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                {label}
              </dt>
              <dd className="text-numeric-s">
                <MetricText
                  metric={metric}
                  denominator={denominator}
                  operator={operator}
                />
              </dd>
            </div>
          );
        })}
      </dl>

      {/* THE BASIS. Two summaries with different treatments are never compared. */}
      <dl className="flex flex-wrap gap-x-5 gap-y-1 text-label-s text-text-tertiary">
        <div className="flex gap-1.5">
          <dt>Population</dt>
          <dd className="text-text-secondary">
            {humanizeCode(summary.trade_population.code)}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Observations</dt>
          <dd className="font-mono text-text-secondary">
            {String(summary.observation_count.value ?? "—")}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Costs</dt>
          <dd className="text-text-secondary">{humanizeCode(summary.cost_treatment)}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Window</dt>
          <dd className="font-mono text-text-secondary">
            {summary.window.from.slice(0, 10)} → {summary.window.to.slice(0, 10)}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Calendar</dt>
          <dd className="text-text-secondary">{humanizeCode(summary.window.calendar.code)}</dd>
        </div>
      </dl>

      <ObservationRules summary={summary} />

      {summary.exclusions.length > 0 && (
        <div
          className="rounded-sm border border-warning/40 bg-warning/10 p-2.5"
          data-testid="population-exclusions"
        >
          <p className="text-label-s leading-relaxed text-warning">
            <strong>The population excludes rows, and they are counted.</strong> An average
            over a silently reduced population is a different metric.
          </p>
          <ul className="mt-1 space-y-0.5">
            {summary.exclusions.map((exclusion) => (
              <li key={exclusion.reason.code} className="text-label-s text-text-secondary">
                <span className="font-mono">{String(exclusion.count.value ?? "—")}</span>{" "}
                {humanizeCode(exclusion.reason.code)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!compact && (
        <p className="max-w-3xl border-t border-border-subtle pt-2.5 text-label-s leading-relaxed text-text-tertiary">
          <strong className="text-text-secondary">
            A metric that passes every rule here is still not a finding.
          </strong>{" "}
          These numbers are displayable — they have definitions, units, denominators, a stated
          cost treatment and declared minimum-observation rules. Evidence of validity is
          preregistration, a named baseline, a locked out-of-sample evaluation, tracked trials
          and a human governance decision, and <strong>none of it has been run</strong>.
        </p>
      )}
    </div>
  );
}

/** The declared minimum-observation rules, shown rather than trusted (§12.1). */
export function ObservationRules({
  summary,
}: {
  summary: PerformanceSummaryPayload;
}) {
  return (
    <ScrollRegion label="Minimum observation rules" data-testid="observation-rules">
      <table className="w-full min-w-[26rem] border-collapse text-label-s">
        <caption className="mb-1 text-left text-label-s text-text-tertiary">
          Every ratio declares a minimum and returns{" "}
          <span className="font-mono">INSUFFICIENT_OBSERVATIONS</span> below it. The counts are
          the ones each ratio was actually computed over.
        </caption>
        <thead>
          <tr className="border-b border-border-subtle text-left text-text-tertiary">
            <th scope="col" className="py-1 pr-3 font-medium">
              Metric
            </th>
            <th scope="col" className="py-1 pr-3 font-medium">
              Counts
            </th>
            <th scope="col" className="py-1 pr-3 font-medium">
              Observed
            </th>
            <th scope="col" className="py-1 pr-3 font-medium">
              Minimum
            </th>
            <th scope="col" className="py-1 font-medium">
              Met
            </th>
          </tr>
        </thead>
        <tbody>
          {summary.observation_rules.map((rule) => (
            <tr
              key={rule.metric_id}
              className="border-b border-border-subtle last:border-0"
              data-rule={rule.metric_id}
            >
              <th scope="row" className="py-1 pr-3 text-left font-mono font-normal text-text-secondary">
                {rule.metric_id}
              </th>
              <td className="py-1 pr-3 text-text-tertiary">
                {humanizeCode(rule.population.code)}
              </td>
              <td className="py-1 pr-3 font-mono text-text-secondary">
                {String(rule.observed.value ?? "—")}
              </td>
              <td className="py-1 pr-3 font-mono text-text-secondary">
                {String(rule.minimum.value ?? "—")}
              </td>
              <td className="py-1">
                <Badge tone={rule.met ? "positive" : "unavailable"}>
                  <span aria-hidden="true">{rule.met ? "●" : "◔"}</span>
                  <span>{rule.met ? "met" : "below minimum"}</span>
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/** The R-multiple distribution, as a labelled bar list rather than a chart. */
export function RMultipleDistribution({
  summary,
}: {
  summary: PerformanceSummaryPayload;
}) {
  const counts = summary.r_multiple_distribution.map((bucket) =>
    typeof bucket.count.value === "number" ? bucket.count.value : 0,
  );
  const largest = Math.max(1, ...counts);
  return (
    <ul className="space-y-1" data-testid="r-distribution">
      {summary.r_multiple_distribution.map((bucket, index) => (
        <li key={bucket.bucket.code} className="flex items-center gap-2">
          <span className="w-44 shrink-0 text-label-s text-text-tertiary">
            {humanizeCode(bucket.bucket.code)}
          </span>
          <span className="h-2.5 flex-1 overflow-hidden rounded-sm bg-surface-sunken">
            <span
              className="block h-full bg-accent"
              style={{ width: `${(counts[index] / largest) * 100}%` }}
              aria-hidden="true"
            />
          </span>
          <span className="w-10 shrink-0 text-right font-mono text-label-s text-text-secondary">
            {counts[index]}
          </span>
        </li>
      ))}
    </ul>
  );
}
