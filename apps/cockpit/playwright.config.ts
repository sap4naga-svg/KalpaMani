import { defineConfig, devices } from "@playwright/test";

/**
 * Browser integration tests.
 *
 * The dev server is bound to LOOPBACK ONLY. Nothing in this configuration reaches an
 * external host, and the application itself makes no network request at all.
 */
const PORT = 3100;
const BASE_URL = `http://127.0.0.1:${PORT}`;

/**
 * The two files that are registered at particular widths rather than at every width.
 *
 * `c10-reference-viewports.spec.ts` covers the three reference viewports of
 * `ui-ux-specification.md` section 12 that the original three projects do not, so it runs in
 * THOSE projects only and the original three ignore it — their run counts are unchanged by
 * it. `c10-visual-regression.spec.ts` owns the committed baseline and runs at the ORIGINAL
 * three widths only, which is the fixed viewport list this suite has always used; running it
 * at six would double the tracked baseline for coverage the structural sweep already gives.
 */
const REFERENCE_VIEWPORTS = /c10-reference-viewports\.spec\.ts/;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 60_000,
  /*
   * The committed baseline lives beside the suite, one directory per project, with the
   * PLATFORM in the file name — text rasterisation differs between operating systems, so a
   * baseline captured on one is not evidence about another, and a platform with no committed
   * baseline must report the snapshot as missing rather than accept whatever it finds.
   */
  snapshotPathTemplate: "{testDir}/visual-baseline/{projectName}/{arg}-{platform}{ext}",
  use: {
    baseURL: BASE_URL,
    trace: "off",
  },
  projects: [
    {
      name: "desktop-1440",
      testIgnore: REFERENCE_VIEWPORTS,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    /*
     * U1 IS STATED AT ONE WIDTH, SO IT IS REGISTERED AT ONE WIDTH. `ui-ux-specification.md`
     * 14 states U1 "at 1440 x 900", and 12 gives tablet and mobile their OWN, different
     * requirements. Ignoring the U1 spec here is not a suppression: a `test.skip` inside it
     * would report a criterion as SKIPPED at two viewports it was never in scope for, which
     * reads as coverage that was withheld rather than coverage that does not apply. Every
     * other spec still runs at all three widths.
     */
    {
      name: "tablet-1024",
      testIgnore: [/u1-first-viewport\.spec\.ts/, REFERENCE_VIEWPORTS],
      use: { ...devices["Desktop Chrome"], viewport: { width: 1024, height: 768 } },
    },
    {
      name: "mobile-390",
      testIgnore: [/u1-first-viewport\.spec\.ts/, REFERENCE_VIEWPORTS],
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
    /*
     * THE THREE REFERENCE VIEWPORTS SECTION 12 NAMES THAT WERE NEVER REGISTERED. Each runs
     * the focused responsive acceptance suite and nothing else, so the accepted regression
     * suite above is neither multiplied nor altered by adding the missing widths.
     */
    {
      name: "desktop-1920",
      testMatch: REFERENCE_VIEWPORTS,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1920, height: 1080 } },
    },
    {
      name: "desktop-1280",
      testMatch: REFERENCE_VIEWPORTS,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "tablet-768",
      testMatch: REFERENCE_VIEWPORTS,
      use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 1024 } },
    },
  ],
  webServer: {
    command: `npx next dev --hostname 127.0.0.1 --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 180_000,
  },
});
