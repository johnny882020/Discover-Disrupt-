import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { getStoredCredential } from "../../src/api/client";
import { SEED_USERS, invitationsStore } from "../../src/mocks/data";
import { ResetPassword } from "../../src/screens/ResetPassword";
import { renderWithProviders, SEEDED_MEMBER } from "../test-utils";

const TOKEN = "ddl_inv_resettest00000000000000000000";

function seedResetToken(): void {
  invitationsStore[TOKEN] = {
    invitation: {
      id: "ffffffff-ffff-ffff-ffff-ffffffffffff",
      org_id: SEED_USERS[SEEDED_MEMBER.email].user.org_id,
      email: SEEDED_MEMBER.email,
      role: "member",
      purpose: "password_reset",
      created_by: null,
      created_at: "2026-09-26T09:00:00Z",
      expires_at: "2099-01-01T00:00:00Z",
      accepted_at: null,
      revoked_at: null,
    },
    org_name: "Acme Therapeutics",
  };
}

function renderReset(hash: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/reset" element={<ResetPassword />} />
      <Route path="/" element={<p>Home</p>} />
    </Routes>,
    { route: `/reset${hash}` },
  );
}

describe("ResetPassword", () => {
  afterEach(() => {
    delete invitationsStore[TOKEN];
    SEED_USERS[SEEDED_MEMBER.email].password = SEEDED_MEMBER.password;
  });

  it("sets a new password and signs the user in", async () => {
    seedResetToken();
    const user = userEvent.setup();
    renderReset(`#token=${TOKEN}`);
    expect(await screen.findByText(SEEDED_MEMBER.email)).toBeInTheDocument();
    await user.type(screen.getByLabelText("New password"), "a brand new passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "a brand new passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(await screen.findByText("Home")).toBeInTheDocument();
    expect(getStoredCredential()?.kind).toBe("session");
    expect(SEED_USERS[SEEDED_MEMBER.email].password).toBe("a brand new passphrase");
  });

  it("rejects an invitation token used as a reset link", async () => {
    renderReset("#token=ddl_inv_welcome000000000000000000000");
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid, expired or already used/i);
    expect(screen.getByText(/expire after 24 hours/i)).toBeInTheDocument();
  });
});
