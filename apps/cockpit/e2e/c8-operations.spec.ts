import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * The six C8 screens, in a browser.
 *
 * Every assertion is about something a reader can see: a label, a state, a separation the
 * specification requires two facts to keep, a control that must not exist. Nothing here
 * asserts an internal shape — that is the unit suite's job — and nothing here reaches a
 * network.
 */

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo&period=3M&gran=DAILY&changes=auto";
const OPERATOR =
  "?mode=operator&env=RESEARCH&scenario=demo&period=ALL&gran=MONTHLY&changes=auto";
const PROJECT =
  "?mode=executive&env=RESEARCH&scenario=project&period=3M&gran=DAILY&changes=auto";
const PAPER = "?mode=executive&env=PAPER&scenario=demo&period=3M&gran=DAILY&changes=auto";

const C8_ROUTES = [
  "/execution/quality",
  "/execution/reconciliation",
  "/system/data-quality",
  "/system/operations",
  "/governance/audit",
  "/system/alerts",
] as const;

async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("context-bar")).toBeVisible();
}

/**
 * Hydration, and then every panel's read resolved.
 *
 * `ReadModelPanel` renders a shape-only skeleton while its query is in flight, so a content
 * assertion made immediately after hydration races the read rather than testing it.
 */
async function waitForPanels(page: Page): Promise<void> {
  await expect(page.getByTestId("context-bar")).toBeVisible();
  await expect(page.getByTestId("skeleton")).toHaveCount(0, { timeout: 20_000 });
}

/**
 * Opens every disclosure on the page, so a detail assertion sees rendered content.
 *
 * Disclosures NEST — a subject card holds a details element whose content holds another — so
 * one pass over the summaries present at the start would try to click one that is still
 * hidden inside a closed parent. This opens what is currently openable and repeats until a
 * pass opens nothing, and it never clicks an ALREADY-OPEN summary, which would close it.
 */
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

/* ================================================================= scoping and states */

test.describe("every C8 route is honest about what it is showing", () => {
  test("labels every C8 route synthetic at page level in the demonstration scenario (U3)", async ({
    page,
  }) => {
    for (const route of C8_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForHydration(page);
      await expect(page.getByTestId("page-provenance-banner")).toContainText(
        "SYNTHETIC DEMONSTRATION DATA",
      );
      await expect(page.getByTestId("source-context")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    }
  });

  test("reports every C8 route unavailable in project scope, with its dependency named", async ({
    page,
  }) => {
    for (const route of C8_ROUTES) {
      await page.goto(`${route}${PROJECT}`);
      await waitForPanels(page);
      const bodies = page.getByTestId("unavailable-body");
      await expect(bodies.first()).toBeVisible();
      await expect(bodies.first()).toContainText("The producing subsystem does not exist");
      await expect(bodies.first()).toContainText("PRODUCER_NOT_IMPLEMENTED");
      await expect(bodies.first()).toContainText("Waiting on:");
    }
  });

  test("shows an absence rather than the same record under a Paper badge", async ({ page }) => {
    await page.goto(`/execution/quality${PAPER}`);
    await waitForPanels(page);
    await expect(page.getByTestId("unavailable-body").first()).toBeVisible();
    await expect(page.getByTestId("execution-table")).toHaveCount(0);
  });

  test("states on every C8 route that it has no control and drives nothing", async ({ page }) => {
    for (const route of C8_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForPanels(page);
      const notice = page.getByTestId("read-only-notice");
      await expect(notice).toBeVisible();
      await expect(notice).toContainText("no such control exists anywhere in this application");
      await expect(notice).toContainText("no order has been placed");
    }
  });
});

/* ============================================================ Area 9 — execution quality */

test.describe("execution quality shows its whole definition, or no number", () => {
  test("names the reference price, its side convention and its clock", async ({ page }) => {
    await page.goto(`/execution/quality${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("reference-name")).toBeVisible();
    await expect(page.getByTestId("side-convention")).toBeVisible();
    await expect(page.getByTestId("clock-source")).toBeVisible();
    await expect(page.getByTestId("execution-basis")).toContainText(
      "Positive is adverse cost",
    );
  });

  test("reports the aggregate as insufficient rather than averaging a small sample", async ({
    page,
  }) => {
    await page.goto(`/execution/quality${DEMO}`);
    await waitForPanels(page);
    const tile = page.getByTestId("tile-slippage.aggregate");
    await expect(tile).toBeVisible();
    await expect(tile).toContainText("Insufficient observations");
    await expect(tile).toContainText("BELOW_MINIMUM_OBSERVATIONS");
    /* The population and the declared minimum are both on the screen, beside it. */
    await expect(page.getByTestId("aggregate-observed")).toBeVisible();
    await expect(page.getByTestId("aggregate-minimum")).toContainText("20");
  });

  test("counts what it excluded from the aggregate, and names why", async ({ page }) => {
    await page.goto(`/execution/quality${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("aggregate-excluded")).toBeVisible();
    await expect(page.getByTestId("exclusion-reasons")).toContainText(
      "Reference price not recorded",
    );
  });

  test("marks its illustrative rows and says the aggregate excludes them", async ({ page }) => {
    await page.goto(`/execution/quality${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("illustrative-row").first()).toBeVisible();
    await expect(page.getByTestId("illustrative-note")).toContainText(
      "illustrative rather than projected from the recorded book",
    );
  });

  test("shows a rejected order with no slippage rather than a zero", async ({ page }) => {
    await page.goto(`/execution/quality${DEMO}&state=REJECTED`);
    await waitForPanels(page);
    const row = page.locator('[data-lifecycle="REJECTED"]').first();
    await expect(row).toBeVisible();
    const table = page.getByTestId("execution-table");
    await expect(table.getByText("Not yet available").first()).toBeVisible();
  });

  test("keeps a cancelled order an order event, never an exit", async ({ page }) => {
    await page.goto(`/execution/quality${DEMO}&state=CANCELLED`);
    await waitForPanels(page);
    await expect(page.locator('[data-lifecycle="CANCELLED"]').first()).toBeVisible();
    await expect(page.getByTestId("execution-outcomes")).toContainText(
      "A cancellation is not an exit",
    );
  });

  test("reports a modelled and a recorded cost side by side, never combined", async ({
    page,
  }) => {
    await page.goto(`/execution/quality${OPERATOR}`);
    await waitForPanels(page);
    await page.getByTestId("execution-table").locator("tbody button").first().click();
    const cost = page.locator('[data-testid^="cost-"]').first();
    await expect(cost).toBeVisible();
    await expect(cost).toContainText("Modelled cost");
    await expect(cost).toContainText("Recorded cost");
    await expect(cost).toContainText("never subtracted from it");
  });

  test("offers no submit, cancel, amend or retry control", async ({ page }) => {
    await page.goto(`/execution/quality${OPERATOR}`);
    await waitForPanels(page);
    for (const label of ["Submit", "Cancel order", "Amend", "Retry", "Route"]) {
      await expect(page.getByRole("button", { name: label })).toHaveCount(0);
    }
  });
});

/* ============================================================ Area 10 — reconciliation */

test.describe("reconciliation shows comparisons and never present health", () => {
  test("separates present health from the newest recorded run", async ({ page }) => {
    await page.goto(`/execution/reconciliation${DEMO}`);
    await waitForPanels(page);
    const health = page.getByTestId("present-health");
    await expect(health).toBeVisible();
    await expect(health).toContainText("Not implemented");
    /* And the newest run carries its own as-of. */
    await expect(page.getByTestId("latest-as-of")).toBeVisible();
    await expect(page.getByTestId("latest-run")).toContainText(
      "a statement about the instant it was taken at",
    );
  });

  test("shows a mismatch with what disagreed, and an orphan count", async ({ page }) => {
    await page.goto(`/execution/reconciliation${DEMO}&result=MISMATCH_RECORDED`);
    await waitForPanels(page);
    await openEveryDisclosure(page);
    await expect(page.locator('[data-testid^="position-diffs-"]').first()).toBeVisible();
    await expect(page.locator('[data-testid^="ownership-"]').first()).toBeVisible();
  });

  test("states a missing comparison input rather than a match", async ({ page }) => {
    await page.goto(`/execution/reconciliation${DEMO}&result=COMPARISON_INPUT_MISSING`);
    await waitForPanels(page);
    const missing = page.locator('[data-testid^="missing-"]').first();
    await expect(missing).toBeVisible();
    await expect(missing).toContainText("not zero and not a match");
    /* The as-of alignment says the broker side was never recorded. */
    await expect(page.locator('[data-alignment="BROKER_AS_OF_NOT_RECORDED"]').first()).toBeVisible();
  });

  test("labels broker-reported equity informational", async ({ page }) => {
    await page.goto(`/execution/reconciliation${DEMO}`);
    await waitForPanels(page);
    await openEveryDisclosure(page);
    const balances = page.locator('[data-testid^="balances-"]').first();
    await expect(balances).toBeVisible();
    await expect(balances).toContainText("Broker reported equity");
    await expect(balances.getByTestId("informational-only").first()).toBeVisible();
    await expect(balances).toContainText("never sizing authority");
  });

  test("offers no connect, reconnect, refresh or repair control", async ({ page }) => {
    await page.goto(`/execution/reconciliation${OPERATOR}`);
    await waitForPanels(page);
    await expect(page.getByTestId("absent-controls")).toContainText("Reconnect");
    for (const label of ["Connect", "Reconnect", "Authenticate", "Refresh", "Repair"]) {
      await expect(page.getByRole("button", { name: label })).toHaveCount(0);
    }
  });
});

/* ============================================================= Area 22 — data quality */

test.describe("data quality declares a profile and never infers one", () => {
  test("renders exactly the three accepted profiles as a legend", async ({ page }) => {
    await page.goto(`/system/data-quality${DEMO}`);
    await waitForPanels(page);
    const legend = page.getByTestId("profile-list");
    await expect(legend).toBeVisible();
    for (const profile of ["PUBLIC_PIT", "PROVIDER_REALISTIC_PIT", "FORWARD_SYSTEM"]) {
      await expect(legend.locator(`[data-profile="${profile}"]`)).toHaveCount(1);
    }
    await expect(legend.locator("li")).toHaveCount(3);
    await expect(page.getByTestId("profile-rule")).toContainText(
      "declared, never inferred",
    );
  });

  test("never renders provider-derived information as PUBLIC_PIT", async ({ page }) => {
    await page.goto(`/system/data-quality${DEMO}`);
    await waitForPanels(page);
    const providerDerived = page.locator(
      '[data-subject]:has([data-information-origin="PROVIDER_DERIVED"])',
    );
    await expect(providerDerived.first()).toBeVisible();
    for (const card of await providerDerived.all()) {
      await expect(card.locator('[data-information-profile="PUBLIC_PIT"]')).toHaveCount(0);
    }
  });

  test("names the gap wherever coverage falls short of the requested extent", async ({
    page,
  }) => {
    await page.goto(`/system/data-quality${DEMO}`);
    await waitForPanels(page);
    const gaps = page.locator('[data-testid^="gaps-"]');
    await expect(gaps.first()).toBeVisible();
    await expect(gaps.first()).toContainText("What is missing, and over what extent");
  });

  test("says no real provider feed exists, and claims no qualification", async ({ page }) => {
    await page.goto(`/system/data-quality${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("real-feed-state")).toContainText(
      "No provider is selected",
    );
    await expect(page.locator("body")).not.toContainText("P1 passed");
  });

  test("reports each subject's own freshness, distinctly from the view's", async ({ page }) => {
    await page.goto(`/system/data-quality${DEMO}`);
    await waitForPanels(page);
    const subjects = page.getByTestId("subject-freshness");
    const cards = page.locator("[data-subject]");
    await expect(subjects).toHaveCount(await cards.count());
    /* The shell keeps exactly one view-level indicator, and it is a different statement. */
    await expect(page.getByTestId("freshness-indicator")).toHaveCount(1);
    /* One subject is past its own contract, and says so rather than borrowing the view's. */
    await expect(
      page.locator('[data-testid="subject-freshness"][data-freshness-state="STALE"]'),
    ).toHaveCount(1);
  });

  test("filters by profile and says what the filter hid", async ({ page }) => {
    await page.goto(`/system/data-quality${DEMO}&profile=FORWARD_SYSTEM`);
    await waitForPanels(page);
    await expect(page.getByTestId("filter-chips")).toContainText("FORWARD_SYSTEM");
    await expect(page.getByTestId("subject-count")).toBeVisible();
    const cards = page.locator("[data-subject]");
    await expect(cards).toHaveCount(1);
  });
});

/* ========================================================== Area 23 — system operations */

test.describe("system operations separates a last success from present health", () => {
  test("shows both, and says the present state is not derived from the last run", async ({
    page,
  }) => {
    await page.goto(`/system/operations${OPERATOR}`);
    await waitForPanels(page);
    await page.getByTestId("job-table").locator("tbody button").first().click();
    const detail = page.locator('[data-testid^="job-detail-"]').first();
    await expect(detail).toBeVisible();
    await expect(detail).toContainText("A recorded historical fact");
    await expect(detail).toContainText("not");
    await expect(detail).toContainText("derived from the last run");
  });

  test("claims present health on no row, because no row observes a running service", async ({
    page,
  }) => {
    await page.goto(`/system/operations${DEMO}`);
    await waitForPanels(page);
    await expect(page.locator('[data-job-state="OPERATING_NORMALLY"]')).toHaveCount(0);
    await expect(page.getByTestId("service-existence-note")).toContainText(
      "not evidence that the service exists",
    );
  });

  test("offers no start, stop, retry, trigger or schedule control", async ({ page }) => {
    await page.goto(`/system/operations${OPERATOR}`);
    await waitForPanels(page);
    const absent = page.getByTestId("absent-controls").first();
    await expect(absent).toContainText("Start");
    for (const label of ["Start", "Stop", "Retry", "Trigger", "Restart", "Schedule"]) {
      await expect(page.getByRole("button", { name: label, exact: true })).toHaveCount(0);
    }
  });

  test("gives an open incident no close time and a closed one exactly when", async ({
    page,
  }) => {
    await page.goto(`/system/operations${DEMO}&incident_state=OPEN`);
    await waitForPanels(page);
    const open = page.locator("[data-incident]").first();
    await expect(open).toBeVisible();
    await expect(open.locator('[data-testid^="closed-"]')).toContainText("Not applicable");

    await page.goto(`/system/operations${DEMO}&incident_state=CLOSED`);
    await waitForPanels(page);
    const closed = page.locator("[data-incident]").first();
    await expect(closed).toBeVisible();
    await expect(closed.locator('[data-testid^="closed-"]')).not.toContainText(
      "Not applicable",
    );
  });

  test("renders an incident timeline as an ordered sequence", async ({ page }) => {
    await page.goto(`/system/operations${DEMO}`);
    await waitForPanels(page);
    const timeline = page.locator('[data-testid^="timeline-"]').first();
    await expect(timeline).toBeVisible();
    expect(await timeline.evaluate((node) => node.tagName)).toBe("OL");
  });
});

/* ================================================================ Area 26 — audit trail */

test.describe("the audit trail is a projection, and it says so", () => {
  test("identifies the projection separately from every event", async ({ page }) => {
    await page.goto(`/governance/audit${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("projection-id")).toBeVisible();
    await expect(page.getByTestId("rebuild-count")).toBeVisible();
    await expect(page.getByTestId("projection-rule")).toContainText(
      "Rebuilding a read model must never mutate a source event",
    );
    await expect(page.getByTestId("source-stream-state")).toContainText("Not implemented");
  });

  test("shows a correction that appends, beside the event it corrects", async ({ page }) => {
    await page.goto(`/governance/audit${DEMO}&kind=CORRECTION_APPENDED`);
    await waitForPanels(page);
    await openEveryDisclosure(page);
    const correction = page.locator('[data-testid^="correction-"]').first();
    await expect(correction).toBeVisible();
    await expect(correction).toContainText("A correction APPENDS");
  });

  test("shows a tombstone naming what it withdrew and under what authority", async ({
    page,
  }) => {
    await page.goto(`/governance/audit${DEMO}&kind=RECORD_TOMBSTONED`);
    await waitForPanels(page);
    await openEveryDisclosure(page);
    const tombstone = page.locator('[data-testid^="tombstone-"]').first();
    await expect(tombstone).toBeVisible();
    await expect(tombstone).toContainText("Deletion authority");
    await expect(tombstone).toContainText("preserves the governance record");
  });

  test("states a gap rather than showing a quieter timeline", async ({ page }) => {
    await page.goto(`/governance/audit${DEMO}`);
    await waitForPanels(page);
    const gaps = page.getByTestId("gap-list");
    await expect(gaps).toBeVisible();
    await expect(gaps).toContainText("A quieter stretch of timeline is not evidence");
  });

  test("renders a record digest of KalpaMani's own record, never a vendor one", async ({
    page,
  }) => {
    await page.goto(`/governance/audit${DEMO}`);
    await waitForPanels(page);
    await openEveryDisclosure(page);
    const digest = page.locator('[data-testid^="digest-"]').first();
    await expect(digest).toBeVisible();
    await expect(digest).toContainText("kalpamani-record-");
  });

  test("offers no append, edit, delete or export control", async ({ page }) => {
    await page.goto(`/governance/audit${OPERATOR}`);
    await waitForPanels(page);
    for (const label of ["Append", "Edit", "Delete", "Sign", "Export"]) {
      await expect(page.getByRole("button", { name: label })).toHaveCount(0);
    }
  });
});

/* ==================================================================== Area 27 — alerts */

test.describe("one condition produces one alert", () => {
  test("renders each condition once, with its occurrence count", async ({ page }) => {
    await page.goto(`/system/alerts${DEMO}`);
    await waitForPanels(page);
    const keys = await page
      .locator("[data-dedup-key]")
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-dedup-key")));
    expect(keys.length).toBeGreaterThan(0);
    expect(new Set(keys).size).toBe(keys.length);
  });

  test("orders severity by the declared rank rather than by comparing text", async ({
    page,
  }) => {
    await page.goto(`/system/alerts${DEMO}`);
    await waitForPanels(page);
    const legend = page.getByTestId("severity-legend");
    await expect(legend).toBeVisible();
    const ranks = await page
      .getByTestId("alert-table")
      .locator("[data-severity-rank]")
      .evaluateAll((nodes) =>
        nodes.map((node) => Number(node.getAttribute("data-severity-rank"))),
      );
    expect(ranks.length).toBeGreaterThan(1);
    /* The rendered order is non-decreasing in the DECLARED rank. */
    for (let index = 1; index < ranks.length; index += 1) {
      expect(ranks[index]).toBeGreaterThanOrEqual(ranks[index - 1]);
    }
  });

  test("states how many duplicate observations it folded away", async ({ page }) => {
    await page.goto(`/system/alerts${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("folded-total")).toBeVisible();
    await expect(page.getByTestId("folded-count").first()).toContainText("folded");
  });

  test("keeps the alert record and the condition identity apart", async ({ page }) => {
    await page.goto(`/system/alerts${OPERATOR}`);
    await waitForPanels(page);
    await page.getByTestId("alert-table").locator("tbody button").first().click();
    const record = page.getByTestId("alert-record-id").first();
    const condition = page.getByTestId("alert-condition-id").first();
    await expect(record).toBeVisible();
    await expect(condition).toBeVisible();
    expect(await record.textContent()).not.toBe(await condition.textContent());
    await expect(page.getByTestId("attention-reconciliation")).toContainText(
      "same condition identities",
    );
  });

  test("names the notification integrations that do not exist", async ({ page }) => {
    await page.goto(`/system/alerts${DEMO}`);
    await waitForPanels(page);
    const absent = page.getByTestId("absent-integrations");
    await expect(absent).toContainText("Email");
    await expect(absent).toContainText("Paging");
  });

  test("offers no acknowledge, resolve, snooze or dismiss control", async ({ page }) => {
    await page.goto(`/system/alerts${OPERATOR}`);
    await waitForPanels(page);
    for (const label of ["Acknowledge", "Resolve", "Snooze", "Dismiss", "Notify"]) {
      await expect(page.getByRole("button", { name: label })).toHaveCount(0);
    }
  });

  test("says what a filter hid rather than showing a shorter list silently", async ({
    page,
  }) => {
    await page.goto(`/system/alerts${DEMO}&severity=HIGH`);
    await waitForPanels(page);
    await expect(page.getByTestId("hidden-total")).toContainText("hidden by the filter");
    await expect(page.getByTestId("row-count")).toBeVisible();
  });
});

/* ================================================== cross-screen navigation and evidence */

test.describe("the C8 screens reach the records they came from", () => {
  test("reaches the data-quality area from an attention item's declared area", async ({
    page,
  }) => {
    await page.goto(`/attention${DEMO}`);
    await waitForHydration(page);
    /*
     * THE ONE DISCLOSURE THAT CARRIES THIS REFERENCE, OPENED DIRECTLY.
     *
     * The attention list holds several evidence disclosures and re-renders on its own
     * freshness tick, so opening every disclosure on the page and then reaching into one of
     * them races that tick. This opens the disclosure that actually contains the reference and
     * waits for the link itself.
     */
    const disclosure = page
      .getByTestId("attention-evidence")
      .filter({ has: page.locator('[data-owning-area="DATA_QUALITY"]') })
      .first();
    await disclosure.locator("summary").click();
    const link = disclosure
      .getByTestId("evidence-reference")
      .filter({ has: page.locator('[data-owning-area="DATA_QUALITY"]') })
      .first()
      .getByTestId("reference-area-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("data-area-status", "implemented");
    await link.click();
    await expect(page).toHaveURL(/\/system\/data-quality/);
    await waitForPanels(page);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Data Quality");
  });

  test("reaches the reconciliation run a trade detail names", async ({ page }) => {
    await page.goto(`/execution/reconciliation${DEMO}`);
    await waitForPanels(page);
    await openEveryDisclosure(page);
    const trades = page.locator('[data-testid^="trades-"]').first();
    await expect(trades).toBeVisible();
    const link = trades.getByTestId("reference-target-link").first();
    await link.click();
    await expect(page).toHaveURL(/\/portfolio\/trades\//);
  });

  test("reaches the alerts area from a data-quality subject's alert reference", async ({
    page,
  }) => {
    await page.goto(`/system/data-quality${DEMO}`);
    await waitForPanels(page);
    await openEveryDisclosure(page);
    const link = page.locator('[data-owning-area="ALERTS"]').first();
    await expect(link).toBeVisible();
    await link.click();
    await expect(page).toHaveURL(/\/system\/alerts/);
    await waitForPanels(page);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Alerts");
  });
});

/* ============================================================ the V1 safety boundary */

test.describe("the C8 screens stay inside the V1 safety boundary", () => {
  test("opens no connection beyond its own assets", async ({ page }) => {
    const offOrigin: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith("http://127.0.0.1:") && !url.startsWith("data:")) {
        offOrigin.push(url);
      }
    });
    for (const route of C8_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForPanels(page);
    }
    expect(offOrigin).toEqual([]);
  });

  test("discloses no private identifier anywhere in the rendered interface (U20)", async ({
    page,
  }) => {
    for (const route of C8_ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForPanels(page);
      await openEveryDisclosure(page);
      const text = (await page.locator("body").textContent()) ?? "";
      for (const forbidden of [
        "AKIA",
        "arn:aws",
        "amazonaws.com",
        "s3://",
        "secretsmanager",
        "IBKR",
        "sharadar",
        "nasdaqdatalink",
      ]) {
        expect(text.toLowerCase(), `${route} must not disclose ${forbidden}`).not.toContain(
          forbidden.toLowerCase(),
        );
      }
      /* No twelve-digit account id, and no broker-native order id shape. */
      expect(/\b\d{12}\b/.test(text), route).toBe(false);
    }
  });

  test("keeps every page free of horizontal scroll at this viewport (U14)", async ({ page }) => {
    for (const route of C8_ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForPanels(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, route).toBeLessThanOrEqual(0);
    }
  });

  test("preserves a drill-down filter across a mode switch (U13, U15)", async ({ page }) => {
    await page.goto(`/system/alerts${DEMO}&severity=HIGH`);
    await waitForPanels(page);
    await page.getByTestId("mode-switch").locator('[data-value="operator"]').click();
    await expect(page).toHaveURL(/severity=HIGH/);
    await expect(page).toHaveURL(/mode=operator/);
    await expect(page.getByTestId("filter-chips")).toContainText("HIGH");
  });

  test("has no detectable serious or critical violation on the C8 routes", async ({ page }) => {
    for (const route of C8_ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForPanels(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const serious = results.violations.filter(
        (violation) => violation.impact === "serious" || violation.impact === "critical",
      );
      expect(
        serious.map((violation) => `${route}: ${violation.id}`),
        route,
      ).toEqual([]);
    }
  });
});
