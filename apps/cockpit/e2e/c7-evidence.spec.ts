import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

/**
 * The C7 review evidence.
 *
 * Written to a DISTINCT directory so the C3, C4, C5, C6 and ADR-0031 captures are untouched,
 * and stamped with the exact commit they were taken at — a screenshot whose revision is
 * unknown is a picture, not evidence.
 *
 * These are REVIEW EVIDENCE, not a visual-regression baseline. Visual regression is specified
 * for a later cycle.
 */
const SHOTS = "screenshots-c7";

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
      "KalpaMani Cockpit -- C7 review evidence",
      "",
      `captured at commit: ${revision}`,
      `working tree:       ${dirty}`,
      `captured on:        ${new Date().toISOString()}`,
      "",
      "Review evidence, not a visual-regression baseline.",
      "",
      "Every populated figure in a `scenario=demo` capture is a repository-owned",
      "deterministic fixture projected from one synthetic research lineage. It is not",
      "a result, not a measurement, and not evidence about any strategy, provider or",
      "market.",
      "",
      "BACKTESTING HAS NOT STARTED. No research engine, learning engine, shadow",
      "runner, governance runtime or AI agent exists; none has ever run; no model was",
      "called; no provider was contacted; and no promotion, capital change, parameter",
      "replacement or release has been approved anywhere in this repository.",
      "",
      "No synthetic figure here closes a gate, qualifies a provider, validates a",
      "strategy or establishes a threshold, and no numerical value appearing in one",
      "becomes a production rule.",
      "",
    ].join("\n"),
    "utf8",
  );
});

async function settle(page: Page): Promise<void> {
  await expect(page.getByTestId("context-bar")).toBeVisible();
  await expect(page.getByTestId("skeleton")).toHaveCount(0, { timeout: 20_000 });
}

test("captures the C7 research, feedback and governance surfaces", async ({
  page,
}, testInfo) => {
  const project = testInfo.project.name;
  const shot = async (name: string, fullPage = true) => {
    await page.screenshot({ path: `${SHOTS}/${project}-${name}.png`, fullPage });
  };

  /* ------------------------------------------------------------- strategy health */
  await page.goto(`/strategy/health${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("health-state-legend")).toBeVisible();
  await shot("health-first-viewport", false);
  await shot("health-demo");

  await page.goto(`/strategy/health${DEMO}&state=NEW_ENTRIES_REDUCED`);
  await settle(page);
  await expect(page.getByTestId("health-queue-reference")).toBeVisible();
  await shot("health-degradation-and-queue-entry");

  await page.goto(`/strategy/health${OPERATOR}`);
  await settle(page);
  await shot("health-operator");

  await page.goto(`/strategy/health${PROJECT}`);
  await settle(page);
  await shot("health-project");

  /* ------------------------------------------------------------ version registry */
  await page.goto(`/strategy/versions${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("rollback-statement")).toBeVisible();
  await shot("versions-first-viewport", false);
  await shot("versions-demo");

  await page.goto(`/strategy/versions${DEMO}&role=CHALLENGER`);
  await settle(page);
  await shot("versions-challenger");

  /* -------------------------------------------------------- champion / challenger */
  await page.goto(`/strategy/champion-challenger${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("comparison-list")).toBeVisible();
  await shot("champion-challenger-first-viewport", false);
  await shot("champion-challenger-demo");

  await page.goto(`/strategy/champion-challenger${OPERATOR}`);
  await settle(page);
  await page.locator('[data-comparison="pead-short-v2-challenger"] button').click();
  await shot("champion-challenger-incomparable");

  /* ------------------------------------------------------------------ research runs */
  await page.goto(`/research/runs${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("run-rows")).toBeVisible();
  await shot("runs-first-viewport", false);
  await shot("runs-demo");

  await page.goto(`/research/runs${DEMO}&state=ABANDONED`);
  await settle(page);
  await shot("runs-abandoned-missing-baseline");

  await page.goto(`/research/runs${OPERATOR}&class=DETERMINISTIC_REPRODUCTION`);
  await settle(page);
  await shot("runs-reproduction-operator");

  await page.goto(`/research/runs${PROJECT}`);
  await settle(page);
  await shot("runs-project");

  /* ---------------------------------------------------------------- research queue */
  await page.goto(`/research/queue${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("queue-rows")).toBeVisible();
  await shot("queue-first-viewport", false);
  await shot("queue-demo");

  await page.goto(`/research/queue${DEMO}&state=WITHDRAWN`);
  await settle(page);
  await shot("queue-withdrawn");

  /* ------------------------------------------------------------ hypothesis registry */
  await page.goto(`/research/hypotheses${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("registration-rows")).toBeVisible();
  await shot("hypotheses-first-viewport", false);
  await shot("hypotheses-demo");

  await page.locator('[data-registration="demo-reg-0003"] button').click();
  await expect(page.getByTestId("ledger-refusal")).toBeVisible();
  await shot("hypotheses-renamed-reuse-refused");

  await page.locator('[data-registration="demo-reg-0004"] button').click();
  await expect(page.getByTestId("ledger-refusal")).toBeVisible();
  await shot("hypotheses-exposure-history-unknown");

  /* ------------------------------------------------------------------ feedback loop */
  await page.goto(`/research/feedback${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("pipeline-stages")).toBeVisible();
  await shot("feedback-first-viewport", false);
  await shot("feedback-demo");

  await page.goto(`/research/feedback${OPERATOR}`);
  await settle(page);
  await shot("feedback-operator");

  /* -------------------------------------------------------------- AI contribution */
  await page.goto(`/research/ai-contribution${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("ai-comparisons")).toBeVisible();
  await shot("ai-contribution-first-viewport", false);
  await shot("ai-contribution-demo");

  await page.goto(`/research/ai-contribution${PROJECT}`);
  await settle(page);
  await shot("ai-contribution-project");

  /* ------------------------------------------------------------ governance packets */
  await page.goto(`/governance/packets${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("packet-rows")).toBeVisible();
  await shot("packets-first-viewport", false);
  await shot("packets-demo");

  await page.goto(`/governance/packets${DEMO}&state=ASSEMBLING`);
  await settle(page);
  await expect(page.getByTestId("packet-missing-list")).toBeVisible();
  await shot("packets-assembling-missing-evidence");

  await page.goto(`/governance/packets${OPERATOR}`);
  await settle(page);
  await shot("packets-operator");
});
