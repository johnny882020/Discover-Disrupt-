/**
 * The context object and its value type, split out from `ApiKeyContext.tsx`
 * so that file exports only the `ApiKeyProvider` component — a file mixing
 * component and non-component exports breaks React Fast Refresh.
 */
import { createContext } from "react";
import type { OrgContext } from "../api/types";

export interface ApiKeyState {
  apiKey: string | null;
  org: OrgContext | null;
  /** Submits a candidate key to `/auth/whoami`; throws on failure. */
  login: (key: string) => Promise<void>;
  logout: () => void;
}

export const ApiKeyContextInternal = createContext<ApiKeyState | undefined>(undefined);
