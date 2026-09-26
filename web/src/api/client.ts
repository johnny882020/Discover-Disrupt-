/**
 * Thin fetch wrapper for the D&D Labs API.
 *
 * Every request carries the current credential, read from `sessionStorage`
 * (mirroring `SessionContext`): a sign-in session token as
 * `Authorization: Bearer`, or an organization API key as `X-API-Key`. Any
 * non-2xx response throws a typed `ApiError` carrying the backend's
 * `detail` message; a 401 on a credentialed request also notifies the
 * registered unauthorized handler, so an expired session signs the user out.
 */
import type { ApiErrorBody } from "./types";

/** How the current user authenticates: a sign-in session, or an API key. */
export type Credential = { kind: "session"; token: string } | { kind: "api_key"; key: string };

export const CREDENTIAL_STORAGE_KEY = "dndlabs.credential";

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

function isCredential(value: unknown): value is Credential {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    (candidate.kind === "session" && typeof candidate.token === "string") ||
    (candidate.kind === "api_key" && typeof candidate.key === "string")
  );
}

/** Read the stored credential, if any (ignoring anything malformed). */
export function getStoredCredential(): Credential | null {
  try {
    const raw = sessionStorage.getItem(CREDENTIAL_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return isCredential(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Persist the credential for this tab only (`sessionStorage`, never
 * `localStorage`, so it does not outlive the browser tab).
 */
export function setStoredCredential(credential: Credential): void {
  try {
    sessionStorage.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify(credential));
  } catch {
    // sessionStorage may be unavailable (e.g. private browsing); the
    // in-memory SessionContext state still carries it for this tab.
  }
}

/** Remove the stored credential. */
export function clearStoredCredential(): void {
  try {
    sessionStorage.removeItem(CREDENTIAL_STORAGE_KEY);
  } catch {
    // Nothing to clean up if storage isn't available.
  }
}

let unauthorizedHandler: (() => void) | null = null;

/**
 * Register the callback run when a credentialed request gets a 401 (the
 * session expired or was revoked). Returns a function that unregisters it.
 */
export function setUnauthorizedHandler(handler: () => void): () => void {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) {
      unauthorizedHandler = null;
    }
  };
}

function authHeaders(credential: Credential | null): Record<string, string> {
  if (credential?.kind === "session") {
    return { Authorization: `Bearer ${credential.token}` };
  }
  if (credential?.kind === "api_key") {
    return { "X-API-Key": credential.key };
  }
  return {};
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
  /** Overrides the stored credential; `null` sends the request without one. */
  credential?: Credential | null;
  /** Parse the response as a Blob instead of JSON (for file downloads). */
  asBlob?: boolean;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const credential = options.credential === undefined ? getStoredCredential() : options.credential;
  const headers = authHeaders(credential);
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
    if (response.status === 401 && credential !== null && options.credential === undefined) {
      unauthorizedHandler?.();
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

/**
 * Typed API client covering every route this frontend consumes. Each call
 * uses the stored credential unless one is passed explicitly (`null` for an
 * unauthenticated call such as sign-in).
 */
export const apiClient = {
  get: <T>(path: string, credential?: Credential | null, signal?: AbortSignal) =>
    request<T>(path, { method: "GET", credential, signal }),
  post: <T>(path: string, body?: unknown, credential?: Credential | null) =>
    request<T>(path, { method: "POST", body, credential }),
  del: <T>(path: string, credential?: Credential | null) =>
    request<T>(path, { method: "DELETE", credential }),
  getBlob: (path: string, credential?: Credential | null) =>
    request<Blob>(path, { method: "GET", credential, asBlob: true }),
};

export { BASE_URL };
