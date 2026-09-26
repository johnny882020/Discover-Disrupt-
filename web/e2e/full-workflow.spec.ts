/**
 * End-to-end workflows against a real backend, driven through the
 * production build:
 *
 * 1. An operator bootstraps an org and invites its admin (admin API); the
 *    admin accepts the invitation by choosing a password, signs out, signs
 *    back in, runs a CSV pipeline, inspects the dataset and its quality
 *    report, and exports it.
 * 2. The org's API key signs in to the web app as well.
 *
 * Each test provisions its own org and invitation, so retries and repeated
 * runs against the same database never collide. Requires a running API
 * (see `playwright.config.ts`) and:
 * - DNDLABS_ADMIN_BOOTSTRAP_SECRET: that API's admin bootstrap secret.
 * - E2E_API_URL (optional): the API base URL; defaults to the local API.
 * - E2E_CSV_PATH (optional): CSV path readable by the API server; defaults
 *   to the bundled fixture, relative to the repo root the API runs from.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const ADMIN_SECRET = process.env.DNDLABS_ADMIN_BOOTSTRAP_SECRET ?? "";
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
const CSV_PATH = process.env.E2E_CSV_PATH ?? "tests/fixtures/lab_export_malformed.csv";
const PASSWORD = "e2e correct horse battery";

interface ProvisionedOrg {
  orgId: string;
  apiKey: string;
  email: string;
  invitePath: string;
}

async function provisionOrg(request: APIRequestContext): Promise<ProvisionedOrg> {
  if (!ADMIN_SECRET) {
    throw new Error("Set DNDLABS_ADMIN_BOOTSTRAP_SECRET to the target API's admin secret.");
  }
  const headers = { "X-Admin-Secret": ADMIN_SECRET };
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const org = await request.post(`${API_URL}/admin/orgs`, { headers, data: { name: `E2E Org ${suffix}` } });
  expect(org.status()).toBe(201);
  const { org_id: orgId, raw_key: apiKey } = (await org.json()) as { org_id: string; raw_key: string };

  const email = `admin-${suffix}@e2e.example`;
  const invitation = await request.post(`${API_URL}/admin/orgs/${orgId}/invitations`, {
    headers,
    data: { email },
  });
  expect(invitation.status()).toBe(201);
  const { accept_url: acceptUrl } = (await invitation.json()) as { accept_url: string };
  // Follow the link's path and fragment on the frontend under test.
  const link = new URL(acceptUrl);
  return { orgId, apiKey, email, invitePath: `${link.pathname}${link.hash}` };
}

async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Email")).toBeVisible();
}

test.describe("full pipeline workflow", () => {
  test("accept an invitation, sign in, run a pipeline, inspect it and export", async ({ page, request }) => {
    const org = await provisionOrg(request);
    const datasetName = `E2E dataset ${Date.now()}`;
    const datasetPattern = new RegExp(datasetName, "i");

    // Accept the invitation by choosing a password; this signs the admin in.
    await page.goto(org.invitePath);
    await expect(page.getByText(org.email)).toBeVisible();
    await expect(page).toHaveURL(/\/invite$/); // token removed from the address bar
    await page.getByLabel("New password").fill(PASSWORD);
    await page.getByLabel("Confirm password").fill(PASSWORD);
    await page.getByRole("button", { name: /create account/i }).click();
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();

    // The invitation is single-use.
    const reuse = await request.post(`${API_URL}/auth/invitations/preview`, {
      data: { token: new URLSearchParams(org.invitePath.split("#")[1]).get("token") },
    });
    expect(reuse.status()).toBe(400);

    // Sign out, then back in with the new password.
    await signOut(page);
    await page.getByLabel("Email").fill(org.email.toUpperCase());
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
    await expect(page.getByText(org.email)).toBeVisible();

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

    // Admins can invite teammates from the web app.
    await page.getByRole("link", { name: "Team" }).click();
    await page.getByLabel("Email").fill(`member-${Date.now()}@e2e.example`);
    await page.getByRole("button", { name: /create invitation/i }).click();
    await expect(page.getByLabel("Invitation link")).toHaveValue(/\/invite#token=ddl_inv_/);
  });

  test("sign in with an organization API key", async ({ page, request }) => {
    const org = await provisionOrg(request);
    await page.goto("/");
    await page.getByRole("button", { name: /use an api key instead/i }).click();
    await page.getByLabel("API key").fill(org.apiKey);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
    await page.getByRole("link", { name: "Account" }).click();
    await expect(page.getByText("Organization API key")).toBeVisible();
    await signOut(page);
  });
});
