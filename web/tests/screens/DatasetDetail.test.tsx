import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { BASE_URL } from "../../src/api/client";
import { buildAssessment } from "../../src/mocks/assessment";
import { RECORDS_ASPIRIN } from "../../src/mocks/data";
import { server } from "../../src/mocks/server";
import { DatasetDetail } from "../../src/screens/DatasetDetail";
import { renderWithProviders, signInWithSeededKey } from "../test-utils";

function renderForDataset(datasetId: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
    </Routes>,
    { route: `/datasets/${datasetId}` },
  );
}

describe("DatasetDetail screen", () => {
  beforeEach(() => {
    signInWithSeededKey();
  });

  it("renders dataset metadata and records", async () => {
    renderForDataset("dataset-aspirin");

    expect(await screen.findByText("Aspirin analogs (PubChem)")).toBeInTheDocument();
    expect(screen.getByText("Compound 0")).toBeInTheDocument();
  });

  it("shows the hit/lead criteria and each compound's computed properties", async () => {
    renderForDataset("dataset-aspirin");

    expect(await screen.findByRole("heading", { name: "Hit/lead criteria" })).toBeInTheDocument();
    expect(screen.getByText("Optimized (< 100 nM): 5")).toBeInTheDocument();
    expect(screen.getByText("Lead (< 1 µM): 3")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Lipinski's rule of five/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "cLogP" })).toBeInTheDocument();
    expect(screen.getAllByText("1.31")).toHaveLength(8);
  });

  it("lists alerts and hides flagged compounds on request", async () => {
    const assessment = buildAssessment("dataset-aspirin", RECORDS_ASPIRIN);
    assessment.profiles[0] = {
      ...assessment.profiles[0],
      alerts: [{ family: "pains", name: "quinone_A(370)", atoms: [0, 1] }],
    };
    server.use(http.get(`${BASE_URL}/datasets/:id/assessment`, () => HttpResponse.json(assessment)));
    const user = userEvent.setup();
    renderForDataset("dataset-aspirin");

    expect(await screen.findByText("PAINS: quinone_A(370)")).toBeInTheDocument();
    expect(screen.getAllByText("Brenk: phenol_ester")).toHaveLength(7);
    await user.click(screen.getByRole("checkbox", { name: "Hide PAINS" }));
    expect(screen.queryByText("PAINS: quinone_A(370)")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 7 of 8")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Hide PAINS" }));
    expect(screen.getByText("PAINS: quinone_A(370)")).toBeInTheDocument();
  });

  it("shows an empty-records state", async () => {
    renderForDataset("dataset-empty");

    expect(await screen.findByText("COX-2 CSV upload")).toBeInTheDocument();
    expect(screen.getByText(/no records yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Hit/lead criteria" })).not.toBeInTheDocument();
  });
});
