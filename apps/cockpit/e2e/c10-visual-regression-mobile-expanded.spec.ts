import { expect, test, type Page } from "@playwright/test";

import { DISCLOSURE_IDS, disclosure, expandByKeyboard } from "./mobile-summary";

/**
 * The four Decision VC expanded-state rows of the visual-regression inventory
 * (ADR-0033 §4.2, the `root` row; §4.5, the one stated exception to URL-only state setup).
 *
 *   VC-root-demo-executive-expanded      /?scenario=demo&mode=executive       390 × 844
 *   VC-root-demo-operator-expanded       /?scenario=demo&mode=operator        390 × 844
 *   VC-root-project-executive-expanded   /?scenario=project&mode=executive    390 × 844
 *   VC-root-project-operator-expanded    /?scenario=project&mode=operator     390 × 844
 *
 * Each is taken at the default `changes` variant (VC-R6): the rows exist to record the
 * EXPANDED DISCLOSURE LAYOUT of the mobile executive summary, and the What Changed variants
 * are already captured at this width in the collapsed state and in full at every wider one.
 *
 * STATE IS SET UP FROM THE URL, WITH ONE STATED EXCEPTION. Expansion is deliberately not in
 * the URL (ADR-0033 M7), so every disclosure is expanded BY KEYBOARD ACTIVATION after the
 * page loads — the only interaction any inventory row may be set up by — and the file name
 * carries the `-expanded` suffix so the exception is visible. Focus is then released, so the
 * last control's focus ring is not part of the record.
 *
 * THE CAPTURE IS THE WHOLE PAGE. A viewport-sized capture at 390 × 844 shows the shell and
 * the first answer tile, which the collapsed rows already record; what these rows exist to
 * record sits below the first viewport, so the page is captured in full. Every other
 * capture condition is the committed recipe unchanged: the clock frozen at the fixed
 * instant, reduced motion, animations disabled, the caret hidden, CSS scale, the seeded
 * fixtures, NOTHING MASKED, and a comparison at ZERO TOLERANCE — a differing pixel fails, and
 * the failure is a review item. The baseline is platform-scoped in its file name and is
 * created only by a reviewed `--update-snapshots` run whose provenance the pull request
 * records; on a platform with no committed baseline the comparison reports it missing and
 * fails.
 *
 * REGISTERED IN THE MOBILE PROJECT ONLY. The rows are stated at 390 × 844 and at no other
 * width (VC-I3), so the spec is ignored by name in every other project.
 */

const FIXED_INSTANT = new Date("2026-09-09T12:00:00.000Z");
const STRICT = { threshold: 0, maxDiffPixels: 0, maxDiffPixelRatio: 0 } as const;
const SETTLE_TIMEOUT_MS = 30_000;

test.use({ reducedMotion: "reduce" });

const ROWS = [
  { name: "VC-root-demo-executive-expanded", scenario: "demo", mode: "executive" },
  { name: "VC-root-demo-operator-expanded", scenario: "demo", mode: "operator" },
  { name: "VC-root-project-executive-expanded", scenario: "project", mode: "executive" },
  { name: "VC-root-project-operator-expanded", scenario: "project", mode: "operator" },
] as const;

async function settle(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible({ timeout: SETTLE_TIMEOUT_MS });
  await expect(page.getByTestId("context-bar")).toBeVisible({ timeout: SETTLE_TIMEOUT_MS });
  await expect(page.getByTestId("attention-panel")).toBeVisible({ timeout: SETTLE_TIMEOUT_MS });
  await expect(page.locator('main [data-testid="skeleton"]')).toHaveCount(0, {
    timeout: SETTLE_TIMEOUT_MS,
  });
}

for (const row of ROWS) {
  test(`${row.name} — the Executive Overview with every disclosure expanded`, async ({ page }) => {
    expect(page.viewportSize(), "these rows are stated at 390 × 844 only").toEqual({
      width: 390,
      height: 844,
    });
    await page.clock.setFixedTime(FIXED_INSTANT);
    await page.goto(`/?scenario=${row.scenario}&mode=${row.mode}`);
    await settle(page);

    const ids = row.mode === "operator" ? DISCLOSURE_IDS : DISCLOSURE_IDS.slice(0, 3);
    for (const id of ids) {
      await expect(disclosure(page, id)).not.toHaveAttribute("open");
      await expandByKeyboard(page, id);
    }
    if (row.mode === "executive") {
      await expect(disclosure(page, "response-evidence")).toHaveCount(0);
    }

    /* The revealed content has rendered: the chart has its width, or its absence is stated. */
    if (row.scenario === "demo") {
      await expect(page.getByTestId("chart-equity").locator("svg.recharts-surface")).toBeVisible({
        timeout: SETTLE_TIMEOUT_MS,
      });
      await expect(page.getByTestId("tile-exposure")).toContainText("gross");
    } else {
      await expect(page.getByTestId("performance-overview").getByTestId("unavailable-body")).toBeVisible();
    }
    await expect(page.locator('main [data-testid="skeleton"]')).toHaveCount(0);

    /* Release focus so the last control's focus ring is not part of the record. */
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await expect(page.locator(":focus")).toHaveCount(0);

    await expect(page).toHaveScreenshot(`${row.name}.png`, {
      fullPage: true,
      animations: "disabled",
      caret: "hide",
      scale: "css",
      ...STRICT,
    });
  });
}
