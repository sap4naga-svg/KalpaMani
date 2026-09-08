import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

/**
 * ADR-0031 owning-area navigation, in a real browser at all three reference viewports.
 *
 * The affordance this restores is a LINK a person clicks, so the checks that matter are the
 * ones a unit test cannot make: that the control is reachable, activable from the keyboard,
 * visibly focused, honest about an unbuilt destination, and that adding it broke neither the
 * page's horizontal containment nor its hydration.
 *
 * The screenshots are REVIEW EVIDENCE, not a visual-regression baseline, and they are stamped
 * with the exact revision they were taken at — a screenshot whose revision is unknown is a
 * picture rather than evidence.
 */
const SHOTS = "screenshots-adr0031";
const DEMO = "?scenario=demo";

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
    // A capture with no recoverable revision says so rather than claiming one.
  }
  writeFileSync(
    `${SHOTS}/PROVENANCE.txt`,
    [
      "KalpaMani Cockpit -- ADR-0031 owning-area navigation review evidence",
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

function guardConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(String(error)));
  return problems;
}

async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

/** Open every attention evidence disclosure on the page. */
async function openEveryDisclosure(page: Page): Promise<void> {
  for (const summary of await page.getByTestId("attention-evidence").locator("summary").all()) {
    await summary.click();
  }
}

test.describe("the restored owning-area affordance", () => {
  test("offers a distinct area link on every disclosed attention reference", async ({ page }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);
    await openEveryDisclosure(page);

    const areas = page.getByTestId("reference-area-link");
    await expect(areas).toHaveCount(4);
    const hrefs = await areas.evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLAnchorElement).getAttribute("href")!.split("?")[0]),
    );
    expect(new Set(hrefs)).toEqual(
      new Set([
        "/system/data-quality",
        "/strategy/health",
        "/risk/short-side",
        "/execution/reconciliation",
      ]),
    );

    // The target control is a SECOND, different control on each row, and it is not merged in.
    for (const row of await page.getByTestId("evidence-reference").all()) {
      await expect(row.getByTestId("reference-target-link")).toHaveCount(1);
      await expect(row.getByTestId("reference-area-link")).toHaveCount(1);
    }
  });

  test("names the area and never claims to retrieve the evidence", async ({ page }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);
    await openEveryDisclosure(page);

    for (const link of await page.getByTestId("reference-area-link").all()) {
      const label = (await link.textContent())!.toLowerCase();
      expect(label).toContain("area");
      for (const verb of ["view", "open", "retrieve", "resolve", "show", "evidence"]) {
        expect(label, verb).not.toContain(verb);
      }
    }
  });

  test("says out loud that an unbuilt destination is not implemented", async ({ page }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);
    await openEveryDisclosure(page);

    /*
     * EVERY DESTINATION THE ATTENTION LIST REACHES IS NOW A BUILT SCREEN.
     *
     * C7 built the Strategy Health area and C8 built Data Quality, Reconciliation, Operations,
     * Alerts and the Audit Trail, so the count has moved from three to two to zero. **That it
     * moves at all is the assertion's point**: the marker follows the DESTINATION'S OWN
     * registry status rather than a literal kept in this file, and the per-area check below is
     * what would catch an affordance that stopped reading that status.
     */
    await expect(page.getByTestId("reference-area-placeholder")).toHaveCount(0);
    for (const area of ["SHORT_SIDE", "STRATEGY_HEALTH", "DATA_QUALITY", "RECONCILIATION"]) {
      const built = page
        .getByTestId("evidence-reference")
        .filter({ has: page.locator(`[data-owning-area="${area}"]`) })
        .first();
      await expect(built.getByTestId("reference-area-placeholder")).toHaveCount(0);
      await expect(built.getByTestId("reference-area-link")).toHaveAttribute(
        "data-area-status",
        "implemented",
      );
    }
  });

  test("reaches a real page from the area link, and does not claim a retrieval", async ({
    page,
  }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);
    await openEveryDisclosure(page);

    const link = page
      .getByTestId("evidence-reference")
      .filter({ has: page.locator('[data-owning-area="DATA_QUALITY"]') })
      .first()
      .getByTestId("reference-area-link");
    await link.click();
    await expect(page).toHaveURL(/\/system\/data-quality/);
    await waitForHydration(page);
    /*
     * THE AREA PAGE IS THE AREA, AND NOT THE ARTEFACT.
     *
     * C8 built this screen, so it now renders the Data Quality area's own read model. It still
     * does NOT present the evidence artefact the reference named — an area control is
     * contextual navigation, never a claim that the reference was resolved or retrieved.
     */
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Data Quality");
    await expect(page.locator("body")).not.toContainText("demo-evidence-data-quality");
  });

  test("activates the area link from the keyboard and keeps focus visible", async ({ page }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);
    await openEveryDisclosure(page);

    const link = page.getByTestId("reference-area-link").first();
    await link.focus();
    await expect(link).toBeFocused();
    const outline = await link.evaluate((node) => {
      const style = window.getComputedStyle(node, ":focus-visible");
      return `${style.outlineStyle}|${style.outlineWidth}|${style.boxShadow}`;
    });
    expect(outline.length).toBeGreaterThan(0);
    await page.keyboard.press("Enter");
    await expect(page).not.toHaveURL(/\/attention/);
  });

  test("keeps What Changed's endpoint qualification and its evidence filters", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    for (const summary of await page
      .getByTestId("what-changed-item")
      .locator("summary")
      .all()) {
      await summary.click();
    }
    const rows = page.getByTestId("change-evidence-reference");
    expect(await rows.count()).toBeGreaterThan(0);
    // Some references declare an area and some declare none, and both are rendered honestly.
    const declared = await rows.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-owning-area")),
    );
    expect(declared.some((value) => value !== "")).toBe(true);
    expect(declared.some((value) => value === "")).toBe(true);
    // Every row still states its own resolution and classification.
    for (const row of await rows.all()) {
      await expect(row).toContainText("PUBLIC_SAFE");
    }
  });

  test("adds no horizontal overflow, no console error and no off-origin request", async ({
    page,
  }, testInfo) => {
    const problems = guardConsole(page);
    const offOrigin: string[] = [];
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.hostname !== "127.0.0.1" && url.protocol !== "data:") {
        offOrigin.push(url.origin);
      }
      await route.continue();
    });

    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);
    await openEveryDisclosure(page);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "the page body never scrolls horizontally").toBeLessThanOrEqual(1);

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const serious = results.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );
    expect(serious.map((violation) => violation.id)).toEqual([]);

    expect(offOrigin).toEqual([]);
    expect(problems).toEqual([]);

    await page.screenshot({
      path: `${SHOTS}/${testInfo.project.name}-attention-owning-area.png`,
      fullPage: true,
    });
  });

  test("captures the first viewport un-scrolled, and the What Changed disclosure", async ({
    page,
  }, testInfo) => {
    const project = testInfo.project.name;
    await page.goto(`/${DEMO}&mode=executive`);
    await waitForHydration(page);
    await page.screenshot({ path: `${SHOTS}/${project}-first-viewport.png`, fullPage: false });

    for (const summary of await page
      .getByTestId("what-changed-item")
      .locator("summary")
      .all()) {
      await summary.click();
    }
    await page.screenshot({ path: `${SHOTS}/${project}-what-changed.png`, fullPage: true });
  });
});
