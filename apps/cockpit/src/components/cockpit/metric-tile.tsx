"use client";

import * as React from "react";

import { Card, CardBody, Label, Numeric } from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { isValueBearing } from "@/contracts/validity";
import type { MetricValue } from "@/contracts/values";
import type { DataProvenance, Unit } from "@/contracts/vocabularies";
import { decimalSign, formatDecimal } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The displayed unit for every unit vocabulary member.
 *
 * EVERY DISPLAYED METRIC SHOWS ITS UNIT (U19). A bare number is not a metric.
 */
const UNIT_SUFFIX: Readonly<Record<Unit, string>> = {
  USD: "USD",
  RATIO: "ratio",
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

const SIGNED_UNITS: readonly Unit[] = ["USD", "PERCENT", "R_MULTIPLE"];

/**
 * The displayed text for a metric's value, or `null` when there is no honest rendering.
 *
 * It never calls `String(value)`. A `String()` fallback turns `null` into "null", an object
 * into "[object Object]" and `NaN` into "NaN", and every one of those is rendered in the
 * same large numeral as a real measurement. Admission now refuses those payloads outright
 * (`contracts/values.ts`); this returns `null` so that even a value which somehow reached a
 * tile is shown as a failure rather than as a number.
 */
function formatValue(value: unknown, unit: Unit, directional: boolean): string | null {
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
  // A closed-vocabulary token is displayed as itself; only digits are formatted as digits.
  return decimal ?? value;
}

/**
 * Signed, and never coloured alone.
 *
 * A positive value shows its sign where sign is meaningful, and COLOUR IS NEVER THE ONLY
 * CARRIER OF DIRECTION (U11) -- the sign character carries it too.
 */
function toneFor(value: unknown, unit: Unit, directional: boolean): string {
  if (!directional || !SIGNED_UNITS.includes(unit)) {
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

export interface MetricTileProps {
  readonly label: string;
  readonly metric: MetricValue;
  readonly provenance: DataProvenance;
  /** Named when the metric is unavailable, so a reader knows what it waits on. */
  readonly dependency?: string;
  /** Operator mode exposes reason codes, metric ids and versions. */
  readonly operator?: boolean;
  readonly size?: "xl" | "l" | "m";
  readonly className?: string;
  /** A ratio states its denominator, or its NOT_APPLICABLE state (U19). */
  readonly denominator?: string;
  /**
   * The value is a MAGNITUDE rather than a direction.
   *
   * `MetricText` has made this distinction since C5 and this tile did not, so a fill rate of
   * 100% rendered as `+100.00 %` — a leading plus is a claim about DIRECTION, and a fill rate
   * is neither a gain nor a loss. Marking a tile neutral drops the profit colouring and the
   * leading plus, and keeps a minus where one belongs.
   */
  readonly neutral?: boolean;
}

/**
 * One tile, with its own availability.
 *
 * A FAILING WIDGET DOES NOT FAIL THE PAGE (U6): each tile renders its own availability and
 * the page reports itself PARTIAL when any widget is degraded.
 */
export function MetricTile({
  label,
  metric,
  provenance,
  dependency,
  operator = false,
  size = "l",
  className,
  denominator,
  neutral = false,
}: MetricTileProps) {
  const bearing = isValueBearing(metric.availability);
  const rendered = bearing ? formatValue(metric.value, metric.unit, !neutral) : null;
  /*
   * A value-bearing metric whose value has no honest rendering is a FAILURE, not a blank
   * numeral. Admission refuses such a payload before it reaches here; this is the second
   * line, and it fails closed rather than printing whatever `String()` would have produced.
   */
  const unrenderable = bearing && rendered === null;
  return (
    <Card className={cn("flex h-full flex-col", className)} data-testid={`tile-${metric.metric_id}`}>
      <CardBody className="flex flex-1 flex-col gap-2 pt-4">
        <div className="flex items-start justify-between gap-2">
          <Label className="min-w-0 break-words">{label}</Label>
          {/*
            * Provenance answers "where did this number come from". An absence carries no
            * number, so it carries no provenance either -- the state, its reason code and
            * its named dependency are the whole answer.
            */}
          {bearing && !unrenderable && (
            <ProvenanceBadge provenance={provenance} className="shrink-0" />
          )}
        </div>

        {bearing && !unrenderable ? (
          <>
            <div className="flex items-baseline gap-1.5">
              <Numeric size={size} className={toneFor(metric.value, metric.unit, !neutral)}>
                {rendered}
              </Numeric>
              {UNIT_SUFFIX[metric.unit] !== "" && (
                <span className="text-label-m text-text-tertiary">
                  {UNIT_SUFFIX[metric.unit]}
                </span>
              )}
            </div>
            {/* STALE and PARTIAL are answers WITH a qualification, never rendered as clean. */}
            {metric.availability !== "AVAILABLE" && (
              <AvailabilityBadge
                state={metric.availability}
                reason={metric.reason}
                className="self-start"
              />
            )}
            {denominator !== undefined && (
              <p className="text-label-s text-text-tertiary">per {denominator}</p>
            )}
            {operator && (
              <dl className="mt-auto space-y-0.5 pt-2 font-mono text-label-s text-text-tertiary">
                <div className="flex gap-2">
                  <dt className="sr-only">Metric id</dt>
                  <dd>{metric.metric_id}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="sr-only">Reason code</dt>
                  <dd>{metric.reason}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="sr-only">As of</dt>
                  <dd>{metric.as_of}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="sr-only">Metric dictionary version</dt>
                  <dd>{metric.metric_definition_version}</dd>
                </div>
              </dl>
            )}
          </>
        ) : (
          <UnavailableBody
            state={unrenderable ? "ERROR" : metric.availability}
            reason={unrenderable ? "PROJECTION_ERROR" : metric.reason}
            dependency={dependency}
          />
        )}
      </CardBody>
    </Card>
  );
}

/** The shape-only loading tile. It carries NO digits and NO plausible placeholder value. */
export function MetricTileSkeleton({ label }: { label: string }) {
  return (
    <Card className="h-full">
      <CardBody className="space-y-3 pt-4">
        <Label>{label}</Label>
        <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
        <div className="skeleton-shape h-3 w-1/3" data-testid="skeleton" />
        <span className="sr-only">Loading</span>
      </CardBody>
    </Card>
  );
}
