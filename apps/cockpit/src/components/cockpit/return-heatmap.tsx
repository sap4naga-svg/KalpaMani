"use client";

import * as React from "react";

import { ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import type { Series } from "@/contracts/values";
import { decimalSign, formatDecimal } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The monthly return heat map.
 *
 * IT IS A LAYOUT OF PRODUCED VALUES, NOT A COMPUTATION. Every cell is one point of the
 * `period_return_series` the producer supplied at monthly granularity, placed in a year row
 * and a month column. Nothing here chains, compounds, annualizes or fills: a month the series
 * has no point for is a **blank cell that says so**, and it is never rendered as a zero.
 *
 * COLOUR IS NEVER THE ONLY CARRIER OF MEANING (U11): every cell shows its signed number, and
 * the sign is the primary cue. The tint is a secondary one.
 */

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

interface Cell {
  readonly value: string;
  readonly sign: -1 | 0 | 1;
  readonly magnitude: number;
}

function buildGrid(series: Series): {
  years: string[];
  cells: Map<string, Cell>;
  strongest: number;
} {
  const cells = new Map<string, Cell>();
  const years = new Set<string>();
  let strongest = 1;
  for (const point of series.points) {
    if (typeof point.v.value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(point.t)) {
      continue;
    }
    const year = point.t.slice(0, 4);
    const month = Number(point.t.slice(5, 7)) - 1;
    years.add(year);
    const magnitude = Math.abs(Number(point.v.value));
    strongest = Math.max(strongest, magnitude);
    cells.set(`${year}-${month}`, {
      value: point.v.value,
      sign: decimalSign(point.v.value),
      magnitude,
    });
  }
  return { years: [...years].sort(), cells, strongest };
}

export function ReturnHeatmap({
  series,
  granularity,
}: {
  series: Series;
  granularity: string;
}) {
  const { years, cells, strongest } = React.useMemo(() => buildGrid(series), [series]);

  if (granularity !== "MONTHLY") {
    return (
      <div className="space-y-2" data-testid="heatmap-wrong-granularity">
        <AvailabilityBadge state="NOT_APPLICABLE" reason="NOT_DEFINED_FOR_SUBJECT" />
        <p className="max-w-2xl text-label-m leading-relaxed text-text-tertiary">
          A monthly heat map needs monthly periods. The series currently requested is{" "}
          <strong className="text-text-secondary">{granularity.toLowerCase()}</strong>, and a
          monthly figure is <strong>not derived from it here</strong> — deriving one in a view
          would report a metric this application did not produce. Select the monthly
          granularity above to request it.
        </p>
      </div>
    );
  }

  if (years.length === 0) {
    return (
      <div className="space-y-2" data-testid="heatmap-empty">
        <AvailabilityBadge state="NOT_YET_AVAILABLE" reason="UPSTREAM_INPUT_MISSING" />
        <p className="text-label-m text-text-tertiary">
          The monthly series carries no dated point, so no cell can be placed.
        </p>
      </div>
    );
  }

  return (
    <ScrollRegion label="Monthly return heat map" data-testid="return-heatmap">
      <table className="w-full min-w-[40rem] border-separate border-spacing-0.5 text-label-s">
        <caption className="mb-2 text-left text-label-s leading-relaxed text-text-tertiary">
          Each cell is one produced monthly time-weighted return, in percent, on the named
          market calendar in UTC. A month with no observation is blank and is{" "}
          <strong className="text-text-secondary">not a zero</strong>.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="px-2 py-1 text-left font-medium text-text-tertiary">
              Year
            </th>
            {MONTHS.map((month) => (
              <th
                key={month}
                scope="col"
                className="px-2 py-1 text-right font-medium text-text-tertiary"
              >
                {month}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((year) => (
            <tr key={year}>
              <th
                scope="row"
                className="px-2 py-1 text-left font-mono font-normal text-text-secondary"
              >
                {year}
              </th>
              {MONTHS.map((month, index) => {
                const cell = cells.get(`${year}-${index}`);
                if (cell === undefined) {
                  return (
                    <td
                      key={month}
                      className="rounded-sm bg-surface-sunken px-2 py-1 text-right text-unavailable"
                      data-observed="false"
                    >
                      <span aria-hidden="true">·</span>
                      <span className="sr-only">No observation</span>
                    </td>
                  );
                }
                /*
                 * THE TINT STAYS DARK, AND THE NUMBER STAYS READABLE.
                 *
                 * A stronger tint lightens the cell until the coloured figure on it falls
                 * below the 4.5:1 contrast requirement — measured, not guessed: at 85% the
                 * positive cells came in at 1.9:1. The magnitude is carried by the SIGNED
                 * NUMBER, which every cell prints; the tint is a secondary cue and is capped
                 * where it stops being one.
                 */
                const intensity = Math.min(0.18, 0.04 + (cell.magnitude / strongest) * 0.14);
                return (
                  <td
                    key={month}
                    className={cn(
                      "rounded-sm px-2 py-1 text-right font-mono tabular-nums",
                      cell.sign > 0
                        ? "text-positive"
                        : cell.sign < 0
                          ? "text-negative"
                          : "text-text-secondary",
                    )}
                    style={{
                      backgroundColor:
                        cell.sign === 0
                          ? "var(--color-surface-sunken)"
                          : cell.sign > 0
                            ? `color-mix(in oklab, var(--color-positive) ${intensity * 100}%, var(--color-surface-sunken))`
                            : `color-mix(in oklab, var(--color-negative) ${intensity * 100}%, var(--color-surface-sunken))`,
                    }}
                    data-observed="true"
                  >
                    {formatDecimal(cell.value, { minimumFractionDigits: 2, signed: true }) ??
                      cell.value}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}
