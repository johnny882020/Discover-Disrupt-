import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import {
  ApiError,
  BASE_URL,
  CREDENTIAL_STORAGE_KEY,
  apiClient,
  formatErrorDetail,
  getStoredCredential,
  setStoredCredential,
  setUnauthorizedHandler,
  type Credential,
} from "../../src/api/client";
import { server } from "../../src/mocks/server";

describe("formatErrorDetail", () => {
  it("passes a string detail through", () => {
    expect(formatErrorDetail("dataset not found")).toBe("dataset not found");
  });

  it("joins FastAPI 422 items by their msg, without pydantic's prefix", () => {
    expect(
      formatErrorDetail([
        { loc: ["body"], msg: "Value error, pubchem source requires at least one identifier", type: "value_error" },
        { loc: ["body", "source"], msg: "Input should be 'pubchem'", type: "enum" },
      ]),
    ).toBe("pubchem source requires at least one identifier; Input should be 'pubchem'");
  });

  it("returns null for a missing or empty detail", () => {
    expect(formatErrorDetail(undefined)).toBeNull();
    expect(formatErrorDetail("")).toBeNull();
    expect(formatErrorDetail([])).toBeNull();
  });
});

async function rejectionOf(promise: Promise<unknown>): Promise<ApiError> {
  const error: unknown = await promise.then(
    () => {
      throw new Error("expected the request to fail");
    },
    (e: unknown) => e,
  );
  if (!(error instanceof ApiError)) {
    throw new Error(`expected an ApiError, got ${String(error)}`);
  }
  return error;
}

const KEY: Credential = { kind: "api_key", key: "ddl_live_acme0000000000000000000000" };

describe("apiClient errors", () => {
  it("raises an ApiError with a readable message for a 422 validation error", async () => {
    server.use(
      http.post(`${BASE_URL}/pipelines/run`, () =>
        HttpResponse.json(
          {
            detail: [
              {
                loc: ["body"],
                msg: "Value error, pubchem source requires at least one identifier (CID)",
                type: "value_error",
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );

    const error = await rejectionOf(apiClient.post("/pipelines/run", { source: "pubchem" }, KEY));

    expect(error.status).toBe(422);
    expect(error.message).toBe("pubchem source requires at least one identifier (CID)");
  });

  it("falls back to a generic message when the body isn't JSON", async () => {
    server.use(http.get(`${BASE_URL}/datasets`, () => new HttpResponse("oops", { status: 502 })));

    const error = await rejectionOf(apiClient.get("/datasets", KEY));

    expect(error.status).toBe(502);
    expect(error.message).toBe("Request failed with status 502");
  });
});

describe("credentials", () => {
  function echoHeaders(): void {
    server.use(
      http.get(`${BASE_URL}/echo`, ({ request }) =>
        HttpResponse.json({
          apiKey: request.headers.get("X-API-Key"),
          authorization: request.headers.get("Authorization"),
        }),
      ),
    );
  }

  it("sends a session as a bearer token and an API key as X-API-Key", async () => {
    echoHeaders();
    const session = await apiClient.get("/echo", { kind: "session", token: "ddl_sess_abc" });
    expect(session).toEqual({ apiKey: null, authorization: "Bearer ddl_sess_abc" });
    const key = await apiClient.get("/echo", { kind: "api_key", key: "ddl_live_x" });
    expect(key).toEqual({ apiKey: "ddl_live_x", authorization: null });
  });

  it("uses the stored credential by default and none when passed null", async () => {
    echoHeaders();
    setStoredCredential({ kind: "session", token: "ddl_sess_stored" });
    expect(await apiClient.get("/echo")).toEqual({ apiKey: null, authorization: "Bearer ddl_sess_stored" });
    expect(await apiClient.get("/echo", null)).toEqual({ apiKey: null, authorization: null });
  });

  it("ignores a malformed stored credential", () => {
    sessionStorage.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify({ kind: "session" }));
    expect(getStoredCredential()).toBeNull();
    sessionStorage.setItem(CREDENTIAL_STORAGE_KEY, "{not json");
    expect(getStoredCredential()).toBeNull();
  });

  it("notifies the unauthorized handler on a 401 with the stored credential only", async () => {
    server.use(http.get(`${BASE_URL}/datasets`, () => HttpResponse.json({ detail: "expired" }, { status: 401 })));
    let calls = 0;
    const unregister = setUnauthorizedHandler(() => {
      calls += 1;
    });
    setStoredCredential({ kind: "session", token: "ddl_sess_old" });

    await rejectionOf(apiClient.get("/datasets"));
    expect(calls).toBe(1);

    await rejectionOf(apiClient.get("/datasets", KEY)); // explicit credential: caller handles it
    expect(calls).toBe(1);

    unregister();
    await rejectionOf(apiClient.get("/datasets"));
    expect(calls).toBe(1);
  });
});
