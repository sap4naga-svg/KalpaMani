import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  BenchmarkComparisonUnavailable,
  BenchmarkComparisonView,
} from "@/components/cockpit/benchmark-comparison";
import { RollingSeriesPanel } from "@/components/cockpit/rolling-series";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

/**
 * How the C5 completion follow-up's surfaces render.
 *
 * THE THINGS BEING CHECKED ARE THE ONES A PICTURE HIDES: that a lookback and a period are
 * printed as two different numbers, that an unavailable point renders as its state rather
 * than as a zero, that the comparability limits are visible without opening anything, and
 * that the chart has a table alternative carrying the same points.
 */

const AS_OF = "2026-09-06T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };
const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });

/* ============================================================ the rolling panel */

describe("the rolling-window panel", () => {
  it("prints the requested extent and the rolling lookback as two separate facts", async () => {
    const envelope = await client.performanceSeries({ ...DEMO, period: "1Y" });
    render(<RollingSeriesPanel envelope={envelope} scope={{ ...DEMO, period: "1Y" }} operator />);
    const basis = screen.getByTestId("rolling-basis");
    expect(within(basis).getByTestId("rolling-extent")).toHaveTextContent("1 year");
    expect(within(basis).getByTestId("rolling-extent")).toHaveTextContent("252");
    expect(within(basis).getByTestId("rolling-lookback")).toHaveTextContent("21 daily periods");
  });

  it("offers one control per served lookback and switches between them", async () => {
    const envelope = await client.performanceSeries({ ...DEMO, period: "1Y" });
    render(<RollingSeriesPanel envelope={envelope} scope={{ ...DEMO, period: "1Y" }} operator />);
    const selector = screen.getByTestId("lookback-selector");
    const buttons = within(selector).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "21 periods",
      "63 periods",
      "126 periods",
    ]);
    await userEvent.click(buttons[1]);
    expect(screen.getByTestId("rolling-lookback")).toHaveTextContent("63 daily periods");
  });

  it("counts the points below the minimum instead of drawing them as zero", async () => {
    const envelope = await client.performanceSeries({ ...DEMO, period: "1Y" });
    render(<RollingSeriesPanel envelope={envelope} scope={{ ...DEMO, period: "1Y" }} operator />);
    const tally = screen.getByTestId("rolling-tally");
    expect(tally).toHaveTextContent("fewer than 21 earlier observations");
    expect(within(tally).getByText("Insufficient observations")).toBeInTheDocument();
  });

  it("says plainly when the extent is too short for any window, and draws nothing", async () => {
    const envelope = await client.performanceSeries({ ...DEMO, period: "1M" });
    render(<RollingSeriesPanel envelope={envelope} scope={{ ...DEMO, period: "1M" }} operator />);
    expect(screen.getByTestId("rolling-none-computed")).toHaveTextContent(
      "No point in this extent has a complete window behind it",
    );
  });

  it("names the gapped points separately from the ones below the minimum", async () => {
    const envelope = await client.performanceSeries({ ...DEMO, period: "ALL" });
    render(<RollingSeriesPanel envelope={envelope} scope={{ ...DEMO, period: "ALL" }} operator />);
    const tally = screen.getByTestId("rolling-tally");
    expect(tally).toHaveTextContent("span a session that carries no observation");
    expect(tally).toHaveTextContent("fewer than 21 earlier observations");
  });

  it("carries a keyboard-reachable table with the same points and their states (U10)", async () => {
    const envelope = await client.performanceSeries({ ...DEMO, period: "1Y" });
    render(<RollingSeriesPanel envelope={envelope} scope={{ ...DEMO, period: "1Y" }} operator />);
    const disclosure = screen.getByTestId("rolling-table-disclosure");
    await userEvent.click(within(disclosure).getByText(/as a table/));
    const table = within(disclosure).getByRole("table");
    /** One row per served period, and the header row above them. */
    expect(within(table).getAllByRole("row")).toHaveLength(253);
    expect(within(table).getAllByText("Insufficient observations").length).toBeGreaterThan(0);
  });

  it("renders a skeleton before the envelope arrives, and never an empty chart", () => {
    render(<RollingSeriesPanel envelope={undefined} scope={DEMO} operator={false} />);
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
  });

  it("names its dependency when the producer serves no payload at all", async () => {
    const envelope = await client.performanceSeries(DEFAULT_SCOPE);
    render(<RollingSeriesPanel envelope={envelope} scope={DEFAULT_SCOPE} operator={false} />);
    expect(screen.getByTestId("unavailable-body")).toHaveTextContent(
      "the portfolio valuation projection",
    );
  });
});

/* ====================================================== the benchmark comparison */

describe("the benchmark comparison", () => {
  async function comparison() {
    const payload = (await client.performanceSeries({ ...DEMO, period: "3M" })).payload;
    const found = payload?.benchmark_comparison;
    if (found === undefined) {
      throw new Error("the demonstration payload carries a comparison");
    }
    return found;
  }

  it("states every comparability limit above the chart, not under a disclosure", async () => {
    render(<BenchmarkComparisonView comparison={await comparison()} operator={false} />);
    const limits = screen.getByTestId("comparability-limits");
    expect(within(limits).getAllByRole("listitem").length).toBeGreaterThanOrEqual(4);
    expect(limits).toHaveTextContent(/cost treatment/i);
    expect(limits).toHaveTextContent(/not a market index/i);
  });

  it("shows the refusal instead of a difference, and says why", async () => {
    render(<BenchmarkComparisonView comparison={await comparison()} operator={false} />);
    const block = screen.getByTestId("comparison-difference");
    expect(within(block).getByTestId("comparison-refusal")).toHaveTextContent(
      /arms differ in cost treatment/i,
    );
    expect(block).toHaveTextContent("never compared, summed or placed in one series");
  });

  it("labels no value alpha, and says so rather than staying silent about it", async () => {
    /*
     * THE ASSERTION IS ABOUT A CLAIM, NOT ABOUT A WORD. The surface says "it would not be
     * alpha either way", which is a DISCLAIMER — banning the string would ban the sentence
     * that does the work. What must not exist is a value, label, heading or term CALLED
     * alpha, so that is what is checked.
     */
    render(<BenchmarkComparisonView comparison={await comparison()} operator />);
    expect(screen.queryByText(/^\s*alpha\s*$/i)).toBeNull();
    for (const term of screen.getAllByRole("term")) {
      expect(term.textContent?.toLowerCase()).not.toContain("alpha");
    }
    const difference = screen.getByTestId("comparison-difference");
    expect(difference.querySelector("[data-metric]")).toBeNull();
    expect(difference).toHaveTextContent("It would not be alpha either way.");
  });

  it("states both arms' bases and cost treatments separately", async () => {
    render(<BenchmarkComparisonView comparison={await comparison()} operator={false} />);
    const basis = screen.getByTestId("comparison-basis");
    expect(basis).toHaveTextContent("Price return · Net all costs");
    expect(basis).toHaveTextContent("Price return · Gross");
  });

  it("shows the common window it was measured over", async () => {
    const found = await comparison();
    render(<BenchmarkComparisonView comparison={found} operator={false} />);
    expect(screen.getByTestId("comparison-window")).toHaveTextContent(
      found.common_window.from.slice(0, 10),
    );
  });

  it("carries a table alternative with one row per common observation", async () => {
    const found = await comparison();
    render(<BenchmarkComparisonView comparison={found} operator={false} />);
    const disclosure = screen.getByTestId("comparison-table-disclosure");
    await userEvent.click(within(disclosure).getByText(/as a table/));
    const table = within(disclosure).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(found.portfolio_series.points.length + 1);
  });

  it("refuses to draw a comparison of one observation", () => {
    render(<BenchmarkComparisonUnavailable />);
    expect(screen.getByTestId("benchmark-comparison-unavailable")).toHaveTextContent(
      "at least two observations both arms carry",
    );
  });
});
