import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiKeyGate } from "../../src/auth/ApiKeyGate";
import { renderWithProviders, SEEDED_API_KEY } from "../test-utils";

describe("ApiKeyGate", () => {
  it("shows the key entry form when no key is stored", () => {
    renderWithProviders(
      <ApiKeyGate>
        <p>Protected content</p>
      </ApiKeyGate>,
    );

    expect(screen.getByLabelText(/api key/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("renders children after a valid key is submitted", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ApiKeyGate>
        <p>Protected content</p>
      </ApiKeyGate>,
    );

    await user.type(screen.getByLabelText(/api key/i), SEEDED_API_KEY);
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("Protected content")).toBeInTheDocument();
  });

  it("shows an error for an invalid key", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ApiKeyGate>
        <p>Protected content</p>
      </ApiKeyGate>,
    );

    await user.type(screen.getByLabelText(/api key/i), "not-a-real-key");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/not recognized/i);
    });
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });
});
