import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  // JUnit carries requirement/bug/issue annotations as <property> elements for
  // traceability/trace_matrix.py and TestRail (trcli parse_junit).
  reporter: [
    ["list"],
    ["html", { open: "never" }],
    ["junit", { outputFile: "test-results/junit-e2e.xml", embedAnnotationsAsProperties: true }],
  ],
  // Keep Playwright artifacts in a subfolder: Playwright empties outputDir on each run,
  // and test-results/ also holds the unit-test JUnit report.
  outputDir: "test-results/playwright",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}) },
    },
  ],
  webServer: [
    {
      // Backend serving the repo's test_data as the "local" source.
      command: "uvicorn app.main:app --port 8000",
      cwd: "../backend",
      env: { PDS_LOCAL_ROOT: "../test_data", PDS_ENABLE_UPLOAD: "true" },
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
