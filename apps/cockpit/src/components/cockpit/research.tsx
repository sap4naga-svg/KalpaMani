"use client";

import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ErrorBar,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { ReferenceChip } from "@/components/cockpit/read-model-panel";
import { ReferenceDestinations } from "@/components/cockpit/reference-links";
import { isValueBearing } from "@/contracts/validity";
import type { MetricValue, ReasonCoded, Ref, RefList } from "@/contracts/values";
import { formatDecimal, humanizeCode } from "@/lib/format";
import type { ViewScope } from "@/lib/scope";
import { cn } from "@/lib/utils";

/**
 * The presentation pieces every C7 screen shares.
 *
 * They exist once because the same four things happen on nine screens, and nine copies is
 * nine chances for one of them to drift:
 *
 *   A CLOSED CODE IS RENDERED AS PROSE       and never as an empty cell. A list with no
 *                                            members says so in a sentence
 *   AN EVALUATION CLASS TRAVELS WITH ITS     `EXPLORATORY_REUSE` is visually distinct from
 *   RESULT                                   `CONFIRMATORY`, and reuse is never displayed as
 *                                            fresh out-of-sample evidence
 *   A CHART HAS A TABLE                      the same numbers, keyboard-reachable and
 *                                            screen-reader-readable (U10)
 *   A REFERENCE OFFERS ITS TWO DESTINATIONS  the record and the owning area, as distinct
 *                                            controls that are never merged (§4.3.2)
 *
 * **NOTHING IN THIS MODULE ACTS.** There is no button that submits, advances, approves,
 * registers, launches or promotes anything; every control here filters, sorts or discloses.
 */

/** A list of closed-vocabulary codes. An empty list is a sentence, never a blank. */
export function ReasonList({
  codes,
  empty,
  tone = "neutral",
  testId,
}: {
  codes: readonly ReasonCoded[];
  empty: string;
  tone?: React.ComponentProps<typeof Badge>["tone"];
  testId?: string;
}) {
  if (codes.length === 0) {
    return (
      <p className="text-label-s text-text-tertiary" data-testid={testId}>
        {empty}
      </p>
    );
  }
  return (
    <ul className="flex flex-wrap gap-1.5" data-testid={testId}>
      {codes.map((code) => (
        <li key={code.code}>
          <Badge tone={tone} data-code={code.code}>
            {humanizeCode(code.code)}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

const CLASS_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  CONFIRMATORY: "info",
  EXPLORATORY_REUSE: "warning",
  DETERMINISTIC_REPRODUCTION: "neutral",
};

const CLASS_MEANING: Readonly<Record<string, string>> = {
  CONFIRMATORY:
    "Eligible only against an untouched holdout, new forward evidence, or a separately governed reuse methodology. The only class that may be described as out-of-sample confirmation.",
  EXPLORATORY_REUSE:
    "A further look at data the ledger already records as exposed. Disclosed, and NEVER presented as fresh out-of-sample evidence.",
  DETERMINISTIC_REPRODUCTION:
    "Re-executing a frozen prior run at its exact manifest, seeds and code identity. It confirms reproducibility and NOTHING ELSE, and it consumes no trial budget.",
};

/** The declared evaluation class, with what it may and may not claim. */
export function EvaluationClassBadge({
  evaluationClass,
  className,
}: {
  evaluationClass: string;
  className?: string;
}) {
  return (
    <Badge
      tone={CLASS_TONE[evaluationClass] ?? "neutral"}
      className={className}
      data-evaluation-class={evaluationClass}
      title={CLASS_MEANING[evaluationClass] ?? ""}
    >
      <span aria-hidden="true">◆</span>
      <span>{humanizeCode(evaluationClass)}</span>
    </Badge>
  );
}

/**
 * The exposure disclosure a result rests on.
 *
 * §2.7.1: "every downstream comparison, packet and report carries the disclosure". An empty
 * disclosure on a first confirmatory touch is a true statement and is written out as one.
 */
export function ExposureDisclosure({
  disclosure,
  testId,
}: {
  disclosure: readonly ReasonCoded[];
  testId?: string;
}) {
  return (
    <div className="space-y-1" data-testid={testId ?? "exposure-disclosure"}>
      <Label>Data exposure disclosure</Label>
      <ReasonList
        codes={disclosure}
        tone="warning"
        empty="This evidence rests on no recorded reuse: the locked set was untouched when it was evaluated."
      />
    </div>
  );
}

/** A labelled measure row set, for a definition list of `MetricValue`s. */
export function MeasureList({
  entries,
  operator = false,
  columns = 3,
  testId,
}: {
  entries: readonly { readonly label: string; readonly value: MetricValue; readonly denominator?: string }[];
  operator?: boolean;
  columns?: 2 | 3 | 4;
  testId?: string;
}) {
  const grid =
    columns === 2
      ? "sm:grid-cols-2"
      : columns === 4
        ? "sm:grid-cols-2 lg:grid-cols-4"
        : "sm:grid-cols-2 lg:grid-cols-3";
  return (
    <dl className={cn("grid gap-3", grid)} data-testid={testId}>
      {entries.map((entry) => (
        <div key={entry.label} className="flex flex-col gap-0.5">
          {/*
            * THE LABEL IS HUMANIZED HERE, ONCE.
            *
            * Call sites pass the closed code they hold, so an underscored token cannot reach a
            * heading on one screen and a readable phrase on another.
            */}
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            {humanizeCode(entry.label)}
          </dt>
          <dd>
            <MetricText
              metric={entry.value}
              denominator={entry.denominator}
              operator={operator}
            />
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** One row of a measure comparison: a label, a value, and an optional uncertainty. */
export interface ComparisonRow {
  readonly label: string;
  readonly value: MetricValue;
  /** The half-width of a stated interval, in the SAME unit as the value. */
  readonly uncertainty?: MetricValue;
  /** A secondary figure shown beside the bar, such as an arm's population. */
  readonly context?: MetricValue;
}

function numericOf(metric: MetricValue): number | null {
  if (!isValueBearing(metric.availability)) {
    return null;
  }
  if (typeof metric.value === "number") {
    return Number.isFinite(metric.value) ? metric.value : null;
  }
  if (typeof metric.value !== "string") {
    return null;
  }
  const parsed = Number(metric.value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * A horizontal comparison chart, with the same numbers in a table beneath it.
 *
 * FOUR RULES, and each one has been broken by a chart somewhere:
 *
 *   AN ABSENCE IS NOT A ZERO BAR       a row whose value is unavailable is EXCLUDED from the
 *                                      plot and stated in the table with its own state. A bar
 *                                      at zero reads as a measured zero
 *   UNCERTAINTY IS DRAWN               where a row carries one, it is an error bar and a
 *                                      column, not a footnote
 *   THE CHART IS NOT THE ONLY ACCESS   the table carries the same values, is reachable by
 *                                      keyboard and is read by a screen reader (U10)
 *   EVERY NUMBER KEEPS ITS UNIT        the table renders `MetricText`, so unit, sign and
 *                                      availability travel with the figure (U19, U11)
 */
export function ComparisonChart({
  caption,
  rows,
  unitLabel,
  contextLabel,
  testId,
}: {
  caption: string;
  rows: readonly ComparisonRow[];
  unitLabel: string;
  contextLabel?: string;
  testId?: string;
}) {
  const plotted = rows
    .map((row) => ({
      row,
      value: numericOf(row.value),
      error: row.uncertainty === undefined ? null : numericOf(row.uncertainty),
    }))
    .filter((entry): entry is { row: ComparisonRow; value: number; error: number | null } =>
      entry.value !== null,
    );
  const omitted = rows.length - plotted.length;
  const data = plotted.map((entry) => ({
    name: humanizeCode(entry.row.label),
    value: entry.value,
    error: entry.error ?? 0,
  }));

  return (
    <div className="space-y-2" data-testid={testId}>
      {data.length === 0 ? (
        <p
          className="rounded-sm border border-border-subtle bg-surface-sunken px-3 py-4 text-label-m text-text-tertiary"
          data-testid="chart-no-plottable-values"
        >
          No row carries a value, so nothing is plotted. Every row and its state is in the
          table below — an unavailable measure is never drawn as a bar at zero.
        </p>
      ) : (
        <div
          className="h-48 w-full sm:h-56"
          role="img"
          aria-label={`${caption}. ${data.length} of ${rows.length} rows carry a value, in ${unitLabel}. A table of the same values follows.`}
          data-testid="comparison-chart-plot"
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 4, right: 16, bottom: 0, left: 8 }}
            >
              <CartesianGrid
                stroke="var(--color-border-subtle)"
                strokeDasharray="2 4"
                horizontal={false}
              />
              <XAxis
                type="number"
                tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
                stroke="var(--color-border-subtle)"
              />
              <YAxis
                type="category"
                dataKey="name"
                width={168}
                tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
                stroke="var(--color-border-subtle)"
              />
              <ReferenceLine x={0} stroke="var(--color-border-strong)" />
              <Tooltip
                cursor={{ fill: "var(--color-surface-sunken)" }}
                contentStyle={{
                  background: "var(--color-surface-overlay)",
                  border: "1px solid var(--color-border-strong)",
                  borderRadius: "4px",
                  fontSize: "12px",
                }}
                formatter={(value) => [`${String(value)} ${unitLabel}`, caption]}
              />
              <Bar dataKey="value" radius={2} isAnimationActive={false}>
                {data.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={entry.value < 0 ? "var(--color-negative)" : "var(--color-accent)"}
                  />
                ))}
                <ErrorBar
                  dataKey="error"
                  width={4}
                  strokeWidth={1}
                  stroke="var(--color-text-tertiary)"
                  direction="x"
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {omitted > 0 && data.length > 0 && (
        <p className="text-label-s text-text-tertiary" data-testid="chart-omitted-rows">
          <strong className="text-text-secondary">{omitted}</strong> of {rows.length} rows
          carry no value and are not plotted. Each is stated with its own availability in the
          table below; an unavailable measure is never drawn as a bar at zero.
        </p>
      )}

      <ScrollRegion label={caption} className="rounded-sm border border-border-subtle">
        <table className="w-full min-w-[26rem] border-collapse text-label-m">
          <caption className="sr-only">
            {caption}. The same values the chart plots, in {unitLabel}, with the availability
            of every row that carries none.
          </caption>
          <thead className="bg-surface-sunken">
            <tr className="border-b border-border-subtle text-left text-text-tertiary">
              <th scope="col" className="px-3 py-2 font-medium">
                Measure
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Value
              </th>
              {rows.some((row) => row.uncertainty !== undefined) && (
                <th scope="col" className="px-3 py-2 font-medium">
                  Stated uncertainty
                </th>
              )}
              {contextLabel !== undefined && (
                <th scope="col" className="px-3 py-2 font-medium">
                  {contextLabel}
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.label}
                className="border-b border-border-subtle last:border-0"
                data-measure={row.label}
              >
                <th
                  scope="row"
                  className="px-3 py-1.5 text-left font-normal text-text-secondary"
                >
                  {humanizeCode(row.label)}
                </th>
                <td className="px-3 py-1.5">
                  <MetricText metric={row.value} />
                </td>
                {rows.some((entry) => entry.uncertainty !== undefined) && (
                  <td className="px-3 py-1.5">
                    {row.uncertainty === undefined ? (
                      <span className="text-text-tertiary">—</span>
                    ) : (
                      <MetricText metric={row.uncertainty} neutral />
                    )}
                  </td>
                )}
                {contextLabel !== undefined && (
                  <td className="px-3 py-1.5">
                    {row.context === undefined ? (
                      <span className="text-text-tertiary">—</span>
                    ) : (
                      <MetricText metric={row.context} neutral />
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
    </div>
  );
}

/**
 * A reference, with both of its destinations.
 *
 * **The two controls are distinct and are never merged** (§4.3.2). The target control names
 * the record; the area control names the AREA and says so, and it never reads as retrieving
 * the artefact. A reference may offer both, one, or neither.
 */
export function ReferenceRow({
  reference,
  label,
  scope,
  testId,
}: {
  reference: Ref;
  label?: string;
  scope: ViewScope;
  testId?: string;
}) {
  return (
    <span
      className="inline-flex flex-wrap items-center gap-2"
      data-testid={testId ?? "reference-row"}
    >
      <ReferenceChip reference={reference} label={label} />
      <span className="font-mono text-label-s text-text-tertiary">{reference.ref_id}</span>
      <span className="inline-flex flex-wrap items-center gap-2 text-label-s">
        <ReferenceDestinations reference={reference} scope={scope} />
      </span>
    </span>
  );
}

/** A reference list, with its population count and every member's destinations. */
export function ReferenceListPanel({
  list,
  label,
  scope,
  empty,
  testId,
}: {
  list: RefList;
  label: string;
  scope: ViewScope;
  empty: string;
  testId?: string;
}) {
  return (
    <div className="space-y-1.5" data-testid={testId}>
      <div className="flex flex-wrap items-baseline gap-2">
        <Label>{label}</Label>
        <span className="text-label-s text-text-tertiary">
          <MetricText metric={list.total} neutral /> in the population
          {list.truncated && <strong className="ml-1 text-warning">· page truncated</strong>}
        </span>
      </div>
      {list.items.length === 0 ? (
        <p className="text-label-s text-text-tertiary">{empty}</p>
      ) : (
        <ul className="space-y-1">
          {list.items.map((reference) => (
            <li key={`${reference.ref_kind}-${reference.ref_id}`}>
              <ReferenceRow reference={reference} scope={scope} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The standing statement every C7 screen carries.
 *
 * **A screen that reads a loop must say that it does not drive it**, and it says so once, in
 * one component, so the sentence cannot drift between nine pages.
 */
export function ReadOnlyNotice({
  subject,
  actions,
  testId,
}: {
  subject: string;
  /** The specific verbs this screen deliberately does not offer. */
  actions: readonly string[];
  testId?: string;
}) {
  return (
    <p
      className="max-w-3xl rounded-sm border border-border-subtle bg-surface-sunken px-3 py-2 text-label-s leading-relaxed text-text-tertiary"
      data-testid={testId ?? "read-only-notice"}
    >
      <strong className="text-text-secondary">This screen reads {subject}.</strong> It has no{" "}
      {actions.join(", ")} control, and no such control exists anywhere in this application.
      Every figure below is a repository-owned synthetic record: <strong>backtesting has not
      started</strong>, no research engine, learning engine, shadow runner or AI agent exists,
      and <strong>no value here is a result, an approval or an authorization</strong>.
    </p>
  );
}

/** An availability statement for a whole section, with its reason code. */
export function SectionState({
  availability,
  reason,
  note,
  testId,
}: {
  availability: React.ComponentProps<typeof AvailabilityBadge>["state"];
  reason: React.ComponentProps<typeof AvailabilityBadge>["reason"];
  note: string;
  testId?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={testId}>
      <AvailabilityBadge state={availability} reason={reason} />
      <span className="max-w-2xl text-label-s leading-relaxed text-text-tertiary">{note}</span>
    </div>
  );
}

/** A decimal string rendered for a compact inline count. Never a parsed float. */
export function CompactDecimal({ value }: { value: string }) {
  return <span className="font-mono tabular-nums">{formatDecimal(value) ?? value}</span>;
}
