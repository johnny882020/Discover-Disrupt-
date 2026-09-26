import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExportPanel } from "../../src/screens/ExportPanel";
import { renderWithProviders, signInWithSeededKey } from "../test-utils";

describe("ExportPanel screen", () => {
  beforeEach(() => {
    signInWithSeededKey();
    URL.createObjectURL = URL.createObjectURL ?? (() => "blob:mock");
    URL.revokeObjectURL = URL.revokeObjectURL ?? (() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("downloads the selected format", async () => {
    // jsdom cannot navigate; capture the download anchor's click instead.
    const clicked: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push(this);
    });
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
    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toMatch(/\.csv$/);
  });
});
