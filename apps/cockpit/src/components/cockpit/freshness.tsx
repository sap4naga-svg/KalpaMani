"use client";

import * as React from "react";

import { Badge } from "@/components/ui/primitives";
import {
  effectiveComposite,
  freshUntil,
  isExpired,
  remainingFreshnessSeconds,
  type FreshnessReport,
} from "@/contracts/freshness";
import type { AvailabilityState, FieldReasonCode } from "@/contracts/vocabularies";
import { useClock } from "@/components/shell/clock-provider";
import type { Clock } from "@/lib/clock";

export interface LiveFreshness {
  readonly state: AvailabilityState;
  readonly reason: FieldReasonCode;
  readonly remainingSeconds: number | null;
  readonly sourceAgeSeconds: number | null;
  readonly oldestRequired: string | undefined;
  readonly expired: boolean;
}

interface ServeTimeStore {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => number;
  getServerSnapshot: () => number;
}

/**
 * Builds the serve-time store.
 *
 * Module scope on purpose: the store owns mutable state, and that state belongs to a plain
 * factory rather than to a hook body.
 */
function createServeTimeStore(
  clock: Clock,
  deadline: number | null,
  serverMs: number,
): ServeTimeStore {
  let snapshot = serverMs;
  const listeners = new Set<() => void>();
  let interval: number | undefined;
  let settle: number | undefined;

  const stop = () => {
    if (interval !== undefined) window.clearInterval(interval);
    if (settle !== undefined) window.clearTimeout(settle);
    interval = undefined;
    settle = undefined;
  };

  const publish = () => {
    snapshot = clock.now();
    for (const listener of listeners) listener();
  };

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      if (listeners.size === 1) {
        // The first subscriber switches the snapshot from the server value to the clock.
        snapshot = clock.now();
        if (deadline !== null && snapshot < deadline) {
          // Tick while the budget runs, and land exactly on the deadline.
          interval = window.setInterval(() => {
            publish();
            if (snapshot >= deadline) stop();
          }, 1000);
          settle = window.setTimeout(publish, Math.max(0, deadline - snapshot) + 25);
        }
      }
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) stop();
      };
    },
    getSnapshot: () => snapshot,
    getServerSnapshot: () => serverMs,
  };
}

/**
 * The serve time, as an external store.
 *
 * A live clock read during render would differ between the server render and the first
 * client render, which is a HYDRATION MISMATCH. `useSyncExternalStore` is the primitive for
 * exactly this: the server snapshot is the origin's own `evaluation_time` -- a value the
 * server and the client agree on -- and the client switches to live readings only after it
 * subscribes.
 */
function useServeTime(clock: Clock, deadline: number | null, serverMs: number): number {
  const store = React.useMemo(
    () => createServeTimeStore(clock, deadline, serverMs),
    [clock, deadline, serverMs],
  );
  return React.useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
}

/**
 * Freshness, evaluated against a live serve time.
 *
 * A MOUNTED VIEW UPDATES ITS STALE INDICATION WHEN THE DEADLINE PASSES, WITHOUT REQUIRING A
 * NAVIGATION (ADR-0029 section 2.2). The store schedules a re-evaluation at the absolute
 * deadline rather than polling for a change it can compute, and ticks once a second while
 * the budget is still running so the remaining budget is legible.
 *
 * QUERY CACHING ALONE IS NOT PROOF THAT A VALUE REMAINS FRESH: this evaluates the source
 * fact's own absolute deadline, and a refetch over unchanged fixtures moves nothing.
 */
export function useLiveFreshness(report: FreshnessReport): LiveFreshness {
  const clock = useClock();
  const deadline = freshUntil(report);
  const serveTime = useServeTime(clock, deadline, Date.parse(report.evaluation_time));

  const composite = effectiveComposite(report, serveTime);
  const sourceAge = report.source_age.value;
  return {
    state: composite.state,
    reason: composite.reason,
    remainingSeconds: remainingFreshnessSeconds(report, serveTime),
    sourceAgeSeconds: typeof sourceAge === "number" ? sourceAge : null,
    oldestRequired: report.oldest_required,
    expired: isExpired(report, serveTime),
  };
}

function formatAge(seconds: number): string {
  if (seconds < 90) return `${seconds}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  if (seconds < 172_800) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86_400)}d`;
}

/**
 * The persistent freshness indicator.
 *
 * Shows the age of the OLDEST required input -- never the newest, and never the build age.
 * A stale value is shown WITH its age and its freshness contract, visually marked.
 */
export function FreshnessIndicator({
  report,
  showDetail = false,
}: {
  report: FreshnessReport;
  showDetail?: boolean;
}) {
  const live = useLiveFreshness(report);
  const stale = live.state !== "AVAILABLE";
  return (
    <span
      className="inline-flex items-center gap-2"
      data-testid="freshness-indicator"
      data-freshness-state={live.state}
    >
      <Badge tone={stale ? "warning" : "neutral"}>
        <span aria-hidden="true">{stale ? "◑" : "●"}</span>
        <span>
          {stale ? "Stale" : "Fresh"}
          {live.sourceAgeSeconds !== null && ` · ${formatAge(live.sourceAgeSeconds)}`}
        </span>
      </Badge>
      {showDetail && (
        <span className="font-mono text-label-s text-text-tertiary">
          {live.oldestRequired !== undefined && `oldest: ${live.oldestRequired}`}
          {live.remainingSeconds !== null && ` · ${live.remainingSeconds}s left`}
          {stale && ` · ${live.reason}`}
        </span>
      )}
      {/* Availability and freshness changes are announced politely, never assertively. */}
      <span className="sr-only" aria-live="polite">
        {stale ? "Data is stale" : "Data is fresh"}
      </span>
    </span>
  );
}
