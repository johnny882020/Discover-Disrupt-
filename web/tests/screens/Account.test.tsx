import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { getStoredCredential, setStoredCredential } from "../../src/api/client";
import { AuthGate } from "../../src/auth/AuthGate";
import { SEED_USERS } from "../../src/mocks/data";
import { Account } from "../../src/screens/Account";
import { renderWithProviders, SEEDED_ADMIN, signInWithSeededKey } from "../test-utils";

async function signInAsAdmin(): Promise<void> {
  const response = await fetch("http://localhost:8000/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(SEEDED_ADMIN),
  });
  const session = (await response.json()) as { token: string };
  setStoredCredential({ kind: "session", token: session.token });
}

function renderAccount() {
  return renderWithProviders(
    <AuthGate>
      <Account />
    </AuthGate>,
  );
}

describe("Account", () => {
  afterEach(() => {
    SEED_USERS[SEEDED_ADMIN.email].password = SEEDED_ADMIN.password;
  });

  it("shows the signed-in user and changes their password", async () => {
    const user = userEvent.setup();
    await signInAsAdmin();
    renderAccount();

    expect(await screen.findByText(SEEDED_ADMIN.email)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Current password"), SEEDED_ADMIN.password);
    await user.type(screen.getByLabelText("New password"), "an even better passphrase");
    await user.type(screen.getByLabelText("Confirm new password"), "an even better passphrase");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    expect(await screen.findByRole("status")).toHaveTextContent(/password changed/i);
    expect(SEED_USERS[SEEDED_ADMIN.email].password).toBe("an even better passphrase");
  });

  it("shows the server's message for a wrong current password", async () => {
    const user = userEvent.setup();
    await signInAsAdmin();
    renderAccount();
    await user.type(await screen.findByLabelText("Current password"), "not my password");
    await user.type(screen.getByLabelText("New password"), "an even better passphrase");
    await user.type(screen.getByLabelText("Confirm new password"), "an even better passphrase");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("current password is incorrect");
    expect(getStoredCredential()).not.toBeNull(); // a 403 does not sign the user out
  });

  it("explains that an API key has no password", async () => {
    signInWithSeededKey();
    renderAccount();
    expect(await screen.findByText("Organization API key")).toBeInTheDocument();
    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
  });
});
