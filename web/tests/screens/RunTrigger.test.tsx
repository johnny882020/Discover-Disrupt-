import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { Dashboard } from "../../src/screens/Dashboard";
import { RunTrigger } from "../../src/screens/RunTrigger";
import { renderWithProviders, signInWithSeededKey } from "../test-utils";

describe("RunTrigger screen", () => {
  beforeEach(() => {
    signInWithSeededKey();
  });

  it("submits a CSV run and navigates to the new dataset", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/runs/new" element={<RunTrigger />} />
        <Route path="/datasets/:datasetId" element={<Dashboard />} />
      </Routes>,
      { route: "/runs/new" },
    );

    await user.type(screen.getByLabelText(/csv path/i), "uploads/compounds.csv");
    await user.click(screen.getByRole("button", { name: /start run/i }));

    expect(await screen.findByText(/dashboard/i)).toBeInTheDocument();
  });
});
