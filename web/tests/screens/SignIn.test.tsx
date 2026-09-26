import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SignIn } from "../../src/screens/SignIn";
import { renderWithProviders } from "../test-utils";

describe("SignIn", () => {
  it("defaults to email and password, with sign-in disabled until both are filled", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignIn />);
    const submit = screen.getByRole("button", { name: "Sign in" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Email"), "ada@acme.example");
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Password"), "x");
    expect(submit).toBeEnabled();
    expect(screen.getByText(/accounts are created from an invitation/i)).toBeInTheDocument();
  });

  it("switches between password and API key sign-in, clearing errors", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignIn />);
    await user.click(screen.getByRole("button", { name: /use an api key instead/i }));
    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "password");
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /use email and password instead/i }));
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("uses autocomplete hints password managers understand", () => {
    renderWithProviders(<SignIn />);
    expect(screen.getByLabelText("Email")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
  });
});
