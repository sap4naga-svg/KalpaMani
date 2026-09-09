import { expect, test, type Locator, type Page, type Request } from "@playwright/test";

import { NAV_ROUTES } from "../src/nav/registry";

/**
 * The reference viewports section 12 names that the three registered projects do not cover.
 *
 * `ui-ux-specification.md` section 12 states requirements at SIX reference viewports —
 * 1920 × 1080, 1440 × 900, 1280 × 800, 1024 × 768, 768 × 1024 and 390 × 844 — and the suite
 * was registered at three of them. Three widths were therefore assessed and three were not
 * assessed at all, which is a gap in a cycle whose own scope is "responsiveness".
 *
 * THIS FILE IS REGISTERED ONLY IN THE THREE PROJECTS THAT WERE MISSING, and the three
 * original projects ignore it. That is deliberate: the accepted full regression suite runs at
 * 1440 × 900, 1024 × 768 and 390 × 844, and its per-project run counts are untouched by this
 * file — so the missing coverage is added without disturbing the coverage that existed.
 *
 * WHAT IT CHECKS IS WHAT SECTION 12 ACTUALLY SAYS. Every route is swept for the requirements
 * section 12 states "at every viewport" — no horizontal page scroll, nothing clipped —
 * together with the persistent context of U2 and U3 and the structural rules of section 11.
 * Each width then gets the requirement stated on ITS OWN ROW and nothing else: the
 * first-viewport rule at 1920, full navigation at 1280, and a table scrolling inside its own
 * container at 768.
 *
 * IT CLAIMS NOTHING IT DOES NOT RUN. No screen-reader pass, no conformance claim, and no
 * performance threshold — an automated sweep establishes the structural properties an
 * automated sweep can establish, and the acceptance record says so in those words.
 */

const ROUTES: readonly string[] = NAV_ROUTES.map((route) => route.href);

/** Fails a test on any console error or uncaught page exception. */
function guardConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(String(error)));
  return problems;
}

/** Records every request that leaves this origin. There must be none. */
function guardOrigin(page: Page): string[] {
  const external: string[] = [];
  page.on("request", (request: Request) => {
    const url = new URL(request.url());
    if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost") {
      external.push(request.url());
    }
  });
  return external;
}

async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

/** The document's horizontal overflow, in CSS pixels. */
async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/**
 * CONTENT THAT ESCAPES THE VIEWPORT WITHOUT A SCROLL CONTAINER TO ESCAPE INTO.
 *
 * MEASURING `documentElement.scrollWidth - clientWidth` ALONE CANNOT FAIL HERE, and that was
 * established by experiment rather than by reading: `globals.css` sets `overflow-x: hidden` on
 * both `html` and `body`, so the root's scroll width is CLAMPED to its client width. Injecting a
 * 2400-pixel-wide element into the page left that measurement reading zero, and every U14
 * assertion in this repository built on it stayed green. The page genuinely never scrolls
 * sideways -- it cannot -- so the number is true, and it is not evidence.
 *
 * WHAT SECTION 12 ACTUALLY FORBIDS IS THE CLIPPING. "no horizontal page scroll * no clipped
 * critical control * no truncated number without a full value available", and U14 asks wide
 * content to scroll "within its own container". So the question is whether any rendered element
 * extends past the viewport WITHOUT sitting inside a real scroll container: content inside an
 * `overflow-x: auto` or `scroll` region is reachable and is exactly what the specification asks
 * for, and content outside one is clipped and unreachable.
 *
 * Only the innermost offenders are reported, so one wide element is one finding rather than a
 * chain of its ancestors, and elements with no box at all are skipped.
 */
async function clippedBeyondViewport(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const limit = document.documentElement.clientWidth;
    const found: string[] = [];
    for (const element of Array.from(document.querySelectorAll("header *, main *"))) {
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) continue;
      if (rect.right <= limit + 1) continue;

      let ancestor: Element | null = element.parentElement;
      let insideScrollContainer = false;
      while (ancestor !== null && ancestor !== document.body) {
        const overflowX = getComputedStyle(ancestor).overflowX;
        if (overflowX === "auto" || overflowX === "scroll") {
          insideScrollContainer = true;
          break;
        }
        ancestor = ancestor.parentElement;
      }
      if (insideScrollContainer) continue;

      /* Report the innermost offender only: an ancestor is wide because its child is. */
      const childOverflows = Array.from(element.children).some(
        (child) => child.getBoundingClientRect().right > limit + 1,
      );
      if (childOverflows) continue;

      const text = (element.textContent ?? "").trim().slice(0, 40);
      found.push(`<${element.tagName.toLowerCase()}> right=${Math.round(rect.right)} "${text}"`);
    }
    return found.slice(0, 5);
  });
}

/**
 * The heading levels a reader can actually reach, in document order.
 *
 * A heading hidden by `display: none` is not in the accessibility tree and is excluded; an
 * `sr-only` heading is clipped rather than hidden, is announced, and is included.
 */
async function visibleHeadingLevels(page: Page): Promise<number[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, h6"))
      .filter((element) => element.getClientRects().length > 0)
      .map((element) => Number(element.tagName.slice(1))),
  );
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

test.describe("section 12 — every route at this reference viewport", () => {
  for (const route of ROUTES) {
    test(`${route} renders, reads and scrolls correctly`, async ({ page }) => {
      const problems = guardConsole(page);
      const external = guardOrigin(page);

      const response = await page.goto(`${route}?scenario=demo`);
      expect(response?.status(), `${route} must not 404`).toBeLessThan(400);
      await waitForHydration(page);

      /* Section 12, "at every viewport": no horizontal page scroll. */
      expect(
        await horizontalOverflow(page),
        `${route} must not scroll horizontally`,
      ).toBeLessThanOrEqual(1);

      /*
       * And the half the root measurement cannot see: nothing is clipped OFF the page.
       * This found real defects -- eleven routes carried a badge whose sentence ran past a
       * 390-pixel viewport, and the attention metadata pairs ran past it on the landing page.
       */
      expect(
        await clippedBeyondViewport(page),
        `${route} must clip no content outside a scroll container`,
      ).toEqual([]);

      /* U2 and U3 — the persistent context, and the page-level synthetic label. */
      await expect(
        page.getByTestId("context-bar"),
        `${route} must carry the context bar`,
      ).toBeVisible();
      await expect(
        page.getByTestId("page-provenance-banner"),
        `${route} must label the synthetic scenario at page level`,
      ).toContainText("SYNTHETIC");

      /* Section 11 — one `h1`, a `main` landmark, and headings that do not skip a level. */
      await expect(page.locator("h1"), `${route} must have exactly one h1`).toHaveCount(1);
      await expect(page.locator("main#main-content")).toBeVisible();
      const levels = await visibleHeadingLevels(page);
      expect(levels.length, `${route} must render at least one heading`).toBeGreaterThan(0);
      const skips = levels
        .map((level, index) => ({ level, previous: levels[index - 1] }))
        .filter((pair) => pair.previous !== undefined && pair.level - pair.previous > 1)
        .map((pair) => `h${pair.previous} then h${pair.level}`);
      expect(skips, `${route} must not skip a heading level`).toEqual([]);

      expect(external, `${route} must open no off-origin request`).toEqual([]);
      expect(problems, `${route} must log no console error`).toEqual([]);
    });
  }
});

/**
 * The requirement on THIS viewport's own row in section 12.
 *
 * Each is asserted only at the width it is stated at, and a width it is not stated at reports
 * nothing about it — a `test.skip` in the other projects would read as coverage withheld from
 * a criterion that was never in scope for them.
 */
test.describe("section 12 — the requirement stated at this width", () => {
  test("meets its own row", async ({ page }) => {
    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();
    const width = viewport!.width;

    if (width === 1920) {
      /*
       * "full executive layout; tier 1 and Attention Required within the first viewport, no
       * scroll". U1 states the same property at 1440 and is registered there; this is section
       * 12's own 1920 row, which had never been checked at any width but that one.
       */
      await page.goto("/?scenario=demo&mode=executive");
      await waitForHydration(page);
      const fold = viewport!.height;
      for (const testId of [
        "tile-strategy-capital",
        "answer-performance",
        "answer-risk",
        "answer-health",
        "answer-changed",
        "answer-attention",
      ]) {
        await expectWithinFold(page.getByTestId(testId), fold, `${testId} at 1920 × 1080`);
      }
      await expectWithinFold(
        page.getByTestId("attention-item").first(),
        fold,
        "the first ranked attention item at 1920 × 1080",
      );
      expect(await page.evaluate(() => window.scrollY), "nothing was scrolled").toBe(0);
      return;
    }

    if (width === 1280) {
      /* "full navigation; tables may drop lowest-priority columns". */
      await page.goto("/portfolio/trades?scenario=demo&mode=operator");
      await waitForHydration(page);
      const nav = page.getByRole("navigation", { name: "Cockpit areas" }).first();
      await expect(
        nav,
        "the grouped navigation is persistent at 1280 × 800, not behind a drawer",
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "Open navigation" })).toBeHidden();
      /* Every registered route is reachable without opening anything. */
      expect(await nav.getByRole("link").count()).toBe(ROUTES.length);
      return;
    }

    if (width === 768) {
      /* "tablet portrait; single-column stacking; tables scroll within their own container". */
      await page.goto("/portfolio/trades?scenario=demo&mode=operator");
      await waitForHydration(page);
      const region = page.locator("[data-table-region]").first();
      await expect(region).toBeVisible();
      const containedScroll = await region.evaluate(
        (node) => (node as HTMLElement).scrollWidth - (node as HTMLElement).clientWidth,
      );
      expect(
        containedScroll,
        "the ledger is wider than 768 and must scroll inside its own region",
      ).toBeGreaterThan(0);
      expect(
        await horizontalOverflow(page),
        "and the page body must not scroll sideways because of it",
      ).toBeLessThanOrEqual(1);
      return;
    }

    throw new Error(`this spec is registered only at 1920, 1280 and 768; got ${width}`);
  });
});
