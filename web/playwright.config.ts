import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    // Some sandboxes ship a full Chromium build but not the separate
    // headless-shell Playwright otherwise expects; point at it explicitly
    // when present, without hardcoding a path that won't exist elsewhere.
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
      : undefined,
  },
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : { command: "npm run preview", url: "http://localhost:5173", reuseExistingServer: true },
});
