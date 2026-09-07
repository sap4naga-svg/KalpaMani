import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * The C5 screens, in a browser.
 *
 * Every assertion below is about something a reader can see: a label, a state, a count, a
 * separation the specification requires two facts to keep. Nothing here asserts an internal
 * shape — that is the unit suite's job — and nothing here reaches a network.
 */

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo&period=3M&gran=DAILY&changes=auto";
const OPERATOR =
  "?mode=operator&env=RESEARCH&scenario=demo&period=ALL&gran=MONTHLY&changes=auto";
const PROJECT =
  "?mode=executive&env=RESEARCH&scenario=project&period=3M&gran=DAILY&changes=auto";

const C5_ROUTES = [
  "/portfolio/performance",
  "/portfolio/positions",
  "/portfolio/trades",
  "/strategy/performance",
  "/market/regime",
  "/risk",
  "/risk/short-side",
] as const;

async function waitForHydration(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("context-bar")).toBeVisible();
}

test.describe("the C5 screens render and stay honest", () => {
  test("labels every C5 route synthetic at page level in the demonstration scenario (U3)", async ({
    page,
  }) => {
    for (const route of C5_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForHydration(page);
      await expect(page.getByTestId("page-provenance-banner")).toContainText(
        "SYNTHETIC DEMONSTRATION DATA",
      );
      // U2: environment, source and freshness are present on every route, at all times.
      await expect(page.getByTestId("source-context")).toBeVisible();
      await expect(page.getByTestId("freshness-indicator")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    }
  });

  test("reports every C5 route unavailable in project scope, with its dependency named", async ({
    page,
  }) => {
    for (const route of C5_ROUTES) {
      await page.goto(`${route}${PROJECT}`);
      await waitForHydration(page);
      const bodies = page.getByTestId("unavailable-body");
      await expect(bodies.first()).toBeVisible();
      await expect(bodies.first()).toContainText("Waiting on:");
      await expect(bodies.first()).toContainText("PRODUCER_NOT_IMPLEMENTED");
    }
  });

  test("scrolls no page body sideways at this viewport (U14)", async ({ page }) => {
    for (const route of [...C5_ROUTES, "/portfolio/trades/demo-trade-cir-0003"]) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForHydration(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${route} must not scroll horizontally`).toBeLessThanOrEqual(1);
    }
  });

  test("reproduces a filtered view from the URL alone (U13)", async ({ page }) => {
    await page.goto(`/portfolio/trades${DEMO}&status=CLOSED&dir=SHORT&outcome=LOSER`);
    await waitForHydration(page);
    const chips = page.getByTestId("filter-chips");
    await expect(chips).toContainText("CLOSED");
    await expect(chips).toContainText("SHORT");
    await expect(chips).toContainText("LOSER");

    // Switching mode preserves the drill-down filters and does not reset the view (U15).
    await page.getByTestId("mode-switch").getByRole("radio", { name: "operator" }).click();
    await expect(page).toHaveURL(/status=CLOSED/);
    await expect(page.getByTestId("filter-chips")).toContainText("CLOSED");
  });
});

test.describe("positions and exposure", () => {
  test("keeps the two planned-risk quantities in separate columns", async ({ page }) => {
    await page.goto(`/portfolio/positions${DEMO}`);
    await waitForHydration(page);
    const table = page.getByTestId("positions-table");
    await expect(
      table.getByRole("columnheader", { name: /Initial planned risk/ }),
    ).toBeVisible();
    await expect(
      table.getByRole("columnheader", { name: /Current open planned risk/ }),
    ).toBeVisible();
    await expect(page.getByTestId("risk-separation-note").first()).toContainText(
      "A moving stop changes only the second",
    );
  });

  test("shows an unknown borrow as unknown and never as available", async ({ page }) => {
    /*
     * ASSERTED IN THE ROW DETAIL, which is present at every viewport.
     *
     * The borrow COLUMN drops on a narrow screen under the declared column priority, and the
     * fact must not drop with it: the row detail carries it at every width, which is what
     * makes dropping the column acceptable in the first place.
     */
    await page.goto(`/portfolio/positions${DEMO}&borrow=BORROW_STATE_UNKNOWN`);
    await waitForHydration(page);
    const rows = page.getByTestId("positions-table").locator("tbody tr[data-row-id]");
    await expect(rows).toHaveCount(1);
    await page.getByRole("button", { name: /Show details for/ }).first().click();
    const detail = page.getByTestId("position-borrow-detail");
    await expect(detail).toBeVisible();
    await expect(detail.locator('[data-borrow-detail*="UNKNOWN"]')).toBeVisible();
    await expect(detail).not.toContainText("Available from record");
    await expect(detail).toContainText("never inferred from price behaviour");
  });

  test("opens a position's detail from a keyboard and shows both risk records", async ({
    page,
  }) => {
    await page.goto(`/portfolio/positions${OPERATOR}`);
    await waitForHydration(page);
    const toggle = page.getByRole("button", { name: /Show details for/ }).first();
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("initial-planned-risk").first()).toBeVisible();
    await expect(page.getByTestId("open-planned-risk").first()).toBeVisible();
  });

  test("reconciles every exposure axis with the portfolio totals it is a view of", async ({
    page,
  }) => {
    await page.goto(`/portfolio/positions${DEMO}`);
    await waitForHydration(page);
    const totals = page.getByTestId("exposure-totals");
    await expect(totals).toBeVisible();
    const grossText = (await totals.textContent()) ?? "";

    const axes = page.getByRole("group", { name: "Grouping axis" }).getByRole("button");
    const count = await axes.count();
    expect(count).toBeGreaterThan(1);
    for (let index = 0; index < count; index += 1) {
      await axes.nth(index).click();
      await expect(page.getByTestId("exposure-table")).toBeVisible();
      // The totals panel is the same on every axis: it is one book seen several ways.
      await expect(page.getByTestId("exposure-totals")).toHaveText(grossText);
    }
  });

  test("reports a permitted limit with no policy reference rather than a number", async ({
    page,
  }) => {
    await page.goto(`/portfolio/positions${DEMO}`);
    await waitForHydration(page);
    const permitted = page.locator('[data-testid^="permitted-"]').first();
    await expect(permitted).toContainText("POLICY_REFERENCE_MISSING");
  });
});

test.describe("the trade ledger and one trade's story", () => {
  test("keeps trade status and data completeness as two separate facts", async ({ page }) => {
    await page.goto(`/portfolio/trades${OPERATOR}`);
    await waitForHydration(page);
    await expect(
      page.getByTestId("trades-table").getByRole("columnheader", { name: /Trade status/ }),
    ).toBeVisible();

    /*
     * The pair is asserted in the ROW DETAIL, which is present at every viewport. The
     * completeness COLUMN drops on a narrow screen; the fact does not drop with it.
     */
    await page.getByRole("button", { name: /Show details for/ }).first().click();
    const detail = page.getByTestId("trade-status-detail");
    await expect(detail).toBeVisible();
    await expect(detail.locator("[data-detail-trade-status]")).toBeVisible();
    await expect(detail.locator("[data-detail-completeness]")).toBeVisible();
    await expect(detail).toContainText("Neither is inferred from the other");
  });

  test("carries a trade that is complete in status and partial in completeness", async ({
    page,
  }) => {
    await page.goto(`/portfolio/trades${OPERATOR}&q=demo-trade-gen-0002`);
    await waitForHydration(page);
    const rows = page.getByTestId("trades-table").locator("tbody tr[data-row-id]");
    await expect(rows).toHaveCount(1);
    await page.getByRole("button", { name: /Show details for/ }).first().click();
    const detail = page.getByTestId("trade-status-detail");
    await expect(detail.locator('[data-detail-trade-status="CLOSED"]')).toBeVisible();
    await expect(detail.locator('[data-detail-completeness="PARTIAL"]')).toBeVisible();
  });

  test("shows a partially exited trade as one row that is not closed", async ({ page }) => {
    await page.goto(`/portfolio/trades${DEMO}&status=PARTIALLY_EXITED`);
    await waitForHydration(page);
    const rows = page.getByTestId("trades-table").locator("tbody tr[data-row-id]");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("Partially exited");
  });

  /*
   * NAMED RATHER THAN FILLED IN, ON A TRADE THAT GENUINELY HAS NOTHING.
   *
   * C5 asserted this on `demo-trade-cir-0003`, which had no execution evidence at the time.
   * C6 records that trade's orders, fills, protective-order events and reconciliation, so
   * those stages are no longer gaps ON IT — and continuing to assert their absence there
   * would assert that the interface still fails to carry facts it now carries.
   *
   * The property this test exists to pin is unchanged and is asserted where it still applies:
   * a trade whose evidence was never written NAMES each missing stage rather than inferring
   * it. Most of the book is in exactly that position.
   */
  test("opens a trade's detail and names every stage it does not carry", async ({ page }) => {
    await page.goto(`/portfolio/trades/demo-trade-gen-0001${OPERATOR}`);
    await waitForHydration(page);
    const gaps = page.getByTestId("trade-gaps");
    await expect(gaps).toBeVisible();
    for (const stage of [
      "Candidate and thesis",
      "Order and fill mechanics",
      "Broker reconciliation",
      "Performance attribution",
      "Risk engine decision",
    ]) {
      await expect(gaps).toContainText(stage);
    }
    // The four concepts stay apart: no order or fill mechanics are rendered here.
    await expect(page.getByTestId("absent-event-kinds")).toContainText("Order submitted");

    /*
     * THE NEGATIVE CONTROL: a trade whose evidence WAS written names fewer gaps.
     *
     * Without it, the loop above would pass on an interface that listed every stage as
     * missing on every trade — which is the opposite failure, and just as wrong.
     */
    await page.goto(`/portfolio/trades/demo-trade-cir-0003${OPERATOR}`);
    await waitForHydration(page);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("DEMO.CIR");
    const carried = page.getByTestId("trade-gaps");
    await expect(carried).toBeVisible();
    /*
     * It still names the stage nobody has built — the audit trail is Area 26's — so the table
     * is genuinely a gap list and not an empty one.
     */
    await expect(carried).toContainText("Immutable audit events");
    await expect(carried).not.toContainText("Order and fill mechanics");
    await expect(carried).not.toContainText("Broker reconciliation");
    /*
     * AND IT NO LONGER NAMES THE RISK DECISION, BECAUSE THIS TRADE HAS ONE.
     *
     * An earlier revision asserted `Risk engine decision` here, when the gap was declared on
     * every trade unconditionally — while `/risk` listed an approved outcome for these same
     * trades. The gap is now reported only where no decision was recorded, and the assertion
     * above at `demo-trade-gen-0001` still requires it there, so the pair distinguishes a
     * recorded decision from an absent one rather than accepting either.
     */
    await expect(carried).not.toContainText("Risk engine decision");
    await expect(page.getByTestId("trade-risk-decision")).toBeVisible();
  });

  /*
   * The pyramid, in a browser. An earlier revision rendered "100 shares at 63.88" for an
   * entry of 60 at 62.40, and printed the SUMMED risk of both stages under a heading that
   * says "Recorded at entry" — so this reads the screen rather than the payload.
   */
  test("separates the original entry from the add it never restates", async ({ page }) => {
    await page.goto(`/portfolio/trades/demo-trade-nvl-0002${OPERATOR}`);
    await waitForHydration(page);
    const identity = page.getByTestId("trade-identity");

    await expect(identity).toContainText("Shares at entry");
    await expect(identity).toContainText("Shares acquired");
    await expect(identity).toContainText("Current basis");
    /* The entry price the trade actually filled at, and the basis the add produced. */
    await expect(identity).toContainText("62.40");
    await expect(identity).toContainText("63.88");
    await expect(identity).toContainText("This trade added to its position.");

    /* The entry's own record: its own risk, at its own reference price. */
    const initial = page.getByTestId("initial-planned-risk").first();
    await expect(initial).toContainText("186.00");
    await expect(initial).toContainText("62.40");

    /* The add's own record, and the SUM that R was divided by, which is neither record. */
    const adds = page.getByTestId("add-planned-risk");
    await expect(adds).toBeVisible();
    await expect(adds).toContainText("Add 1");
    await expect(adds).toContainText("212.00");
    await expect(adds).toContainText("66.10");
    await expect(page.getByTestId("r-denominator")).toContainText("398.00");
    /* Both contributing policy versions are on screen. */
    await expect(page.getByTestId("trade-risk")).toContainText("0.0.0-demo");
    await expect(page.getByTestId("trade-risk")).toContainText("0.0.1-demo");
  });

  test("draws the price marks and carries the same values in a table (U10)", async ({
    page,
  }) => {
    await page.goto(`/portfolio/trades/demo-trade-nvl-0002${DEMO}`);
    await waitForHydration(page);
    const chart = page.getByTestId("trade-chart");
    await expect(chart).toBeVisible();
    await expect(chart).toContainText("Not OHLC");
    // The canvas actually renders in a browser.
    await expect(chart.locator('[data-drawn="true"]')).toBeVisible();
    await expect(chart.locator("canvas").first()).toBeVisible();

    await page.getByText(/Marks and recorded events as a table/).click();
    const alternative = page.getByRole("region", { name: /as a table/ });
    await expect(alternative).toBeVisible();
    // The pyramided trade records two events, and both appear in the alternative.
    await expect(alternative).toContainText("Entry recorded");
    await expect(alternative).toContainText("Pyramid add recorded");
  });

  test("reports an unknown trade identity as an absent record rather than as an error", async ({
    page,
  }) => {
    await page.goto(`/portfolio/trades/demo-trade-does-not-exist${DEMO}`);
    await waitForHydration(page);
    /* ADR-0030 R9: an identifier that names nothing is an ABSENCE, never an inapplicability. */
    await expect(page.getByTestId("unavailable-body").first()).toContainText(
      "REFERENT_NOT_FOUND",
    );
  });
});

test.describe("strategy, risk, short side and regime", () => {
  test("keeps two versions of one module apart", async ({ page }) => {
    await page.goto(`/strategy/performance${DEMO}`);
    await waitForHydration(page);
    const table = page.getByTestId("strategy-table");
    await expect(table.locator('[data-strategy-version="breakout-long-v3"]')).toBeVisible();
    await expect(table.locator('[data-strategy-version="breakout-long-v2"]')).toBeVisible();
    await expect(page.getByTestId("family-rollup").first()).toContainText(
      "No diversification or alpha claim is made here",
    );
  });

  test("reports a ratio below its declared minimum rather than a number", async ({ page }) => {
    await page.goto(`/strategy/performance${DEMO}`);
    await waitForHydration(page);
    await expect(
      page.getByTestId("strategy-table").getByText("Insufficient observations").first(),
    ).toBeVisible();
  });

  test("shows the governed research values as research parameters, badged as tracked", async ({
    page,
  }) => {
    await page.goto(`/risk${DEMO}`);
    await waitForHydration(page);
    const panel = page.getByTestId("research-parameters");
    await expect(panel).toContainText("research parameters, not permitted limits");
    await expect(panel.locator('[data-provenance="REPOSITORY_TRACKED"]')).toBeVisible();
    await expect(page.getByTestId("parameter-table")).toContainText("Strategy capital");
    // The synthetic panel on the same page keeps its own badge (§5).
    await expect(
      page.getByTestId("risk-snapshot").locator('[data-provenance="SYNTHETIC"]'),
    ).toBeVisible();
  });

  test("computes no headroom and offers no control on the risk dashboard", async ({ page }) => {
    await page.goto(`/risk${DEMO}`);
    await waitForHydration(page);
    await expect(page.getByText("No headroom is computed on this page.")).toBeVisible();
    await expect(page.locator("input[type=range]")).toHaveCount(0);
    await expect(page.locator("form")).toHaveCount(0);
  });

  test("never infers borrow from price", async ({ page }) => {
    await page.goto(`/risk/short-side${DEMO}`);
    await waitForHydration(page);
    await expect(page.getByTestId("borrow-inference-note")).toContainText(
      "Borrow availability is never inferred from price",
    );
    await expect(
      page.getByTestId("borrow-table").locator('[data-borrow-availability*="UNKNOWN"]'),
    ).toBeVisible();
  });

  test("declares the regime's information-set profile", async ({ page }) => {
    await page.goto(`/market/regime${DEMO}`);
    await waitForHydration(page);
    await expect(page.locator('[data-profile="FORWARD_SYSTEM"]')).toBeVisible();
    await expect(page.getByText(/PUBLIC_PIT is not reachable/)).toBeVisible();
    await expect(page.getByTestId("stress-history")).toBeVisible();
  });
});

test.describe("portfolio performance", () => {
  test("separates realized from unrealized and states the cash-flow rule", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await waitForHydration(page);
    const pnl = page.getByTestId("pnl-windows");
    await expect(
      pnl.getByRole("columnheader", { name: "Realized", exact: true }),
    ).toBeVisible();
    await expect(
      pnl.getByRole("columnheader", { name: "Unrealized", exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("performance-curves")).toContainText(
      "external cash flow",
    );
    await expect(page.getByTestId("performance-curves")).toContainText(
      "a deposit is not a profit",
    );
  });

  test("draws a monthly heat map only at monthly granularity", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await waitForHydration(page);
    await expect(page.getByTestId("heatmap-wrong-granularity")).toContainText(
      "not derived from it here",
    );

    await page
      .getByRole("group", { name: "Series granularity" })
      .getByRole("button", { name: "Monthly" })
      .click();
    await expect(page.getByTestId("return-heatmap")).toBeVisible();
    await expect(page).toHaveURL(/gran=MONTHLY/);
  });

  test("resolves no named benchmark and says why", async ({ page }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await waitForHydration(page);
    const benchmarks = page.getByTestId("benchmark-panel");
    await expect(benchmarks).toContainText("no market-data provider is selected");
    await expect(benchmarks.locator('[data-resolution="UNRESOLVABLE_V1"]').first()).toBeVisible();
  });

  test("reports a short window's ratio as insufficient rather than as a number", async ({
    page,
  }) => {
    await page.goto(`/portfolio/performance${DEMO}`);
    await waitForHydration(page);
    const trailing = page.getByTestId("trailing-windows");
    await expect(trailing.locator('tr[data-window="1M"]')).toContainText(
      "Insufficient observations",
    );
    await expect(trailing).toContainText("they are not independent samples");
  });
});

test.describe("accessibility and safety", () => {
  test("passes the automated accessibility checks on every C5 route", async ({ page }) => {
    for (const route of [...C5_ROUTES, "/portfolio/trades/demo-trade-cir-0003"]) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForHydration(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(
        results.violations.map((violation) => `${route}: ${violation.id}`),
        JSON.stringify(results.violations.map((v) => ({ id: v.id, nodes: v.nodes.length }))),
      ).toEqual([]);
    }
  });

  test("issues no request to any external origin", async ({ page }) => {
    const external: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith("http://127.0.0.1") && !url.startsWith("data:")) {
        external.push(url);
      }
    });
    for (const route of C5_ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForHydration(page);
    }
    expect(external).toEqual([]);
  });

  test("logs no console error and hydrates without a mismatch", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        errors.push(message.text());
      }
    });
    page.on("pageerror", (error) => errors.push(error.message));
    for (const route of [...C5_ROUTES, "/portfolio/trades/demo-trade-arb-0001"]) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForHydration(page);
    }
    expect(errors).toEqual([]);
  });
});
