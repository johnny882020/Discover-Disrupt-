import { describe, expect, it } from "vitest";
import { ApiError } from "../../src/api/client";
import { authErrorMessage } from "../../src/auth/errorMessage";

describe("authErrorMessage", () => {
  it("shows an API error's message and a generic one for anything else", () => {
    expect(authErrorMessage(new ApiError(401, "invalid email or password"))).toBe("invalid email or password");
    expect(authErrorMessage(new TypeError("Failed to fetch"))).toMatch(/could not reach the server/i);
  });
});
