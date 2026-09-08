import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * The nine C7 screens, in a browser.
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

const C7_ROUTES = [
  "/strategy/health",
  "/strategy/versions",
  "/strategy/champion-challenger",
  "/research/runs",
  "/research/queue",
  "/research/hypotheses",
  "/research/feedback",
  "/research/ai-contribution",
  "/governance/packets",
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

/* ================================================================= scoping and states */

test.describe("every C7 route is honest about what it is showing", () => {
  test("labels every C7 route synthetic at page level in the demonstration scenario (U3)", async ({
    page,
  }) => {
    for (const route of C7_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForHydration(page);
      await expect(page.getByTestId("page-provenance-banner")).toContainText(
        "SYNTHETIC DEMONSTRATION DATA",
      );
      await expect(page.getByTestId("source-context")).toBeVisible();
      await expect(page.getByTestId("freshness-indicator")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    }
  });

  test("reports every C7 route unavailable in project scope, with its dependency named", async ({
    page,
  }) => {
    for (const route of C7_ROUTES) {
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
    await page.goto(`/research/runs${PAPER}`);
    await waitForPanels(page);
    await expect(page.getByTestId("unavailable-body").first()).toBeVisible();
    await expect(page.getByTestId("run-rows")).toHaveCount(0);
  });

  test("states on every C7 route that it has no control and drives nothing", async ({ page }) => {
    for (const route of C7_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForPanels(page);
      const notice = page.getByTestId("read-only-notice");
      await expect(notice).toBeVisible();
      await expect(notice).toContainText("no such control exists anywhere in this application");
      await expect(notice).toContainText("backtesting has not started");
    }
  });
});

/* ==================================================================== Area 5 — health */

test.describe("strategy health displays a recorded state and causes no transition", () => {
  test("renders all seven health states as a legend, with a population for each", async ({
    page,
  }) => {
    await page.goto(`/strategy/health${DEMO}`);
    await waitForPanels(page);
    const legend = page.getByTestId("health-state-legend");
    await expect(legend).toBeVisible();
    for (const state of [
      "HEALTHY",
      "WATCH",
      "DEGRADED",
      "NEW_ENTRIES_REDUCED",
      "NEW_ENTRIES_DISABLED",
      "SUSPENDED",
      "RETIRED",
    ]) {
      await expect(legend.locator(`[data-legend-state="${state}"]`)).toHaveCount(1);
    }
  });

  test("offers no transition, restore or acknowledge control anywhere on the page", async ({
    page,
  }) => {
    await page.goto(`/strategy/health${DEMO}`);
    await waitForPanels(page);
    const labels = await page.getByRole("button").allInnerTexts();
    for (const forbidden of [
      "restore",
      "suspend",
      "retire",
      "disable",
      "acknowledge",
      "resolve",
      "approve",
    ]) {
      expect(labels.join(" ").toLowerCase(), forbidden).not.toContain(forbidden);
    }
    expect(await page.locator("form").count()).toBe(0);
  });

  test("links a recorded degradation to the research queue entry it created", async ({ page }) => {
    await page.goto(`/strategy/health${DEMO}&state=NEW_ENTRIES_REDUCED`);
    await waitForPanels(page);
    await expect(page.getByTestId("health-detail")).toBeVisible();
    const reference = page.getByTestId("health-queue-reference");
    await expect(reference).toBeVisible();
    await expect(reference).toContainText("Research queue entry");
    /*
     * Following the REFERENCE'S OWN target destination opens the queue; it does not advance
     * the item. The link is the allowlisted one the reference carries, and it is the only
     * control on the panel.
     */
    await page.getByTestId("health-queue-reference").getByTestId("reference-target-link").click();
    await waitForPanels(page);
    await expect(page).toHaveURL(/\/research\/queue/);
    await expect(page.getByTestId("queue-rows")).toBeVisible();
  });

  test("shows the count and the minimum where the minimum observations are unmet", async ({
    page,
  }) => {
    await page.goto(`/strategy/health${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("health-rows")).toContainText(
      "below the declared minimum of",
    );
  });

  test("keeps health, lifecycle, environment and availability on four separate panels", async ({
    page,
  }) => {
    await page.goto(`/strategy/health${DEMO}`);
    await waitForPanels(page);
    const axes = page.getByTestId("health-axes");
    await expect(axes).toContainText("Health");
    await expect(axes).toContainText("Lifecycle and maturity");
    await expect(axes).toContainText("Runtime environment");
    await expect(axes).toContainText("Data availability");
    await expect(axes).toContainText("statuses, not maturity stages");
  });
});

/* ================================================================ Area 20 — versions */

test.describe("the version registry shows immutability and open-position pinning", () => {
  test("shows a Challenger beside its Champion, with no open position and no order authority", async ({
    page,
  }) => {
    await page.goto(`/strategy/versions${DEMO}&role=CHALLENGER`);
    await waitForPanels(page);
    const rows = page.locator('[data-role="CHALLENGER"]');
    await expect(rows.first()).toBeVisible();
    await expect(page.getByTestId("version-rows")).toContainText("no order authority");
    await expect(page.getByTestId("version-detail")).toContainText(
      "A Challenger produces no order in any environment",
    );
  });

  test("shows the exact versions that opened each pinned position", async ({ page }) => {
    await page.goto(`/strategy/versions${DEMO}&role=CHAMPION`);
    await waitForPanels(page);
    const positions = page.getByTestId("open-position-list");
    await expect(positions.first()).toBeVisible();
    await positions.getByText("The exact versions that opened this position").first().click();
    await expect(page.locator('[data-pin="risk_policy_version"]').first()).toBeVisible();
  });

  test("states that no rollback is recorded, rather than leaving the field blank", async ({
    page,
  }) => {
    await page.goto(`/strategy/versions${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("rollback-statement")).toContainText(
      "No rollback is recorded anywhere in this registry",
    );
    await expect(page.getByTestId("rollback-statement")).toContainText(
      "no rollback control exists here",
    );
  });
});

/* ==================================================================== Area 14 — runs */

test.describe("the run registry keeps a named baseline first", () => {
  test("renders a run whose baseline did not resolve as incomplete", async ({ page }) => {
    await page.goto(`/research/runs${DEMO}`);
    await waitForPanels(page);
    const incomplete = page.getByTestId("run-baseline-unresolved").first();
    await expect(incomplete).toBeVisible();
    await expect(incomplete).toContainText("incomplete");
    await expect(incomplete).toContainText("no complete comparison is possible");
  });

  test("shows failed and abandoned runs, and says they still spent a trial", async ({ page }) => {
    await page.goto(`/research/runs${DEMO}&state=FAILED`);
    await waitForPanels(page);
    await expect(page.locator('[data-run-state="FAILED"]')).toHaveCount(1);
    await expect(page.getByTestId("run-table")).toContainText("recorded runs spend a trial");
    await expect(page.getByTestId("filter-chips")).toBeVisible();
  });

  test("offers no run, retry, launch or schedule control", async ({ page }) => {
    await page.goto(`/research/runs${DEMO}`);
    await waitForPanels(page);
    const labels = (await page.getByRole("button").allInnerTexts()).join(" ").toLowerCase();
    for (const forbidden of ["run now", "retry", "launch", "schedule", "execute", "abandon"]) {
      expect(labels, forbidden).not.toContain(forbidden);
    }
  });

  test("gives its result chart a keyboard-reachable table with the same values (U10)", async ({
    page,
  }) => {
    await page.goto(`/research/runs${DEMO}&state=COMPLETED`);
    await waitForPanels(page);
    const chart = page.getByTestId("run-result-chart");
    await expect(chart).toBeVisible();
    await expect(chart.getByRole("img")).toHaveAttribute(
      "aria-label",
      /A table of the same values follows/,
    );
    await expect(chart.getByRole("table")).toBeVisible();
  });
});

/* ================================================================== Area 17 — queue */

test.describe("a queue entry is not an authorization", () => {
  test("names an outstanding authorization on every open item", async ({ page }) => {
    await page.goto(`/research/queue${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("queue-detail")).toBeVisible();
    await expect(page.getByTestId("queue-awaiting")).toBeVisible();
    await expect(page.getByTestId("queue-proposal")).toContainText(
      "A queue entry is not permission to execute its proposal",
    );
  });

  test("reaches the strategy health area through the reference's declared area", async ({
    page,
  }) => {
    await page.goto(`/research/queue${DEMO}`);
    await waitForPanels(page);
    const trigger = page.getByTestId("queue-trigger-reference");
    const areaLink = trigger.getByTestId("reference-area-link");
    await expect(areaLink).toHaveAttribute("data-owning-area", "STRATEGY_HEALTH");
    await expect(areaLink).toHaveAttribute("href", /\/strategy\/health/);
    /* The area control names the AREA, and never reads as retrieving the artefact. */
    const label = (await areaLink.innerText()).toLowerCase();
    expect(label).toContain("area");
    for (const verb of ["view", "open", "retrieve", "resolve", "show", "evidence"]) {
      expect(label, verb).not.toContain(verb);
    }
  });
});

/* ============================================================== Area 18 — hypotheses */

test.describe("a rename resets neither the budget nor the exposure", () => {
  test("shows the lineage budget beside the registration's own trial count", async ({ page }) => {
    await page.goto(`/research/hypotheses${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("lineage-budget-note")).toContainText(
      "The budget columns are the LINEAGE",
    );
    await expect(page.getByTestId("lineage-budget-note")).toContainText(
      "failed and abandoned runs count wherever they occurred",
    );
    await expect(page.getByTestId("registration-budget")).toContainText(
      "Renaming a registration or a Challenger resets neither",
    );
  });

  test("refuses a renamed confirmatory reuse and says why, on the screen", async ({ page }) => {
    await page.goto(`/research/hypotheses${DEMO}`);
    await waitForPanels(page);
    await page.locator('[data-registration="demo-reg-0003"] button').click();
    const refusal = page.getByTestId("ledger-refusal");
    await expect(refusal).toBeVisible();
    await expect(refusal).toHaveAttribute("data-refusal", "OUT_OF_SAMPLE_ALREADY_CONSUMED");
    await expect(refusal).toContainText("refused rather than downgraded");
    await expect(refusal).toContainText(
      "not admitted as fresh out-of-sample evidence under any name",
    );
  });

  test("shows an unmeasurable overlap as unknown, never as a zero", async ({ page }) => {
    await page.goto(`/research/hypotheses${DEMO}`);
    await waitForPanels(page);
    await page.locator('[data-registration="demo-reg-0004"] button').click();
    await expect(page.getByTestId("ledger-refusal")).toHaveAttribute(
      "data-refusal",
      "EXPOSURE_HISTORY_UNKNOWN",
    );
    const entries = page.getByTestId("ledger-entries");
    await expect(entries).toContainText("Not yet available");
    await expect(page.getByTestId("registration-ledger")).toContainText(
      "Incomparable is not disjoint",
    );
  });

  test("offers no register, amend or edit control", async ({ page }) => {
    await page.goto(`/research/hypotheses${DEMO}`);
    await waitForPanels(page);
    const labels = (await page.getByRole("button").allInnerTexts()).join(" ").toLowerCase();
    for (const forbidden of ["register", "amend", "edit", "submit", "supersede"]) {
      expect(labels, forbidden).not.toContain(forbidden);
    }
  });
});

/* ======================================================= Area 15 — Champion/Challenger */

test.describe("readiness is displayed and never conferred", () => {
  test("states readiness without any approval verb, and offers no promotion", async ({
    page,
  }) => {
    await page.goto(`/strategy/champion-challenger${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("comparison-readiness")).toContainText(
      "No promotion path exists from this view",
    );
    const labels = (await page.getByRole("button").allInnerTexts()).join(" ").toLowerCase();
    for (const forbidden of ["promote", "approve", "activate", "allocate", "replace"]) {
      expect(labels, forbidden).not.toContain(forbidden);
    }
  });

  test("keeps hypothetical shadow economics apart from realized outcomes", async ({ page }) => {
    await page.goto(`/strategy/champion-challenger${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("comparison-shadow")).toContainText(
      "never placed in a series with a realized result",
    );
    await expect(page.getByTestId("realized-outcomes")).toContainText(
      "A Challenger produces no order in any environment",
    );
  });

  test("reports an incomparable population as a state rather than a ratio", async ({ page }) => {
    await page.goto(`/strategy/champion-challenger${DEMO}`);
    await waitForPanels(page);
    await page.locator('[data-comparison="pead-short-v2-challenger"] button').click();
    await expect(page.getByTestId("comparison-population")).toContainText(
      "No comparable population has been established",
    );
    await expect(page.getByTestId("overlap-chart")).toContainText("Insufficient observations");
  });
});

/* ================================================================== Area 16 — the loop */

test.describe("the loop is read and never driven", () => {
  test("renders ten stages and marks the tenth human-only", async ({ page }) => {
    await page.goto(`/research/feedback${DEMO}`);
    await waitForPanels(page);
    await expect(page.locator("[data-stage]")).toHaveCount(10);
    await expect(page.getByTestId("human-only-stage")).toHaveCount(1);
    await expect(page.locator('[data-automatable="false"]')).toHaveCount(1);
    await expect(page.getByTestId("human-only-note")).toContainText(
      "Self-maturing is not self-governing",
    );
  });

  test("offers no advance, promote or release control", async ({ page }) => {
    await page.goto(`/research/feedback${DEMO}`);
    await waitForPanels(page);
    const labels = (await page.getByRole("button").allInnerTexts()).join(" ").toLowerCase();
    for (const forbidden of ["advance", "promote", "release", "unblock", "approve"]) {
      expect(labels, forbidden).not.toContain(forbidden);
    }
    expect(await page.locator("form").count()).toBe(0);
  });

  test("states that the learning engine writes and the Cockpit reads", async ({ page }) => {
    await page.goto(`/research/feedback${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("loop-boundary")).toContainText("The learning engine writes");
    await expect(page.getByTestId("loop-boundary")).toContainText("It does not exist");
  });
});

/* ============================================================ Area 21 — AI contribution */

test.describe("AI contribution reports a rule rather than an unsupported difference", () => {
  test("renders an insufficient population as its rule and no ratio", async ({ page }) => {
    await page.goto(`/research/ai-contribution${DEMO}`);
    await waitForPanels(page);
    const short = page.locator('[data-minimum-met="false"]').first();
    await expect(short).toBeVisible();
    await expect(short.getByTestId("ai-not-reportable")).toContainText(
      "The rule is reported, and no ratio is",
    );
  });

  test("renders an unmatched arm set as measuring the populations, not the arms", async ({
    page,
  }) => {
    await page.goto(`/research/ai-contribution${DEMO}`);
    await waitForPanels(page);
    const unmatched = page.locator('[data-matched="false"]').first();
    await expect(unmatched).toBeVisible();
    await expect(unmatched).toContainText("would measure the populations rather than the arms");
  });

  test("makes no causal claim, and says AI may remove and never restore", async ({ page }) => {
    await page.goto(`/research/ai-contribution${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("ai-boundary")).toContainText(
      "AI may REMOVE a candidate. It may never RESTORE one.",
    );
    await expect(page.getByTestId("ai-causal").first()).toContainText(
      "No causal alpha claim is made here",
    );
  });
});

/* ================================================================ Area 19 — governance */

test.describe("a packet is evidence for a decision and never the decision", () => {
  test("keeps recommendation, readiness, decision and execution as four labelled facts", async ({
    page,
  }) => {
    await page.goto(`/governance/packets${DEMO}`);
    await waitForPanels(page);
    const vocabulary = page.getByTestId("packet-vocabulary");
    await expect(vocabulary).toContainText("Input to a human decision, never the decision");
    await expect(vocabulary).toContainText("Ready for human review is not an approval");
    await expect(vocabulary).toContainText("Nothing here performs one");
  });

  test("names what an assembling packet is missing", async ({ page }) => {
    await page.goto(`/governance/packets${DEMO}&state=ASSEMBLING`);
    await waitForPanels(page);
    await expect(page.locator('[data-packet-state="ASSEMBLING"]')).toHaveCount(1);
    await expect(page.getByTestId("packet-missing-list")).toContainText("Evidence incomplete");
    await expect(page.getByTestId("packet-missing-list")).toContainText(
      "Trial count unrecorded",
    );
  });

  test("records no approved decision, and says the vocabulary member is unused", async ({
    page,
  }) => {
    await page.goto(`/governance/packets${DEMO}`);
    await waitForPanels(page);
    const vocabulary = page.getByTestId("decision-outcome-vocabulary");
    await expect(vocabulary.locator('[data-outcome="APPROVED"]')).toHaveAttribute(
      "data-recorded",
      "false",
    );
    await expect(vocabulary.locator('[data-outcome="APPROVED"]')).toContainText(
      "none recorded",
    );
    await expect(page.getByTestId("decision-panel")).toContainText(
      "No approved decision appears in this demonstration",
    );
  });

  test("offers no approve, reject or release control", async ({ page }) => {
    await page.goto(`/governance/packets${DEMO}`);
    await waitForPanels(page);
    const labels = (await page.getByRole("button").allInnerTexts()).join(" ").toLowerCase();
    for (const forbidden of ["approve", "reject", "request more", "release", "promote"]) {
      expect(labels, forbidden).not.toContain(forbidden);
    }
    expect(await page.locator("form").count()).toBe(0);
    expect(await page.locator("input:not([type='search']):not([type='date'])").count()).toBe(0);
  });
});

/* ==================================================================== safety and access */

test.describe("the C7 screens stay inside the V1 safety boundary", () => {
  test("opens no connection beyond its own assets", async ({ page }) => {
    const external: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith("http://127.0.0.1:") && !url.startsWith("data:")) {
        external.push(url);
      }
    });
    for (const route of C7_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForPanels(page);
    }
    expect(external).toEqual([]);
  });

  test("discloses no private identifier anywhere in the rendered interface (U20)", async ({
    page,
  }) => {
    for (const route of C7_ROUTES) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForPanels(page);
      const text = (await page.locator("body").innerText()).toLowerCase();
      for (const forbidden of [
        "arn:aws",
        "amazonaws",
        "s3://",
        "secretsmanager",
        "sharadar",
        "nasdaqdatalink",
        "akia",
        "brokerid",
      ]) {
        expect(text, `${route}/${forbidden}`).not.toContain(forbidden);
      }
      /* No twelve-digit identifier, which is the shape of an account id. */
      expect(/\b\d{12}\b/.test(text), route).toBe(false);
    }
  });

  test("keeps every page free of horizontal scroll at this viewport (U14)", async ({ page }) => {
    for (const route of C7_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForPanels(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, route).toBeLessThanOrEqual(1);
    }
  });

  test("preserves the drill-down filter across a mode switch (U13, U15)", async ({ page }) => {
    await page.goto(`/research/runs${DEMO}&state=COMPLETED`);
    await waitForPanels(page);
    await expect(page.getByTestId("filter-chips")).toContainText("COMPLETED");
    await page
      .getByTestId("mode-switch")
      .getByRole("radio", { name: "operator" })
      .click();
    await waitForPanels(page);
    await expect(page).toHaveURL(/state=COMPLETED/);
    await expect(page.getByTestId("filter-chips")).toContainText("COMPLETED");
  });

  test("has no detectable serious or critical violation on the C7 routes", async ({ page }) => {
    for (const route of C7_ROUTES) {
      await page.goto(`${route}${DEMO}`);
      await waitForPanels(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const serious = results.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? ""),
      );
      expect(
        serious.map((violation) => `${route}: ${violation.id}`),
        route,
      ).toEqual([]);
    }
  });
});
