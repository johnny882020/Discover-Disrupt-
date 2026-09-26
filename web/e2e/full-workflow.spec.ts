/**
 * End-to-end workflows against a real backend, driven through the
 * production build:
 *
 * 1. An operator bootstraps an org and invites its admin (admin API); the
 *    admin accepts the invitation by choosing a password, signs out, signs
 *    back in, runs a CSV pipeline, inspects the dataset and its quality
 *    report, and exports it.
 * 2. An admin manages the team: invites a member, issues them a
 *    password-reset link, and removes them.
 * 3. The org's API key signs in to the web app as well.
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
  return { orgId, apiKey, email, invitePath: pathOf(acceptUrl) };
}

/** A one-time link's path and fragment, followed on the frontend under test. */
function pathOf(url: string): string {
  const link = new URL(url);
  return `${link.pathname}${link.hash}`;
}

async function acceptInvitation(page: Page, invitePath: string, password = PASSWORD): Promise<void> {
  await page.goto(invitePath);
  await page.getByLabel("New password").fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
}

async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
}

async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  // Wait for the sign-in screen itself: an "Email" field alone is ambiguous,
  // since the Team page's invite form has one too.
  await expect(page.getByText("Sign in to your organization.")).toBeVisible();
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
    await expect(page.getByLabel("One-time link")).toHaveValue(/\/invite#token=ddl_inv_/);
  });

  test("manage the team: invite a member, reset their password, remove them", async ({ page, request }) => {
    const org = await provisionOrg(request);
    const memberEmail = `member-${Date.now()}@e2e.example`;
    const memberPassword = "e2e member passphrase";
    const resetPassword = "e2e member new passphrase";

    // The admin accepts their invitation, then invites a member from the Team page.
    await acceptInvitation(page, org.invitePath);
    await page.getByRole("link", { name: "Team" }).click();
    await page.getByLabel("Email").fill(memberEmail);
    await page.getByRole("button", { name: /create invitation/i }).click();
    const inviteUrl = await page.getByLabel("One-time link").inputValue();
    await expect(page.getByRole("cell", { name: memberEmail })).toBeVisible(); // pending

    // The member accepts, then signs out.
    await signOut(page);
    await acceptInvitation(page, pathOf(inviteUrl), memberPassword);
    await signOut(page);

    // The admin issues a password-reset link for the member.
    await signIn(page, org.email, PASSWORD);
    await page.getByRole("link", { name: "Team" }).click();
    const memberRow = page.getByRole("row").filter({ hasText: memberEmail });
    await memberRow.getByRole("button", { name: "Reset password" }).click();
    const resetUrl = await page.getByLabel("One-time link").inputValue();
    expect(resetUrl).toMatch(/\/reset#token=ddl_inv_/);
    await signOut(page);

    // The member sets a new password from the link; the old one stops working.
    await page.goto(pathOf(resetUrl));
    await expect(page.getByText(memberEmail)).toBeVisible();
    await page.getByLabel("New password").fill(resetPassword);
    await page.getByLabel("Confirm password").fill(resetPassword);
    await page.getByRole("button", { name: "Set new password" }).click();
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
    await signOut(page);
    await page.getByLabel("Email").fill(memberEmail);
    await page.getByLabel("Password").fill(memberPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toHaveText("invalid email or password");

    // The admin removes the member; the member can no longer sign in.
    await signIn(page, org.email, PASSWORD);
    await page.getByRole("link", { name: "Team" }).click();
    await memberRow.getByRole("button", { name: "Remove" }).click();
    await memberRow.getByRole("button", { name: "Confirm removal" }).click();
    await expect(page.getByRole("cell", { name: memberEmail })).toHaveCount(0);
    await signOut(page);
    await page.getByLabel("Email").fill(memberEmail);
    await page.getByLabel("Password").fill(resetPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toHaveText("invalid email or password");
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
