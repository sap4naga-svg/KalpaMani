import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { columnsFor, DataTable } from "@/components/cockpit/data-table";
import { FilterChips, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText, MoneyText } from "@/components/cockpit/metric-text";
import { ObservationRules, PerformanceSummaryPanel } from "@/components/cockpit/performance-summary";
import { ReferenceChip } from "@/components/cockpit/read-model-panel";
import { ReturnHeatmap } from "@/components/cockpit/return-heatmap";
import {
  AddPlannedRiskRecords,
  InitialPlannedRiskRecord,
  OpenPlannedRiskRecord,
  PermittedRiskRecord,
  RiskSeparationNote,
} from "@/components/cockpit/risk-records";
import { TradePriceChart } from "@/components/cockpit/trade-chart";
import { absent, available, qualified } from "@/contracts/factories";
import type { PerformanceSummaryPayload } from "@/contracts/portfolio-models";
import type { Series } from "@/contracts/values";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

const AS_OF = "2026-09-06T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };
const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });

/* ================================================================= metric text */

describe("inline metric rendering", () => {
  it("shows the unit for every displayed metric (U19)", () => {
    render(
      <MetricText
        metric={available({
          metricId: "risk.open_planned",
          unit: "USD",
          value: "757.15",
          asOf: AS_OF,
        })}
      />,
    );
    expect(screen.getByText("+757.15")).toBeInTheDocument();
    expect(screen.getByText("USD")).toBeInTheDocument();
  });

  it("shows a ratio's denominator beside it", () => {
    render(
      <MetricText
        metric={available({ metricId: "win_rate", unit: "RATIO", value: "0.44", asOf: AS_OF })}
        denominator="defined population"
      />,
    );
    expect(screen.getByText("per defined population")).toBeInTheDocument();
  });

  it("renders an unavailable metric as its state and never as a zero", () => {
    const { container } = render(
      <MetricText
        metric={absent(
          "INSUFFICIENT_OBSERVATIONS",
          "BELOW_MINIMUM_OBSERVATIONS",
          "profit_factor",
          "RATIO",
        )}
      />,
    );
    expect(screen.getByText("Insufficient observations")).toBeInTheDocument();
    expect(/\b0(\.0+)?\b/.test(container.textContent ?? "")).toBe(false);
  });

  it("keeps a STALE value's qualification beside the value", () => {
    render(
      <MetricText
        metric={qualified("STALE", "UPSTREAM_INPUT_STALE", {
          metricId: "risk.open_planned",
          unit: "USD",
          value: "74.55",
          asOf: AS_OF,
        })}
      />,
    );
    expect(screen.getByText("+74.55")).toBeInTheDocument();
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  it("carries the sign as well as the colour for a loss (U11)", () => {
    render(<MoneyText amount="-386.00" signed />);
    expect(screen.getByText("-386.00")).toBeInTheDocument();
  });
});

/* ================================================================== data table */

interface Row {
  readonly id: string;
  readonly symbol: string;
  readonly side: string;
  readonly value: number;
}

const ROWS: Row[] = [
  { id: "one", symbol: "DEMO.ARB", side: "LONG", value: 3 },
  { id: "two", symbol: "DEMO.HLX", side: "SHORT", value: 1 },
  { id: "three", symbol: "DEMO.NVL", side: "LONG", value: 2 },
];

const helper = columnsFor<Row>();
const ROW_COLUMNS = helper.columns([
  helper.accessor((row) => row.symbol, { id: "symbol", header: () => "Security" }),
  helper.accessor((row) => row.side, { id: "side", header: () => "Side" }),
  helper.accessor((row) => row.value, { id: "value", header: () => "Value" }),
]);

function table(props: Partial<React.ComponentProps<typeof DataTable<Row>>> = {}) {
  return render(
    <DataTable
      caption="Demonstration rows"
      columns={ROW_COLUMNS}
      data={ROWS}
      getRowId={(row) => row.id}
      empty={<span>No row matches the filters.</span>}
      testId="demo-table"
      {...props}
    />,
  );
}

describe("the shared data table", () => {
  it("renders real headers with scopes and an accessible caption", () => {
    table();
    const grid = screen.getByTestId("demo-table");
    expect(within(grid).getByText("Demonstration rows")).toBeInTheDocument();
    for (const header of ["Security", "Side", "Value"]) {
      expect(within(grid).getByRole("columnheader", { name: new RegExp(header) })).toBeInTheDocument();
    }
    // The first cell of each row is the row's own header.
    expect(within(grid).getAllByRole("rowheader").length).toBe(ROWS.length);
  });

  it("announces its sort state and sorts from a keyboard-reachable button", async () => {
    const user = userEvent.setup();
    table();
    const header = screen.getByRole("columnheader", { name: /Value/ });
    expect(header).toHaveAttribute("aria-sort", "none");

    /* A numeric column sorts descending first, which is the library's own convention. */
    await user.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "descending");
    expect(screen.getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual([
      "DEMO.ARB",
      "DEMO.NVL",
      "DEMO.HLX",
    ]);

    await user.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual([
      "DEMO.HLX",
      "DEMO.NVL",
      "DEMO.ARB",
    ]);
  });

  it("scrolls inside its own keyboard-reachable region rather than the page", () => {
    table();
    const region = screen.getByRole("region", { name: "Demonstration rows" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region.className).toContain("overflow-x-auto");
  });

  it("opens a row detail from a keyboard, with aria-expanded and aria-controls", async () => {
    const user = userEvent.setup();
    table({ renderDetail: (row) => <p>Detail for {row.symbol}</p> });
    const toggle = screen.getAllByRole("button", { name: /Show details for/ })[0];
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Detail for/)).toBeInTheDocument();
  });

  it("says so when a filter leaves no rows, rather than rendering an empty table", () => {
    table({ data: [], empty: <span>No row matches the filters.</span> });
    expect(screen.getByText("No row matches the filters.")).toBeInTheDocument();
  });

  it("narrows by the global filter without changing the delivered data", () => {
    table({ globalFilter: "HLX" });
    const rows = screen.getAllByRole("rowheader").map((cell) => cell.textContent);
    expect(rows).toEqual(["DEMO.HLX"]);
  });
});

/* ==================================================================== filters */

describe("filters are visible and removable", () => {
  it("renders one removable chip per applied filter", async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    const onClearAll = vi.fn();
    render(
      <FilterChips
        chips={[
          { key: "dir", label: "Side", value: "SHORT" },
          { key: "sector", label: "Sector", value: "ENERGY" },
        ]}
        onRemove={onRemove}
        onClearAll={onClearAll}
      />,
    );
    expect(screen.getByTestId("filter-chips")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove the Side filter" }));
    expect(onRemove).toHaveBeenCalledWith("dir");
    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onClearAll).toHaveBeenCalled();
  });

  it("says explicitly when no filter is applied", () => {
    render(<FilterChips chips={[]} onRemove={vi.fn()} onClearAll={vi.fn()} />);
    expect(screen.getByTestId("filter-chips-empty")).toHaveTextContent(
      /No filter is applied/,
    );
  });

  it("labels every filter control for a screen reader", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <>
        <SearchField
          id="search"
          label="Search"
          value=""
          onChange={onChange}
          placeholder="Symbol"
        />
        <SelectField
          id="side"
          label="Side"
          value=""
          onChange={onChange}
          options={[{ value: "LONG", label: "Long" }]}
        />
      </>,
    );
    expect(screen.getByLabelText("Search")).toBeInTheDocument();
    const select = screen.getByLabelText("Side");
    await user.selectOptions(select, "LONG");
    expect(onChange).toHaveBeenCalledWith("LONG");
  });
});

/* ============================================================== risk records */

describe("the risk records never share a label", () => {
  it("renders the initial record with its recorded instant and its invalidation reference", async () => {
    const positions = await client.positions(DEMO);
    const row = positions.payload?.items[0];
    expect(row).toBeDefined();
    if (row === undefined) return;
    render(<InitialPlannedRiskRecord wrapper={row.initial_planned_risk} operator />);
    expect(screen.getByTestId("initial-planned-risk")).toBeInTheDocument();
    expect(screen.getByText("Initial planned risk")).toBeInTheDocument();
    expect(screen.getByText("Recorded at")).toBeInTheDocument();
    expect(screen.getByText(/Never an order/)).toBeInTheDocument();
    expect(screen.getByText("RISK_RECORD_AT_ENTRY")).toBeInTheDocument();
  });

  it("renders the assessment with its own as-of and marks a stale one", async () => {
    const positions = await client.positions(DEMO);
    const stale = positions.payload?.items.find(
      (item) => item.open_planned_risk.availability === "STALE",
    );
    expect(stale, "the fixture carries one stale assessment").toBeDefined();
    if (stale === undefined) return;
    render(<OpenPlannedRiskRecord wrapper={stale.open_planned_risk} />);
    expect(screen.getByTestId("open-planned-risk")).toBeInTheDocument();
    expect(screen.getByText("Current open planned risk")).toBeInTheDocument();
    expect(screen.getByText("Assessed at")).toBeInTheDocument();
    expect(screen.getByTestId("assessment-stale")).toBeInTheDocument();
  });

  it("renders a permitted limit with no policy reference as absent, never as a number", () => {
    const { container } = render(
      <PermittedRiskRecord
        scope="OPEN_PORTFOLIO"
        wrapper={{ availability: "NOT_YET_AVAILABLE", reason: "POLICY_REFERENCE_MISSING" }}
      />,
    );
    expect(screen.getByTestId("permitted-OPEN_PORTFOLIO")).toBeInTheDocument();
    expect(screen.getAllByText("POLICY_REFERENCE_MISSING").length).toBeGreaterThan(0);
    expect(/\d/.test(container.textContent ?? "")).toBe(false);
  });

  /*
   * 12.4's three facts, on screen: the original record, each add's own record, and the SUM
   * that R was divided by, which is none of them. The version of each contributing policy is
   * printed with its own record, so a trade whose stages differ shows both.
   */
  it("shows each add's own record and the summed R denominator beside them", async () => {
    const trades = await client.trades(DEMO);
    const pyramided = trades.payload?.items.find(
      (item) => item.trade_id === "demo-trade-nvl-0002",
    );
    expect(pyramided?.add_planned_risk, "the fixture carries one pyramid").toBeDefined();
    if (pyramided?.add_planned_risk === undefined) return;

    render(
      <AddPlannedRiskRecords
        adds={pyramided.add_planned_risk}
        denominator={pyramided.r_denominator}
      />,
    );
    expect(screen.getByTestId("add-planned-risk")).toBeInTheDocument();
    expect(screen.getByText("Add 1 — its own record")).toBeInTheDocument();
    /* The add's own reference price, not the trade's blended basis. */
    const addPrice = pyramided.add_planned_risk[0].record.reference_price.amount;
    expect(screen.getByText(new RegExp(addPrice.replace(".", "\.")))).toBeInTheDocument();
    /* And the summed denominator is stated rather than left to be inferred. */
    const summed = screen.getByTestId("r-denominator");
    expect(summed).toHaveTextContent(/retained records summed/);
    expect(summed).toHaveTextContent(/is not the entry record/);
  });

  it("prints every contributing policy version, one per retained record", async () => {
    const trades = await client.trades(DEMO);
    const pyramided = trades.payload?.items.find(
      (item) => item.trade_id === "demo-trade-nvl-0002",
    );
    if (pyramided?.add_planned_risk === undefined) return;
    const entryVersion = pyramided.initial_planned_risk.record?.risk_policy_ref.policy_version;
    const addVersion = pyramided.add_planned_risk[0].record.risk_policy_ref.policy_version;
    expect(entryVersion).not.toBe(addVersion);

    render(
      <>
        <InitialPlannedRiskRecord wrapper={pyramided.initial_planned_risk} />
        <AddPlannedRiskRecords
          adds={pyramided.add_planned_risk}
          denominator={pyramided.r_denominator}
        />
      </>,
    );
    expect(screen.getByText(new RegExp(String(entryVersion)))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(String(addVersion)))).toBeInTheDocument();
  });

  it("states the separation between the two planned-risk quantities", () => {
    render(<RiskSeparationNote />);
    expect(screen.getByTestId("risk-separation-note")).toHaveTextContent(
      /A moving stop changes only the second/,
    );
  });

  it("renders an absent initial record as unavailable rather than inapplicable", async () => {
    const trades = await client.trades(DEMO);
    const orphan = trades.payload?.items.find(
      (item) => item.initial_planned_risk.availability === "NOT_YET_AVAILABLE",
    );
    expect(orphan).toBeDefined();
    if (orphan === undefined) return;
    render(<InitialPlannedRiskRecord wrapper={orphan.initial_planned_risk} />);
    expect(screen.getByTestId("absent-record")).toBeInTheDocument();
    expect(screen.getByText(/never computed from a current stop/)).toBeInTheDocument();
  });
});

/* ========================================================== performance summary */

describe("a summary shows the rules its ratios were computed under", () => {
  async function summary(): Promise<PerformanceSummaryPayload> {
    const response = await client.performanceSummary(DEMO, "ALL");
    const payload = response.payload;
    if (payload === undefined) {
      throw new Error("the demonstration summary is expected to carry a payload");
    }
    return payload;
  }

  it("renders every declared minimum-observation rule", async () => {
    render(<ObservationRules summary={await summary()} />);
    const rules = screen.getByTestId("observation-rules");
    for (const metric of ["win_rate", "profit_factor", "expectancy.currency", "sharpe"]) {
      expect(within(rules).getByText(metric)).toBeInTheDocument();
    }
  });

  it("states that a displayable metric is still not a finding", async () => {
    render(<PerformanceSummaryPanel summary={await summary()} />);
    expect(
      screen.getByText(/A metric that passes every rule here is still not a finding/),
    ).toBeInTheDocument();
  });

  it("counts the rows the population excludes", async () => {
    render(<PerformanceSummaryPanel summary={await summary()} />);
    expect(screen.getByTestId("population-exclusions")).toHaveTextContent(
      /The population excludes rows, and they are counted/,
    );
  });
});

/* ================================================================== heat map */

describe("the monthly return heat map", () => {
  function monthly(points: readonly { t: string; value: string }[]): Series {
    return {
      points: points.map((point) => ({
        t: point.t,
        v: available({
          metricId: "return.period",
          unit: "PERCENT",
          value: point.value,
          asOf: AS_OF,
        }),
      })),
      granularity: "MONTHLY",
      calendar: { code: "XNYS_EQUITY_REGULAR_SESSION", vocabulary: "t", vocabulary_version: "v1" },
      timezone: "UTC",
      coverage: { present: points.length, requested: points.length },
      completeness: "COMPLETE",
    };
  }

  it("leaves a month with no observation blank rather than zero", () => {
    render(
      <ReturnHeatmap
        series={monthly([
          { t: "2026-01-30", value: "1.20" },
          { t: "2026-03-31", value: "-0.80" },
        ])}
        granularity="MONTHLY"
      />,
    );
    const grid = screen.getByTestId("return-heatmap");
    const observed = within(grid).getAllByText(/\+1\.20|-0\.80/);
    expect(observed.length).toBe(2);
    // February carries no observation, and it is announced as one rather than shown as 0.00.
    expect(within(grid).getAllByText("No observation").length).toBeGreaterThan(0);
    expect(within(grid).queryByText("0.00")).toBeNull();
  });

  it("refuses to derive monthly returns from another granularity", () => {
    render(<ReturnHeatmap series={monthly([])} granularity="DAILY" />);
    expect(screen.getByTestId("heatmap-wrong-granularity")).toHaveTextContent(
      /not derived from it here/,
    );
  });
});

/* =============================================================== trade chart */

describe("the trade price view", () => {
  it("carries the same marks and events in a keyboard-reachable table (U10)", async () => {
    const user = userEvent.setup();
    const detail = await client.tradeDetail(DEMO, "demo-trade-cir-0003");
    const lifecycle = await client.tradeLifecycle(DEMO, "demo-trade-cir-0003");
    const series = detail.payload?.chart_series;
    expect(series).toBeDefined();
    if (series === undefined) return;

    const markers = (lifecycle.payload?.events ?? []).map((event) => ({
      day: event.event_time.slice(0, 10),
      label: "Entry",
      kind: "ENTRY" as const,
      price: String(event.price.value),
      quantity: event.quantity,
    }));

    render(
      <TradePriceChart
        series={series}
        markers={markers}
        levels={[
          { label: "Entry reference", price: "88.20", note: "the entry-time reference" },
        ]}
        direction="LONG"
        caption="DEMO.CIR recorded marks"
      />,
    );

    // The plot is labelled, and it states that it is a mark line rather than OHLC.
    expect(screen.getByRole("img", { name: /recorded session marks/ })).toBeInTheDocument();
    expect(screen.getByText(/Not OHLC/)).toBeInTheDocument();

    await user.click(screen.getByText(/Marks and recorded events as a table/));
    const region = screen.getByRole("region", { name: /as a table/ });
    expect(within(region).getAllByRole("row").length).toBe(series.points.length + 1);
    // Every recorded event appears in the alternative, and the sessions without one say so.
    expect(within(region).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("draws no chart at all when no mark path was recorded", () => {
    render(
      <TradePriceChart
        series={{
          points: [],
          granularity: "DAILY",
          calendar: { code: "X", vocabulary: "t", vocabulary_version: "v1" },
          timezone: "UTC",
          coverage: { present: 0, requested: 0 },
          completeness: "UNKNOWN",
        }}
        markers={[]}
        levels={[]}
        direction="LONG"
        caption="nothing"
      />,
    );
    expect(screen.getByTestId("trade-chart-empty")).toHaveTextContent(
      /Nothing is interpolated/,
    );
  });
});

/* =============================================================== references */

describe("references are carried rather than omitted", () => {
  it("states an unresolvable reference's resolution and classification", () => {
    render(
      <ReferenceChip
        reference={{
          ref_id: "demo-candidate",
          ref_kind: "candidate",
          resolution: "UNRESOLVABLE_V1",
          classification: "PUBLIC_SAFE",
        }}
      />,
    );
    expect(screen.getByText("UNRESOLVABLE_V1")).toBeInTheDocument();
    expect(screen.getByText("PUBLIC_SAFE")).toBeInTheDocument();
  });
});
