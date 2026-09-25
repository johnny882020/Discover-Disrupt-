import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { setStoredApiKey } from "../../src/api/client";
import { ExportPanel } from "../../src/screens/ExportPanel";
import { renderWithProviders, SEEDED_API_KEY } from "../test-utils";

describe("ExportPanel screen", () => {
  beforeEach(() => {
    setStoredApiKey(SEEDED_API_KEY);
    URL.createObjectURL = URL.createObjectURL ?? (() => "blob:mock");
    URL.revokeObjectURL = URL.revokeObjectURL ?? (() => undefined);
  });

  it("downloads the selected format", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/datasets/:datasetId/export" element={<ExportPanel />} />
      </Routes>,
      { route: "/datasets/dataset-aspirin/export" },
    );

    expect(await screen.findByRole("button", { name: /download csv/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /download csv/i }));

    expect(await screen.findByText(/download started/i)).toBeInTheDocument();
  });
});
