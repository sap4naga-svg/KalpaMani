import { AxeBuilder } from "@axe-core/playwright";
import { expect, test, type Page, type Request } from "@playwright/test";

/**
 * Browser integration tests.
 *
 * These drive a real browser rather than asserting on snapshots, and they exercise the
 * behaviours a unit test cannot reach: keyboard focus restoration, live freshness expiry
 * on a mounted page, responsive layout, and the network the page actually opens.
 */

const ALL_ROUTES = [
  "/",
  "/attention",
  "/portfolio/performance",
  "/portfolio/positions",
  "/portfolio/trades",
  "/strategy/performance",
  "/strategy/health",
  "/strategy/champion-challenger",
  "/strategy/versions",
  "/signals/funnel",
  "/signals/missed",
  "/risk",
  "/risk/short-side",
  "/market/regime",
  "/execution/quality",
  "/execution/reconciliation",
  "/research/runs",
  "/research/queue",
  "/research/hypotheses",
  "/research/feedback",
  "/research/ai-contribution",
  "/governance/packets",
  "/governance/qualification",
  "/governance/maturity",
  "/governance/audit",
  "/governance/controls",
  "/system/data-quality",
  "/system/operations",
  "/system/alerts",
  "/foundation/states",
];

/** Fails the test on any console error or page exception. */
function guardConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(String(error)));
  return problems;
}

/**
 * Waits until React has hydrated.
 *
 * The freshness indicator only appears once the client query has resolved, so its presence
 * proves the keyboard listener the palette installs on `window` is attached.
 */
async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

test.describe("shell and navigation", () => {
  test("every registered route renders without a 404 or a console error", async ({ page }) => {
    const problems = guardConsole(page);
    for (const route of ALL_ROUTES) {
      const response = await page.goto(route);
      expect(response?.status(), `${route} must not 404`).toBeLessThan(400);
      await expect(page.locator("h1")).toBeVisible();
      await expect(page.getByTestId("context-bar")).toBeVisible();
      await expect(page.getByTestId("page-provenance-banner")).toBeVisible();
    }
    expect(problems).toEqual([]);
  });

  test("has exactly one h1, a main landmark and a working skip link", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("main#main-content")).toBeVisible();

    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await skip.press("Enter");
    await expect(page).toHaveURL(/#main-content/);
  });

  test("no page scrolls horizontally at this viewport", async ({ page }) => {
    for (const route of ["/", "/governance/qualification", "/foundation/states", "/risk"]) {
      await page.goto(route);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${route} must not scroll horizontally`).toBeLessThanOrEqual(1);
    }
  });
});

test.describe("mode, scope and deep links", () => {
  test("preserves the drill-down path and scope across a mode switch (U13, U15)", async ({
    page,
  }) => {
    await page.goto("/governance/qualification?mode=executive&env=PAPER&scenario=demo");
    await page.getByTestId("mode-switch").getByRole("radio", { name: "operator" }).click();

    await expect(page).toHaveURL(/\/governance\/qualification/);
    await expect(page).toHaveURL(/mode=operator/);
    // The rest of the scope is untouched by a mode switch.
    await expect(page).toHaveURL(/env=PAPER/);
    await expect(page).toHaveURL(/scenario=demo/);
  });

  test("reproduces a view from its URL alone", async ({ page }) => {
    await page.goto("/?mode=operator&env=LIVE&scenario=demo");
    await expect(
      page.getByTestId("mode-switch").getByRole("radio", { name: "operator" }),
    ).toHaveAttribute("aria-checked", "true");
    await expect(
      page.getByTestId("environment-switch").getByRole("radio", { name: "live" }),
    ).toHaveAttribute("aria-checked", "true");
    // Operator mode exposes evidence the executive view does not.
    await expect(page.getByText("Response evidence")).toBeVisible();
  });

  test("carries the scope into a navigation", async ({ page }) => {
    // RESEARCH is the environment that carries facts, so the drill-down link exists here.
    // `mode=operator` and `scenario=demo` are both NON-DEFAULT, and all three keys are
    // written by the same `withScope` call -- a scope key that was dropped would default.
    await page.goto("/?mode=operator&env=RESEARCH&scenario=demo");
    await page.getByRole("link", { name: /Each gate is read on its own/ }).click();
    await expect(page).toHaveURL(/\/governance\/qualification/);
    await expect(page).toHaveURL(/env=RESEARCH/);
    await expect(page).toHaveURL(/mode=operator/);
    await expect(page).toHaveURL(/scenario=demo/);
  });

  /**
   * An unpopulated environment shows NOTHING, rather than the same records re-badged.
   *
   * Every fact this application holds was produced in RESEARCH. Selecting Paper or Live
   * must not re-label the real tracked governance record as Paper or Live evidence, and it
   * must not render a count of a thing nobody read: `0 of 0` open gates is a fabricated
   * measurement, and a permanent loading skeleton implies data that is never coming.
   */
  test("shows an unpopulated environment as explicitly unavailable, not re-badged", async ({
    page,
  }) => {
    for (const environment of ["PAPER", "LIVE"]) {
      await page.goto(`/?mode=operator&env=${environment}&scenario=demo`);
      const gates = page.getByTestId("tile-open-gates");
      await expect(gates.getByTestId("unavailable-body")).toBeVisible();
      // No drill-down into facts that are not there, and no fabricated count.
      await expect(gates.getByRole("link")).toHaveCount(0);
      await expect(gates.getByText(/\bof \d/)).toHaveCount(0);
      // The strategy-capital tile is the other reader of that record.
      await expect(
        page.getByTestId("tile-strategy-capital").getByTestId("unavailable-body"),
      ).toBeVisible();
      // And no skeleton is left standing in for data that will never arrive.
      await expect(page.getByTestId("skeleton")).toHaveCount(0);
      await expect(page.getByText("PRODUCER_NOT_IMPLEMENTED").first()).toBeVisible();
    }
  });

  test("shows different information density in each mode", async ({ page }) => {
    await page.goto("/?scenario=demo&mode=executive");
    await expect(page.getByText("Response evidence")).toHaveCount(0);
    await page.goto("/?scenario=demo&mode=operator");
    await expect(page.getByText("Response evidence")).toBeVisible();
    await expect(page.getByText("metric_definition_version").first()).toBeVisible();
  });
});

test.describe("the command palette", () => {
  test("opens with the keyboard, navigates, and restores focus on Escape (U8)", async ({
    page,
  }) => {
    await page.goto("/");
    const trigger = page.getByRole("button", { name: /Search/ });
    await trigger.focus();

    await page.keyboard.press("ControlOrMeta+k");
    const palette = page.getByTestId("command-palette");
    await expect(palette).toBeVisible();

    // Escape closes exactly one layer and returns focus to the invoking element.
    await page.keyboard.press("Escape");
    await expect(palette).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("navigates by keyboard and preserves the scope in the destination", async ({ page }) => {
    await page.goto("/?env=PAPER&scenario=demo");
    await waitForHydration(page);
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByPlaceholder("Search records, areas and view filters…").fill("qualification");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/governance\/qualification/);
    await expect(page).toHaveURL(/env=PAPER/);
  });

  test("offers a useful no-results state", async ({ page }) => {
    await page.goto("/");
    await waitForHydration(page);
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByPlaceholder("Search records, areas and view filters…").fill("zzzqqqxxx");
    /*
     * THE COPY MOVED BECAUSE THE PALETTE DID, AND THE ASSERTION IS UNCHANGED IN STRENGTH.
     *
     * C9 completed Area 30: the palette now searches RECORDS as well as areas and view
     * filters, so "No area or view filter matches that search" described a narrower search
     * than the one that ran. The empty state still names what was searched and still states
     * that the palette has no state-changing command, which is what this test is about.
     */
    await expect(page.getByText("Nothing matches that search")).toBeVisible();
    await expect(
      page.getByText("it has no state-changing command", { exact: false }),
    ).toBeVisible();
  });

  test("exposes no state-changing command, whatever is searched (U9)", async ({ page }) => {
    await page.goto("/");
    await waitForHydration(page);
    await page.keyboard.press("ControlOrMeta+k");
    const input = page.getByPlaceholder("Search records, areas and view filters…");

    /*
     * The palette's matcher is fuzzy, so an execution word can still SURFACE a legitimate
     * navigation item. The property that matters is stronger and is what is asserted: every
     * result the palette can produce is a registered navigation destination or a local view
     * filter, and every one of them is labelled with the closed kind that produced it.
     */
    const permittedHints = new Set([
      "Overview",
      "Portfolio",
      "Strategy",
      "Signals",
      "Risk & Market",
      "Execution",
      "Research",
      "Governance",
      "System",
      "Foundation",
      "Local view filter",
      "Local data scope",
    ]);

    for (const verb of ["order", "execute", "approve", "promote", "kill", "sell", "buy", ""]) {
      await input.fill(verb);
      const items = page.locator("[cmdk-item]");
      for (let index = 0; index < (await items.count()); index += 1) {
        const hint = (await items.nth(index).locator("span + span").innerText()).trim();
        expect(
          permittedHints.has(hint),
          `searching "${verb}" produced a result whose kind is "${hint}"`,
        ).toBe(true);
      }
    }
  });
});

test.describe("availability, provenance and freshness", () => {
  test("labels synthetic data at page level and at component level (U3)", async ({ page }) => {
    await page.goto("/?scenario=demo");
    await expect(page.getByTestId("page-provenance-banner")).toContainText(
      "SYNTHETIC DEMONSTRATION DATA",
    );
    // Wait for the tiles to resolve before counting their component-level badges.
    await expect(page.getByTestId("attention-panel")).toBeVisible();
    const componentBadges = page.locator('[data-provenance="SYNTHETIC"]');
    expect(await componentBadges.count()).toBeGreaterThan(3);
  });

  test("never badges a tracked governance fact as synthetic (section 9.4)", async ({ page }) => {
    await page.goto("/governance/qualification?scenario=demo");
    await expect(page.locator('[data-provenance="REPOSITORY_TRACKED"]').first()).toBeVisible();
    await expect(page.locator("h1")).toContainText("Qualification");
  });

  test("defaults to an honest project readiness view rather than inventing numbers", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByTestId("page-provenance-banner")).toContainText("PROJECT READINESS");
    // The operational tiles state that their producer does not exist.
    await expect(page.locator('[data-availability="NOT_IMPLEMENTED"]').first()).toBeVisible();
  });

  test("renders each availability state distinctly on the reference page (U4, U5)", async ({
    page,
  }) => {
    await page.goto("/foundation/states");
    for (const state of [
      "AVAILABLE",
      "STALE",
      "PARTIAL",
      "EMPTY_VERIFIED",
      "NOT_YET_AVAILABLE",
      "NOT_IMPLEMENTED",
      "NOT_AUTHORIZED",
      "UNEVALUATED",
      "INSUFFICIENT_OBSERVATIONS",
      "NOT_APPLICABLE",
      "ERROR",
    ]) {
      await expect(
        page.locator(`[data-availability="${state}"]`).first(),
        `${state} must render`,
      ).toBeVisible();
    }
  });

  test("distinguishes a measured zero from an empty population", async ({ page }) => {
    await page.goto("/foundation/states");
    await expect(page.getByTestId("measured-zero")).toContainText("Available");
    await expect(page.getByTestId("empty-population")).toContainText("Empty (verified)");
  });

  test("expires freshness while the page stays mounted, with no navigation", async ({ page }) => {
    await page.goto("/foundation/states");
    const demo = page.getByTestId("freshness-demo");
    await expect(demo.locator('[data-availability="AVAILABLE"]')).toBeVisible();

    const url = page.url();
    // The reference budget is five seconds; wait past the absolute deadline.
    await expect(demo.locator('[data-availability="STALE"]')).toBeVisible({ timeout: 15_000 });
    // No navigation occurred, and no refetch renewed anything.
    expect(page.url()).toBe(url);
  });

  test("isolates a failing widget and leaves the page usable (U6)", async ({ page }) => {
    await page.goto("/foundation/states");
    await expect(page.locator('[data-availability="ERROR"]').first()).toBeVisible();
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.getByTestId("context-bar")).toBeVisible();
  });

  test("reports an unavailable What Changed endpoint instead of a delta (U17)", async ({
    page,
  }) => {
    await page.goto("/");
    const panel = page.getByTestId("what-changed-panel");
    await expect(panel).toContainText("A comparison needs two valid");
    // The wrapper and its badge both carry the attribute; either proves the state.
    await expect(panel.locator('[data-availability="NOT_YET_AVAILABLE"]').first()).toBeVisible();
  });
});

test.describe("the safety boundary", () => {
  test("keeps every future control inert, with no button and no handler (U16)", async ({
    page,
  }) => {
    await page.goto("/governance/controls");
    await expect(page.getByTestId("inert-marker")).toBeVisible();
    const cards = page.getByTestId("inert-control");
    expect(await cards.count()).toBeGreaterThan(3);
    // No control on this page is a button, an input or a form.
    expect(await page.locator("main button, main input, main form").count()).toBe(0);
  });

  test("opens no network connection beyond its own assets", async ({ page }) => {
    const external: string[] = [];
    page.on("request", (request: Request) => {
      const url = new URL(request.url());
      if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost") {
        external.push(request.url());
      }
    });
    for (const route of ["/", "/governance/qualification", "/foundation/states"]) {
      await page.goto(route);
      await page.waitForLoadState("networkidle");
    }
    // No provider, broker, AWS, GitHub, LLM, analytics, font or image host is contacted.
    expect(external).toEqual([]);
  });

  test("discloses no private identifier anywhere in the rendered interface (U20)", async ({
    page,
  }) => {
    for (const route of ["/", "/governance/qualification", "/foundation/states"]) {
      await page.goto(`${route}?scenario=demo&mode=operator`);
      const text = (await page.locator("body").innerText()).toLowerCase();
      for (const needle of ["akia", "arn:aws", "secretsmanager", "s3://", "amazonaws"]) {
        expect(text.includes(needle), `${route} must not disclose ${needle}`).toBe(false);
      }
      // No twelve-digit account id, and no bare broker-native order id.
      expect(/\b\d{12}\b/.test(text), `${route} must not show a 12-digit identifier`).toBe(false);
    }
  });
});

test.describe("accessibility", () => {
  test("has no detectable serious or critical violation on the substantive routes", async ({
    page,
  }) => {
    for (const route of ["/", "/governance/qualification", "/governance/controls", "/foundation/states"]) {
      await page.goto(`${route}?scenario=demo`);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const serious = results.violations.filter(
        (violation) => violation.impact === "serious" || violation.impact === "critical",
      );
      expect(
        serious.map((violation) => `${route}: ${violation.id}`),
        "automated checks cover only part of accessibility; a manual pass is still required",
      ).toEqual([]);
    }
  });
});
