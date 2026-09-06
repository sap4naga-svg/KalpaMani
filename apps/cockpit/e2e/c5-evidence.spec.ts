import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

/**
 * The C5 review evidence.
 *
 * Written to a DISTINCT directory so the C3 and C4 captures are untouched, and stamped with
 * the exact commit they were taken at — a screenshot whose revision is unknown is a picture,
 * not evidence.
 *
 * These are REVIEW EVIDENCE, not a visual-regression baseline. Visual regression is specified
 * for a later cycle.
 */
const SHOTS = "screenshots-c5";

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo&period=3M&gran=DAILY&changes=auto";
const OPERATOR =
  "?mode=operator&env=RESEARCH&scenario=demo&period=ALL&gran=MONTHLY&changes=auto";
const PROJECT =
  "?mode=executive&env=RESEARCH&scenario=project&period=3M&gran=DAILY&changes=auto";

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
      "KalpaMani Cockpit -- C5 review evidence",
      "",
      `captured at commit: ${revision}`,
      `working tree:       ${dirty}`,
      `captured on:        ${new Date().toISOString()}`,
      "",
      "Review evidence, not a visual-regression baseline.",
      "Every populated figure in a `scenario=demo` capture is a repository-owned",
      "deterministic fixture projected from one synthetic book. It is not a result,",
      "not a measurement, and not evidence about any strategy, provider or market.",
      "",
    ].join("\n"),
    "utf8",
  );
});

async function settle(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

test("captures the C5 portfolio, strategy, risk and trade surfaces", async ({
  page,
}, testInfo) => {
  const project = testInfo.project.name;
  const shot = async (name: string, fullPage = true) => {
    await page.screenshot({ path: `${SHOTS}/${project}-${name}.png`, fullPage });
  };

  /* ---------------------------------------------------- portfolio performance */
  await page.goto(`/portfolio/performance${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("performance-curves")).toBeVisible();
  await shot("performance-first-viewport", false);
  await shot("performance-demo");

  await page.goto(`/portfolio/performance${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("return-heatmap")).toBeVisible();
  await shot("performance-heatmap-operator");

  await page.goto(`/portfolio/performance${PROJECT}`);
  await settle(page);
  await shot("performance-project");

  /* ------------------------------------------------------ positions and exposure */
  await page.goto(`/portfolio/positions${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("positions-table")).toBeVisible();
  await shot("positions-demo");

  await page.getByRole("button", { name: /Show details for/ }).first().click();
  await expect(page.getByTestId("initial-planned-risk").first()).toBeVisible();
  await shot("positions-row-detail");

  await page.goto(`/portfolio/positions${DEMO}&dir=SHORT`);
  await settle(page);
  await expect(page.getByTestId("filter-chips")).toBeVisible();
  await shot("positions-filtered-short");

  await page.goto(`/portfolio/positions${PROJECT}`);
  await settle(page);
  await shot("positions-project");

  /* --------------------------------------------------------------- trade ledger */
  await page.goto(`/portfolio/trades${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("trades-table")).toBeVisible();
  await shot("trades-operator");

  await page.goto(`/portfolio/trades${DEMO}&status=PARTIALLY_EXITED`);
  await settle(page);
  await expect(page.getByTestId("trades-table")).toBeVisible();
  await page.getByRole("button", { name: /Show details for/ }).first().click();
  await expect(page.getByTestId("trade-status-detail")).toBeVisible();
  await shot("trades-partial-exit-detail");

  /* ---------------------------------------------------------------- trade detail */
  await page.goto(`/portfolio/trades/demo-trade-nvl-0002${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("trade-chart")).toBeVisible();
  await shot("trade-detail-first-viewport", false);
  await shot("trade-detail");

  await page.getByText(/Marks and recorded events as a table/).click();
  await expect(page.getByRole("region", { name: /as a table/ })).toBeVisible();
  await shot("trade-detail-chart-alternative");

  await page.goto(`/portfolio/trades/demo-trade-does-not-exist${DEMO}`);
  await settle(page);
  await shot("trade-detail-unknown");

  /* -------------------------------------------------------- strategy performance */
  await page.goto(`/strategy/performance${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("strategy-table")).toBeVisible();
  await shot("strategy-demo");

  await page.goto(`/strategy/performance${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("strategy-version-detail")).toBeVisible();
  await shot("strategy-version-detail");

  /* ------------------------------------------------------------------------ risk */
  await page.goto(`/risk${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("research-parameters")).toBeVisible();
  await shot("risk-demo");

  await page.goto(`/risk${PROJECT}`);
  await settle(page);
  await shot("risk-project");

  await page.goto(`/risk/short-side${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("borrow-table")).toBeVisible();
  await shot("short-side-demo");

  /* ---------------------------------------------------------------------- regime */
  await page.goto(`/market/regime${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("regime-components")).toBeVisible();
  await shot("regime-demo");
});
