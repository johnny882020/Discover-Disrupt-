/**
 * Thin fetch wrapper for the D&D Labs API.
 *
 * Reads the API key from `sessionStorage` (mirroring `ApiKeyContext`), sets
 * the `X-API-Key` header on every request, and throws a typed `ApiError`
 * with the backend's `detail` message on any non-2xx response.
 */
import type { ApiErrorBody } from "./types";

export const API_KEY_STORAGE_KEY = "dndlabs.apiKey";

const BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api/v1";

/** An error raised by the API client for any non-2xx response. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Read the currently stored API key, if any. */
export function getStoredApiKey(): string | null {
  try {
    return sessionStorage.getItem(API_KEY_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Persist the API key for the duration of the browser session. */
export function setStoredApiKey(key: string): void {
  try {
    sessionStorage.setItem(API_KEY_STORAGE_KEY, key);
  } catch {
    // sessionStorage may be unavailable (e.g. private browsing); the
    // in-memory ApiKeyContext state still carries the key for this tab.
  }
}

/** Remove the stored API key. */
export function clearStoredApiKey(): void {
  try {
    sessionStorage.removeItem(API_KEY_STORAGE_KEY);
  } catch {
    // Nothing to clean up if storage isn't available.
  }
}

/**
 * Turn an error body's `detail` into a human-readable message. FastAPI's
 * 422 list is joined from each item's `msg`, minus pydantic's
 * "Value error, " prefix.
 */
export function formatErrorDetail(detail: ApiErrorBody["detail"] | undefined): string | null {
  if (typeof detail === "string") {
    return detail || null;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => item.msg.replace(/^Value error, /, ""))
      .filter((msg) => msg.length > 0);
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}

interface RequestOptions {
  method?: "GET" | "POST" | "DELETE" | "PUT" | "PATCH";
  body?: unknown;
  apiKey?: string | null;
  /** Parse the response as a Blob instead of JSON (for file downloads). */
  asBlob?: boolean;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const apiKey = options.apiKey ?? getStoredApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as Partial<ApiErrorBody>;
      detail = formatErrorDetail(body.detail) ?? detail;
    } catch {
      // Response body wasn't JSON; fall back to the generic message.
    }
    throw new ApiError(response.status, detail);
  }

  if (options.asBlob) {
    return (await response.blob()) as unknown as T;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** Typed API client covering every route this frontend consumes. */
export const apiClient = {
  get: <T>(path: string, apiKey?: string | null, signal?: AbortSignal) =>
    request<T>(path, { method: "GET", apiKey, signal }),
  post: <T>(path: string, body?: unknown, apiKey?: string | null) =>
    request<T>(path, { method: "POST", body, apiKey }),
  del: <T>(path: string, apiKey?: string | null) => request<T>(path, { method: "DELETE", apiKey }),
  getBlob: (path: string, apiKey?: string | null) =>
    request<Blob>(path, { method: "GET", apiKey, asBlob: true }),
};

export { BASE_URL };
