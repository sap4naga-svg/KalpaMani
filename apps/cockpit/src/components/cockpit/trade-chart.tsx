"use client";

import * as React from "react";

import { Badge, Button, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MoneyText } from "@/components/cockpit/metric-text";
import type { Series } from "@/contracts/values";
import { cn } from "@/lib/utils";

/**
 * The trade price view, with its recorded markers.
 *
 * `ui-ux-specification.md` §13 assigns **price and trade overlays** to TradingView Lightweight
 * Charts, and this is that surface: entry, add, partial-exit and exit markers over the mark
 * path a trade actually recorded.
 *
 * FOUR THINGS IT IS CAREFUL ABOUT.
 *
 *   IT IS A MARK LINE, NOT OHLC        open, high, low and close need a market-data provider.
 *                                      **No provider is selected and G1 is OPEN**, so the
 *                                      chart draws one mark per session and says so. Drawing
 *                                      candles from a single mark would invent three prices
 *   ONLY RECORDED MARKERS ARE DRAWN    every marker comes from a lifecycle event that exists.
 *                                      A missing stage produces no marker and is listed as a
 *                                      gap instead — **a missing event is never inferred**
 *   THE CHART IS NOT THE ONLY ACCESS   a keyboard-reachable, screen-reader-readable table
 *                                      carries the same points and the same markers (U10)
 *   IT LOADS ONLY IN A BROWSER         the library is imported inside an effect, so the server
 *                                      render and the test environment touch no canvas and the
 *                                      table alternative is what they see
 */

export interface ChartMarker {
  /** The session the event was recorded on, as `YYYY-MM-DD`. */
  readonly day: string;
  readonly label: string;
  readonly kind: "ENTRY" | "ADD" | "PARTIAL_EXIT" | "EXIT";
  /** The recorded price, as a decimal string. */
  readonly price: string;
  readonly quantity: number;
}

export interface ChartLevel {
  readonly label: string;
  readonly price: string;
  readonly note: string;
}

const MARKER_GLYPH: Readonly<Record<ChartMarker["kind"], string>> = {
  ENTRY: "▲",
  ADD: "◆",
  PARTIAL_EXIT: "▽",
  EXIT: "▼",
};

/**
 * The short text a plot marker carries.
 *
 * The TABLE below shows the recorded event kind in full — `label` — because that is the fact.
 * A plot marker has room for a word, so it gets one; the two are the same event, and the
 * table is the one a screen reader reads.
 */
const MARKER_TEXT: Readonly<Record<ChartMarker["kind"], string>> = {
  ENTRY: "Entry",
  ADD: "Add",
  PARTIAL_EXIT: "Partial",
  EXIT: "Exit",
};

interface ChartPoint {
  readonly time: string;
  readonly value: number;
}

function toPoints(series: Series): ChartPoint[] {
  const points: ChartPoint[] = [];
  for (const point of series.points) {
    if (typeof point.v.value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(point.t)) {
      continue;
    }
    const value = Number(point.v.value);
    if (Number.isFinite(value)) {
      points.push({ time: point.t, value });
    }
  }
  return points;
}

export function TradePriceChart({
  series,
  markers,
  levels,
  direction,
  caption,
}: {
  series: Series;
  markers: readonly ChartMarker[];
  levels: readonly ChartLevel[];
  direction: "LONG" | "SHORT";
  caption: string;
}) {
  const container = React.useRef<HTMLDivElement | null>(null);
  const [tableOpen, setTableOpen] = React.useState(false);
  const [drawn, setDrawn] = React.useState(false);
  const points = React.useMemo(() => toPoints(series), [series]);
  const markerByDay = React.useMemo(
    () => new Map(markers.map((marker) => [marker.day, marker])),
    [markers],
  );

  React.useEffect(() => {
    const element = container.current;
    if (element === null || points.length === 0) {
      return;
    }
    /*
     * THE PLOT NEEDS A REAL BROWSER, AND SAYS SO BY NOT DRAWING.
     *
     * The library measures a device pixel ratio and observes its own element, so it needs
     * `matchMedia` and `ResizeObserver`. A server render and a jsdom test environment have
     * neither. Checking for them here is not a test accommodation: it is the same condition
     * that decides whether a canvas can be drawn at all, and where it cannot, the table below
     * carries the same points and the same events — which is what a screen reader gets in a
     * real browser too.
     */
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function" ||
      typeof window.ResizeObserver !== "function"
    ) {
      return;
    }
    let disposed = false;
    let dispose: (() => void) | undefined;

    /*
     * Imported inside the effect, and only in a browser.
     *
     * The library builds a canvas on construction; importing it at module scope would run
     * that on the server render and in the test environment, where there is no canvas and no
     * layout. The table below is what those environments render, which is also what a screen
     * reader gets.
     */
    void import("lightweight-charts").then((library) => {
      if (disposed || container.current === null) {
        return;
      }
      const chart = library.createChart(container.current, {
        autoSize: true,
        layout: {
          background: { color: "transparent" },
          textColor: "rgba(190,196,206,0.85)",
          fontFamily:
            '"Cascadia Mono", "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
          fontSize: 11,
          attributionLogo: false,
        },
        grid: {
          vertLines: { visible: false },
          horzLines: { color: "rgba(120,126,138,0.18)" },
        },
        rightPriceScale: { borderColor: "rgba(120,126,138,0.3)" },
        timeScale: { borderColor: "rgba(120,126,138,0.3)" },
        crosshair: { mode: 0 },
        handleScale: false,
        handleScroll: false,
      });
      const line = chart.addSeries(library.LineSeries, {
        color: direction === "LONG" ? "#61c7f2" : "#f2a24b",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(points.map((point) => ({ time: point.time, value: point.value })));

      library.createSeriesMarkers(
        line,
        markers.map((marker) => ({
          time: marker.day,
          position: marker.kind === "EXIT" || marker.kind === "PARTIAL_EXIT" ? "aboveBar" : "belowBar",
          color: marker.kind === "ENTRY" || marker.kind === "ADD" ? "#69d39f" : "#f0836f",
          shape:
            marker.kind === "EXIT" || marker.kind === "PARTIAL_EXIT"
              ? "arrowDown"
              : "arrowUp",
          text: MARKER_TEXT[marker.kind],
        })),
      );

      for (const level of levels) {
        const price = Number(level.price);
        if (Number.isFinite(price)) {
          line.createPriceLine({
            price,
            color: "rgba(240,131,111,0.7)",
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: level.label,
          });
        }
      }
      chart.timeScale().fitContent();
      setDrawn(true);
      dispose = () => chart.remove();
    });

    return () => {
      disposed = true;
      dispose?.();
    };
  }, [direction, levels, markers, points]);

  if (points.length === 0) {
    return (
      <div className="space-y-2" data-testid="trade-chart-empty">
        <AvailabilityBadge state="NOT_YET_AVAILABLE" reason="PRICE_PATH_INCOMPLETE" />
        <p className="text-label-m text-text-tertiary">
          No mark path was recorded for this trade, so no price view is drawn. Nothing is
          interpolated between the events that were recorded.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="trade-chart">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">Mark line</Badge>
        <span className="text-label-s text-text-tertiary">
          One recorded mark per session. <strong>Not OHLC</strong> — open, high, low and close
          need a market-data provider, and none is selected.
        </span>
        {series.completeness !== "COMPLETE" && (
          <AvailabilityBadge state="PARTIAL" reason="PRICE_PATH_INCOMPLETE" />
        )}
      </div>

      <div
        ref={container}
        role="img"
        aria-label={`${caption}. ${points.length} recorded session marks with ${markers.length} recorded events. A table of the same values follows.`}
        className="h-56 w-full rounded-sm border border-border-subtle bg-surface-sunken sm:h-72"
        data-drawn={drawn ? "true" : "false"}
      />

      {levels.length > 0 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-label-s text-text-tertiary">
          {levels.map((level) => (
            <li key={level.label} className="flex items-center gap-1.5">
              <span aria-hidden="true">┈</span>
              <span className="text-text-secondary">{level.label}</span>
              <MoneyText amount={level.price} />
              <span>{level.note}</span>
            </li>
          ))}
        </ul>
      )}

      {/* U10 — the same information, reachable by keyboard and readable by a screen reader. */}
      <details
        className="rounded-sm border border-border-subtle bg-surface-sunken"
        onToggle={(event) => setTableOpen(event.currentTarget.open)}
        data-testid="trade-chart-table-disclosure"
      >
        <summary className="cursor-pointer px-3 py-2 text-label-m text-text-secondary">
          Marks and recorded events as a table ({points.length} sessions, {markers.length}{" "}
          events)
        </summary>
        {tableOpen && (
          <div className="px-3 pb-3">
            <ScrollRegion label={`${caption} as a table`} className="max-h-64 overflow-y-auto">
              <table className="w-full min-w-[22rem] border-collapse text-label-m">
                <caption className="sr-only">
                  {caption}: the recorded mark for each session, and the recorded event on the
                  sessions that have one.
                </caption>
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    <th scope="col" className="py-1.5 pr-3 font-medium text-text-tertiary">
                      Session
                    </th>
                    <th scope="col" className="py-1.5 pr-3 font-medium text-text-tertiary">
                      Mark (USD)
                    </th>
                    <th scope="col" className="py-1.5 font-medium text-text-tertiary">
                      Recorded event
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((point) => {
                    const marker = markerByDay.get(point.time);
                    return (
                      <tr
                        key={point.time}
                        className="border-b border-border-subtle last:border-0"
                      >
                        <th
                          scope="row"
                          className="py-1 pr-3 text-left font-mono font-normal text-text-tertiary"
                        >
                          {point.time}
                        </th>
                        <td className="py-1 pr-3 font-mono text-text-secondary">
                          {point.value.toFixed(2)}
                        </td>
                        <td
                          className={cn(
                            "py-1",
                            marker === undefined ? "text-text-tertiary" : "text-text-primary",
                          )}
                        >
                          {marker === undefined ? (
                            "—"
                          ) : (
                            <span>
                              <span aria-hidden="true">{MARKER_GLYPH[marker.kind]}</span>{" "}
                              {marker.label} · {marker.quantity} sh @ {marker.price}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </ScrollRegion>
          </div>
        )}
      </details>
    </div>
  );
}

export { Button };
