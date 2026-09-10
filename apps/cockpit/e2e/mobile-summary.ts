import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Support for the mobile executive summary — ADR-0033 §2 (Decision M).
 *
 * Below 640 CSS pixels the Executive Overview defers every section that is not part of the
 * accepted summary behind a labelled `<details>` disclosure. A test that drives deferred
 * content on `/` — a chart button, a variant link, an evidence row — therefore reveals it
 * first at that width, BY KEYBOARD, exactly as a reader would. HIDDEN CONTENT IS NEVER READ
 * AS MISSING DATA (M8.2): revealing it is how the test proves it is there.
 *
 * Nothing here is a spec. Playwright matches `*.spec.ts`, so this module runs only when a
 * spec imports it.
 */

/** The breakpoint the summary behaviour applies below (M1). */
export const SUMMARY_BREAKPOINT_PX = 640;

/** The four disclosures, in document order; the fourth exists in Operator mode only. */
export const DISCLOSURE_IDS = [
  "what-changed",
  "performance-overview",
  "supporting-context",
  "response-evidence",
] as const;
export type DisclosureId = (typeof DISCLOSURE_IDS)[number];

/** The fixed labels (M5). */
export const DISCLOSURE_LABEL: Readonly<Record<DisclosureId, string>> = {
  "what-changed": "What changed — details",
  "performance-overview": "Performance overview",
  "supporting-context": "Supporting context",
  "response-evidence": "Response evidence",
};

/** The existing test ids each disclosure must reveal (M8.2). */
export const DEFERRED_TEST_IDS: Readonly<Record<DisclosureId, readonly string[]>> = {
  "what-changed": ["what-changed-panel"],
  "performance-overview": ["performance-overview"],
  "supporting-context": ["tile-open-gates", "tile-exposure", "tile-last-runs"],
  "response-evidence": [],
};

export function isSummaryViewport(page: Page): boolean {
  return (page.viewportSize()?.width ?? 0) < SUMMARY_BREAKPOINT_PX;
}

export function disclosure(page: Page, id: DisclosureId): Locator {
  return page.getByTestId(`disclosure-${id}`);
}

export function control(page: Page, id: DisclosureId): Locator {
  return page.getByTestId(`disclosure-${id}-control`);
}

/** Every disclosure control the page currently renders, whatever its state. */
export function visibleControls(page: Page): Locator {
  return page.locator("details[data-summary-disclosure] > summary:visible");
}

/**
 * Expands one disclosure by keyboard, and proves it opened.
 *
 * `Enter` on the summary is the accepted activation (M5); the control keeps focus after it.
 */
export async function expandByKeyboard(page: Page, id: DisclosureId): Promise<void> {
  const summary = control(page, id);
  await expect(summary).toBeVisible();
  await summary.focus();
  await expect(summary).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(disclosure(page, id)).toHaveAttribute("open", "");
  await expect(summary).toBeFocused();
}

/**
 * Below the breakpoint, expands every disclosure the page renders and returns how many it
 * expanded; at and above it, proves there is nothing to expand and returns zero. Either way
 * the call asserts something, so a caller at the wrong width is never silently a no-op.
 */
export async function revealDeferredSections(page: Page): Promise<number> {
  if (!isSummaryViewport(page)) {
    await expect(visibleControls(page)).toHaveCount(0);
    return 0;
  }
  /*
   * The page is hydrated and has resolved the breakpoint: every disclosure reports the
   * `summary` layout. Before that the control is painted by the CSS fallback and an
   * activation would toggle an element React has not yet taken over.
   */
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
  await expect(
    page.locator('details[data-summary-disclosure]:not([data-summary-layout="summary"])'),
  ).toHaveCount(0);
  let expanded = 0;
  for (const id of DISCLOSURE_IDS) {
    const details = disclosure(page, id);
    if ((await details.count()) === 0) continue;
    if ((await details.getAttribute("open")) === null) {
      await expandByKeyboard(page, id);
    }
    expanded += 1;
  }
  expect(expanded).toBeGreaterThanOrEqual(3);
  return expanded;
}

/** The document's horizontal overflow, in CSS pixels. */
export async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/**
 * Content that escapes the viewport without a scroll container to escape into — the U14
 * check `c10-acceptance.spec.ts` runs on every route, stated here as well so M8.7 can run it
 * with every disclosure expanded. The rule is that spec's: content inside an `overflow-x:
 * auto` or `scroll` region is reachable, content outside one is clipped, and only the
 * innermost offenders are reported.
 */
export async function clippedBeyondViewport(page: Page): Promise<string[]> {
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
