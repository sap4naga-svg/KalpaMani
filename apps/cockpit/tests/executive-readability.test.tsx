import { render, screen, waitFor, within } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import ExecutiveOverviewPage from "@/app/page";
import { Providers } from "@/components/shell/providers";
import { createDefaultReadClient } from "@/data/client/default-client";
import type { ReadClient } from "@/data/client/read-client";
import { fixedClock } from "@/lib/clock";
import { formatDecimal, formatInstant } from "@/lib/format";
import { SUMMARY_MEDIA_QUERY } from "@/lib/mobile-summary";
import { DEFAULT_SCOPE, PERIOD_LABEL } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { ROUTES_BY_HREF } from "@/nav/registry";
import { twMerge } from "tailwind-merge";

/**
 * The Executive Overview's reading hierarchy, after the post-PR #89 usability refinement.
 *
 * The owner found the first cut "clumsy, text-heavy and slow to digest", and each correction
 * below was made against a finding verified in the rendered page. These tests hold the
 * corrections to the rules that justify them rather than to the pixels:
 *
 *   - a tile's destination link is the REGISTERED NAME of the area it goes to, and names no record
 *   - open planned risk is a MAGNITUDE: no leading plus, no gain colour; the return keeps both
 *   - the contract explanations sit behind an accessible disclosure, and the availability and
 *     provenance badges never do
 *   - the headline return states its as-of and that its window is NOT stated by its read model,
 *     and the chart states the window it draws -- two figures, never one implied period
 *   - a baseline instant reads to the minute with its timezone, and its full form stays where
 *     the record is quoted
 */

// --------------------------------------------------------------- a wide viewport, and no drift

/*
 * `matchMedia` does not exist in jsdom. The page asks the breakpoint query once and only
 * that query; these tests render the desktop layout, so the answer is "not below 640".
 */
Object.defineProperty(window, "matchMedia", {
  configurable: true,
  writable: true,
  value: (query: string) => {
    if (query !== SUMMARY_MEDIA_QUERY) {
      throw new Error(`unexpected media query in this test file: ${query}`);
    }
    return {
      matches: false,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent() {
        return true;
      },
    } as unknown as MediaQueryList;
  },
});

let search = "scenario=demo&mode=executive";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  usePathname: () => "/",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
}));

const ORIGIN = Date.parse("2026-09-20T12:00:00.000Z");
const clock = fixedClock(ORIGIN);
const client: ReadClient = createDefaultReadClient(clock);
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };

function renderPage(query = "scenario=demo&mode=executive") {
  search = query;
  return render(
    <Providers clock={clock} readClient={client}>
      <ExecutiveOverviewPage />
    </Providers>,
  );
}

const TILES = [
  "tile-strategy-capital",
  "answer-performance",
  "answer-risk",
  "answer-health",
  "answer-changed",
  "answer-attention",
] as const;

/**
 * A tile whose reads have settled: it exists from the first render, so its existence proves
 * nothing -- the skeleton inside it must have gone before its content can be read.
 */
async function settled(testId: string): Promise<HTMLElement> {
  const tile = await screen.findByTestId(testId);
  await waitFor(() => {
    expect(tile.querySelectorAll('[data-testid="skeleton"]')).toHaveLength(0);
  });
  return tile;
}

/**
 * One named part of a tile. Parts carry `data-tile-part` rather than `data-testid`, because the
 * ADR-0033 governance guard reads every test id in `page.tsx` as a page SECTION that the M3
 * content-to-location table must account for -- and a line inside a tile is not a section.
 */
function part(tile: HTMLElement, name: string): HTMLElement {
  const found = tile.querySelector<HTMLElement>(`[data-tile-part="${name}"]`);
  expect(found, `tile part ${name}`).not.toBeNull();
  return found!;
}

/** The large figure a tile answers with: the `xl` numeric, and exactly one per tile. */
function figureOf(tile: HTMLElement): HTMLElement {
  const figures = tile.querySelectorAll<HTMLElement>("[data-numeric].text-numeric-xl");
  expect(figures, "one primary figure per tile (section 4.4)").toHaveLength(1);
  return figures[0];
}

// ================================================================= cn and the size tokens

describe("cn keeps a text size token beside a text colour (the defect behind the small figures)", () => {
  it("keeps every size token the theme declares when a colour follows it", () => {
    for (const size of ["numeric-xl", "numeric-l", "numeric-m", "numeric-s", "label-m", "label-s"]) {
      for (const colour of ["text-text-primary", "text-positive", "text-negative", "text-warning"]) {
        const merged = cn(`text-${size}`, colour);
        expect(merged.split(" ")).toEqual(expect.arrayContaining([`text-${size}`, colour]));
      }
    }
  });

  it("still lets a later size override an earlier one, and a later colour an earlier one", () => {
    expect(cn("text-numeric-l", "text-numeric-xl")).toBe("text-numeric-xl");
    expect(cn("text-positive", "text-negative")).toBe("text-negative");
    expect(cn("text-label-s", "text-text-tertiary", "text-label-m")).toBe("text-text-tertiary text-label-m");
  });

  it("would have dropped the size under a merge that does not know the tokens (the negative control)", () => {
    /* The stock merge classifies an unknown `text-*` as a colour, so the size loses to the colour. */
    expect(twMerge("text-numeric-xl text-text-primary")).toBe("text-text-primary");
    expect(twMerge("text-label-s text-warning")).toBe("text-warning");
  });

  it("renders every tile figure at the xl token and every badge at the label-s token", async () => {
    renderPage();
    const capital = await settled("tile-strategy-capital");
    expect(figureOf(capital).className.split(" ")).toContain("text-numeric-xl");
    const badge = capital.querySelector("[data-provenance]");
    expect(badge?.className.split(" ")).toContain("text-label-s");
  });
});

// ================================================================= formatInstant

describe("formatInstant — a UTC instant to the minute, with its timezone, and nothing recomputed", () => {
  it("renders a millisecond ISO instant as date, minute and UTC", () => {
    expect(formatInstant("2026-09-09T19:54:43.232Z")).toBe("2026-09-09 19:54 UTC");
  });

  it("renders a second-precision and a minute-precision instant the same way", () => {
    expect(formatInstant("2026-09-09T19:54:43Z")).toBe("2026-09-09 19:54 UTC");
    expect(formatInstant("2026-09-09T19:54Z")).toBe("2026-09-09 19:54 UTC");
  });

  it("takes its characters from the string, so no local timezone can shift the hour", () => {
    /* 23:59 UTC is the next calendar day in every timezone east of UTC; the text must not be. */
    expect(formatInstant("2026-12-31T23:59:59.999Z")).toBe("2026-12-31 23:59 UTC");
  });

  it("returns anything that is not a Z-suffixed ISO instant unchanged rather than guessing", () => {
    for (const other of ["2026-09-09", "absent", "2026-09-09T19:54:43+02:00", ""]) {
      expect(formatInstant(other)).toBe(other);
    }
  });
});

// ================================================================= destinations

describe("each executive answer names its destination as the registry names the area", () => {
  it("labels every tile's link with the registered area label, and nothing else", async () => {
    renderPage();
    for (const testId of TILES) {
      const tile = await settled(testId);
      const link = part(tile, "destination");
      const href = link.getAttribute("href") ?? "";
      const path = href.split("?")[0];
      const route = ROUTES_BY_HREF.get(path);
      expect(route, `${testId} links to ${path}, which must be a registered area`).toBeDefined();
      expect(link.textContent?.trim()).toBe(`${route!.label} →`);
      /* The accessible name is the visible text; no hidden suffix is needed to tell them apart. */
      expect(link.getAttribute("aria-label")).toBeNull();
    }
  });

  it("gives the six tiles six different names, and none that claims to open a record", async () => {
    renderPage();
    const names: string[] = [];
    for (const testId of TILES) {
      const tile = await settled(testId);
      names.push(part(tile, "destination").textContent?.trim() ?? "");
    }
    expect(new Set(names).size).toBe(6);
    for (const name of names) {
      expect(name).not.toMatch(/\b(open|view|show|retrieve|evidence|record|owns)\b/i);
    }
  });

  it("would not name an unregistered destination (the negative control)", () => {
    /* The label comes from the registry, so a path the registry does not know has no label. */
    expect(ROUTES_BY_HREF.get("/risk")?.label).toBe("Risk Dashboard");
    expect(ROUTES_BY_HREF.get("/risk/nowhere")).toBeUndefined();
  });
});

// ================================================================= magnitudes and directions

describe("a magnitude is never dressed as a profit (section 4.3)", () => {
  it("renders open planned risk with no leading plus and no gain colour", async () => {
    const overview = await client.executiveOverview(DEMO);
    const record = overview.payload?.open_planned_risk.record;
    expect(record).toBeDefined();
    const expected = formatDecimal(String(record!.risk_money.value), {
      minimumFractionDigits: 2,
    });
    expect(expected, "the fixture's risk is a positive decimal").toMatch(/^[1-9]/);

    renderPage();
    const tile = await settled("answer-risk");
    const figure = figureOf(tile);
    expect(figure.textContent).toBe(expected);
    expect(figure.textContent).not.toMatch(/^\+/);
    expect(figure.className).not.toContain("text-positive");
    expect(figure.className).not.toContain("text-negative");
    expect(figure.className).toContain("text-text-primary");
  });

  it("keeps the sign and the direction colour on the return, which IS a gain or a loss", async () => {
    const overview = await client.executiveOverview(DEMO);
    const value = String(overview.payload?.return_pct.value);
    const sign = value.startsWith("-") ? -1 : /[1-9]/.test(value) ? 1 : 0;
    expect(sign, "the fixture's return is non-zero").not.toBe(0);

    renderPage();
    const tile = await settled("answer-performance");
    const figure = figureOf(tile);
    expect(figure.textContent).toMatch(sign > 0 ? /^\+/ : /^-/);
    expect(figure.className).toContain(sign > 0 ? "text-positive" : "text-negative");
  });

  it("renders the observed broker balance and the policy limit as magnitudes too", async () => {
    renderPage();
    const equity = await settled("tile-portfolio.broker_reported_equity");
    const figure = within(equity).getByText("1,000,000.00");
    expect(figure.className).not.toContain("text-positive");
    expect(within(equity).queryByText("+1,000,000.00")).toBeNull();
    /* The permitted-risk tile is unavailable in the demo fixture and renders its state. */
    const permitted = await settled("tile-risk.permitted");
    expect(within(permitted).getByTestId("unavailable-body")).toHaveAttribute(
      "data-availability",
      "NOT_YET_AVAILABLE",
    );
  });

  it("keeps drawdown directional, because a drawdown is a loss", async () => {
    const overview = await client.executiveOverview(DEMO);
    const value = String(overview.payload?.drawdown.value);
    /* `drawdown.current` is equity / running peak - 1, never positive: it is a loss or zero. */
    expect(value).not.toMatch(/^[1-9]/);
    const atPeak = !/[1-9]/.test(value);

    renderPage();
    const drawdown = await settled("tile-drawdown.current");
    const figure = drawdown.querySelector<HTMLElement>("[data-numeric]");
    if (atPeak) {
      expect(figure?.textContent).not.toMatch(/^[+-]/);
      expect(figure?.className).toContain("text-text-primary");
    } else {
      expect(figure?.textContent).toMatch(/^-/);
      expect(figure?.className).toContain("text-negative");
    }
  });
});

// ================================================================= what stays visible

describe("supporting prose is on demand; availability and provenance are not", () => {
  it("puts every tile's contract explanation behind a collapsed, named disclosure", async () => {
    renderPage();
    for (const testId of TILES) {
      const tile = await settled(testId);
      const details = part(tile, "details");
      expect(details.tagName).toBe("DETAILS");
      expect(details).not.toHaveAttribute("open");
      const summary = details.querySelector("summary");
      expect(summary?.textContent).toMatch(/^About /);
      expect(summary?.textContent?.length ?? 0).toBeLessThan(40);
    }
    /* The six disclosures are distinguishable, exactly as the six links are. */
    const summaries = Array.from(document.querySelectorAll('[data-tile-part="details"]')).map(
      (d) => d.querySelector("summary")?.textContent ?? "",
    );
    expect(new Set(summaries).size).toBe(6);
  });

  it("keeps the risk tile's PARTIAL badge and provenance badge outside the disclosure", async () => {
    renderPage();
    const tile = await settled("answer-risk");
    const partial = within(tile).getByText("Partial").closest("[data-availability]");
    expect(partial).toHaveAttribute("data-availability", "PARTIAL");
    expect(partial?.closest("details")).toBeNull();
    const provenance = tile.querySelector("[data-provenance]");
    expect(provenance).toHaveAttribute("data-provenance", "SYNTHETIC");
    expect(provenance?.closest("details")).toBeNull();
  });

  it("moves the caveat sentences into the disclosures, and out of the first reading", async () => {
    renderPage();
    const risk = await settled("answer-risk");
    const caveat = within(risk).getByText(/Permitted open risk is a/);
    expect(caveat.closest("details")).not.toBeNull();
    const health = await settled("answer-health");
    expect(within(health).getByText(/never inferred from the absence of an alert/).closest("details")).not.toBeNull();
    const capital = await settled("tile-strategy-capital");
    expect(within(capital).getByText(/never substituted for it/).closest("details")).not.toBeNull();
  });

  it("keeps the no-baseline explanation visible, never behind a disclosure", async () => {
    renderPage("scenario=demo&mode=executive&changes=no-baseline");
    const tile = await settled("answer-changed");
    const explanation = await within(tile).findByText(/No prior endpoint exists/);
    expect(explanation.closest("details")).toBeNull();
  });
});

// ================================================================= period and context

describe("the headline return and the chart each state their own window", () => {
  it("states the headline's as-of and that its read model states no window", async () => {
    const overview = await client.executiveOverview(DEMO);
    const asOf = overview.payload?.return_pct.as_of;
    expect(asOf).toBeDefined();

    renderPage();
    const tile = await settled("answer-performance");
    const note = part(tile, "window-note");
    expect(note.textContent).toContain(`As of ${formatInstant(asOf!)}`);
    expect(note.textContent).toContain("Window: not stated by this read model");
    /* No period label is attached to the headline: that would be the chart's period, not its own. */
    for (const label of Object.values(PERIOD_LABEL)) {
      expect(tile.textContent).not.toContain(label);
    }
  });

  it("states the chart's period, granularity and declared window beside its title", async () => {
    const series = await client.performanceSeries({ ...DEMO, period: "3M" });
    const window = series.payload?.window;
    expect(window).toBeDefined();

    renderPage("scenario=demo&mode=executive&period=3M");
    const stated = await screen.findByTestId("performance-stated-window");
    expect(stated.textContent).toContain("Over 3 months");
    expect(stated.textContent).toContain("daily");
    expect(stated.textContent).toContain(
      `${window!.from.slice(0, 10)} → ${window!.to.slice(0, 10)}`,
    );
  });

  it("shows the risk assessment's share of strategy capital from the record's own field", async () => {
    const overview = await client.executiveOverview(DEMO);
    const record = overview.payload?.open_planned_risk.record;
    const pct = formatDecimal(String(record!.risk_pct_of_capital.value), {
      minimumFractionDigits: 2,
    });
    renderPage();
    const tile = await settled("answer-risk");
    const context = part(tile, "risk-pct");
    expect(context.textContent).toContain(`${pct} %`);
    expect(context.textContent).toContain("of strategy capital");
    expect(part(tile, "context").textContent).toContain(
      `assessed ${formatInstant(record!.as_of)}`,
    );
  });
});

// ================================================================= readable instants

describe("a baseline instant is readable on the tile and exact where the record is quoted", () => {
  it("renders the What Changed baseline to the minute with UTC, and the panel keeps the full instant", async () => {
    const changes = await client.whatChanged(DEMO);
    const baseline = changes.payload?.baseline_as_of;
    expect(baseline).toBeDefined();

    renderPage();
    const tile = await settled("answer-changed");
    expect(part(tile, "context").textContent).toBe(
      `Baseline ${formatInstant(baseline!)}.`,
    );
    expect(tile.textContent).not.toContain(baseline!);
    const panel = await screen.findByTestId("what-changed-panel");
    expect(panel.textContent).toContain(baseline!);
  });

  it("uses the read model's own baseline label as the tile's subject", async () => {
    const changes = await client.whatChanged(DEMO);
    renderPage();
    const tile = await settled("answer-changed");
    expect(within(tile).getByText(changes.payload!.baseline_label)).toBeInTheDocument();
  });
});
