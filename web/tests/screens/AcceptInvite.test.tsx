import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { getStoredCredential } from "../../src/api/client";
import { invitationsStore } from "../../src/mocks/data";
import { AcceptInvite } from "../../src/screens/AcceptInvite";
import { renderWithProviders, SEEDED_INVITATION_TOKEN } from "../test-utils";

function Where(): React.JSX.Element {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.hash}`}</p>;
}

function renderInvite(hash: string) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/invite" element={<AcceptInvite />} />
        <Route path="/" element={<p>Home</p>} />
      </Routes>
      <Where />
    </>,
    { route: `/invite${hash}` },
  );
}

const SEEDED_INVITATION = structuredClone(invitationsStore[SEEDED_INVITATION_TOKEN]);

describe("AcceptInvite", () => {
  beforeEach(() => {
    // Accepting consumes the (shared, in-memory) invitation; restore it.
    invitationsStore[SEEDED_INVITATION_TOKEN] = structuredClone(SEEDED_INVITATION);
  });

  it("previews the invitation and removes the token from the address bar", async () => {
    renderInvite(`#token=${SEEDED_INVITATION_TOKEN}`);
    expect(await screen.findByText("cleo@acme.example")).toBeInTheDocument();
    expect(screen.getByText("Acme Therapeutics")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/invite$/);
  });

  it("creates the account and signs in", async () => {
    const user = userEvent.setup();
    renderInvite(`#token=${SEEDED_INVITATION_TOKEN}`);
    await user.type(await screen.findByLabelText("New password"), "a brand new passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "a brand new passphrase");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText("Home")).toBeInTheDocument();
    expect(getStoredCredential()?.kind).toBe("session");
  });

  it("checks length and confirmation before submitting", async () => {
    const user = userEvent.setup();
    renderInvite(`#token=${SEEDED_INVITATION_TOKEN}`);
    await user.type(await screen.findByLabelText("New password"), "short");
    await user.type(screen.getByLabelText("Confirm password"), "short");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least 12/i);

    await user.clear(screen.getByLabelText("New password"));
    await user.type(screen.getByLabelText("New password"), "a long enough passphrase");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/do not match/i);
    expect(getStoredCredential()).toBeNull();
  });

  it("explains an invalid or used invitation", async () => {
    renderInvite("#token=ddl_inv_unknown");
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid, expired or already used/i);
    expect(screen.getByRole("link", { name: /go to sign in/i })).toBeInTheDocument();
  });

  it("explains a link without a token", () => {
    renderInvite("");
    expect(screen.getByRole("alert")).toHaveTextContent(/incomplete/i);
  });
});
