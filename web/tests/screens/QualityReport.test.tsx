import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { setStoredApiKey } from "../../src/api/client";
import { server } from "../../src/mocks/server";
import { QualityReport } from "../../src/screens/QualityReport";
import { renderWithProviders, SEEDED_API_KEY } from "../test-utils";

const BASE = "*/api/v1";

function renderForDataset(datasetId: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/datasets/:datasetId/quality-report" element={<QualityReport />} />
    </Routes>,
    { route: `/datasets/${datasetId}/quality-report` },
  );
}

describe("QualityReport screen", () => {
  beforeEach(() => {
    setStoredApiKey(SEEDED_API_KEY);
  });

  it("shows a loading state before the report arrives", () => {
    renderForDataset("dataset-aspirin");
    expect(screen.getByText(/loading quality report/i)).toBeInTheDocument();
  });

  it("renders the populated report with stats and issues", async () => {
    renderForDataset("dataset-aspirin");

    expect(await screen.findByText("80.0%")).toBeInTheDocument();
    expect(screen.getAllByText("missing_inchikey").length).toBeGreaterThan(0);
    expect(screen.getByText(/could not be deduplicated/i)).toBeInTheDocument();
  });

  it("shows an empty state when there are no issues", async () => {
    renderForDataset("dataset-empty");

    expect(await screen.findByText(/no issues were found/i)).toBeInTheDocument();
    expect(screen.getByText(/no issues to review/i)).toBeInTheDocument();
  });

  it("shows an error state when the report request fails", async () => {
    server.use(
      http.get(`${BASE}/datasets/:id/quality-report`, () =>
        HttpResponse.json({ detail: "Report unavailable." }, { status: 500 }),
      ),
    );

    renderForDataset("dataset-aspirin");

    await waitFor(() => {
      expect(screen.getByText(/could not load the quality report/i)).toBeInTheDocument();
    });
  });
});
