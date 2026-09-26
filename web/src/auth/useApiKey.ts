import { useContext } from "react";
import { ApiKeyContextInternal, type ApiKeyState } from "./apiKeyContextValue";

export function useApiKey(): ApiKeyState {
  const ctx = useContext(ApiKeyContextInternal);
  if (!ctx) {
    throw new Error("useApiKey must be used within an ApiKeyProvider.");
  }
  return ctx;
}
