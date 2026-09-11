import { expect, test, type Page } from "@playwright/test";

import {
  clippedBeyondViewport,
  horizontalOverflow,
  isSummaryViewport,
  revealDeferredSections,
} from "./mobile-summary";

/**
 * The Executive Overview's reading hierarchy, in the browser, at every registered width.
 *
 * The unit suite (`tests/executive-readability.test.tsx`) holds each correction to the rule
 * that justifies it. What only a browser can establish is here: that the page-level banner
 * describes the page's mixed sources beside the TRACKED FACT badge it renders; that a tile's
 * "About …" disclosure opens by keyboard, keeps focus, and — expanded — clips nothing and
 * scrolls nothing sideways (U14), in the summary layout as well as the wide one; and that the
 * chart's stated window follows the period the URL selects (U13).
 */

async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

const TILES = [
  "tile-strategy-capital",
  "answer-performance",
  "answer-risk",
  "answer-health",
  "answer-changed",
  "answer-attention",
] as const;

test.describe("the page-level provenance sentence describes the mixed sources", () => {
  test("names the fixtures as operational figures and TRACKED FACT as real, beside the badge", async ({
    page,
  }) => {
    await page.goto("/?scenario=demo&mode=executive");
    await waitForHydration(page);
    const banner = page.getByTestId("page-provenance-banner");
    await expect(banner).toContainText("SYNTHETIC DEMONSTRATION DATA");
    await expect(banner).toContainText("Every operational figure on this page");
    await expect(banner).toContainText("TRACKED FACT");
    await expect(banner).not.toContainText("Every figure on this page");
    /* The sentence is true of THIS page: it carries a real tracked fact beside its fixtures. */
    const capital = page.getByTestId("tile-strategy-capital");
    await expect(capital.locator('[data-provenance="REPOSITORY_TRACKED"]')).toBeVisible();
    await expect(page.locator('[data-provenance="SYNTHETIC"]').first()).toBeVisible();
  });

  test("leaves the project scenario's readiness banner as it was", async ({ page }) => {
    await page.goto("/?scenario=project&mode=executive");
    await waitForHydration(page);
    const banner = page.getByTestId("page-provenance-banner");
    await expect(banner).toContainText("PROJECT READINESS");
    await expect(banner).not.toContainText("SYNTHETIC DEMONSTRATION DATA");
  });
});

test.describe("each tile's supporting detail is on demand, keyboard-operable, and clips nothing", () => {
  for (const mode of ["executive", "operator"] as const) {
    test(`opens every "About" disclosure by keyboard in ${mode} mode and stays within the viewport`, async ({
      page,
    }) => {
      await page.goto(`/?scenario=demo&mode=${mode}`);
      await waitForHydration(page);

      for (const testId of TILES) {
        const tile = page.getByTestId(testId);
        const details = tile.locator('[data-tile-part="details"]');
        const summary = details.locator("summary");
        await expect(details).not.toHaveAttribute("open", /.*/);
        await summary.focus();
        await page.keyboard.press("Enter");
        await expect(details).toHaveAttribute("open", /.*/);
        /* Focus stays on the control, so a reader is not thrown to the top of the page. */
        await expect(summary).toBeFocused();
        /* The revealed sentence is real content, not an empty region. */
        const revealed = (await details.locator("summary ~ *").innerText()).trim();
        expect(revealed.length, `${testId} must reveal an explanation`).toBeGreaterThan(40);
      }

      /* U14, with every tile disclosure expanded — and, below the breakpoint, every section too. */
      if (isSummaryViewport(page)) {
        await revealDeferredSections(page);
      }
      expect(await horizontalOverflow(page)).toBe(0);
      expect(await clippedBeyondViewport(page)).toEqual([]);
    });
  }

  test("does not carry an availability or provenance badge inside a disclosure", async ({ page }) => {
    await page.goto("/?scenario=demo&mode=executive");
    await waitForHydration(page);
    for (const testId of TILES) {
      const details = page.getByTestId(testId).locator('[data-tile-part="details"]');
      await expect(details.locator("[data-availability]")).toHaveCount(0);
      await expect(details.locator("[data-provenance]")).toHaveCount(0);
    }
  });
});

test.describe("the chart states the window it draws, and the headline states it has none", () => {
  test("follows the period in the URL and names the declared window (U13)", async ({ page }) => {
    await page.goto("/?scenario=demo&mode=executive&period=1Y");
    await waitForHydration(page);
    await revealDeferredSections(page);
    const stated = page.getByTestId("performance-stated-window");
    await expect(stated).toContainText("Over 1 year");
    await expect(stated).toContainText("daily");
    await expect(stated).toContainText(/\d{4}-\d{2}-\d{2} → \d{4}-\d{2}-\d{2}/);

    const overview = page.getByTestId("performance-overview");
    await overview.getByRole("button", { name: "3M", exact: true }).click();
    await expect(page).toHaveURL(/period=3M/);
    await expect(stated).toContainText("Over 3 months");

    const note = page.getByTestId("answer-performance").locator('[data-tile-part="window-note"]');
    await expect(note).toContainText("Window: not stated by this read model");
    await expect(note).not.toContainText("3 months");
    await expect(note).not.toContainText("1 year");
  });
});
