import { defineConfig } from "@playwright/test";

// E2E runs against the production build (`vite preview`, port 4173) talking
// to a real backend — the API URL is baked in at build time via
// VITE_API_BASE_URL. Set PLAYWRIGHT_BASE_URL to target an already-running
// frontend instead of starting a preview server.
const PREVIEW_URL = "http://localhost:4173";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? PREVIEW_URL,
    trace: "retain-on-failure",
    // Some sandboxes ship a full Chromium build but not the separate
    // headless-shell Playwright otherwise expects; point at it explicitly
    // when present, without hardcoding a path that won't exist elsewhere.
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
      : undefined,
  },
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run preview -- --port 4173 --strictPort",
        url: PREVIEW_URL,
        reuseExistingServer: !process.env.CI,
      },
});
