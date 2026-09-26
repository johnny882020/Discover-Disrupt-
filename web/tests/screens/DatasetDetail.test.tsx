import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
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

  it("shows an empty-records state", async () => {
    renderForDataset("dataset-empty");

    expect(await screen.findByText("COX-2 CSV upload")).toBeInTheDocument();
    expect(screen.getByText(/no records yet/i)).toBeInTheDocument();
  });
});
