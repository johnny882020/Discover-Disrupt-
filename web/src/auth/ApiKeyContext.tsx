/**
 * React context that carries the current org's API key and identity.
 *
 * The key lives in memory for the lifetime of the provider plus
 * `sessionStorage` (never `localStorage`, so it doesn't outlive the tab).
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { ApiError, apiClient, clearStoredApiKey, getStoredApiKey, setStoredApiKey } from "../api/client";
import type { OrgContext } from "../api/types";

interface ApiKeyState {
  apiKey: string | null;
  org: OrgContext | null;
  /** Submits a candidate key to `/auth/whoami`; throws on failure. */
  login: (key: string) => Promise<void>;
  logout: () => void;
}

const ApiKeyContextInternal = createContext<ApiKeyState | undefined>(undefined);

export function ApiKeyProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const [apiKey, setApiKey] = useState<string | null>(() => getStoredApiKey());
  const [org, setOrg] = useState<OrgContext | null>(null);

  const login = useCallback(async (key: string) => {
    const trimmed = key.trim();
    if (!trimmed) {
      throw new ApiError(401, "Enter an API key.");
    }
    const resolved = await apiClient.get<OrgContext>("/auth/whoami", trimmed);
    setStoredApiKey(trimmed);
    setApiKey(trimmed);
    setOrg(resolved);
  }, []);

  const logout = useCallback(() => {
    clearStoredApiKey();
    setApiKey(null);
    setOrg(null);
  }, []);

  const value = useMemo<ApiKeyState>(
    () => ({ apiKey, org, login, logout }),
    [apiKey, org, login, logout],
  );

  return <ApiKeyContextInternal.Provider value={value}>{children}</ApiKeyContextInternal.Provider>;
}

export function useApiKey(): ApiKeyState {
  const ctx = useContext(ApiKeyContextInternal);
  if (!ctx) {
    throw new Error("useApiKey must be used within an ApiKeyProvider.");
  }
  return ctx;
}
