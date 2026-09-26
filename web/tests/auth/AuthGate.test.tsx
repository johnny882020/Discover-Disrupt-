import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { BASE_URL, getStoredCredential } from "../../src/api/client";
import { AuthGate } from "../../src/auth/AuthGate";
import { useSession } from "../../src/auth/useSession";
import { server } from "../../src/mocks/server";
import { renderWithProviders, SEEDED_ADMIN, SEEDED_API_KEY } from "../test-utils";

function Protected(): React.JSX.Element {
  const { org, signOut } = useSession();
  return (
    <div>
      <p>Signed in to {org?.org_name}</p>
      <button type="button" onClick={() => void signOut()}>
        Sign out
      </button>
    </div>
  );
}

function renderGate() {
  return renderWithProviders(
    <AuthGate>
      <Protected />
    </AuthGate>,
  );
}

describe("AuthGate", () => {
  it("shows the sign-in form when signed out", () => {
    renderGate();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.queryByText(/signed in to/i)).not.toBeInTheDocument();
  });

  it("signs in with email and password, then out again (revoking the session)", async () => {
    const user = userEvent.setup();
    renderGate();

    await user.type(screen.getByLabelText("Email"), SEEDED_ADMIN.email);
    await user.type(screen.getByLabelText("Password"), SEEDED_ADMIN.password);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Signed in to Acme Therapeutics")).toBeInTheDocument();
    const credential = getStoredCredential();
    expect(credential?.kind).toBe("session");

    let loggedOut = false;
    server.use(
      http.post(`${BASE_URL}/auth/logout`, () => {
        loggedOut = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
    expect(loggedOut).toBe(true);
    expect(getStoredCredential()).toBeNull();
  });

  it("shows the server's message for wrong credentials", async () => {
    const user = userEvent.setup();
    renderGate();
    await user.type(screen.getByLabelText("Email"), SEEDED_ADMIN.email);
    await user.type(screen.getByLabelText("Password"), "not the password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid email or password");
  });

  it("signs in with an API key", async () => {
    const user = userEvent.setup();
    renderGate();
    await user.click(screen.getByRole("button", { name: /use an api key instead/i }));
    await user.type(screen.getByLabelText("API key"), SEEDED_API_KEY);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Signed in to Acme Therapeutics")).toBeInTheDocument();
    expect(getStoredCredential()).toEqual({ kind: "api_key", key: SEEDED_API_KEY });
  });

  it("rejects an unknown API key", async () => {
    const user = userEvent.setup();
    renderGate();
    await user.click(screen.getByRole("button", { name: /use an api key instead/i }));
    await user.type(screen.getByLabelText("API key"), "ddl_live_bogus");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(getStoredCredential()).toBeNull();
  });
});
