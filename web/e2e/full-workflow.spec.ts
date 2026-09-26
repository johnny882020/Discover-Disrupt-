/**
 * End-to-end workflow against a real backend: enter API key -> dashboard ->
 * trigger a CSV run -> dataset detail -> quality report -> export.
 *
 * Requires a running API (see `playwright.config.ts`) and:
 * - PLAYWRIGHT_API_KEY: a valid org key for that API.
 * - E2E_CSV_PATH (optional): CSV path readable by the API server; defaults
 *   to the bundled fixture, relative to the repo root the API runs from.
 */
import { expect, test } from "@playwright/test";

const API_KEY = process.env.PLAYWRIGHT_API_KEY ?? "";
const CSV_PATH = process.env.E2E_CSV_PATH ?? "tests/fixtures/lab_export_malformed.csv";

test.describe("full pipeline workflow", () => {
  test("enter key, trigger a run, inspect the dataset, view quality, export", async ({ page }) => {
    if (!API_KEY) {
      throw new Error("Set PLAYWRIGHT_API_KEY to a valid org key for the target API.");
    }
    // Unique per run, so repeated runs against the same database never collide.
    const datasetName = `E2E dataset ${Date.now()}`;
    const datasetPattern = new RegExp(datasetName, "i");

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
    await page.getByLabel(/dataset name/i).fill(datasetName);
    await page.getByLabel(/csv path/i).fill(CSV_PATH);
    await page.getByRole("button", { name: /start run/i }).click();

    // The run redirects to its new dataset's detail page.
    await expect(page).toHaveURL(/\/datasets\/[^/]+$/);
    await expect(page.getByRole("heading", { name: datasetPattern })).toBeVisible();

    // The run should also now appear on the dashboard.
    await page.getByRole("link", { name: /d&d labs/i }).click();
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
    await expect(page.getByText(datasetPattern)).toBeVisible();

    // Open the dataset detail again from the dashboard.
    await page.getByRole("link", { name: datasetPattern }).click();
    await expect(page.getByRole("heading", { name: datasetPattern })).toBeVisible();

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
