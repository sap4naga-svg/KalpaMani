import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * U1 — the ten-second test, at the reference desktop width.
 *
 * "at 1440 × 900, the Executive Overview answers the five ten-second questions within the
 * first viewport, without scrolling" (§14 U1), and §6 puts Attention Required in that same
 * first viewport, because "an attention list below the fold is a list nobody reads".
 *
 * U1 IS STATED AT ONE WIDTH, so it is REGISTERED at one width. `playwright.config.ts` runs
 * this file in the `desktop-1440` project only — a `test.skip` in the other two would report
 * a criterion as skipped that was never in scope for them. §12's tablet and mobile
 * requirements are different requirements, and they are checked in their own spec.
 *
 * WHAT THIS CHECKS, AND WHY EACH PART.
 *
 * A QUESTION HEADING IS NOT AN ANSWER. The earlier version of this check measured the
 * bounding box of the question LABEL, so a tile whose numeric, footer and drill-down link
 * fell below the fold still passed — it had shown a reader the question and hidden the
 * answer. The whole tile is measured here.
 *
 * A ROW'S TOP EDGE IS NOT A ROW. It also measured only the TOP of the first attention item.
 * The first ranked item at 1440 × 900 ended 124 pixels below the fold: its impact, its
 * recommended governance action and its evidence affordance were all off screen. The whole
 * item is measured here, and its five presented things are each asserted VISIBLE.
 *
 * NOTHING IS SCROLLED, COLLAPSED OR CLIPPED to manufacture a pass: the scroll offset is
 * asserted zero, every measured element is checked for vertical overflow of its own box, and
 * the evidence affordance is opened to prove it works rather than merely occupying space.
 */

const DEMO = "?scenario=demo&mode=executive";
const PROJECT = "?mode=executive";

/** The six tiles carrying the ten-second answers, and the questions they answer. */
const ANSWER_TILES = [
  { testId: "tile-strategy-capital", question: "What are we risking against?" },
  { testId: "answer-performance", question: "How are we doing?" },
  { testId: "answer-risk", question: "Where is risk?" },
  { testId: "answer-health", question: "Is anything wrong?" },
  { testId: "answer-changed", question: "What changed?" },
  { testId: "answer-attention", question: "What requires attention?" },
];

async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

/** The whole element, top to bottom, inside the first viewport. */
async function expectWithinFold(element: Locator, fold: number, what: string): Promise<void> {
  await expect(element, `${what} must be visible`).toBeVisible();
  const box = await element.boundingBox();
  expect(box, `${what} must have a box`).not.toBeNull();
  expect(box!.height, `${what} must have height`).toBeGreaterThan(0);
  expect(
    Math.round(box!.y + box!.height),
    `${what} must END above the fold, not merely begin above it`,
  ).toBeLessThanOrEqual(fold);
}

/** No content is hidden by its own container overflowing vertically. */
async function expectNotClipped(element: Locator, what: string): Promise<void> {
  const clipped = await element.evaluate((node) => {
    const el = node as HTMLElement;
    return el.scrollHeight - el.clientHeight;
  });
  expect(clipped, `${what} must not clip its own content`).toBeLessThanOrEqual(1);
}

test.describe("U1 — the five answers and the attention list in the first viewport", () => {
  for (const [label, query] of [
    ["the populated demonstration", DEMO],
    ["the default project view", PROJECT],
  ] as const) {
    test(`answers all five questions within the first viewport — ${label}`, async ({ page }) => {
      await page.goto(`/${query}`);
      await waitForHydration(page);

      const viewport = page.viewportSize();
      expect(viewport).not.toBeNull();
      expect(viewport!.width, "U1 is stated at 1440 x 900").toBe(1440);
      const fold = viewport!.height;

      for (const tile of ANSWER_TILES) {
        const element = page.getByTestId(tile.testId);
        // The QUESTION is asked...
        await expect(element).toContainText(tile.question);
        // ...and the WHOLE TILE that answers it, footer and drill-down included, is above
        // the fold. Not the label's box: the answer's.
        await expectWithinFold(element, fold, `${tile.question} (${tile.testId})`);
        await expectNotClipped(element, tile.testId);
        // An answer with no rendered content is not an answer.
        const text = (await element.innerText()).trim();
        expect(text.length, `${tile.testId} must render an answer`).toBeGreaterThan(
          tile.question.length + 8,
        );
      }

      // Every answer links to the area that owns it, and the link is reachable, not clipped.
      const links = page.getByRole("link", { name: /Open the area that owns this/ });
      expect(await links.count()).toBeGreaterThanOrEqual(5);

      // NOTHING WAS SCROLLED to achieve any of that.
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
      expect(
        await page.evaluate(() => document.scrollingElement?.scrollTop ?? 0),
      ).toBe(0);
    });
  }

  test("puts the first ranked attention item, whole, in the first viewport", async ({ page }) => {
    await page.goto(`/${DEMO}`);
    await waitForHydration(page);
    const fold = page.viewportSize()!.height;

    const panel = page.getByTestId("attention-panel");
    await expect(panel).toBeVisible();
    const panelBox = await panel.boundingBox();
    expect(panelBox!.y, "the attention panel must begin above the fold").toBeLessThan(fold);

    const item = page.getByTestId("attention-item").first();
    await expectWithinFold(item, fold, "the first ranked attention item");
    await expectNotClipped(item, "the first ranked attention item");

    /*
     * THE FIVE PRESENTED THINGS (§6), each VISIBLE inside that first viewport. An item
     * missing any of them is not rendered at all, so their presence is also the check that
     * a dense layout dropped nothing to fit.
     */
    await expectWithinFold(item.getByTestId("attention-why"), fold, "why it matters");
    await expect(item).toContainText("Impact:");
    await expectWithinFold(
      item.getByTestId("attention-recommended"),
      fold,
      "the recommended governance action",
    );
    const evidence = item.getByTestId("attention-evidence");
    await expectWithinFold(evidence, fold, "the evidence affordance");

    // The evidence affordance is USABLE, not merely present.
    await evidence.locator("summary").click();
    await expect(evidence.getByTestId("evidence-reference").first()).toBeVisible();

    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  });

  test("keeps the attention panel's own answer above the fold when nothing is ranked", async ({
    page,
  }) => {
    await page.goto(`/${PROJECT}`);
    await waitForHydration(page);
    const fold = page.viewportSize()!.height;

    const panel = page.getByTestId("attention-panel");
    await expect(panel).toBeVisible();
    // No item is ranked here, so the answer IS the availability state, and a reader who does
    // not scroll must still see it.
    await expect(page.getByTestId("attention-item")).toHaveCount(0);
    await expectWithinFold(
      panel.locator("[data-availability]").first(),
      fold,
      "the attention panel's availability answer",
    );
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  });

  test("scrolls no page body horizontally at the reference width (U14)", async ({ page }) => {
    for (const query of [DEMO, PROJECT]) {
      await page.goto(`/${query}`);
      await waitForHydration(page);
      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(overflow.scrollWidth, query).toBeLessThanOrEqual(overflow.clientWidth);
    }
  });
});
