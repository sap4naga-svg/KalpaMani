import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

/**
 * The C4 review evidence.
 *
 * Written to a DISTINCT directory so the C3 author and reviewer screenshots are untouched,
 * and stamped with the exact commit they were taken at — a screenshot whose revision is
 * unknown is a picture, not evidence.
 *
 * These are REVIEW EVIDENCE, not a visual-regression baseline. Visual regression is specified
 * for a later cycle.
 */
const SHOTS = "screenshots-c4";

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
  let revision = "unknown";
  let dirty = "unknown";
  try {
    revision = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
    dirty =
      execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }).trim().length === 0
        ? "clean"
        : "uncommitted changes present";
  } catch {
    // A screenshot set with no recoverable revision says so rather than claiming one.
  }
  writeFileSync(
    `${SHOTS}/PROVENANCE.txt`,
    [
      "KalpaMani Cockpit -- C4 review evidence",
      "",
      `captured at commit: ${revision}`,
      `working tree:       ${dirty}`,
      `captured on:        ${new Date().toISOString()}`,
      "",
      "Review evidence, not a visual-regression baseline.",
      "Every populated figure in a `scenario=demo` capture is a repository-owned",
      "deterministic fixture. It is not a result and not a measurement.",
      "",
    ].join("\n"),
    "utf8",
  );
});

async function settle(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

test("captures the C4 executive, governance and chart surfaces", async ({ page }, testInfo) => {
  const project = testInfo.project.name;
  const shot = async (name: string, fullPage = true) => {
    await page.screenshot({ path: `${SHOTS}/${project}-${name}.png`, fullPage });
  };

  // THE FIRST VIEWPORT, un-scrolled -- the capture U1 is actually about.
  await page.goto("/?scenario=demo&mode=executive");
  await settle(page);
  await expect(page.getByTestId("attention-item").first()).toBeVisible();
  await shot("executive-demo-first-viewport", false);
  await shot("executive-demo");

  // The honest default: every operational read model reports its producer does not exist.
  await page.goto("/?scenario=project&mode=executive");
  await settle(page);
  await shot("executive-project");

  await page.goto("/?scenario=demo&mode=operator");
  await settle(page);
  await shot("executive-operator");

  // The chart's three views, its gapped extent and its table alternative.
  await page.goto("/?scenario=demo&mode=executive&period=1Y");
  await settle(page);
  await page.getByTestId("performance-overview").getByRole("button", { name: "Return" }).click();
  await expect(page.getByTestId("chart-return")).toBeVisible();
  await shot("performance-return");

  await page.goto("/?scenario=demo&mode=executive&period=ALL");
  await settle(page);
  await page
    .getByTestId("performance-overview")
    .getByRole("button", { name: "Drawdown" })
    .click();
  await expect(page.getByTestId("chart-drawdown")).toBeVisible();
  await expect(page.getByTestId("series-partial")).toBeVisible();
  await shot("performance-drawdown-partial");

  await page.goto("/?scenario=demo&mode=executive&period=1M");
  await settle(page);
  await page.getByTestId("series-table-disclosure").locator("summary").click();
  await expect(page.getByTestId("series-table-disclosure").getByRole("table")).toBeVisible();
  await shot("performance-table-alternative");

  // Attention, filtered and with an evidence drill-down open.
  await page.goto("/attention?scenario=demo&mode=operator");
  await settle(page);
  const first = page.getByTestId("attention-item").first();
  await first.locator("summary").first().click();
  await expect(first.getByTestId("evidence-reference").first()).toBeVisible();
  await shot("attention-evidence");

  // Each of the four comparison behaviours §7 requires.
  for (const variant of ["valid", "none", "no-baseline", "degraded"] as const) {
    await page.goto(`/?scenario=demo&mode=executive&changes=${variant}`);
    await settle(page);
    await expect(page.getByTestId("what-changed-panel")).toBeVisible();
    await shot(`what-changed-${variant}`);
  }

  // Governance: the real tracked facts, and the maturity mapping.
  await page.goto("/governance/qualification?scenario=project&mode=operator");
  await settle(page);
  await shot("qualification");

  await page.goto("/governance/maturity?scenario=project&mode=executive");
  await settle(page);
  await shot("maturity");
});
