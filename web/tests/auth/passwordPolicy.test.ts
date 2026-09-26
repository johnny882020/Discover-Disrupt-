import { describe, expect, it } from "vitest";
import { MAX_PASSWORD_LENGTH, newPasswordProblem } from "../../src/auth/passwordPolicy";

describe("newPasswordProblem", () => {
  it("accepts a long matching password", () => {
    expect(newPasswordProblem("correct horse battery", "correct horse battery")).toBeNull();
  });

  it("rejects short, overlong and mismatched passwords", () => {
    expect(newPasswordProblem("short", "short")).toMatch(/at least 12/);
    const long = "x".repeat(MAX_PASSWORD_LENGTH + 1);
    expect(newPasswordProblem(long, long)).toMatch(/at most/);
    expect(newPasswordProblem("correct horse battery", "correct horse")).toMatch(/do not match/);
  });
});
