import { defineConfig, devices } from "@playwright/test";

/**
 * Browser integration tests.
 *
 * The dev server is bound to LOOPBACK ONLY. Nothing in this configuration reaches an
 * external host, and the application itself makes no network request at all.
 */
const PORT = 3100;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: BASE_URL,
    trace: "off",
  },
  projects: [
    {
      name: "desktop-1440",
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
      testIgnore: /u1-first-viewport\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1024, height: 768 } },
    },
    {
      name: "mobile-390",
      testIgnore: /u1-first-viewport\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: {
    command: `npx next dev --hostname 127.0.0.1 --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 180_000,
  },
});
