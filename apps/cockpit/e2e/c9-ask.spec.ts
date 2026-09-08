import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Ask KalpaMani and the completed command palette, in a browser.
 *
 * Every assertion is about something a reader can see: what the answer says it answered, a
 * refusal that renders no control, a citation that names a record, a scope that survives a
 * navigation. Nothing here asserts an internal shape — that is the unit suite's job — and
 * nothing here reaches a network.
 */

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo&period=3M&gran=DAILY&changes=auto";
const OPERATOR =
  "?mode=operator&env=RESEARCH&scenario=demo&period=3M&gran=DAILY&changes=auto";
const PROJECT =
  "?mode=executive&env=RESEARCH&scenario=project&period=3M&gran=DAILY&changes=auto";
const PAPER = "?mode=executive&env=PAPER&scenario=demo&period=3M&gran=DAILY&changes=auto";

const TRADE = "demo-trade-arb-0001";

async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("context-bar")).toBeVisible();
}

/** Opens the global Ask surface from the header control it is reached by. */
async function openAsk(page: Page, query = DEMO, route = "/"): Promise<void> {
  await page.goto(`${route}${query}`);
  await waitForHydration(page);
  await page.getByTestId("ask-launcher").click();
  await expect(page.getByTestId("ask-panel")).toBeVisible();
}

/** Asks one question through the real input, and waits for the read to resolve. */
async function ask(page: Page, question: string): Promise<void> {
  await page.getByTestId("ask-input").fill(question);
  await page.getByTestId("ask-submit").click();
}

/** The answer block, once its read has resolved into a rendered answer. */
async function waitForAnswer(page: Page): Promise<void> {
  await expect(page.getByTestId("ask-answer")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("ask-loading")).toHaveCount(0);
}

/* =========================================================== the surface is global */

test.describe("Ask is a global surface", () => {
  test("is reachable from every kind of route", async ({ page }) => {
    for (const route of ["/", "/portfolio/trades", "/system/alerts", "/research/runs"]) {
      await openAsk(page, DEMO, route);
      await expect(page.getByTestId("ask-panel")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByTestId("ask-panel")).toHaveCount(0);
    }
  });

  test("returns focus to the control that opened it", async ({ page }) => {
    await openAsk(page);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("ask-panel")).toHaveCount(0);
    await expect(page.getByTestId("ask-launcher")).toBeFocused();
  });

  test("is operable from the keyboard alone", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    await page.getByTestId("ask-launcher").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("ask-panel")).toBeVisible();
    /* The input is reachable, and a question can be asked without a pointer. */
    await page.getByTestId("ask-input").focus();
    await page.keyboard.type("What needs attention?");
    await page.keyboard.press("Enter");
    await waitForAnswer(page);
  });
});

/* ================================================================ grounded answers */

test.describe("an answer says what it answered, and cites what it read", () => {
  test("answers a portfolio question and states the interpreted window", async ({ page }) => {
    await openAsk(page);
    await ask(page, "How did the portfolio perform over 6 months?");
    await waitForAnswer(page);
    await expect(page.getByTestId("ask-question-class")).toContainText(/portfolio return/i);
    await expect(page.getByTestId("ask-interpreted-window")).toContainText(/6m/i);
    await expect(page.getByTestId("ask-interpreted-environment")).toContainText("RESEARCH");
    await expect(page.getByTestId("ask-citation").first()).toBeVisible();
  });

  test("answers a trade question about the trade that was named", async ({ page }) => {
    await openAsk(page);
    await ask(page, `What happened to trade ${TRADE}?`);
    await waitForAnswer(page);
    await expect(page.getByTestId("ask-interpreted-subject")).toContainText(TRADE);
    const subject = page.getByTestId("ask-subject-ref");
    await expect(subject).toBeVisible();
    await expect(subject.getByTestId("reference-target-link")).toHaveAttribute(
      "href",
      new RegExp(`/portfolio/trades/${TRADE}`),
    );
  });

  test("reports the same figure the portfolio screen reports", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await expect(page.getByTestId("context-bar")).toBeVisible();
    await expect(page.getByTestId("skeleton")).toHaveCount(0, { timeout: 20_000 });
    const onScreen = await page
      .locator('[data-metric="return.time_weighted"]')
      .first()
      .textContent();
    await page.getByTestId("ask-launcher").click();
    await ask(page, "How did the portfolio perform over 3 months?");
    await waitForAnswer(page);
    const inAnswer = await page.getByTestId("ask-answer-value").textContent();
    /*
     * THE SAME NUMBER, because the answer carries the read model's OWN `MetricValue`.
     *
     * The screen's element carries the metric's denominator beside the figure and the answer
     * does not, so the screen's text is asserted to CONTAIN the answer's rather than to equal
     * it -- the figure is what must agree, and it does.
     */
    expect((onScreen ?? "").replace(/\s+/g, "")).toContain(
      (inAnswer ?? "").replace(/\s+/g, ""),
    );
  });

  test("opens the area an answer was drawn from, carrying the scope", async ({ page }) => {
    await openAsk(page);
    await ask(page, "How many alerts are open?");
    await waitForAnswer(page);
    await page.getByTestId("ask-source-area-link").first().click();
    await expect(page).toHaveURL(/\/system\/alerts/);
    await expect(page).toHaveURL(/scenario=demo/);
    await expect(page).toHaveURL(/env=RESEARCH/);
  });
});

/* ================================================================ honest non-answers */

test.describe("what Ask will not do, it says plainly", () => {
  test("refuses an action-shaped request and renders no control", async ({ page }) => {
    await openAsk(page);
    await ask(page, "buy 100 shares of the top ranked candidate");
    const refused = page.getByTestId("ask-action-refused");
    await expect(refused).toBeVisible();
    await expect(refused).toContainText(/cannot place, change or cancel anything/i);
    await expect(refused.getByRole("button")).toHaveCount(0);
    await expect(page.getByTestId("ask-answer")).toHaveCount(0);
  });

  test("refers a qualification question to the governance area", async ({ page }) => {
    await openAsk(page);
    await ask(page, "what is the qualification gate status?");
    await expect(page.getByTestId("ask-referred")).toBeVisible();
    await page.getByTestId("ask-referral-link").click();
    await expect(page).toHaveURL(/\/governance\/qualification/);
  });

  test("asks which period rather than choosing one", async ({ page }) => {
    await openAsk(page);
    await ask(page, "how did the portfolio perform?");
    await expect(page.getByTestId("ask-needs-window")).toBeVisible();
    await expect(page.getByTestId("ask-answer")).toHaveCount(0);
    await page.getByTestId("ask-window-1Y").click();
    await waitForAnswer(page);
    await expect(page.getByTestId("ask-interpreted-window")).toContainText(/1y/i);
  });

  test("asks which subject rather than choosing one, and offers the indexed records", async ({
    page,
  }) => {
    await openAsk(page);
    await ask(page, "what happened to the trade?");
    await expect(page.getByTestId("ask-needs-subject")).toBeVisible();
    const picker = page.getByTestId("ask-subject-picker");
    await expect(picker).toBeVisible({ timeout: 20_000 });
    await picker.getByRole("button").first().click();
    await waitForAnswer(page);
    await expect(page.getByTestId("ask-interpreted-subject")).toBeVisible();
  });

  test("states an unsupported question and offers what it does answer", async ({ page }) => {
    await openAsk(page);
    await ask(page, "what will the market do tomorrow");
    await expect(page.getByTestId("ask-unsupported")).toBeVisible();
    await page.getByTestId("ask-suggestion-ATTENTION_SUMMARY").click();
    await waitForAnswer(page);
    await expect(page.getByTestId("ask-question-class")).toContainText(/attention/i);
  });

  test("reports an unavailable producer rather than an answer", async ({ page }) => {
    for (const query of [PROJECT, PAPER]) {
      await openAsk(page, query);
      await ask(page, "How many alerts are open?");
      await expect(page.getByTestId("ask-unavailable")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId("ask-answer")).toHaveCount(0);
    }
  });
});

/* ============================================================ no answer outlives its question */

test.describe("an old answer never stands as the answer to a new request", () => {
  test("clears the answer when the next question is refused", async ({ page }) => {
    await openAsk(page);
    await ask(page, "How many alerts are open?");
    await waitForAnswer(page);
    await ask(page, "cancel every working order");
    await expect(page.getByTestId("ask-action-refused")).toBeVisible();
    await expect(page.getByTestId("ask-answer")).toHaveCount(0);
  });

  test("flags an edited question rather than letting the old answer read as current", async ({
    page,
  }) => {
    await openAsk(page);
    await ask(page, "How many alerts are open?");
    await waitForAnswer(page);
    await page.getByTestId("ask-input").fill("How did the portfolio perform over 1 year?");
    await expect(page.getByTestId("ask-edited-hint")).toBeVisible();
    await expect(page.getByTestId("ask-question-class")).toContainText(/alerts/i);
  });

  test("re-reads under a new scope rather than showing the previous scope's answer", async ({
    page,
  }) => {
    await openAsk(page);
    await ask(page, "How many alerts are open?");
    await waitForAnswer(page);
    await page.keyboard.press("Escape");
    await page.getByTestId("scenario-switch").locator('[data-value="project"]').click();
    await page.getByTestId("ask-launcher").click();
    await ask(page, "How many alerts are open?");
    await expect(page.getByTestId("ask-unavailable")).toBeVisible({ timeout: 20_000 });
  });
});

/* ============================================================ the palette searches records */

test.describe("the command palette reaches records, and never a verb", () => {
  test("finds a record and opens it with the scope carried", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByTestId("command-palette")).toBeVisible();
    await page.getByPlaceholder(/search areas/i).fill(TRADE);
    const row = page.getByTestId(`palette-entity-${TRADE}`);
    await expect(row).toBeVisible({ timeout: 20_000 });
    await row.click();
    await expect(page).toHaveURL(new RegExp(`/portfolio/trades/${TRADE}`));
    await expect(page).toHaveURL(/scenario=demo/);
  });

  test("groups records by environment and never presents a combined list", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByPlaceholder(/search areas/i).fill("demo-trade");
    await expect(page.getByTestId("palette-entities-RESEARCH")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByTestId("palette-entities-PAPER")).toHaveCount(0);
    await expect(page.getByTestId("palette-entities-LIVE")).toHaveCount(0);
  });

  test("exposes no state-changing command anywhere in the palette", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    await page.getByRole("button", { name: "Search" }).click();
    const palette = page.getByTestId("command-palette");
    await expect(palette).toBeVisible();
    const text = ((await palette.textContent()) ?? "").toLowerCase();
    for (const verb of [
      "place order",
      "submit",
      "cancel",
      "promote",
      "approve",
      "authorize",
      "acknowledge",
      "retry",
      "deploy",
      "kill",
    ]) {
      expect(text, `palette must expose no "${verb}"`).not.toContain(verb);
    }
  });
});

/* ============================================================== the V1 safety boundary */

test.describe("Ask stays inside the V1 safety boundary", () => {
  test("opens no connection beyond its own assets", async ({ page }) => {
    const offOrigin: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith("http://127.0.0.1:") && !url.startsWith("data:")) {
        offOrigin.push(url);
      }
    });
    await openAsk(page, OPERATOR);
    await ask(page, `What happened to trade ${TRADE}?`);
    await waitForAnswer(page);
    await ask(page, "Is there a data quality problem?");
    await waitForAnswer(page);
    expect(offOrigin).toEqual([]);
  });

  test("discloses no private identifier in an answer (U20)", async ({ page }) => {
    await openAsk(page, OPERATOR);
    for (const question of [
      `What happened to trade ${TRADE}?`,
      "Is there a data quality problem?",
      "Did the last reconciliation match?",
    ]) {
      await ask(page, question);
      await waitForAnswer(page);
      const text = ((await page.getByTestId("ask-panel").textContent()) ?? "").toLowerCase();
      for (const forbidden of [
        "akia",
        "arn:aws",
        "amazonaws.com",
        "s3://",
        "secretsmanager",
        "ibkr",
        "sharadar",
        "nasdaqdatalink",
      ]) {
        expect(text, `an answer must not disclose ${forbidden}`).not.toContain(forbidden);
      }
      expect(/\b\d{12}\b/.test(text)).toBe(false);
    }
  });

  test("keeps the panel free of horizontal scroll at this viewport (U14)", async ({ page }) => {
    await openAsk(page, OPERATOR);
    await ask(page, `What happened to trade ${TRADE}?`);
    await waitForAnswer(page);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("logs no console error while answering", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("pageerror", (error) => errors.push(error.message));
    await openAsk(page, OPERATOR);
    await ask(page, "What needs attention?");
    await waitForAnswer(page);
    expect(errors).toEqual([]);
  });

  test("has no detectable serious or critical violation on the Ask surface", async ({
    page,
  }) => {
    await openAsk(page, OPERATOR);
    await ask(page, `What happened to trade ${TRADE}?`);
    await waitForAnswer(page);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const serious = results.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );
    expect(serious.map((violation) => violation.id)).toEqual([]);
  });
});
