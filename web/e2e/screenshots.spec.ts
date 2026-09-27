/**
 * Screenshot verification: drives the main screens against a real backend
 * and saves a full-page PNG of each at desktop and phone widths, in light
 * and dark mode, to `e2e/screenshots/<screen>-<width>-<scheme>.png` (CI
 * uploads them as the `screenshots` artifact for review).
 *
 * These are not pixel baselines: each capture instead asserts that the
 * screen's key content is visible and that the page does not scroll
 * sideways, the layout bug a phone-width screenshot exists to catch.
 *
 * Needs the same running API and environment as `full-workflow.spec.ts`
 * (see `helpers.ts`). Runs as its own Playwright project after the
 * workflows, since its long run holds the API's run worker.
 */
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { provisionOrg, signInWithApiKey } from "./helpers";

const SCREENSHOT_DIR = path.resolve(import.meta.dirname, "screenshots");

const VIEWPORTS = [
  { width: 1280, height: 900 },
  { width: 390, height: 844 },
] as const;

const SCHEMES = ["light", "dark"] as const;

/**
 * A small assay export: aspirin measured in both assay formats, ibuprofen, a
 * positive control, and one invalid SMILES so the quality report has an error.
 */
const SMALL_CSV = [
  "compound_id,smiles,target,assay_format,control,activity_value,activity_unit",
  "A1,CC(=O)Oc1ccccc1C(=O)O,COX-1,biochemical,no,50,nM",
  "A1,CC(=O)Oc1ccccc1C(=O)O,COX-1,cell-based,no,2000,nM",
  "I1,CC(C)Cc1ccc(cc1)C(C)C(=O)O,COX-1,biochemical,,5000,nM",
  "C1,Cn1cnc2c1c(=O)n(C)c(=O)n2C,COX-1,biochemical,positive,10,nM",
  "X1,C1CC(,COX-1,biochemical,,300,nM",
].join("\n");

/**
 * Enough rows that the run is still in progress while it is captured and
 * cancelled: a few structures repeated under unique compound ids.
 */
function largeCsv(rows: number): string {
  const smiles = ["CC(=O)Oc1ccccc1C(=O)O", "CC(C)Cc1ccc(cc1)C(C)C(=O)O", "Cn1cnc2c1c(=O)n(C)c(=O)n2C", "c1ccccc1O"];
  const lines = ["compound_id,smiles"];
  for (let i = 0; i < rows; i++) {
    lines.push(`L${i},${smiles[i % smiles.length]}`);
  }
  return lines.join("\n");
}

/**
 * Capture `screen` at every viewport and colour scheme. `ready` returns the
 * locators that must be visible in each capture. The screenshot is saved
 * before the overflow check, so a failing layout is still there to inspect.
 */
async function capture(page: Page, screen: string, ready: () => Locator[]): Promise<void> {
  for (const viewport of VIEWPORTS) {
    for (const colorScheme of SCHEMES) {
      await page.setViewportSize(viewport);
      await page.emulateMedia({ colorScheme });
      for (const locator of ready()) {
        await expect(locator).toBeVisible();
      }
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${screen}-${viewport.width}-${colorScheme}.png`),
        fullPage: true,
      });
      const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
      expect(fits, `${screen} scrolls sideways at ${viewport.width}px (${colorScheme})`).toBe(true);
    }
  }
  // Leave the page at desktop size for the next step's interactions.
  await page.setViewportSize(VIEWPORTS[0]);
}

async function uploadCsv(page: Page, name: string, csv: string): Promise<void> {
  await page.getByLabel(/csv, tsv, excel/i).setInputFiles({
    name,
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await expect(page.getByLabel("Role for column smiles")).toHaveValue("smiles");
}

test("screenshots of the main screens", async ({ page, request }) => {
  // Three runs and twenty captures: well beyond the default per-test timeout.
  test.setTimeout(240_000);
  const org = await provisionOrg(request);
  const datasetName = `Screenshot assay panel ${Date.now()}`;
  await signInWithApiKey(page, org.apiKey);

  // A large run, captured while it is in progress, then cancelled.
  await page.getByRole("link", { name: /new pipeline run/i }).click();
  await uploadCsv(page, "large_library.csv", largeCsv(3000));
  await page.getByLabel(/dataset name/i).fill(`Screenshot cancelled ${Date.now()}`);
  await page.getByRole("button", { name: /start run/i }).click();
  const stepper = page.getByRole("list", { name: "Run progress" });
  const cancel = page.getByRole("button", { name: "Cancel run" });
  await expect(stepper).toBeVisible();
  // Wait for the worker to pick the run up, so the stepper shows a stage
  // under way rather than only "Queued".
  await expect(stepper.locator('[aria-current="step"]')).not.toHaveText(/^Queued/, { timeout: 30_000 });
  await capture(page, "run-in-progress", () => [stepper, page.getByText("Run in progress"), cancel]);

  await cancel.click();
  const cancelled = page.getByRole("alert").filter({ hasText: "The run was cancelled; nothing was saved." });
  await expect(cancelled).toBeVisible({ timeout: 30_000 });
  await capture(page, "run-cancelled", () => [cancelled]);

  // A small run to completion: it opens the new dataset.
  await page.getByRole("button", { name: "Choose a different file" }).click();
  await uploadCsv(page, "assay_panel.csv", SMALL_CSV);
  await page.getByLabel(/dataset name/i).fill(datasetName);
  await page.getByRole("button", { name: /start run/i }).click();
  await expect(page).toHaveURL(/\/datasets\/[^/]+$/, { timeout: 30_000 });
  await capture(page, "dataset", () => [
    page.getByRole("heading", { name: datasetName }),
    page.getByRole("table", { name: "Potency by assay format" }),
    page.getByRole("columnheader", { name: "Assay", exact: true }),
    page.getByText("Positive control"),
    page.locator('img[src^="data:image/svg+xml"]').first(),
  ]);

  await page.getByRole("link", { name: /quality report/i }).click();
  await capture(page, "quality-report", () => [
    page.getByRole("heading", { name: "Quality report" }),
    page.getByText("Pass rate"),
    page.getByText("error", { exact: true }).first(),
  ]);

  // The dashboard last, so it lists the dataset and both runs.
  await page.getByRole("link", { name: /d&d labs/i }).click();
  await capture(page, "dashboard", () => [
    page.getByRole("heading", { name: "Dashboard" }),
    page.getByRole("link", { name: datasetName }),
    page.getByRole("cell", { name: "cancelled" }),
  ]);
});
