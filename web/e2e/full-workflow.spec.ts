/**
 * End-to-end workflow: enter API key -> dashboard -> trigger a CSV run ->
 * see it appear -> open dataset detail -> view quality report -> export.
 *
 * This spec targets a real backend at `PLAYWRIGHT_BASE_URL` (see
 * `playwright.config.ts`). It is not run against the MSW mock server, and
 * is expected to be unrunnable until a live compose stack (frontend +
 * FastAPI backend + Postgres) is wired up for the test environment. It
 * must, however, be valid, type-checked Playwright/TypeScript.
 */
import { expect, test } from "@playwright/test";

const API_KEY = process.env.PLAYWRIGHT_API_KEY ?? "dnd_live_acme0000000000000000000000";

test.describe("full pipeline workflow", () => {
  test("enter key, trigger a run, inspect the dataset, view quality, export", async ({ page }) => {
    await page.goto("/");

    // Enter API key.
    await page.getByLabel(/api key/i).fill(API_KEY);
    await page.getByRole("button", { name: /continue/i }).click();

    // Dashboard loads.
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();

    // Trigger a CSV pipeline run.
    await page.getByRole("link", { name: /new pipeline run/i }).click();
    await expect(page.getByRole("heading", { name: /new pipeline run/i })).toBeVisible();

    await page.getByLabel(/source/i).selectOption("csv");
    await page.getByLabel(/dataset name/i).fill("E2E smoke test dataset");
    await page.getByLabel(/csv path/i).fill("uploads/e2e-smoke.csv");
    await page.getByRole("button", { name: /start run/i }).click();

    // The run redirects to its new dataset's detail page.
    await expect(page).toHaveURL(/\/datasets\/[^/]+$/);
    await expect(page.getByRole("heading", { name: /e2e smoke test dataset/i })).toBeVisible();

    // The run should also now appear on the dashboard.
    await page.getByRole("link", { name: /d&d labs/i }).click();
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
    await expect(page.getByText(/e2e smoke test dataset/i)).toBeVisible();

    // Open the dataset detail again from the dashboard.
    await page.getByRole("link", { name: /e2e smoke test dataset/i }).click();
    await expect(page.getByRole("heading", { name: /e2e smoke test dataset/i })).toBeVisible();

    // View its quality report.
    await page.getByRole("link", { name: /quality report/i }).click();
    await expect(page.getByRole("heading", { name: /quality report/i })).toBeVisible();
    await expect(page.getByText(/total records/i)).toBeVisible();
    await expect(page.getByText(/pass rate/i)).toBeVisible();

    // Go back and export the dataset as CSV.
    await page.goBack();
    await page.getByRole("link", { name: /^export$/i }).click();
    await expect(page.getByRole("heading", { name: /export/i })).toBeVisible();

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: /download csv/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
  });
});
