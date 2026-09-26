import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { setStoredCredential } from "../../src/api/client";
import { AuthGate } from "../../src/auth/AuthGate";
import { SEED_USERS } from "../../src/mocks/data";
import { Team } from "../../src/screens/Team";
import { renderWithProviders, SEEDED_ADMIN, SEEDED_MEMBER, signInWithSeededKey } from "../test-utils";

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

describe("Team", () => {
  it("lets an admin create an invitation and copy its one-time link", async () => {
    const user = userEvent.setup(); // installs a clipboard stub
    await signInAs(SEEDED_ADMIN.email, SEEDED_ADMIN.password);
    renderTeam();

    await user.type(await screen.findByLabelText("Email"), "dora@acme.example");
    await user.selectOptions(screen.getByRole("combobox"), "admin");
    await user.click(screen.getByRole("button", { name: /create invitation/i }));

    const link = await screen.findByLabelText("Invitation link");
    expect((link as HTMLInputElement).value).toMatch(/\/invite#token=ddl_inv_/);
    expect(screen.getByRole("heading", { name: /invitation for dora@acme.example/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(await navigator.clipboard.readText()).toBe((link as HTMLInputElement).value);
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows the server's reason when an invitation is refused", async () => {
    const user = userEvent.setup();
    signInWithSeededKey(); // API keys act as admins
    renderTeam();
    await user.type(await screen.findByLabelText("Email"), SEEDED_MEMBER.email);
    await user.click(screen.getByRole("button", { name: /create invitation/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already belongs to a member/i);
  });

  it("tells members that only admins can invite", async () => {
    await signInAs(SEEDED_MEMBER.email, SEEDED_MEMBER.password);
    renderTeam();
    expect(await screen.findByText(/only your organization's admins/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create invitation/i })).not.toBeInTheDocument();
    expect(SEED_USERS[SEEDED_MEMBER.email].user.role).toBe("member");
  });
});
