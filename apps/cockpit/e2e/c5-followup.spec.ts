import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * The C5 completion follow-up, in a browser.
 *
 * Every assertion is about something a reader can see: two numbers a reader must not
 * confuse, an absence rendered as its own state, a limit stated above the picture rather
 * than under it, and a table carrying the same points as the chart.
 *
 * READINESS IS A VISIBLE ELEMENT, NEVER A NETWORK PROXY. `networkidle` says the socket went
 * quiet, which is not the same as the screen being ready, and a suite that waits on it is
 * waiting on the wrong thing.
 */

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo&period=1Y&gran=DAILY&changes=auto";
const DEMO_SHORT =
  "?mode=executive&env=RESEARCH&scenario=demo&period=1M&gran=DAILY&changes=auto";
const DEMO_ALL = "?mode=executive&env=RESEARCH&scenario=demo&period=ALL&gran=DAILY&changes=auto";
const OPERATOR =
  "?mode=operator&env=RESEARCH&scenario=demo&period=1Y&gran=DAILY&changes=auto";
const PROJECT =
  "?mode=executive&env=RESEARCH&scenario=project&period=1Y&gran=DAILY&changes=auto";

async function ready(page: Page): Promise<void> {
  await expect(page.getByTestId("context-bar")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

test.describe("rolling windows on the portfolio performance screen", () => {
  test("prints the requested extent and the rolling lookback as two different numbers", async ({
    page,
  }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const panel = page.getByTestId("rolling-windows");
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("rolling-extent")).toContainText("1 year");
    await expect(panel.getByTestId("rolling-extent")).toContainText("252");
    await expect(panel.getByTestId("rolling-lookback")).toContainText("21 daily periods");
  });

  test("recomputes the window when the lookback changes, and says which one is drawn", async ({
    page,
  }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const panel = page.getByTestId("rolling-windows");
    await panel.getByTestId("lookback-selector").getByRole("button", { name: "126 periods" }).click();
    await expect(panel.getByTestId("rolling-lookback")).toContainText("126 daily periods");
    await expect(
      panel.getByTestId("lookback-selector").getByRole("button", { name: "126 periods" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  test("shows the points below the minimum as a state and never as a zero", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const tally = page.getByTestId("rolling-windows").getByTestId("rolling-tally");
    await expect(tally).toContainText("fewer than 21 earlier observations");
    await expect(tally).toContainText("Insufficient observations");
  });

  test("separates a gapped window from a window that is merely too early", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO_ALL}`);
    await ready(page);
    const tally = page.getByTestId("rolling-windows").getByTestId("rolling-tally");
    await expect(tally).toContainText("span a session that carries no observation");
    await expect(tally).toContainText("fewer than 21 earlier observations");
  });

  test("says plainly when a period is shorter than every lookback it offers", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO_SHORT}`);
    await ready(page);
    await expect(
      page.getByTestId("rolling-windows").getByTestId("rolling-none-computed"),
    ).toContainText("No point in this extent has a complete window behind it");
  });

  test("carries a keyboard-reachable table alternative for the chart (U10)", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const disclosure = page.getByTestId("rolling-table-disclosure");
    await disclosure.getByText(/as a table/).click();
    await expect(disclosure.getByRole("table")).toBeVisible();
    await expect(disclosure.getByRole("table")).toContainText("Insufficient observations");
  });

  test("renders its unavailable state in project scope, with its dependency named", async ({
    page,
  }) => {
    await page.goto(`/portfolio/performance${PROJECT}`);
    await ready(page);
    const panel = page.getByTestId("rolling-windows");
    await expect(panel.getByTestId("unavailable-body")).toContainText(
      "the portfolio valuation projection",
    );
  });
});

test.describe("the portfolio benchmark comparison", () => {
  test("draws two separately labelled arms rebased to a common start", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const comparison = page.getByTestId("benchmark-comparison");
    await expect(comparison).toBeVisible();
    await expect(comparison.getByTestId("comparison-chart")).toBeVisible();
    await expect(comparison).toContainText("Demonstration broad market index");
    await expect(comparison.getByText("SYNTHETIC").first()).toBeVisible();
  });

  test("states its comparability limits on the screen rather than under a disclosure", async ({
    page,
  }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const limits = page.getByTestId("comparability-limits");
    await expect(limits).toBeVisible();
    await expect(limits).toContainText(/cost treatment/i);
    await expect(limits).toContainText(/not a market index/i);
    await expect(limits).toContainText(/establishes nothing about any strategy/i);
  });

  test("refuses the difference and names the incompatibility", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const block = page.getByTestId("comparison-difference");
    await expect(block.getByTestId("comparison-refusal")).toContainText(
      /arms differ in cost treatment/i,
    );
    await expect(block).toContainText("never compared, summed or placed in one series");
  });

  test("keeps the named benchmarks unresolved and says the requirement is still open", async ({
    page,
  }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    await expect(page.getByTestId("named-benchmark-outstanding")).toContainText(
      "The named-benchmark requirement is not satisfied by this",
    );
    await expect(page.getByTestId("named-benchmark-outstanding")).toContainText("G1 is OPEN");
  });

  test("recomputes the comparison when the period changes rather than cropping it", async ({
    page,
  }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const window = page.getByTestId("comparison-window");
    const before = await window.textContent();
    await page
      .getByTestId("performance-curves")
      .getByTestId("period-selector")
      .getByRole("button", { name: "3M" })
      .click();
    await expect(window).not.toHaveText(String(before));
    /** Both arms still start at the rebase base after the recompute. */
    const disclosure = page.getByTestId("comparison-table-disclosure");
    await disclosure.getByText(/as a table/).click();
    const firstRow = disclosure.getByRole("row").nth(1);
    await expect(firstRow).toContainText("100.00");
  });

  test("carries a table alternative with both arms", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const disclosure = page.getByTestId("comparison-table-disclosure");
    await disclosure.getByText(/as a table/).click();
    await expect(disclosure.getByRole("table")).toContainText("Portfolio");
  });
});

test.describe("rolling expectancy and capacity on the strategy screen", () => {
  test("shows the lookback in closed trades, not in sessions", async ({ page }) => {
    await page.goto(`/strategy/performance${OPERATOR}`);
    await ready(page);
    const first = page.getByTestId(/^rolling-expectancy-/).first();
    await expect(first).toBeVisible();
    await expect(first.getByTestId("expectancy-lookback")).toContainText("30 closed trades");
    await expect(first).toContainText("Closed trade");
  });

  test("reports how many points were computed and how many the version carries", async ({
    page,
  }) => {
    await page.goto(`/strategy/performance${OPERATOR}`);
    await ready(page);
    const first = page.getByTestId(/^rolling-expectancy-/).first();
    await expect(first.getByTestId("expectancy-observed")).toBeVisible();
    await expect(first.getByTestId("expectancy-computed")).toBeVisible();
  });

  test("names what capacity is waiting on instead of leaving it merely unavailable", async ({
    page,
  }) => {
    await page.goto(`/strategy/performance${OPERATOR}`);
    await ready(page);
    const capacity = page.getByTestId("capacity-dependencies").first();
    await expect(capacity).toBeVisible();
    await expect(capacity).toContainText("No liquidity or market-impact model exists");
    await expect(capacity).toContainText("G1 is OPEN");
    await expect(capacity).toContainText("No accepted definition exists");
    await expect(capacity).toContainText("The requirement stays");
  });

  test("says capacity is not capital, cash, buying power or a limit", async ({ page }) => {
    await page.goto(`/strategy/performance${OPERATOR}`);
    await ready(page);
    const capacity = page.getByTestId("capacity-dependencies").first();
    await expect(capacity).toContainText("not strategy capital");
    await expect(capacity).toContainText("not buying power");
  });
});

test.describe("the follow-up surfaces stay inside the boundary", () => {
  const ROUTES = ["/portfolio/performance", "/strategy/performance"] as const;

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

  test("reaches the new controls from the keyboard with a visible focus ring", async ({
    page,
  }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await ready(page);
    const button = page
      .getByTestId("lookback-selector")
      .getByRole("button", { name: "63 periods" });
    await button.focus();
    await expect(button).toBeFocused();
    const outline = await button.evaluate((element) =>
      window.getComputedStyle(element).getPropertyValue("outline-style"),
    );
    expect(outline === "none").toBe(false);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("rolling-lookback")).toContainText("63 daily periods");
  });

  test("exposes no control that would run, adjust or approve anything", async ({ page }) => {
    for (const route of ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await ready(page);
      for (const verb of [/^run$/i, /^approve$/i, /^apply$/i, /^retry$/i, /^promote$/i]) {
        await expect(page.getByRole("button", { name: verb })).toHaveCount(0);
      }
      await expect(page.locator("form")).toHaveCount(0);
    }
  });

  test("logs no console error and hydrates without a mismatch", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        errors.push(message.text());
      }
    });
    page.on("pageerror", (error) => errors.push(error.message));
    for (const route of ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await ready(page);
      await page.getByTestId("rolling-table-disclosure").first().isVisible();
    }
    expect(errors).toEqual([]);
  });

  test("issues no request to any external origin", async ({ page }) => {
    const external: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith("http://127.0.0.1") && !url.startsWith("http://localhost")) {
        external.push(url);
      }
    });
    for (const route of ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await ready(page);
    }
    expect(external).toEqual([]);
  });

  test("passes the automated accessibility scan on both screens", async ({ page }) => {
    for (const route of ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await ready(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(
        results.violations.map((violation) => `${route}: ${violation.id}`),
        JSON.stringify(results.violations.map((v) => ({ id: v.id, nodes: v.nodes.length }))),
      ).toEqual([]);
    }
  });
});
