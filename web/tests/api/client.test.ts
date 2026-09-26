import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApiError, BASE_URL, apiClient, formatErrorDetail } from "../../src/api/client";
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

    const error = await rejectionOf(apiClient.post("/pipelines/run", { source: "pubchem" }, "key"));

    expect(error.status).toBe(422);
    expect(error.message).toBe("pubchem source requires at least one identifier (CID)");
  });

  it("falls back to a generic message when the body isn't JSON", async () => {
    server.use(http.get(`${BASE_URL}/datasets`, () => new HttpResponse("oops", { status: 502 })));

    const error = await rejectionOf(apiClient.get("/datasets", "key"));

    expect(error.status).toBe(502);
    expect(error.message).toBe("Request failed with status 502");
  });
});
