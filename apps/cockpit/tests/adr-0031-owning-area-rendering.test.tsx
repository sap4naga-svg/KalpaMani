/**
 * ADR-0031 — the two navigation affordances, rendered.
 *
 * §4.3.2 states the presentation rules as rules rather than as style: the two controls are
 * distinct and never merged, the area control names the AREA and may never read as retrieval,
 * an absent area renders nothing at all, and a destination whose screen is not built stays
 * visibly not yet implemented. Each of those is checkable on the real components, so each is
 * checked on them here rather than on the table they read from.
 *
 * Nothing here reads `Date.now()`.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ROUTES_BY_HREF } from "@/nav/registry";

import { AttentionPanel } from "@/components/cockpit/attention";
import { WhatChangedPanel } from "@/components/cockpit/what-changed";
import { ClockProvider } from "@/components/shell/clock-provider";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE, type ViewScope } from "@/lib/scope";

const ORIGIN = Date.parse("2026-09-20T12:00:00.000Z");
const clock = fixedClock(ORIGIN);
const client = () => new FixtureReadClient({ clock, originMs: ORIGIN });
const demo = (over: Partial<ViewScope> = {}): ViewScope => ({
  ...DEFAULT_SCOPE,
  scenario: "demo",
  ...over,
});

const attentionPanel = async (operator = false) => {
  const envelope = await client().attention(demo());
  return render(
    <ClockProvider clock={clock}>
      <AttentionPanel envelope={envelope} scope={demo()} operator={operator} withFilters />
    </ClockProvider>,
  );
};

const whatChangedPanel = async () => {
  const envelope = await client().whatChanged(demo());
  return render(
    <ClockProvider clock={clock}>
      <WhatChangedPanel envelope={envelope} scope={demo()} operator={false} />
    </ClockProvider>,
  );
};

describe("the attention disclosure renders both affordances, apart", () => {
  it("offers an area control on every visible reference, to four different areas", async () => {
    await attentionPanel();
    const areas = screen
      .getAllByTestId("reference-area-link")
      .map((link) => link.getAttribute("href"));
    expect(areas).toHaveLength(4);
    expect(new Set(areas.map((href) => href!.split("?")[0]))).toEqual(
      new Set([
        "/system/data-quality",
        "/strategy/health",
        "/risk/short-side",
        "/execution/reconciliation",
      ]),
    );
  });

  it("keeps the target control and the area control as two separate links", async () => {
    await attentionPanel();
    for (const row of screen.getAllByTestId("evidence-reference")) {
      const target = within(row).getByTestId("reference-target-link");
      const area = within(row).getByTestId("reference-area-link");
      expect(target).not.toBe(area);
      // The target names the record's own destination; the area names the area.
      expect(target.getAttribute("href")).toContain("/governance/audit");
      expect(area.getAttribute("href")).not.toContain("/governance/audit");
    }
  });

  it("labels the area control as AREA navigation and never as retrieval", async () => {
    await attentionPanel();
    for (const link of screen.getAllByTestId("reference-area-link")) {
      const label = link.textContent!.toLowerCase();
      expect(label).toContain("area");
      for (const verb of ["view", "open", "retrieve", "resolve", "show", "evidence"]) {
        expect(label, verb).not.toContain(verb);
      }
    }
  });

  it("says out loud when the destination screen is not built yet", async () => {
    await attentionPanel();
    const rows = screen.getAllByTestId("evidence-reference");
    const shortSide = rows.find((row) =>
      within(row)
        .getByTestId("reference-area-link")
        .getAttribute("href")!
        .startsWith("/risk/short-side"),
    )!;
    // The one implemented destination carries no "not yet implemented" qualification...
    expect(within(shortSide).queryByTestId("reference-area-placeholder")).toBeNull();
    expect(
      within(shortSide).getByTestId("reference-area-link").getAttribute("data-area-status"),
    ).toBe("implemented");

    const health = rows.find((row) =>
      within(row)
        .getByTestId("reference-area-link")
        .getAttribute("href")!
        .startsWith("/strategy/health"),
    )!;
    expect(within(health).queryByTestId("reference-area-placeholder")).toBeNull();
    expect(
      within(health).getByTestId("reference-area-link").getAttribute("data-area-status"),
    ).toBe("implemented");

    /*
     * ...AND THE MARKER IS DERIVED, NOT COUNTED.
     *
     * C7 built the Strategy Health area and C8 built the remaining five, so every destination
     * the attention list reaches is now a built screen and the marker appears nowhere. **The
     * expectation is computed from the registry rather than written as a number**, so it is
     * the same assertion it always was: the marker is present exactly where the DESTINATION'S
     * OWN status says the screen is not built, and it moves the moment that changes.
     */
    const expectedMarkers = rows.filter((row) => {
      const href = within(row).getByTestId("reference-area-link").getAttribute("href")!;
      const route = ROUTES_BY_HREF.get(href.split("?")[0]);
      return route === undefined || route.status !== "implemented";
    }).length;
    expect(screen.queryAllByTestId("reference-area-placeholder")).toHaveLength(
      expectedMarkers,
    );
    for (const row of rows) {
      const link = within(row).getByTestId("reference-area-link");
      const route = ROUTES_BY_HREF.get(link.getAttribute("href")!.split("?")[0])!;
      expect(link.getAttribute("data-area-status"), link.getAttribute("href")!).toBe(
        route.status,
      );
      expect(
        within(row).queryByTestId("reference-area-placeholder") !== null,
        link.getAttribute("href")!,
      ).toBe(route.status !== "implemented");
    }
  });

  it("still renders no owning-area control where the reference declares none", async () => {
    await whatChangedPanel();
    const rows = screen.getAllByTestId("change-evidence-reference");
    const declared = rows.filter((row) => row.getAttribute("data-owning-area") !== "");
    const absent = rows.filter((row) => row.getAttribute("data-owning-area") === "");
    expect(declared.length).toBeGreaterThan(0);
    expect(absent.length).toBeGreaterThan(0);
    for (const row of absent) {
      // No control, and no substitute control either.
      expect(within(row).queryByTestId("reference-area-link")).toBeNull();
      expect(within(row).getByTestId("reference-target-link")).toBeTruthy();
    }
  });

  it("gives What Changed the same two affordances as attention", async () => {
    await whatChangedPanel();
    const areas = screen
      .getAllByTestId("reference-area-link")
      .map((link) => link.getAttribute("href")!.split("?")[0]);
    expect(new Set(areas)).toEqual(new Set(["/strategy/health", "/system/operations"]));
  });

  it("keeps the evidence-kind filter chips from the CONTRACT, not from the areas", async () => {
    await attentionPanel();
    // section 4.5 declares two kinds for this field, and neither is an owning area.
    for (const kind of ["Evidence", "Source fact"]) {
      expect(screen.getAllByRole("button", { name: new RegExp(kind, "i") }).length)
        .toBeGreaterThan(0);
    }
    for (const area of ["Data quality area", "Short-side area"]) {
      expect(screen.queryByRole("button", { name: area })).toBeNull();
    }
  });
});
