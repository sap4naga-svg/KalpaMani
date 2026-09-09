import { expect, test, type Page } from "@playwright/test";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

/**
 * The C10 review evidence.
 *
 * A FOCUSED, INDEXED SET — not a screenshot of everything. `ui-ux-specification.md` section 15
 * describes visual regression as "a fixed synthetic fixture set, a fixed viewport list,
 * deterministic rendering, and a stable baseline per route and per state", where "a diff is a
 * review item, not an auto-accept". This file supplies the fixed fixture set, the fixed viewport
 * list and the per-route, per-state captures. It does NOT commit a baseline image: this
 * repository keeps screenshots out of the tracked tree, so an image baseline would have to live
 * outside it, and a baseline nobody can diff against in review is not a baseline. That half of
 * the criterion is recorded as outstanding in the acceptance record rather than claimed here.
 *
 * Every capture is written to a DISTINCT directory, so the C3 to C9 sets are untouched, and is
 * stamped with the exact commit it was taken at — a screenshot whose revision is unknown is a
 * picture, not evidence. Each is listed in `INDEX.txt` with what it is there to show, because a
 * directory of ninety images nobody can navigate is not evidence either.
 */
const SHOTS = "screenshots-c10";

const DEMO = "?mode=executive&env=RESEARCH&scenario=demo";
const OPERATOR = "?mode=operator&env=RESEARCH&scenario=demo";
const PROJECT = "?mode=executive&env=RESEARCH&scenario=project";

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
  let revision = "unknown";
  let dirty = "unknown";
  try {
    revision = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
    dirty =
      execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }).trim().length === 0
        ? "clean"
        : "uncommitted changes present";
  } catch {
    // A capture set with no recoverable revision says so rather than claiming one.
  }
  writeFileSync(
    `${SHOTS}/PROVENANCE.txt`,
    [
      "KalpaMani Cockpit -- C10 polish and acceptance review evidence",
      "",
      `captured at commit: ${revision}`,
      `working tree:       ${dirty}`,
      `captured on:        ${new Date().toISOString()}`,
      "",
      "Review evidence. NOT a committed visual-regression baseline: this repository",
      "keeps screenshots outside the tracked tree, so no image baseline is committed",
      "and no image diff gates anything.",
      "",
      "Every populated figure in a `scenario=demo` capture is a repository-owned",
      "deterministic fixture. It is not a result, not a measurement, and not evidence",
      "about any strategy, provider, broker or market.",
      "",
      "Rendering a screen is not implementing the subsystem behind it. No Brain,",
      "strategy, portfolio, risk, execution, broker, research, learning, alert or",
      "audit runtime exists; none is authorized; and no provider is selected.",
      "",
      "Viewports: 1440x900 (desktop-1440), 1024x768 (tablet-1024), 390x844",
      "(mobile-390) -- the three reference widths this suite is registered at.",
      "",
    ].join("\n"),
    "utf8",
  );
  writeFileSync(`${SHOTS}/INDEX.txt`, "file\twhat it shows\n", "utf8");
});

/** Records one capture in the index, so the set can be navigated rather than guessed at. */
function index(file: string, what: string): void {
  appendFileSync(`${SHOTS}/INDEX.txt`, `${file}\t${what}\n`, "utf8");
}

async function waitForHydration(page: Page): Promise<void> {
  await expect(page.getByTestId("freshness-indicator")).toBeVisible();
}

async function capture(page: Page, project: string, name: string, what: string): Promise<void> {
  const file = `${project}-${name}.png`;
  await page.screenshot({ path: `${SHOTS}/${file}`, fullPage: true });
  index(file, what);
}

test("captures the executive answers, in both scenarios and both modes", async ({
  page,
}, testInfo) => {
  const project = testInfo.project.name;

  await page.goto(`/${DEMO}`);
  await waitForHydration(page);
  await expect(page.getByTestId("attention-panel")).toBeVisible();
  await capture(page, project, "overview-demo-executive", "Area 1/28/29 — the five ten-second answers and the ranked attention list, synthetic scenario, Executive mode");

  await page.goto(`/${OPERATOR}`);
  await waitForHydration(page);
  await expect(page.getByText("Response evidence").first()).toBeVisible();
  await capture(page, project, "overview-demo-operator", "Area 29 — the same read models at Operator density, with response evidence");

  await page.goto(`/${PROJECT}`);
  await waitForHydration(page);
  await expect(page.getByTestId("page-provenance-banner")).toContainText("PROJECT READINESS");
  await capture(page, project, "overview-project", "Areas 1/24 — the default project scenario: tracked governance facts real, operational read models reported as NOT_IMPLEMENTED rather than zero");
});

test("captures the dense operator screens", async ({ page }, testInfo) => {
  const project = testInfo.project.name;

  await page.goto(`/portfolio/trades${OPERATOR}`);
  await waitForHydration(page);
  await expect(page.getByTestId("trades-table")).toBeVisible();
  await capture(page, project, "trades-ledger", "Area 36 — the trade ledger: business status and data completeness as separate columns, and a table that scrolls inside its own region");

  await page.goto(`/portfolio/performance${OPERATOR}`);
  await waitForHydration(page);
  await capture(page, project, "portfolio-performance", "Area 2 — equity, drawdown and rolling windows, with the named-benchmark requirement disclosed as unavailable");

  await page.goto(`/strategy/health${OPERATOR}`);
  await waitForHydration(page);
  await capture(page, project, "strategy-health", "Area 5 — the seven health states and the rolling tail loss with its window, population, tail fraction and observation count");

  await page.goto(`/strategy/performance${OPERATOR}`);
  await waitForHydration(page);
  await capture(page, project, "strategy-performance", "Area 4 — per-version attribution, and strategy capacity rendered NOT_YET_AVAILABLE by the admission gate rather than as a number");

  await page.goto(`/risk${OPERATOR}`);
  await waitForHydration(page);
  await capture(page, project, "risk", "Area 12 — the four risk quantities separately labelled, each permitted value with its policy reference");
});

test("captures the governance and state reference screens", async ({ page }, testInfo) => {
  const project = testInfo.project.name;

  await page.goto(`/governance/qualification${OPERATOR}`);
  await waitForHydration(page);
  await expect(page.getByTestId("run-authorization").first()).toBeVisible();
  await capture(page, project, "qualification", "Area 24 — tracked governance facts under REPOSITORY_TRACKED, gates read independently, P1-P9 UNEVALUATED");

  await page.goto(`/governance/controls${DEMO}`);
  await waitForHydration(page);
  await expect(page.getByTestId("inert-control").first()).toBeVisible();
  await capture(page, project, "controls-inert", "Area 35/U16 — every future control inert, with no button, no form and no control API route");

  await page.goto(`/foundation/states${DEMO}`);
  await waitForHydration(page);
  await expect(page.getByTestId("freshness-demo")).toBeVisible();
  await capture(page, project, "availability-states", "U4/U5 — all eleven availability states rendered distinctly, none as zero or as a healthy value");
});

test("captures the global surfaces", async ({ page }, testInfo) => {
  const project = testInfo.project.name;

  await page.goto(`/${DEMO}`);
  await waitForHydration(page);
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByTestId("command-palette")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-palette.png` });
  index(`${project}-palette.png`, "Area 30/U9 — the command palette: navigation and filters only, with no state-changing verb");
  await page.keyboard.press("Escape");

  await page.goto(`/${DEMO}`);
  await waitForHydration(page);
  await page.getByRole("button", { name: "Ask KalpaMani" }).click();
  await expect(page.getByTestId("ask-panel")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-ask.png` });
  index(`${project}-ask.png`, "Area 31 — Ask KalpaMani: a closed catalogue of question classes, every answer cited, no model anywhere");
});

test("captures the navigation affordance this viewport actually uses", async ({
  page,
}, testInfo) => {
  const project = testInfo.project.name;
  const width = page.viewportSize()?.width ?? 0;

  await page.goto(`/portfolio/trades${DEMO}`);
  await waitForHydration(page);
  await expect(page.locator("[data-table-region]").first()).toBeVisible();

  if (width >= 1024) {
    /* The two skip links, revealed by the keyboard that reaches them. */
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("skip-to-main")).toBeFocused();
    await page.screenshot({ path: `${SHOTS}/${project}-skip-main.png` });
    index(`${project}-skip-main.png`, "Section 10 — the first skip link, reached by the first Tab");
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("skip-to-table")).toBeFocused();
    await page.screenshot({ path: `${SHOTS}/${project}-skip-table.png` });
    index(`${project}-skip-table.png`, "Section 10 — the second skip link, which reaches the primary table");
    return;
  }

  const menu = page.getByRole("button", { name: "Open navigation" });
  await expect(menu).toBeVisible();
  await menu.click();
  await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${project}-drawer.png` });
  index(`${project}-drawer.png`, "Section 12 — grouped navigation as a drawer below the desktop breakpoint, focus trapped and released to its trigger");
});
