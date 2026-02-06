import { defineConfig, devices } from "@playwright/test";

/**
 * Full-stack E2E tests. Requires backend + frontend running.
 * Use `npm run test:e2e` which starts both via webServer.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "html",
  use: {
    baseURL: "http://localhost:5174",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run start:e2e",
    url: "http://localhost:5174",
    reuseExistingServer: false,
    timeout: 60000,
  },
});
