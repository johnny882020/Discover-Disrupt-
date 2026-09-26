/**
 * Holds who the user is: their credential (a sign-in session token, or an
 * organization API key) and the org context it resolves to.
 *
 * The credential lives in memory plus `sessionStorage` (never
 * `localStorage`, so it does not outlive the tab). A stored credential is
 * re-verified against `/auth/whoami` on load, and any 401 from the API
 * (expired or revoked session) signs the user out. Cached query data is
 * cleared whenever the identity changes, so one org's data is never shown
 * to another.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ApiError,
  apiClient,
  clearStoredCredential,
  getStoredCredential,
  setStoredCredential,
  setUnauthorizedHandler,
  type Credential,
} from "../api/client";
import type { OrgContext, SessionCreated } from "../api/types";
import { SessionContextInternal, type SessionState } from "./sessionContextValue";

const EXPIRED_NOTICE = "Your session has ended. Please sign in again.";

export function SessionProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const queryClient = useQueryClient();
  const [credential, setCredential] = useState<Credential | null>(() => getStoredCredential());
  const [org, setOrg] = useState<OrgContext | null>(null);
  const [checking, setChecking] = useState<boolean>(() => getStoredCredential() !== null);
  const [notice, setNotice] = useState<string | null>(null);

  const forget = useCallback(
    (reason: string | null) => {
      clearStoredCredential();
      queryClient.clear();
      setCredential(null);
      setOrg(null);
      setNotice(reason);
    },
    [queryClient],
  );

  const establish = useCallback(
    async (next: Credential) => {
      const resolved = await apiClient.get<OrgContext>("/auth/whoami", next);
      setStoredCredential(next);
      queryClient.clear();
      setCredential(next);
      setOrg(resolved);
      setNotice(null);
    },
    [queryClient],
  );

  // Re-verify a credential restored from sessionStorage.
  useEffect(() => {
    const stored = getStoredCredential();
    if (!stored) {
      return;
    }
    let cancelled = false;
    apiClient
      .get<OrgContext>("/auth/whoami", stored)
      .then((resolved) => {
        if (!cancelled) {
          setOrg(resolved);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          forget(
            err instanceof ApiError && err.status === 401
              ? EXPIRED_NOTICE
              : "Could not reach the server. Please sign in again.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setChecking(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [forget]);

  useEffect(() => setUnauthorizedHandler(() => forget(EXPIRED_NOTICE)), [forget]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const session = await apiClient.post<SessionCreated>("/auth/login", { email, password }, null);
      await establish({ kind: "session", token: session.token });
    },
    [establish],
  );

  const signInWithApiKey = useCallback(
    async (key: string) => {
      const trimmed = key.trim();
      if (!trimmed) {
        throw new ApiError(401, "Enter an API key.");
      }
      await establish({ kind: "api_key", key: trimmed });
    },
    [establish],
  );

  const acceptInvitation = useCallback(
    async (token: string, password: string) => {
      const session = await apiClient.post<SessionCreated>("/auth/invitations/accept", { token, password }, null);
      await establish({ kind: "session", token: session.token });
    },
    [establish],
  );

  const signOut = useCallback(async () => {
    if (credential?.kind === "session") {
      try {
        await apiClient.post<void>("/auth/logout", undefined, credential);
      } catch {
        // Already expired or unreachable: forgetting it locally is enough.
      }
    }
    forget(null);
  }, [credential, forget]);

  const status = org ? "signed_in" : checking ? "checking" : "signed_out";

  const value = useMemo<SessionState>(
    () => ({ status, credential, org, notice, signIn, signInWithApiKey, acceptInvitation, signOut }),
    [status, credential, org, notice, signIn, signInWithApiKey, acceptInvitation, signOut],
  );

  return <SessionContextInternal.Provider value={value}>{children}</SessionContextInternal.Provider>;
}
