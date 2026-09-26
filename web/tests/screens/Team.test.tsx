import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setStoredCredential } from "../../src/api/client";
import { AuthGate } from "../../src/auth/AuthGate";
import { SEED_USERS, invitationsStore, type SeedUser, type StoredToken } from "../../src/mocks/data";
import { Team } from "../../src/screens/Team";
import { renderWithProviders, SEEDED_ADMIN, SEEDED_MEMBER, signInWithSeededKey } from "../test-utils";

let usersBefore: Record<string, SeedUser>;
let tokensBefore: Record<string, StoredToken>;

beforeEach(() => {
  usersBefore = structuredClone(SEED_USERS);
  tokensBefore = structuredClone(invitationsStore);
});

afterEach(() => {
  for (const store of [SEED_USERS, invitationsStore] as Record<string, unknown>[]) {
    for (const key of Object.keys(store)) delete store[key];
  }
  Object.assign(SEED_USERS, usersBefore);
  Object.assign(invitationsStore, tokensBefore);
});

async function signInAs(email: string, password: string): Promise<void> {
  const response = await fetch("http://localhost:8000/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const session = (await response.json()) as { token: string };
  setStoredCredential({ kind: "session", token: session.token });
}

function renderTeam() {
  return renderWithProviders(
    <AuthGate>
      <Team />
    </AuthGate>,
  );
}

async function memberRow(email: string): Promise<HTMLElement> {
  const escaped = email.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const cell = await screen.findByText(new RegExp(`^${escaped}`));
  const row = cell.closest("tr");
  if (!row) throw new Error(`no row for ${email}`);
  return row;
}

describe("Team", () => {
  it("creates an invitation with a copyable one-time link, then lists it as pending", async () => {
    const user = userEvent.setup(); // installs a clipboard stub
    await signInAs(SEEDED_ADMIN.email, SEEDED_ADMIN.password);
    renderTeam();

    await user.type(await screen.findByLabelText("Email"), "dora@acme.example");
    await user.selectOptions(screen.getByRole("combobox", { name: "Role" }), "admin");
    await user.click(screen.getByRole("button", { name: /create invitation/i }));

    const link = (await screen.findByLabelText("One-time link")) as HTMLInputElement;
    expect(link.value).toMatch(/\/invite#token=ddl_inv_/);
    expect(screen.getByRole("heading", { name: /invitation for dora@acme.example/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(await navigator.clipboard.readText()).toBe(link.value);
    expect(await screen.findByText("dora@acme.example")).toBeInTheDocument(); // pending list
  });

  it("lists members, marks the current user, and changes a role", async () => {
    const user = userEvent.setup();
    await signInAs(SEEDED_ADMIN.email, SEEDED_ADMIN.password);
    renderTeam();

    expect(await screen.findByText(`${SEEDED_ADMIN.email} (you)`)).toBeInTheDocument();
    const bob = await memberRow(SEEDED_MEMBER.email);
    await user.selectOptions(within(bob).getByRole("combobox"), "admin");
    await waitFor(() => expect(SEED_USERS[SEEDED_MEMBER.email].user.role).toBe("admin"));
    expect(within(await memberRow(`${SEEDED_ADMIN.email} (you)`)).queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("refuses to demote the last admin and shows why", async () => {
    const user = userEvent.setup();
    await signInAs(SEEDED_ADMIN.email, SEEDED_ADMIN.password);
    renderTeam();
    const me = await memberRow(`${SEEDED_ADMIN.email} (you)`);
    await user.selectOptions(within(me).getByRole("combobox"), "member");
    expect(await screen.findByRole("alert")).toHaveTextContent("an organization must keep at least one admin");
  });

  it("removes a member after confirmation", async () => {
    const user = userEvent.setup();
    await signInAs(SEEDED_ADMIN.email, SEEDED_ADMIN.password);
    renderTeam();
    const bob = await memberRow(SEEDED_MEMBER.email);
    await user.click(within(bob).getByRole("button", { name: "Remove" }));
    await user.click(within(bob).getByRole("button", { name: "Cancel" }));
    await user.click(within(bob).getByRole("button", { name: "Remove" }));
    await user.click(within(bob).getByRole("button", { name: "Confirm removal" }));
    await waitFor(() => expect(screen.queryByText(SEEDED_MEMBER.email)).not.toBeInTheDocument());
    expect(SEED_USERS[SEEDED_MEMBER.email]).toBeUndefined();
  });

  it("issues a password-reset link for a member", async () => {
    const user = userEvent.setup();
    await signInAs(SEEDED_ADMIN.email, SEEDED_ADMIN.password);
    renderTeam();
    const bob = await memberRow(SEEDED_MEMBER.email);
    await user.click(within(bob).getByRole("button", { name: "Reset password" }));
    expect(await screen.findByRole("heading", { name: /password-reset link for bob@acme.example/i })).toBeInTheDocument();
    expect((screen.getByLabelText("One-time link") as HTMLInputElement).value).toMatch(/\/reset#token=ddl_inv_/);
  });

  it("revokes a pending invitation", async () => {
    const user = userEvent.setup();
    signInWithSeededKey(); // API keys act as admins
    renderTeam();
    expect(await screen.findByText("cleo@acme.example")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    expect(await screen.findByText("No pending invitations.")).toBeInTheDocument();
  });

  it("shows the server's reason when an invitation is refused", async () => {
    const user = userEvent.setup();
    signInWithSeededKey();
    renderTeam();
    await user.type(await screen.findByLabelText("Email"), SEEDED_MEMBER.email);
    await user.click(screen.getByRole("button", { name: /create invitation/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already belongs to a member/i);
  });

  it("tells members that only admins can manage the team", async () => {
    await signInAs(SEEDED_MEMBER.email, SEEDED_MEMBER.password);
    renderTeam();
    expect(await screen.findByText(/only your organization's admins/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create invitation/i })).not.toBeInTheDocument();
  });
});
