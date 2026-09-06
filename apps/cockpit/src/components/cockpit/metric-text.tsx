"use client";

import * as React from "react";

import { Badge } from "@/components/ui/primitives";
import { STATE_PRESENTATION } from "@/components/cockpit/availability";
import { isValueBearing } from "@/contracts/validity";
import type { MetricValue } from "@/contracts/values";
import type { Unit } from "@/contracts/vocabularies";
import { decimalSign, formatDecimal, humanizeCode } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A metric, rendered INLINE — in a table cell, a definition list or a sentence.
 *
 * `MetricTile` is a card and answers a headline question; this answers the same question in
 * one line, under the same rules:
 *
 *   EVERY DISPLAYED METRIC SHOWS ITS UNIT (U19). A bare number is not a metric
 *   AN UNAVAILABLE METRIC SHOWS ITS STATE, never a zero, a dash or an empty cell
 *   COLOUR IS NEVER THE ONLY CARRIER OF DIRECTION (U11): the sign character carries it too
 *   A QUALIFIED VALUE KEEPS ITS QUALIFICATION — a `STALE` figure is shown as stale
 */

const UNIT_SUFFIX: Readonly<Record<Unit, string>> = {
  USD: "USD",
  RATIO: "",
  PERCENT: "%",
  BPS: "bps",
  SHARES: "sh",
  SECONDS: "s",
  TRADING_DAYS: "td",
  CALENDAR_DAYS: "d",
  COUNT: "",
  R_MULTIPLE: "R",
  DIMENSIONLESS: "",
};

const SIGNED_UNITS: readonly Unit[] = ["USD", "PERCENT", "R_MULTIPLE", "BPS"];

/**
 * A LEADING PLUS IS A CLAIM ABOUT DIRECTION, so only a directional quantity gets one.
 *
 * `+41.85 USD` beside an entry price reads as a gain of 41.85, and it is a price. The unit
 * says a value COULD be directional; `directional` says whether this particular field is —
 * profit and loss and a return are, and a price, a risk amount, a limit and a concentration
 * are magnitudes. A negative value always shows its minus sign, whichever it is.
 */
function renderValue(value: unknown, unit: Unit, directional: boolean): string | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value.toLocaleString("en-US") : null;
  }
  if (typeof value !== "string") {
    return null;
  }
  const decimal = formatDecimal(value, {
    minimumFractionDigits: unit === "USD" ? 2 : 0,
    signed: directional && SIGNED_UNITS.includes(unit),
  });
  /* A closed-vocabulary token is prose, not digits, and is humanized rather than formatted. */
  return decimal ?? humanizeCode(value);
}

function toneOf(value: unknown, unit: Unit): string {
  if (!SIGNED_UNITS.includes(unit)) {
    return "text-text-primary";
  }
  const sign =
    typeof value === "string"
      ? decimalSign(value)
      : typeof value === "number" && Number.isFinite(value)
        ? Math.sign(value)
        : 0;
  if (sign === 0) return "text-text-primary";
  return sign > 0 ? "text-positive" : "text-negative";
}

export interface MetricTextProps {
  readonly metric: MetricValue;
  /** A ratio states its denominator, or its unavailable state (U19). */
  readonly denominator?: string;
  /** Operator mode adds the metric id and the reason code. */
  readonly operator?: boolean;
  readonly className?: string;
  /**
   * The value is a MAGNITUDE rather than a direction.
   *
   * A price, a risk amount, a permitted limit, a share count and a concentration have no
   * profit sign: they are neither gains nor losses. Marking one neutral drops both the
   * profit colouring and the leading plus, and keeps a minus where one belongs.
   */
  readonly neutral?: boolean;
}

/** The compact unavailable marker: a glyph, the state, and the reason on hover. */
export function UnavailableInline({
  metric,
  className,
}: {
  metric: MetricValue;
  className?: string;
}) {
  const presentation = STATE_PRESENTATION[metric.availability];
  return (
    <span
      className={cn("inline-flex items-center gap-1 text-unavailable", className)}
      data-availability={metric.availability}
      data-reason={metric.reason}
      title={`${presentation.meaning} (${metric.reason})`}
    >
      <span aria-hidden="true">{presentation.glyph}</span>
      <span className="text-label-s">{presentation.label}</span>
    </span>
  );
}

export function MetricText({
  metric,
  denominator,
  operator = false,
  className,
  neutral = false,
}: MetricTextProps) {
  const bearing = isValueBearing(metric.availability);
  const rendered = bearing ? renderValue(metric.value, metric.unit, !neutral) : null;
  if (!bearing || rendered === null) {
    return <UnavailableInline metric={metric} className={className} />;
  }
  const suffix = UNIT_SUFFIX[metric.unit];
  return (
    <span
      className={cn("inline-flex flex-wrap items-baseline gap-1", className)}
      data-availability={metric.availability}
      data-metric={metric.metric_id}
    >
      <span
        className={cn(
          "font-mono tabular-nums",
          neutral ? "text-text-primary" : toneOf(metric.value, metric.unit),
        )}
      >
        {rendered}
      </span>
      {suffix !== "" && <span className="text-label-s text-text-tertiary">{suffix}</span>}
      {denominator !== undefined && (
        <span className="text-label-s text-text-tertiary">per {denominator}</span>
      )}
      {/* STALE and PARTIAL are answers WITH a qualification, never rendered as clean. */}
      {metric.availability !== "AVAILABLE" && (
        <Badge
          tone="warning"
          data-availability={metric.availability}
          data-reason={metric.reason}
          title={STATE_PRESENTATION[metric.availability].meaning}
        >
          <span aria-hidden="true">{STATE_PRESENTATION[metric.availability].glyph}</span>
          <span>{STATE_PRESENTATION[metric.availability].label}</span>
        </Badge>
      )}
      {operator && (
        <span className="font-mono text-label-s text-text-tertiary">
          {metric.metric_id} · {metric.reason}
        </span>
      )}
    </span>
  );
}

/**
 * A labelled metric row, for a definition list.
 *
 * The label, the value and the metadata are three separate elements, so a screen reader
 * reads a term and its definition rather than a run-on line.
 */
export function MetricRow({
  label,
  metric,
  denominator,
  operator,
  hint,
}: {
  label: string;
  metric: MetricValue;
  denominator?: string;
  operator?: boolean;
  hint?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5 py-1">
      <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">{label}</dt>
      <dd className="text-numeric-s">
        <MetricText metric={metric} denominator={denominator} operator={operator} />
        {hint !== undefined && (
          <p className="mt-0.5 text-label-s leading-relaxed text-text-tertiary">{hint}</p>
        )}
      </dd>
    </div>
  );
}

/** A `Money` value. It has no availability axis: a record that exists carries its amount. */
export function MoneyText({
  amount,
  className,
  signed = false,
}: {
  amount: string;
  className?: string;
  signed?: boolean;
}) {
  const formatted = formatDecimal(amount, { minimumFractionDigits: 2, signed });
  return (
    <span
      className={cn(
        "inline-flex items-baseline gap-1 font-mono tabular-nums",
        signed ? toneOf(amount, "USD") : "text-text-primary",
        className,
      )}
    >
      <span>{formatted ?? amount}</span>
      <span className="text-label-s text-text-tertiary">USD</span>
    </span>
  );
}
