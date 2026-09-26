/**
 * The session context object and its value type, split out from
 * `SessionContext.tsx` so that file exports only the `SessionProvider`
 * component — a file mixing component and non-component exports breaks
 * React Fast Refresh.
 */
import { createContext } from "react";
import type { Credential } from "../api/client";
import type { OrgContext } from "../api/types";

/** Where the app is in establishing who the user is. */
export type SessionStatus = "checking" | "signed_out" | "signed_in";

export interface SessionState {
  status: SessionStatus;
  credential: Credential | null;
  /** The authenticated principal and its organization, once signed in. */
  org: OrgContext | null;
  /** Why the user was signed out (e.g. an expired session), if not by choice. */
  notice: string | null;
  /** Signs in with an email and password; throws `ApiError` on failure. */
  signIn: (email: string, password: string) => Promise<void>;
  /** Signs in with an organization API key; throws `ApiError` on failure. */
  signInWithApiKey: (key: string) => Promise<void>;
  /** Redeems an invitation with a chosen password and signs the new user in. */
  acceptInvitation: (token: string, password: string) => Promise<void>;
  /** Ends the session server-side (for sessions) and forgets the credential. */
  signOut: () => Promise<void>;
}

export const SessionContextInternal = createContext<SessionState | undefined>(undefined);
