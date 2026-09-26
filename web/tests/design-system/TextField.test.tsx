import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TextField } from "../../src/design-system/TextField";

describe("TextField", () => {
  it("labels the input and links the hint for assistive technology", () => {
    render(<TextField label="Password" hint="At least 12 characters." type="password" />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAccessibleDescription("At least 12 characters.");
  });

  it("omits the description when there is no hint", () => {
    render(<TextField label="Email" />);
    expect(screen.getByLabelText("Email")).not.toHaveAttribute("aria-describedby");
  });
});
