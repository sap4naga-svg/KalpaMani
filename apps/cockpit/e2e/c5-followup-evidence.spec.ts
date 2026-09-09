import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

/**
 * The C5 completion follow-up review evidence.
 *
 * Written to a DISTINCT directory so every earlier capture is untouched, and stamped with the
 * exact commit it was taken at — a screenshot whose revision is unknown is a picture, not
 * evidence.
 *
 * These are REVIEW EVIDENCE, not a visual-regression baseline. Visual regression is specified
 * for a later cycle.
 */
const SHOTS = "screenshots-c5-followup";

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo&period=1Y&gran=DAILY&changes=auto";
const SHORT = "?mode=executive&env=RESEARCH&scenario=demo&period=1M&gran=DAILY&changes=auto";
const GAPPED = "?mode=executive&env=RESEARCH&scenario=demo&period=ALL&gran=DAILY&changes=auto";
const MONTHLY =
  "?mode=operator&env=RESEARCH&scenario=demo&period=ALL&gran=MONTHLY&changes=auto";
const OPERATOR = "?mode=operator&env=RESEARCH&scenario=demo&period=1Y&gran=DAILY&changes=auto";
const PROJECT =
  "?mode=executive&env=RESEARCH&scenario=project&period=1Y&gran=DAILY&changes=auto";

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
      "KalpaMani Cockpit -- C5 completion follow-up review evidence",
      "",
      `captured at commit: ${revision}`,
      `working tree:       ${dirty}`,
      `captured on:        ${new Date().toISOString()}`,
      "",
      "Review evidence, not a visual-regression baseline.",
      "Every populated figure in a `scenario=demo` capture is a repository-owned",
      "deterministic fixture projected from one synthetic book. The benchmark arm is an",
      "invented curve with no market behind it. Nothing here is a result, a measurement,",
      "or evidence about any strategy, provider or market.",
      "",
    ].join("\n"),
    "utf8",
  );
});

async function settle(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

test("captures the rolling, comparison and capacity surfaces", async ({ page }, testInfo) => {
  const project = testInfo.project.name;
  const shot = async (name: string, fullPage = true) => {
    await page.screenshot({ path: `${SHOTS}/${project}-${name}.png`, fullPage });
  };

  /* ------------------------------------------------- rolling, computed and refused */
  await page.goto(`/portfolio/performance${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("rolling-windows")).toBeVisible();
  await shot("rolling-1y-21-periods");

  await page
    .getByTestId("lookback-selector")
    .getByRole("button", { name: "126 periods" })
    .click();
  await expect(page.getByTestId("rolling-lookback")).toContainText("126");
  await shot("rolling-1y-126-periods");

  await page.getByRole("button", { name: "Rolling max drawdown" }).click();
  await expect(page.getByTestId("rolling-chart-drawdown")).toBeVisible();
  await shot("rolling-drawdown");

  /* A period shorter than every lookback: the refusal, on the screen. */
  await page.goto(`/portfolio/performance${SHORT}`);
  await settle(page);
  await expect(page.getByTestId("rolling-none-computed")).toBeVisible();
  await shot("rolling-extent-too-short");

  /* A gapped extent: the two absences, counted apart. */
  await page.goto(`/portfolio/performance${GAPPED}`);
  await settle(page);
  await expect(page.getByTestId("rolling-tally")).toBeVisible();
  await shot("rolling-gapped-extent");

  /* A lookback that counts MONTHS, and says so. */
  await page.goto(`/portfolio/performance${MONTHLY}`);
  await settle(page);
  await expect(page.getByTestId("rolling-lookback")).toContainText("monthly periods");
  await shot("rolling-monthly-periods");

  /* The table alternative, open. */
  await page.goto(`/portfolio/performance${OPERATOR}`);
  await settle(page);
  await page.getByTestId("rolling-table-disclosure").getByText(/as a table/).click();
  await expect(page.getByTestId("rolling-table-disclosure").getByRole("table")).toBeVisible();
  await shot("rolling-table-alternative");

  /* ------------------------------------------------------- the benchmark comparison */
  await expect(page.getByTestId("benchmark-comparison")).toBeVisible();
  await page.getByTestId("comparability-limits").scrollIntoViewIfNeeded();
  await shot("benchmark-comparison");

  await page.getByTestId("comparison-table-disclosure").getByText(/as a table/).click();
  await expect(
    page.getByTestId("comparison-table-disclosure").getByRole("table"),
  ).toBeVisible();
  await shot("benchmark-comparison-table");

  await page.getByTestId("named-benchmark-outstanding").scrollIntoViewIfNeeded();
  await shot("named-benchmarks-still-outstanding");

  /* The producer serves nothing in project scope, and the panel says what it waits on. */
  await page.goto(`/portfolio/performance${PROJECT}`);
  await settle(page);
  await expect(page.getByTestId("rolling-windows")).toBeVisible();
  await shot("rolling-project-scope-unavailable");

  /* ------------------------------------------- rolling expectancy, and what capacity waits on */
  await page.goto(`/strategy/performance${OPERATOR}`);
  await settle(page);
  const rolling = page.getByTestId(/^rolling-expectancy-/).first();
  await rolling.scrollIntoViewIfNeeded();
  await expect(rolling).toBeVisible();
  await shot("rolling-expectancy");

  const capacity = page.getByTestId("capacity-dependencies").first();
  await capacity.scrollIntoViewIfNeeded();
  await expect(capacity).toBeVisible();
  await shot("capacity-dependencies");

  await shot("strategy-performance-full");
});
