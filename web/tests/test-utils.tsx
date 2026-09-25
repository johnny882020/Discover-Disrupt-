/** Shared test render helpers: wraps components with the app's providers. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { ApiKeyProvider } from "../src/auth/ApiKeyContext";

export function renderWithProviders(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiKeyProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </ApiKeyProvider>
    </QueryClientProvider>,
  );
}

export const SEEDED_API_KEY = "dnd_live_acme0000000000000000000000";
