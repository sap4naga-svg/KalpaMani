import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AbsentControls,
  Fact,
  FactGrid,
  HistoricalFact,
  OperationsReadOnlyNotice,
  PresentState,
  SeverityBadge,
  StateBadge,
  Timeline,
  WindowStatement,
} from "@/components/cockpit/operations";
import { MetricTile } from "@/components/cockpit/metric-tile";
import { ComparisonChart } from "@/components/cockpit/research";
import { SEVERITY_RANK } from "@/contracts/operations-models";
import type { ReasonCoded } from "@/contracts/values";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { fixedClock } from "@/lib/clock";
import { humanizeCode } from "@/lib/format";
import { DEFAULT_SCOPE, type ViewScope } from "@/lib/scope";

/**
 * What the C8 surfaces actually SHOW.
 *
 * These render real payloads through the shared components the six screens are built from, so
 * a rule satisfied in the contract and dropped in the presentation is caught here rather than
 * by a reviewer reading a screenshot. The full pages are exercised end to end by the browser
 * suite; what is checked here is the presentation the pages delegate.
 *
 * Nothing here reads `Date.now()`.
 */

const ORIGIN = Date.parse("2026-09-08T12:00:00.000Z");
const clock = fixedClock(ORIGIN);
const client = () => new FixtureReadClient({ clock, originMs: ORIGIN });
const demo: ViewScope = { ...DEFAULT_SCOPE, scenario: "demo" };

function reason(code: string): ReasonCoded {
  return { code, vocabulary: "kalpamani.demo", vocabulary_version: "v1" };
}

/* ========================================================= a chart never draws an absence */

describe("a C8 chart states an unmeasured count rather than drawing it as zero", () => {
  it("excludes the unevaluated outcome from the plot and keeps it in the table", async () => {
    const page = (await client().executionQuality(demo)).payload!;
    render(
      <ComparisonChart
        caption="Recorded lifecycle outcomes in the window"
        rows={page.outcomes.map((entry) => ({
          label: entry.outcome.code,
          value: entry.count,
        }))}
        unitLabel="observations"
        testId="outcome-chart"
      />,
    );
    /* The plot exists, because most outcomes were measured. */
    expect(screen.getByTestId("comparison-chart-plot")).toBeInTheDocument();
    /*
     * AND THE UNMEASURED ONE IS IN THE TABLE, AS A STATE.
     *
     * `MISSED_FILLS` is `UNEVALUATED`: nobody asked the question. A bar at zero would read as
     * a measured zero, which is the opposite of what the record says.
     */
    expect(screen.getByText(/missed fills/i)).toBeInTheDocument();
    expect(screen.getAllByText("Unevaluated").length).toBeGreaterThan(0);
  });
});

/* ============================================= a magnitude carries no direction claim */

describe("a tile signs a direction and never a magnitude", () => {
  it("gives a fill rate no leading plus, and a signed return one", async () => {
    const page = (await client().executionQuality(demo)).payload!;
    render(
      <MetricTile
        label="Fill rate"
        metric={page.aggregate.fill_rate}
        provenance="SYNTHETIC"
        neutral
      />,
    );
    const tile = screen.getByTestId("tile-execution.fill_rate");
    /*
     * A FILL RATE IS NEITHER A GAIN NOR A LOSS.
     *
     * `+100.00 %` beside a fill rate reads as a rise of a hundred percent. The unit says a
     * value COULD be directional; `neutral` says this particular field is not.
     */
    expect(tile.textContent).not.toContain("+");
    expect(tile.textContent).toContain("100.00");
  });

  it("still signs a directional value on the same component", () => {
    render(
      <MetricTile
        label="Slippage"
        metric={{
          value: "8.42",
          unit: "PERCENT",
          availability: "AVAILABLE",
          reason: "NONE",
          as_of: "2026-09-08T12:00:00.000Z",
          metric_id: "return.period",
          metric_definition_version: "metrics.v1",
        }}
        provenance="SYNTHETIC"
      />,
    );
    expect(screen.getByTestId("tile-return.period").textContent).toContain("+8.42");
  });
});

/* ================================================= an acronym keeps its own casing */

describe("a closed code renders acronyms as acronyms", () => {
  it("preserves the acronyms the format module declares", () => {
    expect(humanizeCode("US_EQUITY_DAILY_MARKS")).toBe("US equity daily marks");
    expect(humanizeCode("SMS")).toBe("SMS");
    /* And an ordinary word is still lowercased after the first. */
    expect(humanizeCode("MARK_DATA_OLDER_THAN_CONTRACT")).toBe(
      "Mark data older than contract",
    );
  });
});

/* ===================================================== severity is ranked, never compared */

describe("a severity renders with the rank the accepted vocabulary declares", () => {
  it("carries its declared rank as an attribute, and its code as prose", () => {
    render(
      <>
        <SeverityBadge severity={reason("HIGH")} />
        <SeverityBadge severity={reason("MEDIUM")} />
        <SeverityBadge severity={reason("LOW")} />
      </>,
    );
    for (const [code, rank] of Object.entries(SEVERITY_RANK)) {
      const badge = document.querySelector(`[data-severity="${code}"]`)!;
      expect(badge, code).toBeTruthy();
      expect(badge.getAttribute("data-severity-rank"), code).toBe(String(rank));
    }
    /* Colour is never the only carrier: the code is rendered as prose beside the tone. */
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Medium")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();
  });
});

/* ============================================ a historical fact is not a present statement */

describe("a last success and a present state render as two different things", () => {
  it("says a recorded fact is not a statement about the present", async () => {
    const jobs = (await client().systemJobs(demo)).payload!;
    const succeeded = jobs.items.find(
      (job) => job.last_success.availability === "AVAILABLE",
    )!;
    render(<HistoricalFact label="Last successful run" metric={succeeded.last_success} />);
    expect(screen.getByText(/not a statement about the present/i)).toBeInTheDocument();
    /* The instant it was true at travels with it. */
    expect(screen.getByText(succeeded.last_success.value as string)).toBeInTheDocument();
  });

  it("renders a present state as its own availability, with a reason code", async () => {
    const page = (await client().reconciliation(demo)).payload!;
    render(
      <PresentState
        label="Present reconciliation health"
        availability={page.current_health.availability}
        reason={page.current_health.reason}
        note={page.current_health.note}
        testId="present-health"
      />,
    );
    const badge = within(screen.getByTestId("present-health")).getByText("Not implemented");
    expect(badge).toBeInTheDocument();
    expect(
      screen.getByTestId("present-health").querySelector('[data-reason]')!.getAttribute(
        "data-reason",
      ),
    ).toBe("PRODUCER_NOT_IMPLEMENTED");
    /* And no digit stands in for the answer it does not have. */
    expect(/\d/.test(screen.getByTestId("present-health").textContent ?? "")).toBe(false);
  });
});

/* ================================================== the controls a screen does not have */

describe("a screen names what it cannot do", () => {
  it("renders every absent control from the payload's own closed list", async () => {
    const jobs = (await client().systemJobs(demo)).payload!;
    render(
      <AbsentControls controls={jobs.absent_controls} label="Controls this screen lacks" />,
    );
    const list = screen.getByTestId("absent-controls");
    /*
     * MATCHED ON THE CODE, NOT ON THE RENDERED WORDS.
     *
     * `START` is a substring of `RESTART`, so a text match would find two elements for one
     * control and pass for the wrong reason. The code is what the payload carries.
     */
    for (const control of jobs.absent_controls) {
      expect(list.querySelector(`[data-code="${control.code}"]`), control.code).toBeTruthy();
    }
    expect(list.querySelectorAll("[data-code]")).toHaveLength(jobs.absent_controls.length);
    /* They are rendered as prose, not as buttons. */
    expect(list.querySelectorAll("button")).toHaveLength(0);
  });

  it("states on a read-only notice that no such control exists anywhere", () => {
    render(
      <OperationsReadOnlyNotice
        subject="recorded job runs and incidents"
        actions={["start", "stop", "retry"]}
        producer="No scheduler or service runtime exists"
      />,
    );
    const notice = screen.getByTestId("read-only-notice");
    expect(notice.textContent).toContain("no such control exists anywhere in this application");
    expect(notice.textContent).toContain("no order has been placed");
    expect(notice.querySelectorAll("button")).toHaveLength(0);
  });
});

/* =============================================================== timelines and windows */

describe("a recorded timeline reads as a sequence, with its instants", () => {
  it("renders an ordered list carrying every entry's instant", async () => {
    const incidents = (await client().systemIncidents(demo)).payload!;
    const incident = incidents.items.find((entry) => entry.timeline.length > 1)!;
    render(
      <Timeline
        entries={incident.timeline.map((entry, index) => ({
          key: `${incident.incident_id}-${index}`,
          at: entry.at,
          title: entry.event.code,
        }))}
        empty="No entry."
        testId="incident-timeline"
      />,
    );
    const list = screen.getByTestId("incident-timeline");
    expect(list.tagName).toBe("OL");
    expect(within(list).getAllByRole("listitem")).toHaveLength(incident.timeline.length);
    for (const entry of incident.timeline) {
      expect(within(list).getByText(entry.at)).toBeInTheDocument();
    }
  });

  it("says so in a sentence when a timeline has no entry", () => {
    render(<Timeline entries={[]} empty="This incident records no timeline entry." />);
    expect(screen.getByText("This incident records no timeline entry.")).toBeInTheDocument();
  });

  it("states a window's calendar basis and timezone beside its boundaries", async () => {
    const page = (await client().executionQuality(demo)).payload!;
    render(<WindowStatement window={page.window} label="Recorded events from" />);
    const statement = screen.getByTestId("window-statement");
    expect(within(statement).getByText("UTC")).toBeInTheDocument();
    expect(statement.textContent).toContain("half-open");
    expect(within(statement).getByText(page.window.from)).toBeInTheDocument();
    expect(within(statement).getByText(page.window.to)).toBeInTheDocument();
  });
});

/* ===================================================== states, facts and closed codes */

describe("a closed code renders as prose and keeps its code for a test", () => {
  it("exposes the code on a data attribute and the prose to a reader", () => {
    render(<StateBadge state={reason("COMPARISON_INPUT_MISSING")} attribute="result" />);
    const badge = screen.getByText("Comparison input missing");
    expect(badge.getAttribute("data-result")).toBe("COMPARISON_INPUT_MISSING");
  });

  it("renders a fact grid as a definition list, so a term reads with its definition", () => {
    render(
      <FactGrid columns={2}>
        <Fact label="Internal as of">
          <span>2026-09-08T11:00:00.000Z</span>
        </Fact>
        <Fact label="Broker as of">
          <span>2026-09-08T10:58:00.000Z</span>
        </Fact>
      </FactGrid>,
    );
    expect(document.querySelectorAll("dl")).toHaveLength(1);
    expect(document.querySelectorAll("dt")).toHaveLength(2);
    expect(document.querySelectorAll("dd")).toHaveLength(2);
    expect(screen.getByText("Internal as of")).toBeInTheDocument();
  });
});
