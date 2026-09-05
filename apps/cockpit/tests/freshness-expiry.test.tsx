import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FreshnessIndicator } from "@/components/cockpit/freshness";
import { ClockProvider } from "@/components/shell/clock-provider";
import { available, instantOf } from "@/contracts/factories";
import type { FreshnessReport } from "@/contracts/freshness";
import type { Clock } from "@/lib/clock";

/**
 * Freshness expiry WHILE THE VIEW STAYS MOUNTED.
 *
 * The deadline is absolute and belongs to the source fact, so a mounted view must update
 * its stale indication when the deadline passes -- with NO navigation and NO refetch.
 *
 * The clock is CONTROLLED, so the equality boundary is tested exactly rather than raced.
 */
const ORIGIN = Date.parse("2026-09-05T12:00:00.000Z");
const CONTRACT_SECONDS = 60;

function reportAt(sourceEffectiveMs: number, evaluationMs: number): FreshnessReport {
  const ageSeconds = Math.floor((evaluationMs - sourceEffectiveMs) / 1000);
  const metric = (value: number) =>
    available({
      metricId: "freshness.source_age",
      unit: "SECONDS",
      value,
      asOf: instantOf(evaluationMs),
    });
  return {
    inputs: [
      {
        input_id: "positions.mark",
        required: true,
        source_effective_time: instantOf(sourceEffectiveMs),
        source_age: metric(ageSeconds),
        contract_max_age: CONTRACT_SECONDS,
        state: "AVAILABLE",
        reason: "NONE",
      },
    ],
    oldest_required: "positions.mark",
    source_age: metric(ageSeconds),
    projection_lag: metric(0),
    build_age: metric(0),
    composite_state: "AVAILABLE",
    evaluation_time: instantOf(evaluationMs),
  };
}

let currentTime = ORIGIN;
const controlledClock: Clock = { now: () => currentTime, kind: "fixed" };

beforeEach(() => {
  currentTime = ORIGIN;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function advance(ms: number) {
  act(() => {
    currentTime += ms;
    vi.advanceTimersByTime(ms);
  });
}

describe("freshness expiry while mounted", () => {
  it("flips from fresh to stale at the deadline, without a navigation or a refetch", () => {
    // The source fact is already 45 seconds old against a 60-second contract, so 15
    // seconds of eligibility remain. A refetch would not change that.
    const report = reportAt(ORIGIN - 45_000, ORIGIN);
    render(
      <ClockProvider clock={controlledClock}>
        <FreshnessIndicator report={report} showDetail />
      </ClockProvider>,
    );

    const indicator = () => screen.getByTestId("freshness-indicator");
    expect(indicator().dataset.freshnessState).toBe("AVAILABLE");

    // One second before the deadline it is still permitted to be available.
    advance(14_000);
    expect(indicator().dataset.freshnessState).toBe("AVAILABLE");

    // AT EQUALITY the entry is expired, and it degrades to STALE rather than to available.
    advance(1_000);
    expect(indicator().dataset.freshnessState).toBe("STALE");
    expect(indicator().textContent).toContain("Stale");
    expect(indicator().textContent).toContain("UPSTREAM_INPUT_STALE");
  });

  it("never renders an expired entry as available, however long it is held", () => {
    const report = reportAt(ORIGIN - 45_000, ORIGIN);
    render(
      <ClockProvider clock={controlledClock}>
        <FreshnessIndicator report={report} />
      </ClockProvider>,
    );
    advance(600_000);
    expect(screen.getByTestId("freshness-indicator").dataset.freshnessState).toBe("STALE");
  });

  it("retains the value while marking it stale, rather than discarding it", () => {
    const report = reportAt(ORIGIN - 59_000, ORIGIN);
    render(
      <ClockProvider clock={controlledClock}>
        <FreshnessIndicator report={report} />
      </ClockProvider>,
    );
    advance(1_000);
    const indicator = screen.getByTestId("freshness-indicator");
    expect(indicator.dataset.freshnessState).toBe("STALE");
    // The age is still reported: retaining content is not claiming it is fresh.
    expect(indicator.textContent).toMatch(/\d/);
  });
});
