import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

/**
 * The C8 review evidence.
 *
 * Written to a DISTINCT directory so the C3, C4, C5, C6, C7 and ADR-0031 captures are
 * untouched, and stamped with the exact commit they were taken at — a screenshot whose
 * revision is unknown is a picture, not evidence.
 *
 * These are REVIEW EVIDENCE, not a visual-regression baseline. Visual regression is specified
 * for a later cycle.
 */
const SHOTS = "screenshots-c8";

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
      "KalpaMani Cockpit -- C8 review evidence",
      "",
      `captured at commit: ${revision}`,
      `working tree:       ${dirty}`,
      `captured on:        ${new Date().toISOString()}`,
      "",
      "Review evidence, not a visual-regression baseline.",
      "",
      "Every populated figure in a `scenario=demo` capture is a repository-owned",
      "deterministic fixture projected from the existing synthetic book. It is not a",
      "result, not a measurement, and not evidence about any strategy, provider,",
      "broker or market.",
      "",
      "DISPLAYING EXECUTION DOES NOT EXECUTE ORDERS. Displaying reconciliation does",
      "not contact a broker. Displaying jobs does not run jobs. Displaying audit",
      "records does not implement an authoritative audit store. Displaying alerts",
      "does not send notifications.",
      "",
      "No automated execution runtime, broker session, scheduler, service runtime,",
      "provider feed, alert pipeline or audit store exists; none has ever run; no",
      "order has been placed beyond the certified Phase 2 scope; the broker is flat;",
      "and no provider has been contacted.",
      "",
      "No synthetic figure here closes a gate, qualifies a provider, validates a",
      "strategy or establishes a threshold, and no numerical value appearing in one",
      "becomes a production rule. G1 and G2 stay OPEN, P1 to P9 stay UNEVALUATED,",
      "data correctness is NOT ESTABLISHED and live trading is HARD-DISABLED.",
      "",
    ].join("\n"),
    "utf8",
  );
});

async function settle(page: Page): Promise<void> {
  await expect(page.getByTestId("context-bar")).toBeVisible();
  await expect(page.getByTestId("skeleton")).toHaveCount(0, { timeout: 20_000 });
}

/** Opens every disclosure, repeating so a nested one reached by opening its parent opens too. */
async function openEveryDisclosure(page: Page): Promise<void> {
  for (let pass = 0; pass < 5; pass += 1) {
    const closed = await page.locator("details:not([open]) > summary:visible").all();
    if (closed.length === 0) {
      return;
    }
    for (const summary of closed) {
      if (await summary.isVisible()) {
        await summary.click();
      }
    }
  }
}

test("captures the C8 execution, operations, audit and alert surfaces", async ({
  page,
}, testInfo) => {
  const project = testInfo.project.name;
  const shot = async (name: string, fullPage = true) => {
    await page.screenshot({ path: `${SHOTS}/${project}-${name}.png`, fullPage });
  };

  /* ------------------------------------------------------------ execution quality */
  await page.goto(`/execution/quality${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("execution-aggregate")).toBeVisible();
  await shot("execution-quality-first-viewport", false);
  await shot("execution-quality-demo");

  await page.goto(`/execution/quality${DEMO}&state=REJECTED`);
  await settle(page);
  await shot("execution-quality-rejected-order");

  await page.goto(`/execution/quality${OPERATOR}`);
  await settle(page);
  await page.getByTestId("execution-table").locator("tbody button").first().click();
  await shot("execution-quality-operator-detail");

  await page.goto(`/execution/quality${PROJECT}`);
  await settle(page);
  await shot("execution-quality-project");

  /* ---------------------------------------------------------------- reconciliation */
  await page.goto(`/execution/reconciliation${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("present-health")).toBeVisible();
  await shot("reconciliation-first-viewport", false);
  await shot("reconciliation-demo");

  await page.goto(`/execution/reconciliation${DEMO}&result=COMPARISON_INPUT_MISSING`);
  await settle(page);
  await openEveryDisclosure(page);
  await shot("reconciliation-missing-input");

  await page.goto(`/execution/reconciliation${OPERATOR}`);
  await settle(page);
  await openEveryDisclosure(page);
  await shot("reconciliation-operator");

  /* ------------------------------------------------------------------ data quality */
  await page.goto(`/system/data-quality${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("profile-list")).toBeVisible();
  await shot("data-quality-first-viewport", false);
  await shot("data-quality-demo");

  await page.goto(`/system/data-quality${OPERATOR}`);
  await settle(page);
  await openEveryDisclosure(page);
  await shot("data-quality-operator");

  await page.goto(`/system/data-quality${PROJECT}`);
  await settle(page);
  await shot("data-quality-project");

  /* --------------------------------------------------------------------- operations */
  await page.goto(`/system/operations${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("job-table")).toBeVisible();
  await shot("operations-first-viewport", false);
  await shot("operations-demo");

  await page.goto(`/system/operations${OPERATOR}`);
  await settle(page);
  await page.getByTestId("job-table").locator("tbody button").first().click();
  await shot("operations-last-success-against-current-state");

  await page.goto(`/system/operations${DEMO}&incident_state=CLOSED`);
  await settle(page);
  await shot("operations-closed-incident");

  /* -------------------------------------------------------------------- audit trail */
  await page.goto(`/governance/audit${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("audit-timeline")).toBeVisible();
  await shot("audit-first-viewport", false);
  await shot("audit-demo");

  await page.goto(`/governance/audit${DEMO}&kind=RECORD_TOMBSTONED`);
  await settle(page);
  await openEveryDisclosure(page);
  await shot("audit-tombstone");

  await page.goto(`/governance/audit${DEMO}&kind=CORRECTION_APPENDED`);
  await settle(page);
  await openEveryDisclosure(page);
  await shot("audit-correction");

  /* ------------------------------------------------------------------------- alerts */
  await page.goto(`/system/alerts${DEMO}`);
  await settle(page);
  await expect(page.getByTestId("alert-table")).toBeVisible();
  await shot("alerts-first-viewport", false);
  await shot("alerts-demo");

  await page.goto(`/system/alerts${DEMO}&state=RESOLVED`);
  await settle(page);
  await shot("alerts-resolved-history");

  await page.goto(`/system/alerts${OPERATOR}`);
  await settle(page);
  await page.getByTestId("alert-table").locator("tbody button").first().click();
  await shot("alerts-operator-detail");

  await page.goto(`/system/alerts${PROJECT}`);
  await settle(page);
  await shot("alerts-project");
});
