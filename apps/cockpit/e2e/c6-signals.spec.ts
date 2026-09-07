import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * The C6 screens, in a browser.
 *
 * Every assertion is about something a reader can see: a label, a state, a separation the
 * specification requires two facts to keep. Nothing here asserts an internal shape — that is
 * the unit suite's job — and nothing here reaches a network.
 */

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo&period=3M&gran=DAILY&changes=auto";
const OPERATOR =
  "?mode=operator&env=RESEARCH&scenario=demo&period=ALL&gran=MONTHLY&changes=auto";
const PROJECT =
  "?mode=executive&env=RESEARCH&scenario=project&period=3M&gran=DAILY&changes=auto";

const C6_ROUTES = ["/signals/funnel", "/signals/missed"] as const;

/** The trade whose execution evidence C6 records in full. */
const RECORDED_TRADE = "/portfolio/trades/demo-trade-sol-0006";
/** A candidate the Brain had no objection to, and that risk declined downstream. */
const DECLINED_CANDIDATE = "/signals/candidates/demo-candidate-0006";
/** A trade whose sizing nobody recorded — no candidate was journaled for it. */
const UNSIZED_TRADE = "/portfolio/trades/demo-trade-gen-0001";

async function waitForHydration(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("context-bar")).toBeVisible();
}

/**
 * Hydration, and then every panel's read resolved.
 *
 * `ReadModelPanel` renders a shape-only skeleton while its query is in flight, so a content
 * assertion made immediately after hydration races the read rather than testing it. Waiting
 * for the skeletons to clear is waiting for the answer to ARRIVE, which is a stronger
 * condition than `networkidle` and a more direct one — so this deliberately does not wait on
 * the network at all. The development server keeps its own long-lived connections open, and
 * `networkidle` is a statement about those rather than about this page's data.
 */
async function waitForPanels(page: Page): Promise<void> {
  await expect(page.getByTestId("context-bar")).toBeVisible();
  await expect(page.getByTestId("skeleton")).toHaveCount(0, { timeout: 20_000 });
}

test.describe("the C6 signals screens render and stay honest", () => {
  test("labels every C6 route synthetic at page level in the demonstration scenario (U3)", async ({
    page,
  }) => {
    for (const route of [...C6_ROUTES, DECLINED_CANDIDATE]) {
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

  test("reports every C6 route unavailable in project scope, with its dependency named", async ({
    page,
  }) => {
    for (const route of [...C6_ROUTES, DECLINED_CANDIDATE]) {
      await page.goto(`${route}${PROJECT}`);
      await waitForHydration(page);
      const bodies = page.getByTestId("unavailable-body");
      await expect(bodies.first()).toBeVisible();
      await expect(bodies.first()).toContainText("Waiting on:");
      await expect(bodies.first()).toContainText("PRODUCER_NOT_IMPLEMENTED");
    }
  });

  test("scrolls no page body sideways at this viewport (U14)", async ({ page }) => {
    for (const route of [...C6_ROUTES, DECLINED_CANDIDATE, RECORDED_TRADE]) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForHydration(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${route} must not scroll horizontally`).toBeLessThanOrEqual(1);
    }
  });
});

test.describe("the signal funnel", () => {
  test("says what each stage counts, and never subtracts two different subjects", async ({
    page,
  }) => {
    await page.goto(`/signals/funnel${DEMO}`);
    await waitForPanels(page);
    const stages = page.getByTestId("funnel-stages");
    await expect(stages).toBeVisible();
    await expect(stages.locator('[data-stage="UNIVERSE"]')).toContainText("securities");
    await expect(stages.locator('[data-stage="GENERATED"]')).toContainText("module decisions");
    await expect(stages.locator('[data-stage="CONSOLIDATED"]')).toContainText("candidates");
    await expect(stages).toContainText("not one decreasing population");
  });

  test("renders the eight Brain states as a closed set", async ({ page }) => {
    await page.goto(`/signals/funnel${DEMO}`);
    await waitForPanels(page);
    const axis = page.getByTestId("funnel-brain-axis");
    for (const state of [
      "READY_FOR_RISK_REVIEW",
      "WATCHLIST",
      "REJECTED",
      "BLOCKED_DATA",
      "BLOCKED_EVENT",
      "BLOCKED_AI",
      "BLOCKED_CONTRADICTION",
      "BLOCKED_BORROW",
    ]) {
      await expect(axis.locator(`[data-brain-state="${state}"]`)).toBeVisible();
    }
  });

  test("never presents READY_FOR_RISK_REVIEW as a successful end state", async ({ page }) => {
    await page.goto(`/signals/funnel${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("ready-is-not-approval")).toContainText(
      "handoff, not an approval to trade",
    );
    /* It is a state on the axis, never a fifth stage in the funnel. */
    await expect(
      page.getByTestId("funnel-stages").locator('[data-stage="READY_FOR_RISK_REVIEW"]'),
    ).toHaveCount(0);
  });

  test("keeps the downstream axis separate, counted on a stated basis", async ({ page }) => {
    await page.goto(`/signals/funnel${DEMO}`);
    await waitForPanels(page);
    const downstream = page.getByTestId("funnel-downstream-axis");
    await expect(downstream).toContainText("Risk review pending");
    await expect(downstream).toContainText("Order filled");
    /* All nine stages, and the population every count was drawn over. */
    await expect(downstream.locator("li")).toHaveCount(9);
    await expect(page.getByTestId("funnel-downstream-population")).toContainText("Counted over");
    /*
     * THE OVERLAP IS STATED ON THE SCREEN, not left for a reader to assume. An axis of
     * ever-reached counts does not decrease and is never summed.
     */
    await expect(downstream).toContainText("ever reached");
    await expect(downstream).toContainText("overlap");
    await expect(downstream).toContainText("no risk engine, order router or execution runtime");
    /* And the Brain vocabulary is still nowhere on this axis. */
    await expect(downstream).not.toContainText("Blocked borrow");
    await expect(downstream).not.toContainText("Ready for risk review");
  });

  test("resolves a recorded risk decision and reports an absent one", async ({ page }) => {
    /*
     * The size a decision assigned lives on the TRADE, with the two prices it was assigned
     * against, so a reader can check the arithmetic rather than trust the number.
     */
    await page.goto(`${RECORDED_TRADE}${DEMO}`);
    await waitForPanels(page);
    const decision = page.getByTestId("trade-risk-decision");
    await expect(decision).toBeVisible();
    await expect(decision).toContainText("Shares assigned");
    await expect(decision).toContainText("Invalidation level");
    await expect(page.getByTestId("risk-decision-outcome")).toContainText("Risk approved");

    /* And a trade nobody sized on record still reports the absence rather than a number. */
    await page.goto(`${UNSIZED_TRADE}${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("trade-risk-decision-absent")).toBeVisible();
    await expect(page.getByTestId("trade-risk-decision")).toHaveCount(0);
  });

  test("does not claim a fill for a candidate whose orders nobody recorded", async ({ page }) => {
    /*
     * A trade reference is not order evidence. This candidate was approved and entered, and
     * no order was ever written down, so its ledger row stops at the risk decision while a
     * candidate whose fills WERE recorded reports the fill.
     */
    await page.goto(`/signals/funnel${DEMO}`);
    await waitForPanels(page);
    const unrecorded = page.locator('[data-candidate-id="demo-candidate-0017"]');
    await expect(unrecorded).toContainText("Risk approved");
    await expect(unrecorded).not.toContainText("Order filled");
    const recorded = page.locator('[data-candidate-id="demo-candidate-0001"]');
    await expect(recorded).toContainText("Order filled");
  });

  test("refuses a rate between two stages counting different subjects", async ({ page }) => {
    await page.goto(`/signals/funnel${DEMO}`);
    await waitForPanels(page);
    const table = page.getByTestId("funnel-conversions");
    const refused = table.locator('tr[data-comparable="false"]');
    await expect(refused.first()).toBeVisible();
    await expect(refused.first()).toContainText("two different subjects do not divide");
    /* And a comparable one does carry a rate, so the refusal is selective. */
    const comparable = table.locator('tr[data-comparable="true"]');
    await expect(comparable.first()).toBeVisible();
  });

  test("marks an overlapping reason distribution as overlapping", async ({ page }) => {
    await page.goto(`/signals/funnel${DEMO}`);
    await waitForPanels(page);
    const borrow = page
      .getByTestId("funnel-brain-axis")
      .locator('[data-brain-state="BLOCKED_BORROW"]');
    await expect(borrow.getByText("overlapping").first()).toBeVisible();
    await expect(page.getByTestId("funnel-brain-axis")).toContainText(
      "tally of reason occurrences",
    );
  });

  test("reproduces a filtered candidate view from the URL alone (U13)", async ({ page }) => {
    await page.goto(`/signals/funnel${DEMO}&state=BLOCKED_AI`);
    await waitForPanels(page);
    await expect(page.getByTestId("filter-chips")).toContainText("Blocked AI");
    const rows = page.getByTestId("candidate-table").locator("tbody tr[data-candidate-id]");
    await expect(rows).toHaveCount(2);
    for (const row of await rows.all()) {
      expect(await row.getAttribute("data-brain-state")).toBe("BLOCKED_AI");
    }
    /* A mode switch preserves the drill-down filter (U15). */
    await page.getByTestId("mode-switch").getByRole("radio", { name: "operator" }).click();
    await expect(page).toHaveURL(/state=BLOCKED_AI/);
  });

  test("opens a candidate's explanation from its row", async ({ page }) => {
    await page.goto(`/signals/funnel${DEMO}`);
    await waitForPanels(page);
    await page.getByTestId("candidate-table").getByRole("link").first().click();
    await waitForPanels(page);
    await expect(page.getByTestId("candidate-decision")).toBeVisible();
    await expect(page).toHaveURL(/\/signals\/candidates\/demo-candidate-/);
  });
});

test.describe("candidate explainability", () => {
  test("shows no share count, dollar amount or order type anywhere", async ({ page }) => {
    await page.goto(`${DECLINED_CANDIDATE}${OPERATOR}`);
    await waitForPanels(page);
    const body = (await page.locator("main").textContent()) ?? "";
    /*
     * THE SCREEN IS READ, NOT THE PAYLOAD.
     *
     * A currency figure or a share count reaching this page is the failure §6.2 forbids, and
     * it would reach it as rendered text. The words below are the ones the page uses to
     * EXPLAIN the exclusion, so they are removed before the search rather than matched.
     */
    const withoutProse = body
      .replace(/no share count, dollar amount[^.]*\./gi, "")
      .replace(/not an amount of capital[^.]*\./gi, "");
    expect(withoutProse).not.toMatch(/\bUSD\b/);
    expect(withoutProse).not.toMatch(/\bSHARES\b/);
    expect(withoutProse).not.toMatch(/\bsh\b/);
  });

  test("carries the invalidation level as a reference and the risk basis as a distance", async ({
    page,
  }) => {
    await page.goto(`${DECLINED_CANDIDATE}${DEMO}`);
    await waitForPanels(page);
    const context = page.getByTestId("candidate-risk-context");
    await expect(context).toContainText("This is a distance, not an amount of capital");
    await expect(context.locator('[data-ref-kind="evidence"]').first()).toBeVisible();
    await expect(context).toContainText("never as an order");
  });

  test("states an AI absence as an absence rather than an empty list", async ({ page }) => {
    await page.goto(`/signals/candidates/demo-candidate-0013${DEMO}`);
    await waitForPanels(page);
    const panel = page.getByTestId("candidate-ai-absent");
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("answered nothing at all");
    await expect(panel).toContainText("never resolves in the candidate");
  });

  test("marks the AI evidence that removed a candidate, and never one that restored it", async ({
    page,
  }) => {
    await page.goto(`/signals/candidates/demo-candidate-0012${DEMO}`);
    await waitForPanels(page);
    const evidence = page.getByTestId("candidate-ai-evidence");
    await expect(evidence.locator('[data-removes="true"]').first()).toBeVisible();
    await expect(evidence).toContainText("may never restore one");
    await expect(page.getByTestId("candidate-contradictions")).toBeVisible();

    /* A ready candidate carries no removing reference at all. */
    await page.goto(`${DECLINED_CANDIDATE}${DEMO}`);
    await waitForPanels(page);
    await expect(
      page.getByTestId("candidate-ai-evidence").locator('[data-removes="true"]'),
    ).toHaveCount(0);
    await expect(page.getByTestId("ready-note")).toContainText("not an approval to trade");
  });

  test("carries model, prompt and publish provenance on every AI reference", async ({ page }) => {
    await page.goto(`/signals/candidates/demo-candidate-0001${DEMO}`);
    await waitForPanels(page);
    const first = page.getByTestId("candidate-ai-evidence").locator("[data-evidence-id]").first();
    await expect(first).toContainText("model_version");
    await expect(first).toContainText("prompt_version");
    await expect(first).toContainText("schema_version");
    await expect(first).toContainText("source published");
    await expect(first).toContainText("observed here");
  });

  test("shows a short candidate's borrow context and a long candidate none", async ({ page }) => {
    await page.goto(`/signals/candidates/demo-candidate-0011${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("candidate-short-context")).toContainText(
      "never inferred from price behaviour",
    );
    await page.goto(`/signals/candidates/demo-candidate-0001${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("candidate-short-context")).toHaveCount(0);
  });

  test("returns an honest not-found for an unknown candidate", async ({ page }) => {
    await page.goto(`/signals/candidates/demo-candidate-nope${DEMO}`);
    await waitForPanels(page);
    const bodies = page.getByTestId("unavailable-body");
    await expect(bodies.first()).toBeVisible();
    await expect(bodies.first()).toContainText("NOT_DEFINED_FOR_SUBJECT");
    /* And it is not some OTHER candidate served under this identity. */
    await expect(page.getByTestId("candidate-decision")).toHaveCount(0);
  });
});

test.describe("missed opportunities", () => {
  test("says hindsight is not achievable profit, on the page", async ({ page }) => {
    await page.goto(`/signals/missed${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("hindsight-warning")).toContainText(
      "not profit that was available",
    );
    await expect(page.getByTestId("hindsight-warning")).toContainText("A price path is not a position");
  });

  test("refuses a money counterfactual and says why", async ({ page }) => {
    await page.goto(`/signals/missed${DEMO}`);
    await waitForPanels(page);
    await page.getByTestId("missed-table").getByRole("button").first().click();
    const detail = page.locator('[data-testid^="miss-detail-"]').first();
    await expect(detail).toBeVisible();
    await expect(detail).toContainText("HYPOTHETICAL");
    await expect(detail).toContainText("only under an approved sizing basis, and none exists");
    await expect(detail.locator('[data-availability="NOT_YET_AVAILABLE"]').first()).toBeVisible();
  });

  test("shows the registered window and the assumptions it does not model", async ({ page }) => {
    await page.goto(`/signals/missed${DEMO}`);
    await waitForPanels(page);
    await page.getByTestId("missed-table").getByRole("button").first().click();
    const detail = page.locator('[data-testid^="miss-detail-"]').first();
    await expect(detail).toContainText("Fixed at the decision, before any of the path below was read");
    const assumptions = detail.locator('[data-testid^="assumptions-"]');
    await expect(assumptions).toContainText("No position size assumed");
    await expect(assumptions).toContainText("No protective stop modelled");
  });

  test("renders an incomplete follow-up path as PARTIAL rather than completing it", async ({
    page,
  }) => {
    await page.goto(`/signals/missed${DEMO}`);
    await waitForPanels(page);
    const partial = page.getByTestId("missed-table").locator('[data-path="PARTIAL"]');
    await expect(partial.first()).toBeVisible();
    await expect(
      page.getByTestId("missed-table").locator('[data-path="COMPLETE"]').first(),
    ).toBeVisible();
  });

  test("computes one rate over a defined population and refuses the other", async ({ page }) => {
    await page.goto(`/signals/missed${DEMO}`);
    await waitForPanels(page);
    const rates = page.getByTestId("missed-rates");
    await expect(rates.locator('[data-rate="FALSE_POSITIVE"]')).toContainText("Computed over");
    const negative = rates.locator('[data-rate="FALSE_NEGATIVE"]');
    await expect(negative).toContainText("No population is defined");
    await expect(negative).toContainText("rate is refused");
  });

  test("compares one pair of arms and refuses another, showing why", async ({ page }) => {
    await page.goto(`/signals/missed${DEMO}`);
    await waitForPanels(page);
    await expect(page.getByTestId("comparison-compatible")).toContainText("A comparable pair");
    const refused = page.getByTestId("comparison-refused");
    await expect(refused).toContainText("refuses to compare");
    await expect(refused).toContainText("Cost treatment");
    /* Each arm carries the dimensions that decide comparability. */
    const arms = page.getByTestId("comparison-compatible").locator("[data-arm]");
    await expect(arms).toHaveCount(2);
    await expect(arms.first()).toContainText("Information profile");
  });

  test("links a miss to the decision that produced it", async ({ page }) => {
    await page.goto(`/signals/missed${DEMO}`);
    await waitForPanels(page);
    await page.getByTestId("missed-table").getByRole("button").first().click();
    const detail = page.locator('[data-testid^="miss-detail-"]').first();
    await detail.getByRole("link", { name: "Why this decision was made" }).click();
    await waitForPanels(page);
    await expect(page.getByTestId("candidate-decision")).toBeVisible();
  });
});

test.describe("the complete trade lifecycle", () => {
  test("reconstructs orders, fills, protection and reconciliation", async ({ page }) => {
    await page.goto(`${RECORDED_TRADE}${OPERATOR}`);
    await waitForPanels(page);
    const events = page.getByTestId("lifecycle-events");
    for (const kind of [
      "ORDER_SUBMITTED_RECORDED",
      "ORDER_ACKNOWLEDGED_RECORDED",
      "FILL_RECORDED",
      "PROTECTIVE_ORDER_PLACED",
      "PROTECTIVE_ORDER_AMENDED",
      "PROTECTIVE_ORDER_CANCELLED",
      "BROKER_RECONCILIATION_RECORDED",
    ]) {
      await expect(events.locator(`[data-event-kind="${kind}"]`).first()).toBeVisible();
    }
  });

  test("shows an appended correction beside the event it corrects", async ({ page }) => {
    await page.goto(`${RECORDED_TRADE}${OPERATOR}`);
    await waitForPanels(page);
    const events = page.getByTestId("lifecycle-events");
    const correction = events.locator('[data-event-kind="PROTECTIVE_LEVEL_CORRECTED"]');
    await expect(correction).toBeVisible();
    await expect(correction).toContainText("Corrects");
    /* The corrected event is still there: a correction appends, and never overwrites. */
    await expect(events.locator('[data-event-kind="PROTECTIVE_ORDER_AMENDED"]')).toHaveCount(2);
    await expect(page.getByTestId("trade-lifecycle-panel")).toContainText("A correction appends");
  });

  test("marks a late observation at the instant it happened", async ({ page }) => {
    await page.goto(`/portfolio/trades/demo-trade-arb-0001${OPERATOR}`);
    await waitForPanels(page);
    const late = page.getByTestId("late-observation");
    await expect(late).toHaveCount(1);
    await expect(late).toContainText("later than it happened");
  });

  test("distinguishes a partially filled order from a partial position exit", async ({
    page,
  }) => {
    await page.goto(`/portfolio/trades/demo-trade-arb-0001${OPERATOR}`);
    await waitForPanels(page);
    const partialFill = page
      .getByTestId("lifecycle-events")
      .locator('[data-event-kind="PARTIAL_FILL_RECORDED"]');
    await expect(partialFill).toBeVisible();
    await expect(partialFill).toContainText("Order partially filled");

    await page.goto(`/portfolio/trades/demo-trade-cir-0003${OPERATOR}`);
    await waitForPanels(page);
    const partialExit = page
      .getByTestId("lifecycle-events")
      .locator('[data-event-kind="PARTIAL_EXIT_RECORDED"]');
    await expect(partialExit).toBeVisible();
    /* The ORDER filled completely; the POSITION was reduced. Two different facts. */
    await expect(partialExit).toContainText("Order filled");
    await expect(partialExit).not.toContainText("Order partially filled");
  });

  test("shows each fill against its named reference, with the sign convention", async ({
    page,
  }) => {
    await page.goto(`/portfolio/trades/demo-trade-arb-0001${OPERATOR}`);
    await waitForPanels(page);
    const fills = page.getByTestId("fill-quality");
    await expect(fills).toBeVisible();
    await expect(fills.locator("tbody tr")).toHaveCount(2);
    await expect(page.getByTestId("trade-execution")).toContainText(
      "Positive slippage is adverse, on both sides",
    );
    await expect(page.getByTestId("trade-execution")).toContainText(
      "The order side is not the position",
    );
  });

  test("keeps a short's order sides opposite to its position direction", async ({ page }) => {
    await page.goto(`/portfolio/trades/demo-trade-hlx-0004${OPERATOR}`);
    await waitForPanels(page);
    const fills = page.getByTestId("fill-quality");
    await expect(fills.locator('[data-side="SELL_TO_OPEN"]')).toBeVisible();
    /* The trade itself is a SHORT: the side and the direction are visibly different words. */
    await expect(page.getByTestId("trade-identity")).toContainText("SHORT");
  });

  test("reports the aggregate below its minimum rather than computing it", async ({ page }) => {
    await page.goto(`${RECORDED_TRADE}${OPERATOR}`);
    await waitForPanels(page);
    const aggregate = page.getByTestId("aggregate-quality");
    await expect(aggregate).toContainText("Below its minimum, so it is not computed");
    await expect(aggregate).toContainText("declared minimum of");
    await expect(aggregate).toContainText("Excluded fills");
  });

  test("shows an attribution that sums to the outcome, with its recorded status", async ({
    page,
  }) => {
    await page.goto(`${RECORDED_TRADE}${OPERATOR}`);
    await waitForPanels(page);
    const attribution = page.getByTestId("trade-attribution");
    await expect(attribution).toContainText("sum to the outcome exactly");
    await expect(attribution).toContainText("FINAL");
    /* And a trade nobody attributed says so instead. */
    await page.goto(`/portfolio/trades/demo-trade-nvl-0002${OPERATOR}`);
    await waitForPanels(page);
    await expect(page.getByTestId("trade-attribution")).toContainText(
      "a producer that does not exist",
    );
  });

  test("aligns the benchmark to this trade's holding period and states its basis", async ({
    page,
  }) => {
    await page.goto(`${RECORDED_TRADE}${OPERATOR}`);
    await waitForPanels(page);
    const benchmark = page.getByTestId("trade-benchmark");
    await expect(benchmark).toContainText("PRICE_RETURN");
    await expect(benchmark).toContainText("synthetic demonstration series, not a real benchmark");
    await expect(benchmark).toContainText("G1 is OPEN");
  });

  test("names a missing stage rather than inferring it", async ({ page }) => {
    await page.goto(`/portfolio/trades/demo-trade-nvl-0002${OPERATOR}`);
    await waitForPanels(page);
    const absent = page.getByTestId("absent-event-kinds");
    await expect(absent).toContainText("Broker reconciliation");
    await expect(absent).toContainText("Not yet available");
    /* And this trade carries fills, so the absence is selective rather than blanket. */
    await expect(
      page.getByTestId("lifecycle-events").locator('[data-event-kind="FILL_RECORDED"]').first(),
    ).toBeVisible();
  });

  test("says nothing was recorded for a trade with no execution evidence", async ({ page }) => {
    await page.goto(`/portfolio/trades/demo-trade-gen-0001${OPERATOR}`);
    await waitForPanels(page);
    await expect(page.getByTestId("trade-execution-absent")).toContainText(
      "No order or fill evidence was recorded",
    );
    await expect(page.getByTestId("trade-execution-absent")).toContainText(
      "manufacture an execution history out of a position size",
    );
  });

  test("draws only position markers on the plot, and the whole timeline in the table", async ({
    page,
  }) => {
    await page.goto(`${RECORDED_TRADE}${OPERATOR}`);
    await waitForPanels(page);
    const chart = page.getByTestId("trade-chart");
    await expect(chart).toBeVisible();
    /*
     * FOUR MARKERS, AND A LIFECYCLE WITH MANY MORE EVENTS.
     *
     * One entry and three exits are the only POSITION events; the timeline also carries order
     * submissions, acknowledgements, protective-order events and a reconciliation, and none of
     * those is a price this trade transacted at. The disclosure states both counts.
     */
    const disclosure = page.getByTestId("trade-chart-table-disclosure");
    await expect(disclosure).toContainText("4 events");
    await disclosure.getByText(/Marks and recorded events as a table/).click();
    await expect(disclosure.getByRole("table")).toBeVisible();
  });
});

test.describe("C6 accessibility and isolation", () => {
  test("has no automatically detectable accessibility violation", async ({ page }) => {
    for (const route of [...C6_ROUTES, DECLINED_CANDIDATE, RECORDED_TRADE]) {
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

  test("opens a miss detail from the keyboard and restores focus", async ({ page }) => {
    await page.goto(`/signals/missed${OPERATOR}`);
    await waitForHydration(page);
    const toggle = page.getByTestId("missed-table").getByRole("button").first();
    await toggle.focus();
    await expect(toggle).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator('[data-testid^="miss-detail-"]').first()).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toBeFocused();
  });

  test("issues no request to any external origin", async ({ page }) => {
    const external: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith("http://127.0.0.1") && !url.startsWith("data:")) {
        external.push(url);
      }
    });
    for (const route of [...C6_ROUTES, DECLINED_CANDIDATE, RECORDED_TRADE]) {
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
    for (const route of [...C6_ROUTES, DECLINED_CANDIDATE, RECORDED_TRADE]) {
      await page.goto(`${route}${OPERATOR}`);
      await waitForHydration(page);
    }
    expect(errors).toEqual([]);
  });
});
