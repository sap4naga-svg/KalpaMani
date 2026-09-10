import { expect, test, type Page } from "@playwright/test";

import {
  DEFERRED_TEST_IDS,
  DISCLOSURE_IDS,
  DISCLOSURE_LABEL,
  SUMMARY_BREAKPOINT_PX,
  clippedBeyondViewport,
  control,
  disclosure,
  expandByKeyboard,
  horizontalOverflow,
  isSummaryViewport,
  revealDeferredSections,
  visibleControls,
  type DisclosureId,
} from "./mobile-summary";

/**
 * The mobile executive summary — ADR-0033 §2 (Decision M), M8.1 to M8.10.
 *
 * This spec runs in ALL SIX projects. Every test asserts at every width: below the
 * breakpoint it establishes the summary, the disclosures and their semantics; at and above
 * it, it establishes that no disclosure renders and every section is visible (M8.6). A
 * test that found itself at the wrong width does not skip — a skipped criterion reads as
 * coverage that was withheld — it asserts the other half of the same requirement.
 *
 * A TEST THAT FINDS A SECTION ABSENT HAS FOUND A DEFECT OR A COLLAPSED DISCLOSURE, AND IT
 * MUST KNOW WHICH (M8). Every "absent" assertion below is paired with the control that
 * reveals it and with the revealed content's existing test ids.
 */

const FIXED_INSTANT = new Date("2026-09-09T12:00:00.000Z");

const SCOPES = [
  { scenario: "demo", mode: "executive" },
  { scenario: "demo", mode: "operator" },
  { scenario: "project", mode: "executive" },
  { scenario: "project", mode: "operator" },
] as const;

type Scope = (typeof SCOPES)[number];

function url(scope: Scope, extra = ""): string {
  return `/?scenario=${scope.scenario}&mode=${scope.mode}${extra}`;
}

/** The disclosures a scope renders: the fourth exists in Operator mode only (M3). */
function disclosuresFor(scope: Scope): readonly DisclosureId[] {
  return scope.mode === "operator" ? DISCLOSURE_IDS : DISCLOSURE_IDS.slice(0, 3);
}

async function settle(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
  await expect(page.getByTestId("context-bar")).toBeVisible();
  await expect(page.getByTestId("attention-panel")).toBeVisible();
  // The last tier-1 read to settle in either scenario: no skeleton remains in tier one.
  await expect(
    page.locator('section[aria-labelledby="tier-one"] [data-testid="skeleton"]'),
  ).toHaveCount(0);
}

async function open(page: Page, scope: Scope, extra = ""): Promise<void> {
  await page.clock.setFixedTime(FIXED_INSTANT);
  await page.goto(url(scope, extra));
  await settle(page);
}

/** The states a control's badges carry, in the order they render. */
async function badgeStates(page: Page, id: DisclosureId): Promise<string[]> {
  return control(page, id)
    .locator("[data-availability]")
    .evaluateAll((elements) => elements.map((e) => e.getAttribute("data-availability") ?? ""));
}

async function provenanceBadges(page: Page, id: DisclosureId): Promise<string[]> {
  return control(page, id)
    .locator("[data-provenance]")
    .evaluateAll((elements) => elements.map((e) => e.getAttribute("data-provenance") ?? ""));
}

/**
 * The content behind a disclosure, as a comparable record: its text with the charts' SVG
 * excluded — a responsive chart's tick labels depend on its width and are not content — and
 * the test ids it carries, in order.
 */
async function contentRecord(page: Page, id: DisclosureId): Promise<{ text: string; ids: string[] }> {
  return page.evaluate((contentId) => {
    const root = document.getElementById(contentId);
    if (root === null) throw new Error(`no content for ${contentId}`);
    const clone = root.cloneNode(true) as HTMLElement;
    for (const svg of Array.from(clone.querySelectorAll("svg"))) svg.remove();
    const ids = Array.from(root.querySelectorAll("[data-testid]")).map(
      (e) => e.getAttribute("data-testid") ?? "",
    );
    return { text: (clone.textContent ?? "").replace(/\s+/g, " ").trim(), ids };
  }, `summary-disclosure-${id}-content`);
}

async function activeElementId(page: Page): Promise<string> {
  return page.evaluate(() => document.activeElement?.id ?? "");
}

// ------------------------------------------------------------------ M8.1 the summary set

for (const scope of SCOPES) {
  test(`M8.1 — ${scope.scenario} ${scope.mode}: the initially visible set is exactly the summary, in order`, async ({
    page,
  }) => {
    await open(page, scope);
    const mobile = isSummaryViewport(page);

    /* The summary set (M2), each part visible without any interaction, in document order. */
    const summarySelectors = [
      '[data-testid="skip-to-main"]',
      '[data-testid="context-bar"]',
      '[data-testid="page-provenance-banner"]',
      "h1",
      '[data-testid="tile-strategy-capital"]',
      '[data-testid="answer-performance"]',
      '[data-testid="answer-risk"]',
      '[data-testid="answer-health"]',
      '[data-testid="answer-changed"]',
      '[data-testid="answer-attention"]',
      '[data-testid="attention-panel"]',
    ];
    for (const selector of summarySelectors.slice(1)) {
      await expect(page.locator(selector).first(), selector).toBeVisible();
    }
    const ordered = await page.evaluate((selectors) => {
      const nodes = selectors.map((s) => document.querySelector(s));
      if (nodes.some((n) => n === null)) return false;
      return nodes.every(
        (node, index) =>
          index === 0 ||
          (nodes[index - 1]!.compareDocumentPosition(node!) & Node.DOCUMENT_POSITION_FOLLOWING) !==
            0,
      );
    }, summarySelectors);
    expect(ordered, "the summary renders in the accepted document order").toBe(true);

    /* The two highest-ranked attention items, and the link to the full list (M2, M4). */
    if (scope.scenario === "demo") {
      await expect(page.getByTestId("attention-item")).toHaveCount(2);
      await expect(page.getByRole("link", { name: "All attention items →" })).toBeVisible();
    } else {
      await expect(page.getByTestId("attention-panel").getByTestId("unavailable-body")).toBeVisible();
    }

    /* The project scenario's explanation of the unavailable state is never deferred (M2). */
    if (scope.scenario === "project" && scope.mode === "executive") {
      await expect(page.getByText("Why these tiles are empty")).toBeVisible();
    } else {
      await expect(page.getByText("Why these tiles are empty")).toHaveCount(0);
    }

    /* The closing note is the page's statement of what every figure is, and stays visible. */
    await expect(page.getByText("No production read API, projection or metric engine exists")).toBeVisible();

    if (mobile) {
      /* Every other section's control is present and collapsed; its content is not visible. */
      for (const id of disclosuresFor(scope)) {
        await expect(control(page, id), id).toBeVisible();
        await expect(disclosure(page, id), id).not.toHaveAttribute("open");
        await expect(
          control(page, id).getByRole("heading", { level: 2, name: DISCLOSURE_LABEL[id] }),
        ).toBeVisible();
        for (const deferred of DEFERRED_TEST_IDS[id]) {
          await expect(page.getByTestId(deferred), `${deferred} is deferred`).toBeHidden();
        }
      }
      await expect(visibleControls(page)).toHaveCount(disclosuresFor(scope).length);
      /* No fourth disclosure exists outside Operator mode. */
      if (scope.mode === "executive") {
        await expect(disclosure(page, "response-evidence")).toHaveCount(0);
      }
    } else {
      /* At and above the breakpoint every section is simply visible (M8.6). */
      await expect(visibleControls(page)).toHaveCount(0);
      for (const id of disclosuresFor(scope)) {
        for (const deferred of DEFERRED_TEST_IDS[id]) {
          await expect(page.getByTestId(deferred), deferred).toBeVisible();
        }
      }
      await expect(page.getByTestId("performance-overview")).toBeVisible();
      if (scope.mode === "operator") {
        await expect(page.locator('section[aria-labelledby="operator-evidence"]')).toBeVisible();
      }
    }
  });
}

// ------------------------------------------------------------------ M8.2 presence, not absence

for (const scope of SCOPES) {
  test(`M8.2 — ${scope.scenario} ${scope.mode}: every deferred section is revealed by keyboard, with its existing content`, async ({
    page,
  }) => {
    await open(page, scope);
    const mobile = isSummaryViewport(page);

    if (mobile) {
      /*
       * The same page instance, first at a width above the breakpoint, records what the full
       * layout renders for this scope; then, back below it, each disclosure is expanded and
       * must reveal exactly that content -- the same DOM nodes, so the same text and ids.
       */
      await page.setViewportSize({ width: 1024, height: 768 });
      await expect(visibleControls(page)).toHaveCount(0);
      const fullLayout = new Map<DisclosureId, { text: string; ids: string[] }>();
      for (const id of disclosuresFor(scope)) {
        fullLayout.set(id, await contentRecord(page, id));
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(visibleControls(page)).toHaveCount(disclosuresFor(scope).length);

      for (const id of disclosuresFor(scope)) {
        await expect(disclosure(page, id)).not.toHaveAttribute("open");
        await expandByKeyboard(page, id);
        for (const deferred of DEFERRED_TEST_IDS[id]) {
          await expect(page.getByTestId(deferred), `${deferred} revealed`).toBeVisible();
        }
        const revealed = await contentRecord(page, id);
        expect(revealed.ids, `${id}: the same test ids`).toEqual(fullLayout.get(id)!.ids);
        expect(revealed.text, `${id}: the same content`).toBe(fullLayout.get(id)!.text);
        expect(revealed.text.length, `${id}: the content is not empty`).toBeGreaterThan(20);
      }
      if (scope.mode === "operator") {
        await expect(page.locator('section[aria-labelledby="operator-evidence"]')).toBeVisible();
        await expect(page.getByRole("region", { name: "Response evidence fields" })).toBeVisible();
      }
    } else {
      const count = await revealDeferredSections(page);
      expect(count).toBe(0);
      for (const id of disclosuresFor(scope)) {
        const record = await contentRecord(page, id);
        expect(record.text.length, `${id}: rendered in full`).toBeGreaterThan(20);
        for (const deferred of DEFERRED_TEST_IDS[id]) {
          expect(record.ids).toContain(deferred);
        }
      }
    }
  });
}

// ------------------------------------------------------------------ M8.3 the exceptions

test("M8.3 — a degraded tier-2 tile is reported on the collapsed control, and at page level", async ({
  page,
}) => {
  await open(page, { scenario: "demo", mode: "executive" });
  /* The demo scenario degrades the permitted-risk tile: the page reads PARTIAL at every width. */
  await expect(page.getByTestId("page-state")).toBeVisible();
  await expect(page.getByTestId("page-state")).toContainText("Page partial");

  if (isSummaryViewport(page)) {
    await expect(disclosure(page, "supporting-context")).not.toHaveAttribute("open");
    const states = await badgeStates(page, "supporting-context");
    expect(states).toContain("NOT_YET_AVAILABLE");
    /* And the tile behind it keeps its own detailed state, reason and dependency (M6). */
    await expandByKeyboard(page, "supporting-context");
    const tile = page.getByTestId("tile-risk.permitted");
    await expect(tile.getByTestId("unavailable-body")).toBeVisible();
    await expect(tile).toContainText("POLICY_REFERENCE_MISSING");
  } else {
    await expect(visibleControls(page)).toHaveCount(0);
    await expect(page.getByTestId("tile-risk.permitted").getByTestId("unavailable-body")).toBeVisible();
  }
});

// ------------------------------------------------------------------ M8.4 no value on a control

for (const scope of SCOPES) {
  test(`M8.4 — ${scope.scenario} ${scope.mode}: no disclosure control carries a digit, a currency, a percent or an R figure`, async ({
    page,
  }) => {
    await open(page, scope);
    if (isSummaryViewport(page)) {
      for (const id of disclosuresFor(scope)) {
        const text = (await control(page, id).textContent()) ?? "";
        expect(text, `${id}: ${text}`).not.toMatch(/[0-9$%]|\bR\b/);
        expect(text).toContain(DISCLOSURE_LABEL[id]);
        await expect(control(page, id).getByTestId("skeleton")).toHaveCount(0);
      }
    } else {
      /* No control exists to carry anything; the sections carry their own values as before. */
      await expect(visibleControls(page)).toHaveCount(0);
      await expect(page.locator("details[data-summary-disclosure] > summary")).toHaveCount(
        disclosuresFor(scope).length,
      );
      for (const id of disclosuresFor(scope)) {
        await expect(control(page, id)).toBeHidden();
      }
    }
  });
}

// ------------------------------------------------------------------ M8.5 focus

test("M8.5 — Enter and Space toggle a control, focus stays on it, and Escape changes nothing", async ({
  page,
}) => {
  await open(page, { scenario: "demo", mode: "executive" });
  if (isSummaryViewport(page)) {
    const id: DisclosureId = "performance-overview";
    const summary = control(page, id);
    const controlId = `summary-disclosure-${id}-control`;

    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(disclosure(page, id)).toHaveAttribute("open", "");
    expect(await activeElementId(page)).toBe(controlId);
    await expect(page.getByTestId("performance-overview")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(disclosure(page, id)).toHaveAttribute("open", "");
    expect(await activeElementId(page)).toBe(controlId);
    await expect(page.getByTestId("performance-overview")).toBeVisible();
    await expect(page.getByTestId("command-palette")).toHaveCount(0);

    await page.keyboard.press("Space");
    await expect(disclosure(page, id)).not.toHaveAttribute("open");
    expect(await activeElementId(page)).toBe(controlId);
    await expect(page.getByTestId("performance-overview")).toBeHidden();

    /* The controls sit in the tab order in document order: what changed, then performance. */
    await control(page, "what-changed").focus();
    await page.keyboard.press("Tab");
    expect(await activeElementId(page)).toBe(controlId);
  } else {
    /* Above the breakpoint the summaries are hidden and are not in the tab order. */
    await expect(visibleControls(page)).toHaveCount(0);
    const reachable = await page.evaluate(() =>
      Array.from(document.querySelectorAll("details[data-summary-disclosure] > summary")).every(
        (summary) => (summary as HTMLElement).offsetParent === null,
      ),
    );
    expect(reachable).toBe(true);
    await page.getByTestId("performance-overview").getByRole("button", { name: "Drawdown" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("chart-drawdown")).toBeVisible();
  }
});

// ------------------------------------------------------------------ M8.6 above the breakpoint

test("M8.6 — no disclosure renders at or above 640 px, and every section is visible", async ({
  page,
}) => {
  await open(page, { scenario: "demo", mode: "operator" });
  const width = page.viewportSize()?.width ?? 0;
  if (width < SUMMARY_BREAKPOINT_PX) {
    await expect(visibleControls(page)).toHaveCount(4);
    /* And the boundary itself is exact: 640 is above it, 639 is below it. */
    await page.setViewportSize({ width: SUMMARY_BREAKPOINT_PX, height: 844 });
    await expect(visibleControls(page)).toHaveCount(0);
    await expect(page.getByTestId("tile-open-gates")).toBeVisible();
    await page.setViewportSize({ width: SUMMARY_BREAKPOINT_PX - 1, height: 844 });
    await expect(visibleControls(page)).toHaveCount(4);
    await expect(page.getByTestId("tile-open-gates")).toBeHidden();
  } else {
    await expect(visibleControls(page)).toHaveCount(0);
    for (const testId of ["what-changed-panel", "performance-overview", "tile-open-gates", "tile-exposure", "tile-last-runs"]) {
      await expect(page.getByTestId(testId), testId).toBeVisible();
    }
    await expect(page.locator('section[aria-labelledby="operator-evidence"]')).toBeVisible();
    /*
     * No duplicate text across layouts: the hidden control carries no label, so a text
     * locator finds each visible heading exactly once -- as the pre-existing specs expect.
     */
    await expect(page.getByText("Response evidence", { exact: true })).toHaveCount(1);
    await expect(page.getByText("Supporting context", { exact: true })).toHaveCount(1);
    await expect(page.getByText("What changed — details")).toHaveCount(0);
    for (const id of DISCLOSURE_IDS) {
      expect(await control(page, id).evaluate((el) => el.textContent)).toBe("");
    }
    /*
     * The headings stand where they always did: outside any control. The performance section
     * has carried two -- its `sr-only` section heading and the card's own title -- since
     * before this decision, and the count is stated so a change to it is a review item.
     */
    for (const id of DISCLOSURE_IDS) {
      const heading = page.getByRole("heading", { level: 2, name: DISCLOSURE_LABEL[id] });
      if (id === "what-changed") {
        await expect(heading).toHaveCount(0);
      } else {
        await expect(heading).toHaveCount(id === "performance-overview" ? 2 : 1);
        expect(
          await heading.evaluateAll((list) => list.every((h) => h.closest("summary") === null)),
        ).toBe(true);
      }
    }
  }
});

// ------------------------------------------------------------------ M8.7 U14, expanded

for (const scope of SCOPES) {
  test(`M8.7 — ${scope.scenario} ${scope.mode}: nothing is clipped with every disclosure expanded, or collapsed`, async ({
    page,
  }) => {
    await open(page, scope);
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
    expect(await clippedBeyondViewport(page)).toEqual([]);

    const expanded = await revealDeferredSections(page);
    if (isSummaryViewport(page)) {
      expect(expanded).toBe(disclosuresFor(scope).length);
      for (const id of disclosuresFor(scope)) {
        await expect(disclosure(page, id)).toHaveAttribute("open", "");
      }
    } else {
      expect(expanded).toBe(0);
    }
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1);
    expect(await clippedBeyondViewport(page)).toEqual([]);
  });
}

// ------------------------------------------------------------------ M8.8 provenance and freshness

test("M8.8 — U2 and U3 hold collapsed and expanded, and the mixed section carries both provenances", async ({
  page,
}) => {
  await open(page, { scenario: "demo", mode: "executive" });
  const check = async () => {
    await expect(page.getByTestId("context-bar")).toBeVisible();
    await expect(page.getByTestId("freshness-indicator")).toBeVisible();
    await expect(page.getByTestId("page-provenance-banner")).toContainText("SYNTHETIC");
  };
  await check();
  if (isSummaryViewport(page)) {
    expect(await provenanceBadges(page, "supporting-context")).toEqual([
      "SYNTHETIC",
      "REPOSITORY_TRACKED",
    ]);
    expect(await provenanceBadges(page, "what-changed")).toEqual(["SYNTHETIC"]);
    expect(await provenanceBadges(page, "performance-overview")).toEqual(["SYNTHETIC"]);
    await revealDeferredSections(page);
    await check();
    /* The tiles inside keep their own badges exactly as before. */
    await expect(page.getByTestId("tile-open-gates").locator("[data-provenance='REPOSITORY_TRACKED']")).toBeVisible();
    await expect(page.getByTestId("tile-exposure").locator("[data-provenance='SYNTHETIC']")).toBeVisible();
  } else {
    await expect(visibleControls(page)).toHaveCount(0);
    await expect(page.getByTestId("tile-open-gates").locator("[data-provenance='REPOSITORY_TRACKED']")).toBeVisible();
    await expect(page.getByTestId("tile-exposure").locator("[data-provenance='SYNTHETIC']")).toBeVisible();
  }
});

test("M8.8 — the project scenario's controls carry the tracked fact and no synthetic label", async ({
  page,
}) => {
  await open(page, { scenario: "project", mode: "executive" });
  await expect(page.getByTestId("page-provenance-banner")).toContainText("PROJECT READINESS");
  if (isSummaryViewport(page)) {
    expect(await provenanceBadges(page, "supporting-context")).toEqual(["REPOSITORY_TRACKED"]);
    expect(await provenanceBadges(page, "what-changed")).toEqual([]);
    expect(await provenanceBadges(page, "performance-overview")).toEqual([]);
    /* And every deferred section reports its absence on the control, never as a value. */
    expect(await badgeStates(page, "what-changed")).toEqual(["NOT_YET_AVAILABLE"]);
    expect(await badgeStates(page, "performance-overview")).toEqual(["NOT_IMPLEMENTED"]);
    expect(await badgeStates(page, "supporting-context")).toEqual(["NOT_IMPLEMENTED"]);
  } else {
    await expect(visibleControls(page)).toHaveCount(0);
    await expect(page.getByTestId("what-changed-panel").getByTestId("unavailable-body")).toBeVisible();
  }
});

// ------------------------------------------------------------------ M8.9 mixed states

test("M8.9 — two widgets in two different states put both badges on the control, in vocabulary order", async ({
  page,
}) => {
  await open(page, { scenario: "demo", mode: "executive" });
  if (isSummaryViewport(page)) {
    /*
     * The demo fixture's Supporting context holds the permitted-risk tile at NOT_YET_AVAILABLE
     * and both last-run records at NOT_IMPLEMENTED: two distinct absences, reported as two
     * badges in the order `AVAILABILITY_STATES` declares them, and never as one.
     */
    expect(await badgeStates(page, "supporting-context")).toEqual([
      "NOT_YET_AVAILABLE",
      "NOT_IMPLEMENTED",
    ]);
    await expect(control(page, "supporting-context").getByTestId("skeleton")).toHaveCount(0);
    /* The pending-read half of M8.9 is established in the unit suite with a held read. */
  } else {
    await expect(visibleControls(page)).toHaveCount(0);
    await expect(page.getByTestId("tile-risk.permitted")).toContainText("Not yet available");
    await expect(page.getByTestId("tile-last-runs").locator("[data-availability='NOT_IMPLEMENTED']")).toHaveCount(2);
  }
});

const VARIANT_BADGES = [
  ["valid", []],
  ["none", ["EMPTY_VERIFIED"]],
  ["no-baseline", ["NOT_YET_AVAILABLE"]],
  ["degraded", ["PARTIAL"]],
] as const;

for (const [variant, expected] of VARIANT_BADGES) {
  test(`M8.9 — the What changed control carries the ${variant} variant's state and no count`, async ({
    page,
  }) => {
    await open(page, { scenario: "demo", mode: "executive" }, `&changes=${variant}`);
    if (isSummaryViewport(page)) {
      expect(await badgeStates(page, "what-changed")).toEqual([...expected]);
      const text = (await control(page, "what-changed").textContent()) ?? "";
      expect(text).not.toMatch(/[0-9]/);
      await expandByKeyboard(page, "what-changed");
      await expect(page.getByTestId("what-changed-panel")).toBeVisible();
    } else {
      await expect(visibleControls(page)).toHaveCount(0);
      await expect(page.getByTestId("what-changed-panel")).toBeVisible();
    }
    /* The tier-1 tile's state stays visible at every width (M4). */
    await expect(page.getByTestId("answer-changed")).toBeVisible();
  });
}

// ------------------------------------------------------------------ M8.10 focus across a resize

test("M8.10 — focus inside an expanded section survives a crossing in each direction", async ({
  page,
}) => {
  await open(page, { scenario: "demo", mode: "executive" });
  const link = page.getByRole("link", { name: "Each gate is read on its own →" });

  if (isSummaryViewport(page)) {
    await expandByKeyboard(page, "supporting-context");
    await link.focus();
    await expect(link).toBeFocused();

    await page.setViewportSize({ width: 1024, height: 768 });
    await expect(visibleControls(page)).toHaveCount(0);
    await expect(link).toBeFocused();

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(visibleControls(page)).toHaveCount(3);
    await expect(link).toBeFocused();
    await expect(disclosure(page, "supporting-context")).toHaveAttribute("open", "");
    /* A section the reader never expanded is still collapsed after the round trip. */
    await expect(disclosure(page, "what-changed")).not.toHaveAttribute("open");
    await expect(disclosure(page, "performance-overview")).not.toHaveAttribute("open");
  } else {
    /* Focus inside a section that was never expanded, then cross downward: never collapsed. */
    await link.focus();
    await expect(link).toBeFocused();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(visibleControls(page)).toHaveCount(3);
    await expect(link).toBeFocused();
    await expect(disclosure(page, "supporting-context")).toHaveAttribute("open", "");
    await expect(disclosure(page, "what-changed")).not.toHaveAttribute("open");
    /* And back up: everything visible, focus unchanged, no control. */
    await page.setViewportSize({ width: 1024, height: 768 });
    await expect(visibleControls(page)).toHaveCount(0);
    await expect(link).toBeFocused();
  }
});

// ------------------------------------------------------------------ M7 persistence

test("M7 — expansion lives for the page instance: it survives a mode switch, never enters the URL, and resets on reload", async ({
  page,
}) => {
  await open(page, { scenario: "demo", mode: "executive" });
  if (isSummaryViewport(page)) {
    await expandByKeyboard(page, "performance-overview");
    const before = page.url();
    expect(before).not.toMatch(/expand|open|disclos/i);

    /* A mode switch on the same page preserves it (U15), and Response evidence arrives collapsed. */
    await page.getByTestId("mode-switch").getByRole("radio", { name: "operator" }).click();
    await expect(page).toHaveURL(/mode=operator/);
    await expect(disclosure(page, "response-evidence")).not.toHaveAttribute("open");
    await expect(disclosure(page, "performance-overview")).toHaveAttribute("open", "");
    await expect(disclosure(page, "what-changed")).not.toHaveAttribute("open");
    expect(page.url()).not.toMatch(/expand|open|disclos/i);

    /* A reload returns to the default. */
    await page.reload();
    await settle(page);
    for (const id of DISCLOSURE_IDS) {
      await expect(disclosure(page, id)).not.toHaveAttribute("open");
    }

    /* And so does a navigation away and back. */
    await expandByKeyboard(page, "what-changed");
    await page.getByRole("link", { name: "All attention items →" }).click();
    await expect(page).toHaveURL(/\/attention/);
    await page.goBack();
    await settle(page);
    await expect(disclosure(page, "what-changed")).not.toHaveAttribute("open");
    expect(
      await page.evaluate(() =>
        Object.keys(localStorage).concat(Object.keys(sessionStorage)).filter((k) =>
          /disclos|expand|summary/i.test(k),
        ),
      ),
    ).toEqual([]);
  } else {
    /* A mode switch above the breakpoint renders the fourth section in full, with no control. */
    await page.getByTestId("mode-switch").getByRole("radio", { name: "operator" }).click();
    await expect(page).toHaveURL(/mode=operator/);
    await expect(page.locator('section[aria-labelledby="operator-evidence"]')).toBeVisible();
    await expect(visibleControls(page)).toHaveCount(0);
  }
});

// ------------------------------------------------------------------ M3 heading structure

test("M5 — heading navigation lists every deferred section exactly once, collapsed or expanded", async ({
  page,
}) => {
  await open(page, { scenario: "demo", mode: "operator" });
  /*
   * The headings a reader can reach. `checkVisibility` is false inside a closed `<details>`,
   * whose content is skipped, and true for an `sr-only` heading, which is clipped rather than
   * hidden and is announced -- which is exactly the distinction heading navigation makes.
   */
  const headings = async () =>
    page.evaluate(() =>
      Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, h6"))
        .filter((element) => element.checkVisibility())
        .map((element) => `${element.tagName.toLowerCase()}:${(element.textContent ?? "").trim()}`),
    );
  const levelsDoNotSkip = (list: string[]) => {
    const levels = list.map((entry) => Number(entry.slice(1, 2)));
    return levels.every((level, index) => index === 0 || level - levels[index - 1] <= 1);
  };

  const collapsed = await headings();
  expect(collapsed.filter((h) => h === "h1:Executive Overview — Operator")).toHaveLength(1);
  expect(levelsDoNotSkip(collapsed)).toBe(true);

  if (isSummaryViewport(page)) {
    for (const id of DISCLOSURE_IDS) {
      expect(collapsed.filter((h) => h === `h2:${DISCLOSURE_LABEL[id]}`), id).toHaveLength(1);
    }
    /* The deferred detail's own inner headings are not listed while it is collapsed ... */
    expect(collapsed).not.toContain("h3:Exposure");
    await revealDeferredSections(page);
    const expanded = await headings();
    /* ... and are listed once it is expanded, under the section's own h2, with no skipped level. */
    expect(expanded).toContain("h3:Exposure");
    expect(levelsDoNotSkip(expanded)).toBe(true);
    for (const id of DISCLOSURE_IDS) {
      expect(expanded.filter((h) => h === `h2:${DISCLOSURE_LABEL[id]}`), id).toHaveLength(1);
    }
  } else {
    expect(collapsed).toContain("h3:Exposure");
    expect(collapsed.filter((h) => h === "h2:Supporting context")).toHaveLength(1);
    expect(collapsed.filter((h) => h === "h2:Response evidence")).toHaveLength(1);
    expect(collapsed).not.toContain("h2:What changed — details");
  }
});
