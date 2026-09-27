/**
 * Shared setup for the e2e specs: provisioning a fresh org through the admin
 * API, and signing in to the web app with its API key.
 *
 * Every test provisions its own org, so retries and repeated runs against
 * the same database never collide. Reads:
 * - DNDLABS_ADMIN_BOOTSTRAP_SECRET: the target API's admin bootstrap secret.
 * - E2E_API_URL (optional): the API base URL; defaults to the local API.
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";

const ADMIN_SECRET = process.env.DNDLABS_ADMIN_BOOTSTRAP_SECRET ?? "";
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";

export interface ProvisionedOrg {
  orgId: string;
  apiKey: string;
  email: string;
  invitePath: string;
}

/** Create an org (with its API key) and an invitation for its first admin. */
export async function provisionOrg(request: APIRequestContext): Promise<ProvisionedOrg> {
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
export function pathOf(url: string): string {
  const link = new URL(url);
  return `${link.pathname}${link.hash}`;
}

/** Sign in to the web app with an organization API key and wait for the dashboard. */
export async function signInWithApiKey(page: Page, apiKey: string): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: /use an api key instead/i }).click();
  await page.getByLabel("API key").fill(apiKey);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
}
