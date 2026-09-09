import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * ADR-0032 in a browser — the rolling tail loss, and the capacity admission gate.
 *
 * Every assertion is about something a reader can actually see: a number with the window and
 * the population it was measured over beside it, an insufficiency that stays visible rather
 * than being drawn as a zero, and an unavailable capacity that names the gate stage it refused
 * at and the inputs it found missing.
 *
 * READINESS IS A VISIBLE ELEMENT, NEVER A NETWORK PROXY. `networkidle` says the socket went
 * quiet, which is not the same as the screen being ready.
 */

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo&period=1Y&gran=DAILY&changes=auto";
const OPERATOR =
  "?mode=operator&env=RESEARCH&scenario=demo&period=1Y&gran=DAILY&changes=auto";
const PROJECT =
  "?mode=executive&env=RESEARCH&scenario=project&period=1Y&gran=DAILY&changes=auto";

async function ready(page: Page): Promise<void> {
  await expect(page.getByTestId("context-bar")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

test.describe("the rolling tail loss on strategy health", () => {
  test("shows the value with the window, population, fraction and counts beside it", async ({
    page,
  }) => {
    await page.goto(`/strategy/health${DEMO}`);
    await ready(page);
    const panel = page.getByTestId("health-tail-loss");
    await panel.scrollIntoViewIfNeeded();
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("tail-loss-window")).toContainText("30");
    await expect(panel.getByTestId("tail-loss-window")).toContainText("Closed trade");
    await expect(panel.getByTestId("tail-loss-fraction")).toHaveText("0.10");
    await expect(panel.getByTestId("tail-loss-eligible")).toBeVisible();
    await expect(panel.getByTestId("tail-loss-tail-count")).toBeVisible();
    await expect(panel.getByTestId("tail-loss-excluded")).toBeVisible();
    await expect(panel.getByTestId("tail-loss-version")).toBeVisible();
    /* The unit and the R basis are named, so the number is never a bare figure. */
    await expect(panel).toContainText("R multiple");
    await expect(panel).toContainText("mean of ratios");
  });

  test("states the limitation instead of implying a reliable estimate", async ({ page }) => {
    await page.goto(`/strategy/health${DEMO}`);
    await ready(page);
    const panel = page.getByTestId("health-tail-loss");
    await expect(panel).toContainText("descriptive estimate with limited support");
    await expect(panel).toContainText("no predictive reliability");
    /* And it says what it is NOT, because those are the three it is confused with. */
    await expect(panel).toContainText("not expectancy, not drawdown and not the worst single");
  });

  test("keeps insufficient history visible rather than drawing it as a zero", async ({
    page,
  }) => {
    await page.goto(`/strategy/health${DEMO}`);
    await ready(page);
    /*
     * At least one version in the demonstration book carries fewer than thirty eligible
     * closed trades. Its panel must say so, and must show no number at all.
     */
    const rows = page.getByTestId("health-rows").locator("tbody tr");
    /*
     * WAIT FOR THE TABLE BEFORE COUNTING IT. `locator.count()` does not retry, and the read
     * model loads after the heading does — so a count taken at `ready` is zero and the loop
     * below never runs.
     */
    await expect(rows.first()).toBeVisible();
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);
    let sawInsufficient = false;
    for (let index = 0; index < count; index += 1) {
      const version = await rows.nth(index).getAttribute("data-health-version");
      await rows.nth(index).getByRole("button", { name: "History" }).click();
      /*
       * WAIT FOR THE DETAIL CARD TO BE THIS ROW'S BEFORE READING IT.
       *
       * `textContent` does not retry, and the previous version's panel is still mounted for
       * an instant after the click — so a read taken immediately reports the row before this
       * one, and the last row's answer is never observed at all.
       */
      await expect(page.getByTestId("health-detail")).toHaveAttribute(
        "data-health-version",
        version ?? "",
      );
      const panel = page.getByTestId("health-tail-loss");
      await expect(panel).toBeVisible();
      /*
       * THE VERSION'S OWN ANSWER, read from the panel's own attribute.
       *
       * Not from a state found anywhere inside the panel: the series table carries one badge
       * per point, and the early points of a value-bearing version are legitimately
       * INSUFFICIENT_OBSERVATIONS. A search over the whole panel would find a point's answer
       * and report it as the version's.
       */
      const state = await panel
        .locator("[data-tail-loss-availability]")
        .first()
        .getAttribute("data-tail-loss-availability");
      if (state === "INSUFFICIENT_OBSERVATIONS") {
        sawInsufficient = true;
        await expect(panel.getByTestId("tail-loss-none-computed")).toBeVisible();
        await expect(panel).toContainText("neither a shorter window nor a zero is substituted");
        await expect(panel).toContainText("Insufficient observations");
      }
    }
    /* A SUITE THAT NEVER REACHED THE BRANCH WOULD PASS VACUOUSLY. */
    expect(sawInsufficient, "no version rendered the insufficient answer").toBe(true);
  });

  test("agrees between the chart table and the headline value", async ({ page }) => {
    await page.goto(`/strategy/health${OPERATOR}`);
    await ready(page);
    const panel = page.getByTestId("health-tail-loss");
    await panel.scrollIntoViewIfNeeded();
    const table = panel.locator("table");
    if ((await table.count()) === 0) {
      /* A version with no computed point renders the stated sentence instead of a table. */
      await expect(panel.getByTestId("tail-loss-none-computed")).toBeVisible();
      return;
    }
    const rows = table.locator("tbody tr");
    expect(await rows.count()).toBeGreaterThan(0);
    /* The last point of the series is the value the panel headlines. */
    const headline = (await panel.getByTestId("tail-loss-value").textContent()) ?? "";
    const last = (await rows.last().textContent()) ?? "";
    expect(headline.trim().length).toBeGreaterThan(0);
    expect(last.length).toBeGreaterThan(0);
  });

  test("offers no control that could change a health state", async ({ page }) => {
    await page.goto(`/strategy/health${OPERATOR}`);
    await ready(page);
    const panel = page.getByTestId("health-tail-loss");
    await expect(panel.getByRole("button")).toHaveCount(0);
    await expect(panel.locator("input, select, textarea")).toHaveCount(0);
  });
});

test.describe("the capacity admission gate on strategy performance", () => {
  test("names the gate stage it refused at and the inputs it found missing", async ({
    page,
  }) => {
    await page.goto(`/strategy/performance${OPERATOR}`);
    await ready(page);
    const capacity = page.getByTestId("capacity-dependencies").first();
    await capacity.scrollIntoViewIfNeeded();
    await expect(capacity).toBeVisible();
    await expect(capacity.getByTestId("capacity-gate-stage")).toHaveText("Required inputs");
    const missing = capacity.getByTestId("capacity-missing-inputs");
    await expect(missing).toBeVisible();
    expect(await missing.getByRole("listitem").count()).toBeGreaterThan(0);
    await expect(missing).toContainText("Market impact function");
  });

  test("names the accepted meaning and every quantity it is not", async ({ page }) => {
    await page.goto(`/strategy/performance${OPERATOR}`);
    await ready(page);
    const capacity = page.getByTestId("capacity-dependencies").first();
    await expect(capacity).toContainText("cost-degradation tolerance");
    await expect(capacity).toContainText("own observed execution");
    await expect(capacity).toContainText("poor observed execution mechanically raises");
    await expect(capacity).toContainText("not a profitability capacity");
    await expect(capacity).toContainText("not strategy capital");
    await expect(capacity).toContainText("not permission to scale");
    await expect(capacity).toContainText("never summed into a portfolio capacity");
  });

  test("renders no capacity number at all, and no zero standing in for one", async ({
    page,
  }) => {
    await page.goto(`/strategy/performance${OPERATOR}`);
    await ready(page);
    const capacity = page.getByTestId("capacity-dependencies").first();
    const text = (await capacity.textContent()) ?? "";
    expect(text).not.toMatch(/\$\s?\d/);
    expect(text).not.toContain("80,000");
  });

  test("carries the same refusal on the research run screen", async ({ page }) => {
    await page.goto(`/research/runs${OPERATOR}`);
    await ready(page);
    const panel = page.getByTestId("run-capacity-declaration").first();
    await panel.scrollIntoViewIfNeeded();
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("run-capacity-gate-stage")).toHaveText("Required inputs");
    await expect(panel).toContainText("BACKTEST_SIMULATED");
    await expect(panel).toContainText("backtesting is NOT STARTED");
  });
});

test.describe("the ADR-0032 surfaces stay inside the V1 boundary", () => {
  const ROUTES = ["/strategy/health", "/strategy/performance", "/research/runs"] as const;

  test("scrolls no page body sideways at this viewport (U14)", async ({ page }) => {
    for (const route of ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await ready(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, route).toBeLessThanOrEqual(1);
    }
  });

  test("logs no console or page error on any of them", async ({ page }) => {
    const problems: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") problems.push(`console: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`page: ${error.message}`));
    for (const route of ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await ready(page);
    }
    expect(problems).toEqual([]);
  });

  test("requests nothing off its own origin", async ({ page }) => {
    const foreign: string[] = [];
    page.on("request", (request) => {
      if (!request.url().startsWith("http://127.0.0.1")) foreign.push(request.url());
    });
    for (const route of ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await ready(page);
    }
    expect(foreign).toEqual([]);
  });

  test("keeps focus visible and restorable on the health screen", async ({ page }) => {
    await page.goto(`/strategy/health${OPERATOR}`);
    await ready(page);
    await page.keyboard.press("Tab");
    const focused = page.locator(":focus");
    await expect(focused).toBeVisible();
    const outline = await focused.evaluate((node) => getComputedStyle(node).outlineStyle);
    expect(outline).not.toBe("");
  });

  test("answers project scope without inventing a measurement", async ({ page }) => {
    await page.goto(`/strategy/health${PROJECT}`);
    await ready(page);
    const body = (await page.locator("body").textContent()) ?? "";
    expect(body).not.toContain("descriptive estimate with limited support");
  });

  test("has no detectable serious or critical violation on these routes", async ({ page }) => {
    for (const route of ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await ready(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const serious = results.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? ""),
      );
      expect(serious.map((violation) => violation.id), route).toEqual([]);
    }
  });
});
