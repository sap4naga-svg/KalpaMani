import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ComparisonChart,
  EvaluationClassBadge,
  ExposureDisclosure,
  MeasureList,
  ReadOnlyNotice,
  ReasonList,
  ReferenceListPanel,
  ReferenceRow,
} from "@/components/cockpit/research";
import { ClockProvider } from "@/components/shell/clock-provider";
import type { ReasonCoded } from "@/contracts/values";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { QUEUE_ITEMS, REGISTRATIONS, RUNS } from "@/data/fixtures/lineage";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE, type ViewScope } from "@/lib/scope";

/**
 * What the C7 surfaces actually SHOW.
 *
 * These render real payloads through the shared components the nine screens are built from, so
 * a rule that is satisfied in the contract and dropped in the presentation is caught here
 * rather than by a reviewer reading a screenshot. The full pages are exercised end to end by
 * the browser suite; what is checked here is the presentation the pages delegate.
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

/* ================================================================== charts and tables */

describe("a C7 chart never draws an absence, and always has a table beside it", () => {
  it("plots only the rows that carry a value, and states the rest in the table", async () => {
    const runs = (await client().researchRuns(demo)).payload!;
    const failed = runs.items.find((entry) => entry.run_id === RUNS.failed)!;
    const { container } = render(
      <ComparisonChart
        caption="Recorded results"
        rows={failed.results.map((entry) => ({
          label: entry.measure.code,
          value: entry.value,
        }))}
        unitLabel="their own declared units"
      />,
    );
    /* Every measure of a failed run is an absence, so NOTHING is plotted. */
    expect(screen.queryByTestId("comparison-chart-plot")).toBeNull();
    expect(screen.getByTestId("chart-no-plottable-values")).toBeInTheDocument();
    /* And no bar at zero, and no zero anywhere, stands in for the missing measurement. */
    expect(/\b0(\.0+)?\b/.test(container.textContent ?? "")).toBe(false);
    /* The table still carries every row, with its own state. */
    for (const entry of failed.results) {
      expect(screen.getByText(new RegExp(entry.measure.code.replace(/_/g, " "), "i"))).toBeTruthy();
    }
    expect(screen.getAllByText("Not yet available").length).toBe(failed.results.length);
  });

  it("keeps a keyboard-reachable table carrying the same rows as the plot", async () => {
    const runs = (await client().researchRuns(demo)).payload!;
    const completed = runs.items.find((entry) => entry.run_id === RUNS.confirmatory)!;
    render(
      <ComparisonChart
        caption="Recorded results"
        rows={completed.results.map((entry) => ({
          label: entry.measure.code,
          value: entry.value,
        }))}
        unitLabel="their own declared units"
      />,
    );
    const plot = screen.getByTestId("comparison-chart-plot");
    /* The plot is labelled and names its alternative; the table carries the numbers. */
    expect(plot.getAttribute("role")).toBe("img");
    expect(plot.getAttribute("aria-label")).toContain("A table of the same values follows");
    const region = screen.getByRole("region", { name: "Recorded results" });
    expect(region.getAttribute("tabindex")).toBe("0");
    const rows = within(region).getAllByRole("row");
    /* One header row plus one row per measure. */
    expect(rows).toHaveLength(completed.results.length + 1);
  });

  it("draws an arm uncertainty as a column rather than a footnote", async () => {
    const contribution = (await client().aiContribution(demo)).payload!;
    const reportable = contribution.items.find(
      (entry) => entry.matched && entry.minimum_observations_met,
    )!;
    render(
      <ComparisonChart
        caption="Arm outcomes"
        rows={reportable.arms.map((arm) => ({
          label: arm.arm.code,
          value: arm.outcome,
          uncertainty: arm.uncertainty,
          context: arm.population,
        }))}
        unitLabel="R"
        contextLabel="Matched population"
      />,
    );
    expect(screen.getByText("Stated uncertainty")).toBeInTheDocument();
    expect(screen.getByText("Matched population")).toBeInTheDocument();
  });

  it("renders an insufficient arm as its rule and never as a ratio", async () => {
    const contribution = (await client().aiContribution(demo)).payload!;
    const short = contribution.items.find((entry) => !entry.minimum_observations_met)!;
    render(
      <MeasureList
        entries={short.arms.map((arm) => ({ label: arm.arm.code, value: arm.outcome }))}
      />,
    );
    expect(screen.getAllByText("Insufficient observations").length).toBe(short.arms.length);
  });
});

/* ============================================================== evaluation classes */

describe("an evaluation class is rendered as what it may claim", () => {
  it("distinguishes exploratory reuse from confirmation, and says what reuse is not", () => {
    render(<EvaluationClassBadge evaluationClass="EXPLORATORY_REUSE" />);
    const badge = screen.getByText("Exploratory reuse").closest("span")!.parentElement!;
    expect(badge.getAttribute("data-evaluation-class")).toBe("EXPLORATORY_REUSE");
    expect(badge.getAttribute("title")).toContain(
      "NEVER presented as fresh out-of-sample evidence",
    );
  });

  it("says a deterministic reproduction confirms reproducibility and nothing else", () => {
    render(<EvaluationClassBadge evaluationClass="DETERMINISTIC_REPRODUCTION" />);
    const badge = screen
      .getByText("Deterministic reproduction")
      .closest("span")!.parentElement!;
    expect(badge.getAttribute("title")).toContain("NOTHING ELSE");
    expect(badge.getAttribute("title")).toContain("consumes no trial budget");
  });

  it("writes an empty disclosure out as a sentence rather than leaving a blank", () => {
    render(<ExposureDisclosure disclosure={[]} />);
    expect(screen.getByText(/rests on no recorded reuse/)).toBeInTheDocument();
  });

  it("renders a recorded disclosure as its own chips", async () => {
    const runs = (await client().researchRuns(demo)).payload!;
    const reuse = runs.items.find((entry) => entry.run_id === RUNS.reuse)!;
    render(<ExposureDisclosure disclosure={reuse.exposure_disclosure} />);
    expect(
      screen.getByText("Never presented as fresh out of sample evidence"),
    ).toBeInTheDocument();
  });
});

/* ====================================================================== reason lists */

describe("a closed code is rendered as prose, and an empty list as a sentence", () => {
  it("renders an empty list as its stated sentence, never as nothing", () => {
    render(<ReasonList codes={[]} empty="No requirement is recorded." testId="empty-list" />);
    expect(screen.getByTestId("empty-list").textContent).toBe("No requirement is recorded.");
  });

  it("renders every member of a populated list", () => {
    render(
      <ReasonList
        codes={[reason("BUDGET_EXHAUSTED"), reason("LEAKAGE_RISK_DETECTED")]}
        empty="none"
        testId="codes"
      />,
    );
    const rendered = within(screen.getByTestId("codes")).getAllByRole("listitem");
    expect(rendered).toHaveLength(2);
    expect(rendered[0].textContent).toBe("Budget exhausted");
  });
});

/* =================================================================== reference rows */

describe("a reference offers its two destinations as distinct controls", () => {
  it("offers a target link and an area link, and never merges them", async () => {
    const queue = (await client().researchQueue(demo)).payload!;
    const health = queue.items.find((entry) => entry.item_id === QUEUE_ITEMS.pullback)!;
    render(
      <ClockProvider clock={clock}>
        <ReferenceRow reference={health.trigger_ref} label="Trigger" scope={demo} />
      </ClockProvider>,
    );
    /* `source_fact` maps to the audit area as a TARGET; the owning area is separate. */
    const target = screen.getByTestId("reference-target-link");
    const area = screen.getByTestId("reference-area-link");
    expect(target).not.toBe(area);
    expect(area.getAttribute("href")).toContain("/strategy/health");
    expect(target.getAttribute("href")).not.toContain("/strategy/health");
    /* The area control NAMES THE AREA and never reads as retrieval. */
    const label = area.textContent!.toLowerCase();
    expect(label).toContain("area");
    for (const verb of ["view", "open", "retrieve", "resolve", "show", "evidence"]) {
      expect(label, verb).not.toContain(verb);
    }
  });

  it("renders no area control where the reference declares none", async () => {
    const queue = (await client().researchQueue(demo)).payload!;
    const missed = queue.items.find((entry) => entry.item_id === QUEUE_ITEMS.missed)!;
    render(
      <ClockProvider clock={clock}>
        <ReferenceRow reference={missed.trigger_ref} scope={demo} />
      </ClockProvider>,
    );
    expect(screen.queryByTestId("reference-area-link")).toBeNull();
    expect(screen.getByTestId("reference-target-link")).toBeTruthy();
  });

  it("says out loud where the target allowlist maps a kind to no destination", async () => {
    const health = (await client().strategyHealth(demo)).payload!;
    const cluster = health.items
      .flatMap((entry) => entry.failure_clusters)
      .find((entry) => entry.evidence_refs.items.length > 0)!;
    render(
      <ClockProvider clock={clock}>
        <ReferenceRow reference={cluster.evidence_refs.items[0]} scope={demo} />
      </ClockProvider>,
    );
    /* `evidence` is deliberately unmapped: no guess, and the absence is stated. */
    expect(screen.getByTestId("evidence-no-destination")).toBeInTheDocument();
    expect(screen.queryByTestId("reference-target-link")).toBeNull();
  });

  it("states a reference population from its total rather than from the page length", async () => {
    const hypotheses = (await client().hypotheses(demo)).payload!;
    const amendment = hypotheses.items.find(
      (entry) => entry.registration_id === REGISTRATIONS.amendment,
    )!;
    render(
      <ClockProvider clock={clock}>
        <ReferenceListPanel
          list={amendment.linked_results}
          label="Runs"
          scope={demo}
          empty="none"
          testId="linked-runs"
        />
      </ClockProvider>,
    );
    const panel = screen.getByTestId("linked-runs");
    expect(panel.textContent).toContain("in the population");
    expect(within(panel).getAllByRole("listitem")).toHaveLength(
      amendment.linked_results.items.length,
    );
  });

  it("renders an empty reference list as its stated sentence", () => {
    render(
      <ClockProvider clock={clock}>
        <ReferenceListPanel
          list={{
            items: [],
            cardinality: "ZERO_OR_MORE",
            truncated: false,
            total: {
              value: 0,
              unit: "COUNT",
              availability: "AVAILABLE",
              reason: "NONE",
              as_of: "2026-09-08T12:00:00.000Z",
              metric_id: "reference.total",
              metric_definition_version: "metrics.v1",
            },
          }}
          label="Shadow evidence"
          scope={demo}
          empty="This comparison cites no shadow evidence."
          testId="empty-refs"
        />
      </ClockProvider>,
    );
    expect(screen.getByTestId("empty-refs").textContent).toContain(
      "This comparison cites no shadow evidence.",
    );
  });
});

/* ==================================================================== the read-only notice */

describe("every C7 screen states what it cannot do", () => {
  it("names the absent controls and the absent producers", () => {
    render(
      <ReadOnlyNotice
        subject="assembled packets and recorded decisions"
        actions={["approve", "reject", "release"]}
      />,
    );
    const notice = screen.getByTestId("read-only-notice").textContent!;
    expect(notice).toContain("has no approve, reject, release control");
    expect(notice).toContain("no such control exists anywhere in this application");
    expect(notice).toContain("backtesting has not started");
    expect(notice).toContain("no value here is a result, an approval or an authorization");
  });
});
