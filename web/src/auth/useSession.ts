import { useContext } from "react";
import { SessionContextInternal, type SessionState } from "./sessionContextValue";

/** The current session; must be used inside a `SessionProvider`. */
export function useSession(): SessionState {
  const ctx = useContext(SessionContextInternal);
  if (!ctx) {
    throw new Error("useSession must be used within a SessionProvider.");
  }
  return ctx;
}
