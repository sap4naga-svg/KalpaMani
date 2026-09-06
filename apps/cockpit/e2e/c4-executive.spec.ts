import { AxeBuilder } from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/**
 * The C4 surfaces, driven in a real browser.
 *
 * These exercise what a unit test cannot reach: the layout at a reference viewport, keyboard
 * reachability of the chart's alternative, the URL round-trip of a period and a comparison
 * variant, and the absence of any control that could act.
 */

const DEMO = "?scenario=demo&mode=executive";

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

/**
 * U1 lives in `u1-first-viewport.spec.ts`.
 *
 * It is stated at ONE reference width, so it is REGISTERED at one width by the project's
 * `testIgnore` rather than skipped at the other two — a skipped criterion reports as
 * unchecked at viewports it was never in scope for. What remains here is the drill-down
 * link check, which is a requirement at every viewport.
 */
test.describe("the ten-second answers", () => {
  test("links each answer to the area that owns it", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    const links = page.getByRole("link", { name: /Open the area that owns this/ });
    // Every answer tile that names an owning area carries one.
    expect(await links.count()).toBeGreaterThanOrEqual(5);
  });
});

test.describe("the performance overview", () => {
  test("switches view and period, and keeps the period in the URL (U13)", async ({ page }) => {
    const problems = guardConsole(page);
    await page.goto(`/${DEMO}&period=3M`);
    await waitForHydration(page);

    const overview = page.getByTestId("performance-overview");
    await expect(overview).toBeVisible();
    await expect(page.getByTestId("chart-equity")).toBeVisible();

    // The view toggle swaps which series is drawn, without a navigation.
    await overview.getByRole("button", { name: "Drawdown" }).click();
    await expect(page.getByTestId("chart-drawdown")).toBeVisible();
    await overview.getByRole("button", { name: "Return" }).click();
    await expect(page.getByTestId("chart-return")).toBeVisible();

    // A period IS a request parameter, so it goes into the URL and survives a reload.
    await overview.getByRole("button", { name: "1Y", exact: true }).click();
    await expect(page).toHaveURL(/period=1Y/);
    await page.reload();
    await waitForHydration(page);
    await expect(
      page.getByTestId("performance-overview").getByRole("button", { name: "1Y", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");

    expect(problems).toEqual([]);
  });

  test("states its window, calendar, timezone, costs and coverage (U19)", async ({ page }) => {
    await page.goto(`/${DEMO}&period=3M`);
    await waitForHydration(page);
    const overview = page.getByTestId("performance-overview");
    for (const basis of ["Window", "Calendar", "Timezone", "Costs", "Sessions"]) {
      await expect(overview.getByText(basis, { exact: true })).toBeVisible();
    }
    await expect(overview.getByText("63 of 63")).toBeVisible();
  });

  test("reports a gapped extent as PARTIAL rather than drawing through it", async ({ page }) => {
    await page.goto(`/${DEMO}&period=ALL`);
    await waitForHydration(page);
    const partial = page.getByTestId("series-partial");
    await expect(partial).toBeVisible();
    await expect(partial).toContainText("carry no observation");
    await expect(partial).toContainText("nothing is interpolated");
  });

  test("offers a keyboard-reachable, readable table alternative (U10)", async ({ page }) => {
    await page.goto(`/${DEMO}&period=1M`);
    await waitForHydration(page);
    const disclosure = page.getByTestId("series-table-disclosure");
    await expect(disclosure).toBeVisible();

    // Reachable and operable by keyboard alone.
    await disclosure.locator("summary").focus();
    await expect(disclosure.locator("summary")).toBeFocused();
    await page.keyboard.press("Enter");

    const table = disclosure.getByRole("table");
    await expect(table).toBeVisible();
    // The SAME information: one row per session, with its unit in the header.
    await expect(table.getByRole("row")).toHaveCount(22); // 21 sessions plus the header
    await expect(table.getByRole("columnheader", { name: /Equity \(USD\)/ })).toBeVisible();
  });

  test("shows no curve at all in project scope, and says why", async ({ page }) => {
    await page.goto("/?scenario=project&mode=executive");
    await waitForHydration(page);
    const overview = page.getByTestId("performance-overview");
    await expect(overview.getByTestId("unavailable-body")).toBeVisible();
    await expect(overview).toContainText("No equity history exists");
    // Nothing is drawn.
    await expect(page.getByTestId("chart-equity")).toHaveCount(0);
  });
});

test.describe("attention", () => {
  test("ranks, deduplicates and reports what it withheld", async ({ page }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);

    const items = page.getByTestId("attention-item");
    await expect(items).toHaveCount(4);
    // Ranked: the HIGH item is first.
    await expect(items.first()).toHaveAttribute("data-severity", "HIGH");
    await expect(page.getByTestId("attention-deduplicated")).toContainText("1 folded");
    await expect(page.getByTestId("attention-withheld")).toContainText("1 withheld");
  });

  test("filters by severity and by evidence kind, and says what the filter hid", async ({
    page,
  }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);

    await page.getByTestId("attention-filters").getByRole("button", { name: "HIGH" }).click();
    await expect(page.getByTestId("attention-item")).toHaveCount(1);
    // The unfiltered total stays visible, so a subset is never read as the whole.
    await expect(page.getByTestId("attention-panel")).toContainText("4 items");

    // Filtering to nothing states how many are hidden rather than showing a blank panel.
    await page.getByTestId("attention-filters").getByRole("button", { name: "HIGH" }).click();
    await page.getByTestId("attention-filters").getByRole("button", { name: "LOW" }).click();
    await page
      .getByTestId("attention-filters")
      .getByRole("button", { name: "Health transition" })
      .click();
    await expect(page.getByTestId("attention-panel")).toContainText("hidden by them");
  });

  test("opens an evidence drill-down with its resolution and classification", async ({
    page,
  }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);

    const first = page.getByTestId("attention-item").first();
    await first.getByRole("group").or(first.locator("summary")).first().click();
    const reference = first.getByTestId("evidence-reference").first();
    await expect(reference).toBeVisible();
    await expect(reference).toContainText("UNRESOLVABLE_V1");
    await expect(reference).toContainText("PUBLIC_SAFE");
  });

  test("shows the same count on the landing page as the list it links to", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    const summary = page.getByTestId("answer-attention");
    await expect(summary).toContainText("4");

    await page.getByRole("link", { name: "All attention items →" }).click();
    await waitForHydration(page);
    await expect(page.getByTestId("attention-item")).toHaveCount(4);
  });

  test("offers no control that could act on an item (U9, U16)", async ({ page }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);

    for (const verb of ["Acknowledge", "Dismiss", "Resolve", "Snooze", "Assign", "Suppress"]) {
      await expect(page.getByRole("button", { name: verb, exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: verb, exact: true })).toHaveCount(0);
    }
    // Every button on the page is a filter, and none of them submits anything.
    for (const button of await page.getByRole("button").all()) {
      await expect(button).not.toHaveAttribute("type", "submit");
    }
    await expect(page.locator("form")).toHaveCount(0);
  });
});

test.describe("what changed", () => {
  const cases = [
    {
      variant: "valid",
      expect: async (page: Page) => {
        await expect(page.getByTestId("what-changed-item")).toHaveCount(3);
        await expect(page.getByTestId("what-changed-panel")).toContainText("baseline as-of");
      },
    },
    {
      variant: "none",
      expect: async (page: Page) => {
        await expect(page.getByTestId("what-changed-item")).toHaveCount(0);
        // A completed comparison that found nothing is NOT a missing baseline.
        await expect(page.getByTestId("what-changed-panel")).toContainText("nothing changed");
        await expect(page.getByTestId("what-changed-panel")).toContainText("Empty (verified)");
      },
    },
    {
      variant: "no-baseline",
      expect: async (page: Page) => {
        await expect(page.getByTestId("what-changed-item")).toHaveCount(0);
        const panel = page.getByTestId("what-changed-panel");
        await expect(panel.getByTestId("unavailable-body")).toBeVisible();
        await expect(panel).toContainText("fabricated change");
        await expect(panel).toContainText("absent");
      },
    },
    {
      variant: "degraded",
      expect: async (page: Page) => {
        const items = page.getByTestId("what-changed-item");
        await expect(items).toHaveCount(2);
        /*
         * U17: EVERY ENTRY REPORTS ITS ENDPOINT STATES INSTEAD OF A DELTA. The earlier
         * assertion here accepted a row that drew `before -> after` as long as it carried a
         * qualifying badge, and the badge it carried was the AFTER endpoint's -- so a stale
         * baseline reported as AVAILABLE. Both endpoints now answer for themselves, and no
         * materiality is asserted over a comparison that is not sound.
         */
        for (const item of await items.all()) {
          await expect(item).toHaveAttribute("data-comparison", "UNAVAILABLE");
          await expect(item.getByTestId("change-delta")).toHaveCount(0);
          await expect(item.getByTestId("change-materiality")).toHaveCount(0);
          await expect(item.getByTestId("endpoint-baseline")).toBeVisible();
          await expect(item.getByTestId("endpoint-comparison")).toBeVisible();
          await expect(item).toContainText("NOT COMPARABLE");
        }
      },
    },
  ] as const;

  for (const scenario of cases) {
    test(`renders the ${scenario.variant} comparison deterministically`, async ({ page }) => {
      await page.goto(`/?scenario=demo&mode=executive&changes=${scenario.variant}`);
      await waitForHydration(page);
      await scenario.expect(page);
    });
  }

  test("carries the comparison variant in the URL, so a link reproduces it", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    await page.getByTestId("change-variant-selector").getByRole("link", { name: "Missing baseline" }).click();
    await expect(page).toHaveURL(/changes=no-baseline/);
    await waitForHydration(page);
    await expect(page.getByTestId("what-changed-panel")).toContainText("fabricated change");
  });
});

test.describe("qualification governance", () => {
  test("keeps Run B's date and its authorization as two separate facts", async ({ page }) => {
    await page.goto("/governance/qualification?scenario=project&mode=executive");
    await waitForHydration(page);

    const runB = page.locator('[data-testid="run-authorization"][data-run="RUN_B"]');
    await expect(runB).toBeVisible();
    // The date is displayed...
    await expect(runB).toContainText("2026-09-12");
    await expect(runB).toContainText("UTC calendar date");
    await expect(runB).toContainText("8 calendar days");
    // ...and the authorization is NOT derived from it, whatever the date says.
    await expect(runB).toContainText("NOT_AUTHORIZED");
    await expect(runB).toContainText("A separate written decision");
    await expect(runB).toContainText("cannot be started from here");
    // The standing is a statement about a DATE, and never about permission.
    const standing = await runB.getAttribute("data-date-standing");
    expect(["NOT_REACHED", "REACHED"]).toContain(standing);
    await expect(runB).toContainText("Earliest target date");
    await expect(runB).not.toContainText("Ready");
    await expect(runB).not.toContainText("Eligible to run");
  });

  test("reads every gate independently and renders P1-P9 unevaluated", async ({ page }) => {
    await page.goto("/governance/qualification?scenario=project&mode=executive");
    await waitForHydration(page);
    await expect(page.getByTestId("decision-gate")).toHaveCount(7);
    await expect(page.locator('[data-gate="G3"]')).toContainText("CLOSED");
    await expect(page.locator('[data-gate="G3"]')).toContainText(
      "Sharadar personal use licence only",
    );
    await expect(page.locator('[data-gate="G1"]')).toContainText("OPEN");
    for (const test of ["P1", "P5", "P9"]) {
      await expect(page.getByText(test, { exact: true })).toBeVisible();
    }
    await expect(page.getByText("Data correctness NOT ESTABLISHED")).toBeVisible();
  });

  test("states the next required governance event and the chain in front of it", async ({
    page,
  }) => {
    await page.goto("/governance/qualification?scenario=project&mode=executive");
    await waitForHydration(page);
    const next = page.getByTestId("next-required-event");
    await expect(next).toContainText("Run B written authorization");
    await expect(next).toContainText("Owner");
    await expect(next).toContainText("human decision recorded elsewhere");
    await expect(page.getByTestId("blocker")).toHaveCount(5);
    // A chain of recorded states, never a score.
    await expect(page.getByTestId("blockers")).toContainText("Not a score");
  });

  test("separates the source as-of from the day the snapshot was transcribed", async ({
    page,
  }) => {
    await page.goto("/governance/qualification?scenario=project&mode=operator");
    await waitForHydration(page);
    const provenance = page.getByTestId("snapshot-provenance");
    await expect(provenance).toContainText("source commit");
    await expect(provenance).toContainText("source as-of");
    await expect(provenance).toContainText("transcribed on");
    await expect(provenance).toContainText("74790b82b9939e3a8f21e4ed71425717318288ad");
  });

  test("exposes no control that would run a governed operation", async ({ page }) => {
    for (const route of [
      "/governance/qualification?scenario=project",
      "/governance/maturity?scenario=project",
    ]) {
      await page.goto(route);
      await waitForHydration(page);
      for (const verb of [
        "Run",
        "Authorize",
        "Approve",
        "Start",
        "Execute",
        "Promote",
        "Advance",
        "Retry",
      ]) {
        await expect(
          page.getByRole("button", { name: new RegExp(`^${verb}\\b`, "i") }),
        ).toHaveCount(0);
      }
      await expect(page.locator("form")).toHaveCount(0);
      await expect(page.locator("input")).toHaveCount(0);
    }
  });
});

test.describe("environment and maturity", () => {
  test("maps every stage to its environment and shows what has been reached", async ({
    page,
  }) => {
    await page.goto("/governance/maturity?scenario=project&mode=executive");
    await waitForHydration(page);
    await expect(page.getByTestId("maturity-stage")).toHaveCount(5);

    const shadow = page.locator('[data-stage="SHADOW"]');
    await expect(shadow).toContainText("RESEARCH");
    // Shadow shows NO order authority.
    await expect(shadow).toContainText("No orders");

    const paper = page.locator('[data-stage="AUTOMATED_PAPER"]');
    await expect(paper).toContainText("PAPER");
    await expect(paper).toContainText("Produces orders");
    await expect(paper).toContainText("Not yet available");

    await expect(page.locator('[data-stage="RESEARCH"]')).toContainText("Reached");
  });

  test("advances no maturity when the environment selector changes", async ({ page }) => {
    await page.goto("/governance/maturity?scenario=project&env=LIVE");
    await waitForHydration(page);
    // Selecting Live changes the VIEWING SCOPE and nothing else.
    await expect(page.locator('[data-stage="SCALED_LIVE"]')).toContainText("Not yet available");
    await expect(page.locator('[data-stage="RESEARCH"]')).toContainText("Reached");
    /*
     * Under an unpopulated environment there is no governance record to read, so the page
     * shows the STATE rather than a hard-coded constant dressed as a tracked fact.
     */
    await expect(
      page.getByTestId("live-trading").locator('[data-availability="NOT_IMPLEMENTED"]'),
    ).toBeVisible();
  });
});

test.describe("the C4 surfaces stay within the boundary", () => {
  test("has no detectable serious or critical accessibility violation", async ({ page }) => {
    for (const route of [
      `/${DEMO}`,
      `/attention${DEMO}`,
      "/governance/maturity?scenario=project",
      "/?scenario=demo&mode=operator&period=ALL",
    ]) {
      await page.goto(route);
      await waitForHydration(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const serious = results.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? ""),
      );
      expect(serious, `${route}: ${serious.map((v) => v.id).join(", ")}`).toEqual([]);
    }
  });

  test("opens no network connection beyond its own assets", async ({ page }) => {
    const external: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith("http://127.0.0.1:") && !url.startsWith("data:")) {
        external.push(url);
      }
    });
    for (const route of [`/${DEMO}&period=ALL`, `/attention${DEMO}`, "/governance/maturity"]) {
      await page.goto(route);
      await waitForHydration(page);
    }
    expect(external).toEqual([]);
  });

  test("scrolls no page body sideways at any reference viewport (U14)", async ({ page }) => {
    for (const route of [
      `/${DEMO}&period=ALL`,
      `/attention${DEMO}`,
      "/governance/qualification?scenario=project&mode=operator",
      "/governance/maturity?scenario=project",
    ]) {
      await page.goto(route);
      await waitForHydration(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${route} must not scroll horizontally`).toBeLessThanOrEqual(1);
    }
  });

  test("isolates a degraded widget and reports the page PARTIAL (U6)", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    // The permitted-risk tile is unavailable while the rest of the page renders values.
    await expect(page.getByTestId("page-state")).toBeVisible();
    await expect(page.getByTestId("tile-risk.permitted").getByTestId("unavailable-body")).toBeVisible();
    /*
     * The long exposure of the demonstration book, which C5 rebuilt from a coherent ledger:
     * the overview, the position table and the exposure aggregates are now three projections
     * of one set of positions rather than three hand-written numbers.
     */
    await expect(page.getByTestId("tile-exposure")).toContainText("17,999.00");
    await expect(page.getByTestId("performance-overview")).toBeVisible();
  });
});
