import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

/**
 * C10 — the performance measurement, and what it is not.
 *
 * `ui-ux-specification.md` section 15 lists "performance targets — interaction responsiveness,
 * first meaningful render and bounded query time — set as targets for the implementation cycle
 * to measure", and section 16 records that the specification cycle "measures nothing and claims
 * nothing". This cycle measures.
 *
 * NO BUDGET IS ASSERTED, AND THAT IS DELIBERATE. No numeric performance budget exists anywhere
 * in tracked authority — not in the specification, not in an ADR, not in the traceability
 * matrix. Inventing one here would make a threshold up and then enforce it as though somebody
 * had accepted it, and a made-up number that passes is worse than no number at all. What is
 * asserted is that each measurement was actually obtained and is a real, finite, positive
 * duration, and that each interaction it timed actually happened; the durations themselves are
 * WRITTEN TO THE EVIDENCE FILE with the conditions they were taken under.
 *
 * THE CONDITIONS ARE PART OF THE MEASUREMENT. This suite drives `next dev`, on one worker, on
 * whatever machine ran it, against the local fixture adapter. A development server compiles on
 * demand and ships an unminified bundle, so these numbers are an UPPER BOUND on a production
 * build's and are not comparable to one. They are recorded so a later cycle has a starting
 * point, not so anybody can quote them as the Cockpit's performance.
 */

const EVIDENCE = "screenshots-c10";

/** The routes measured: the landing page, a dense table, a chart and a governance screen. */
const MEASURED: readonly string[] = [
  "/",
  "/portfolio/trades",
  "/portfolio/performance",
  "/governance/qualification",
  "/system/alerts",
];

interface RouteMeasurement {
  readonly route: string;
  /** Wall-clock milliseconds from navigation start to the first resolved client read. */
  readonly firstAnswerMs: number;
  readonly firstContentfulPaintMs: number | null;
  readonly domContentLoadedMs: number;
  readonly loadEventMs: number;
  readonly transferredBytes: number;
}

const measurements: RouteMeasurement[] = [];
const interactions: { readonly what: string; readonly durationMs: number }[] = [];

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

test.describe("C10 — bounded local performance measurement", () => {
  for (const route of MEASURED) {
    test(`measures ${route}`, async ({ page }) => {
      const started = Date.now();
      await page.goto(`${route}?scenario=demo`);
      await waitForHydration(page);
      const firstAnswerMs = Date.now() - started;

      const timings = await page.evaluate(() => {
        const navigation = performance.getEntriesByType(
          "navigation",
        )[0] as PerformanceNavigationTiming | undefined;
        const paint = performance
          .getEntriesByType("paint")
          .find((entry) => entry.name === "first-contentful-paint");
        return {
          fcp: paint === undefined ? null : paint.startTime,
          domContentLoaded: navigation?.domContentLoadedEventEnd ?? 0,
          load: navigation?.loadEventEnd ?? 0,
          transferred: performance
            .getEntriesByType("resource")
            .reduce(
              (total, entry) => total + (entry as PerformanceResourceTiming).transferSize,
              0,
            ),
        };
      });

      /*
       * A MEASUREMENT THAT WAS NOT TAKEN IS NOT A PASS. These assert that the numbers are real
       * durations rather than that they fall under a threshold nobody set.
       */
      expect(Number.isFinite(firstAnswerMs)).toBe(true);
      expect(firstAnswerMs).toBeGreaterThan(0);
      expect(Number.isFinite(timings.domContentLoaded)).toBe(true);
      expect(timings.domContentLoaded).toBeGreaterThan(0);
      if (timings.fcp !== null) {
        expect(timings.fcp).toBeGreaterThan(0);
      }

      measurements.push({
        route,
        firstAnswerMs,
        firstContentfulPaintMs: timings.fcp === null ? null : Math.round(timings.fcp),
        domContentLoadedMs: Math.round(timings.domContentLoaded),
        loadEventMs: Math.round(timings.load),
        transferredBytes: Math.round(timings.transferred),
      });
    });
  }

  test("measures interaction responsiveness", async ({ page }) => {
    await page.goto("/?scenario=demo&mode=executive");
    await waitForHydration(page);

    const paletteStarted = Date.now();
    await page.keyboard.press("ControlOrMeta+k");
    await expect(page.getByTestId("command-palette")).toBeVisible();
    const paletteMs = Date.now() - paletteStarted;
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("command-palette")).toBeHidden();

    const modeStarted = Date.now();
    await page.getByTestId("mode-switch").getByRole("radio", { name: "operator" }).click();
    await expect(page.getByText("Response evidence").first()).toBeVisible();
    const modeMs = Date.now() - modeStarted;

    /* Each interaction actually completed, and each duration is a real one. */
    expect(Number.isFinite(paletteMs)).toBe(true);
    expect(paletteMs).toBeGreaterThan(0);
    expect(Number.isFinite(modeMs)).toBe(true);
    expect(modeMs).toBeGreaterThan(0);

    interactions.push(
      { what: "open the command palette with Ctrl/Cmd+K", durationMs: paletteMs },
      { what: "switch Executive to Operator and render its evidence", durationMs: modeMs },
    );
  });
});

/* Playwright requires the object-destructuring form for a hook's first argument. */
test.afterAll(async ({}, testInfo) => {
  const project = testInfo.project.name;
  const report = {
    capturedAt: new Date().toISOString(),
    project,
    viewport: testInfo.project.use.viewport ?? null,
    conditions: [
      "next dev — a development server, compiled on demand and unminified",
      "one Playwright worker, local loopback, local fixture adapter, no network",
      "an UPPER BOUND on a production build, and not comparable to one",
      "no accepted numeric performance budget exists; none is asserted or implied",
    ],
    routes: measurements,
    interactions,
  };
  writeFileSync(
    `${EVIDENCE}/performance-${project}.json`,
    `${JSON.stringify(report, null, 2)}\n`,
    "utf8",
  );
});
