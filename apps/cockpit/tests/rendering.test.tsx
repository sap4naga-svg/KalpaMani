import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { MetricTile, MetricTileSkeleton } from "@/components/cockpit/metric-tile";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { ClockProvider } from "@/components/shell/clock-provider";
import { available, absent, qualified } from "@/contracts/factories";
import { AVAILABILITY_STATES } from "@/contracts/vocabularies";
import { PERMITTED_REASONS, isValueBearing } from "@/contracts/validity";
import { fixedClock } from "@/lib/clock";
import { humanizeCode } from "@/lib/format";

const AS_OF = "2026-09-05T12:00:00.000Z";
const clock = fixedClock(AS_OF);

function withClock(node: React.ReactNode) {
  return render(<ClockProvider clock={clock}>{node}</ClockProvider>);
}

describe("availability rendering (U4, U5)", () => {
  it("renders every one of the eleven states distinctly", () => {
    const labels = new Set<string>();
    for (const state of AVAILABILITY_STATES) {
      const { unmount } = render(
        <AvailabilityBadge state={state} reason={PERMITTED_REASONS[state][0]} />,
      );
      const badge = document.querySelector(`[data-availability="${state}"]`);
      expect(badge, state).not.toBeNull();
      const text = badge?.textContent ?? "";
      expect(labels.has(text), `${state} must render distinctly`).toBe(false);
      labels.add(text);
      unmount();
    }
    expect(labels.size).toBe(AVAILABILITY_STATES.length);
  });

  it("distinguishes the five states the specification names as an acceptance criterion", () => {
    const rendered = (
      ["EMPTY_VERIFIED", "NOT_YET_AVAILABLE", "NOT_IMPLEMENTED", "NOT_AUTHORIZED", "STALE"] as const
    ).map((state) => {
      const { container, unmount } = render(
        <AvailabilityBadge state={state} reason={PERMITTED_REASONS[state][0]} />,
      );
      const text = container.textContent ?? "";
      unmount();
      return text;
    });
    expect(new Set(rendered).size).toBe(5);
  });

  it("never renders an unavailable state as zero, healthy or passed", () => {
    for (const state of AVAILABILITY_STATES.filter((candidate) => !isValueBearing(candidate))) {
      const { container, unmount } = render(
        <UnavailableBody state={state} reason={PERMITTED_REASONS[state][0]} />,
      );
      const text = (container.textContent ?? "").toLowerCase();
      expect(/\b0(\.0+)?\b/.test(text), `${state} must not render a zero`).toBe(false);
      expect(text.includes("healthy"), state).toBe(false);
      expect(text.includes("passed"), state).toBe(false);
      unmount();
    }
  });

  it("carries a non-colour cue for every state (U11)", () => {
    for (const state of AVAILABILITY_STATES) {
      const { container, unmount } = render(
        <AvailabilityBadge state={state} reason={PERMITTED_REASONS[state][0]} />,
      );
      // A glyph and a text label accompany the tone.
      expect(container.querySelector('[aria-hidden="true"]'), state).not.toBeNull();
      expect((container.textContent ?? "").trim().length, state).toBeGreaterThan(1);
      unmount();
    }
  });
});

describe("metric tiles", () => {
  it("shows the unit for a displayed metric (U19)", () => {
    withClock(
      <MetricTile
        label="Day realized P/L"
        provenance="SYNTHETIC"
        metric={available({ metricId: "pnl.realized", unit: "USD", value: "125.00", asOf: AS_OF })}
      />,
    );
    expect(screen.getByText("USD")).toBeInTheDocument();
  });

  it("renders a measured zero as a value rather than as an empty state", () => {
    withClock(
      <MetricTile
        label="Drawdown"
        provenance="SYNTHETIC"
        metric={available({ metricId: "risk.drawdown", unit: "PERCENT", value: "0.00", asOf: AS_OF })}
      />,
    );
    expect(screen.getByText("0.00")).toBeInTheDocument();
    expect(screen.queryByTestId("unavailable-body")).toBeNull();
  });

  it("keeps a STALE value visible AND qualified", () => {
    withClock(
      <MetricTile
        label="Unrealized"
        provenance="SYNTHETIC"
        metric={qualified("STALE", "UPSTREAM_INPUT_STALE", {
          metricId: "pnl.unrealized",
          unit: "USD",
          value: "-318.40",
          asOf: AS_OF,
        })}
      />,
    );
    expect(screen.getByText("-318.40")).toBeInTheDocument();
    expect(document.querySelector('[data-availability="STALE"]')).not.toBeNull();
  });

  it("renders an absence with its reason and dependency, and no number", () => {
    withClock(
      <MetricTile
        label="Permitted open risk"
        provenance="REPOSITORY_TRACKED"
        dependency="a versioned risk-policy reference"
        metric={absent(
          "NOT_YET_AVAILABLE",
          "POLICY_REFERENCE_MISSING",
          "risk.permitted_open_risk",
          "USD",
        )}
      />,
    );
    const body = screen.getByTestId("unavailable-body");
    expect(within(body).getByText("POLICY_REFERENCE_MISSING")).toBeInTheDocument();
    expect(within(body).getByText(/versioned risk-policy reference/)).toBeInTheDocument();
    expect(body.textContent).not.toMatch(/\d+\.\d+/);
  });

  it("puts no digit and no plausible placeholder in a loading skeleton (U7)", () => {
    const { container } = render(<MetricTileSkeleton label="Loading" />);
    expect(container.querySelectorAll('[data-testid="skeleton"]').length).toBeGreaterThan(0);
    expect(/\d/.test(container.textContent ?? "")).toBe(false);
  });
});

describe("provenance badges (U3, section 9.4)", () => {
  it("never renders a tracked fact under the synthetic badge", () => {
    const { container: synthetic, unmount } = render(<ProvenanceBadge provenance="SYNTHETIC" />);
    const syntheticText = synthetic.textContent;
    unmount();
    const { container: tracked } = render(<ProvenanceBadge provenance="REPOSITORY_TRACKED" />);
    expect(tracked.textContent).not.toBe(syntheticText);
    expect(tracked.querySelector('[data-provenance="REPOSITORY_TRACKED"]')).not.toBeNull();
  });

  it("makes SYNTHETIC unmissable rather than a tooltip", () => {
    const { container } = render(<ProvenanceBadge provenance="SYNTHETIC" />);
    expect(container.textContent).toContain("SYNTHETIC");
  });
});

describe("closed-vocabulary code formatting", () => {
  it("keeps acronyms and identifiers, and does not lowercase them into prose", () => {
    expect(humanizeCode("KALPAMANI_STRATEGY_CAPITAL_USD")).toBe(
      "KalpaMani strategy capital USD",
    );
    expect(humanizeCode("RUN_A_RETRY")).toBe("Run A retry");
    expect(humanizeCode("RUN_B")).toBe("Run B");
    expect(humanizeCode("INC_0002")).toBe("INC 0002");
    expect(humanizeCode("DATA_QUALITY_AND_PIT")).toBe("Data quality and PIT");
    expect(humanizeCode("PROVIDER_SELECTION_AND_QUALIFICATION")).toBe(
      "Provider selection and qualification",
    );
  });
});
