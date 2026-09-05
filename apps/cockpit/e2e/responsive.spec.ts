import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";

/**
 * Responsive behaviour, and the screenshots a reviewer inspects.
 *
 * The screenshots are written to `screenshots/` and are review evidence, not a visual
 * regression baseline. Visual regression is specified for a later cycle.
 */
const SHOTS = "screenshots";

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
});

test("captures the executive, operator and reference views", async ({ page }, testInfo) => {
  const project = testInfo.project.name;

  await page.goto("/?scenario=demo&mode=executive");
  // Capture the RESOLVED view: a screenshot of skeletons is not review evidence.
  await expect(page.getByTestId("attention-panel")).toBeVisible();
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-executive-demo.png`, fullPage: true });

  await page.goto("/?scenario=project&mode=executive");
  await expect(page.getByTestId("page-provenance-banner")).toContainText("PROJECT READINESS");
  await expect(page.getByTestId("attention-panel")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-executive-project.png`, fullPage: true });

  await page.goto("/?scenario=demo&mode=operator");
  await expect(page.getByText("Response evidence")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-operator-demo.png`, fullPage: true });

  await page.goto("/governance/qualification?mode=operator");
  await expect(page.getByTestId("run-authorization").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-qualification.png`, fullPage: true });

  await page.goto("/foundation/states");
  await expect(page.getByTestId("freshness-demo")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-states.png`, fullPage: true });

  await page.goto("/governance/controls");
  await expect(page.getByTestId("inert-control").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-controls.png`, fullPage: true });
});

test("captures the open command palette", async ({ page }, testInfo) => {
  await page.goto("/?scenario=demo");
  // The palette listener attaches on hydration; the freshness indicator proves it has.
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByTestId("command-palette")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${testInfo.project.name}-palette.png` });
});

test("uses a drawer for navigation below the desktop breakpoint", async ({ page }, testInfo) => {
  const width = page.viewportSize()?.width ?? 0;
  await page.goto("/?scenario=demo");

  const menu = page.getByRole("button", { name: "Open navigation" });
  if (width >= 1024) {
    // The persistent rail is present at desktop widths.
    await expect(page.getByRole("navigation", { name: "Cockpit areas" }).first()).toBeVisible();
    return;
  }

  await expect(menu).toBeVisible();
  await menu.click();
  const drawer = page.getByRole("dialog", { name: "Navigation" });
  await expect(drawer).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${testInfo.project.name}-mobile-nav.png` });

  // Navigating from the drawer closes it and preserves the scope.
  await drawer.getByRole("link", { name: "Project & Qualification" }).click();
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL(/\/governance\/qualification/);
  await expect(page).toHaveURL(/scenario=demo/);
});

test("keeps wide content inside its own scroll container", async ({ page }) => {
  await page.goto("/governance/qualification?mode=operator");
  const pageOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(pageOverflow).toBeLessThanOrEqual(1);
});

test("removes non-essential motion when reduced motion is preferred (U12)", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/?scenario=demo");
  const duration = await page.evaluate(() => {
    const probe = document.querySelector("header a") as HTMLElement | null;
    return probe === null ? "0s" : getComputedStyle(probe).transitionDuration;
  });
  // The reduced-motion rule collapses every transition to an imperceptible 0.01ms.
  const seconds = Number.parseFloat(duration);
  expect(Number.isFinite(seconds)).toBe(true);
  expect(seconds).toBeLessThan(0.001);
});
