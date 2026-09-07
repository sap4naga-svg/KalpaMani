import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

/**
 * The C6 review evidence.
 *
 * Written to a DISTINCT directory so the C3, C4 and C5 captures are untouched, and stamped
 * with the exact commit they were taken at — a screenshot whose revision is unknown is a
 * picture, not evidence.
 *
 * These are REVIEW EVIDENCE, not a visual-regression baseline. Visual regression is specified
 * for a later cycle.
 */
const SHOTS = "screenshots-c6";

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
      "KalpaMani Cockpit -- C6 review evidence",
      "",
      `captured at commit: ${revision}`,
      `working tree:       ${dirty}`,
      `captured on:        ${new Date().toISOString()}`,
      "",
      "Review evidence, not a visual-regression baseline.",
      "",
      "Every populated figure in a `scenario=demo` capture is a repository-owned",
      "deterministic fixture projected from one synthetic book. It is not a result,",
      "not a measurement, and not evidence about any strategy, provider or market.",
      "",
      "No candidate here was produced by a Brain, no order was ever sent, no fill",
      "ever occurred, no model was called, and no benchmark price was requested from",
      "any provider. The Brain runtime, the risk engine and the execution runtime do",
      "not exist, and no provider is selected.",
      "",
    ].join("\n"),
    "utf8",
  );
});

async function settle(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

test("captures the C6 signals, candidate and trade-lifecycle surfaces", async ({
  page,
}, testInfo) => {
  const project = testInfo.project.name;
  const shot = async (name: string, fullPage = true) => {
    await page.screenshot({ path: `${SHOTS}/${project}-${name}.png`, fullPage });
  };

  /* --------------------------------------------------------------- signal funnel */
  await page.goto(`/signals/funnel${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("funnel-stages")).toBeVisible();
  await shot("funnel-first-viewport", false);
  await shot("funnel-demo");

  await page.goto(`/signals/funnel${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("funnel-brain-axis")).toBeVisible();
  await shot("funnel-operator");

  await page.goto(`/signals/funnel${DEMO}&state=BLOCKED_AI`);
  await settle(page);
  await expect(page.getByTestId("filter-chips")).toBeVisible();
  await shot("funnel-filtered-blocked-ai");

  await page.goto(`/signals/funnel${PROJECT}`);
  await settle(page);
  await shot("funnel-project");

  /* ------------------------------------------------------------ candidate detail */
  await page.goto(`/signals/candidates/demo-candidate-0006${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("candidate-decision")).toBeVisible();
  await shot("candidate-ready-first-viewport", false);
  await shot("candidate-ready-declined-downstream");

  await page.goto(`/signals/candidates/demo-candidate-0012${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("candidate-ai-evidence")).toBeVisible();
  await shot("candidate-blocked-contradiction-operator");

  await page.goto(`/signals/candidates/demo-candidate-0013${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("candidate-ai-absent")).toBeVisible();
  await shot("candidate-ai-evidence-unavailable");

  await page.goto(`/signals/candidates/demo-candidate-0011${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("candidate-short-context")).toBeVisible();
  await shot("candidate-blocked-borrow-short-context");

  await page.goto(`/signals/candidates/demo-candidate-nope${DEMO}`);
  await settle(page);
  await shot("candidate-unknown");

  /* ------------------------------------------------------- missed opportunities */
  await page.goto(`/signals/missed${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("hindsight-warning")).toBeVisible();
  await shot("missed-first-viewport", false);
  await shot("missed-demo");

  await page.getByTestId("missed-table").getByRole("button").first().click();
  await expect(page.locator('[data-testid^="miss-detail-"]').first()).toBeVisible();
  await shot("missed-row-detail-counterfactual");

  await page.goto(`/signals/missed${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("missed-rates")).toBeVisible();
  await shot("missed-operator-rates-and-comparison");

  await page.goto(`/signals/missed${PROJECT}`);
  await settle(page);
  await shot("missed-project");

  /* ------------------------------------------------- the complete trade lifecycle */
  await page.goto(`/portfolio/trades/demo-trade-sol-0006${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("lifecycle-events")).toBeVisible();
  await shot("trade-lifecycle-first-viewport", false);
  await shot("trade-lifecycle-complete");

  await page.goto(`/portfolio/trades/demo-trade-arb-0001${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("fill-quality")).toBeVisible();
  await shot("trade-partial-fill-and-late-observation");

  await page.goto(`/portfolio/trades/demo-trade-nvl-0002${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("absent-event-kinds")).toBeVisible();
  await shot("trade-missing-reconciliation-and-attribution");

  await page.goto(`/portfolio/trades/demo-trade-gen-0001${OPERATOR}`);
  await settle(page);
  await expect(page.getByTestId("trade-execution-absent")).toBeVisible();
  await shot("trade-without-execution-evidence");
});
