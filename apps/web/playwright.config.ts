import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests drive a real browser against the whole stack:
 *
 *   docker compose up --build -d     (from the repository root)
 *   npm run test:e2e
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  // One at a time: the tests share one server-side queue.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
