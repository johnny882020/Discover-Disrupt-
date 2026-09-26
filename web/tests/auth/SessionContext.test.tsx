import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { BASE_URL, apiClient, getStoredCredential, setStoredCredential } from "../../src/api/client";
import { AuthGate } from "../../src/auth/AuthGate";
import { useSession } from "../../src/auth/useSession";
import { server } from "../../src/mocks/server";
import { renderWithProviders, signInWithSeededKey } from "../test-utils";

function Protected(): React.JSX.Element {
  const { org } = useSession();
  return <p>Signed in to {org?.org_name}</p>;
}

function renderGate() {
  return renderWithProviders(
    <AuthGate>
      <Protected />
    </AuthGate>,
  );
}

describe("SessionProvider", () => {
  it("restores a stored credential after verifying it", async () => {
    signInWithSeededKey();
    renderGate();
    expect(screen.getByText(/checking your session/i)).toBeInTheDocument();
    expect(await screen.findByText("Signed in to Acme Therapeutics")).toBeInTheDocument();
  });

  it("signs out with a notice when the stored session has expired", async () => {
    setStoredCredential({ kind: "session", token: "ddl_sess_expired" });
    renderGate();
    expect(await screen.findByRole("status")).toHaveTextContent(/session has ended/i);
    expect(getStoredCredential()).toBeNull();
  });

  it("signs out when a later request is rejected with 401", async () => {
    signInWithSeededKey();
    renderGate();
    expect(await screen.findByText("Signed in to Acme Therapeutics")).toBeInTheDocument();

    server.use(http.get(`${BASE_URL}/datasets`, () => HttpResponse.json({ detail: "revoked" }, { status: 401 })));
    await apiClient.get("/datasets").catch(() => undefined);

    await waitFor(() => expect(screen.getByLabelText("Email")).toBeInTheDocument());
  });

  it("reports an unreachable server when the stored credential cannot be verified", async () => {
    server.use(http.get(`${BASE_URL}/auth/whoami`, () => HttpResponse.error()));
    signInWithSeededKey();
    renderGate();
    expect(await screen.findByRole("status")).toHaveTextContent(/could not reach the server/i);
  });

  it("throws when used outside a provider", () => {
    function Orphan(): React.JSX.Element {
      useSession();
      return <p />;
    }
    expect(() => renderWithoutProvider(<Orphan />)).toThrow(/SessionProvider/);
  });
});

/** Render expecting a render error, keeping React's and jsdom's reports of it out of the output. */
function renderWithoutProvider(ui: React.JSX.Element): void {
  const original = console.error;
  const swallow = (event: ErrorEvent): void => event.preventDefault();
  console.error = () => undefined;
  window.addEventListener("error", swallow);
  try {
    render(ui);
  } finally {
    window.removeEventListener("error", swallow);
    console.error = original;
  }
}
