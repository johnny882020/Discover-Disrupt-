/** Shared test render helpers: wraps components with the app's providers. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { setStoredCredential } from "../src/api/client";
import { SessionProvider } from "../src/auth/SessionContext";

export function renderWithProviders(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

/** Seeded mock API credentials (see `src/mocks/data.ts`). */
export const SEEDED_API_KEY = "ddl_live_acme0000000000000000000000";
export const SEEDED_ADMIN = { email: "ada@acme.example", password: "correct horse battery" };
export const SEEDED_MEMBER = { email: "bob@acme.example", password: "a member's passphrase" };
export const SEEDED_INVITATION_TOKEN = "ddl_inv_welcome000000000000000000000";

/** Store the seeded org API key, as if the user had signed in with it. */
export function signInWithSeededKey(): void {
  setStoredCredential({ kind: "api_key", key: SEEDED_API_KEY });
}
