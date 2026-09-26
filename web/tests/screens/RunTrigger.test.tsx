import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BASE_URL } from "../../src/api/client";
import type { RunPipelineRequest } from "../../src/api/types";
import { server } from "../../src/mocks/server";
import { createUploadPreview, templatesStore } from "../../src/mocks/uploadHandlers";
import { RunTrigger } from "../../src/screens/RunTrigger";
import { renderWithProviders, signInWithSeededKey } from "../test-utils";

vi.mock("../../src/chem/rdkit", () => ({
  loadRDKit: vi.fn(() => new Promise(() => undefined)), // never loads: SMILES text stays
  depictSvg: vi.fn(),
}));

const CSV = "compound_id,name,Structure,potency\nLAB-1,Aspirin,CC(=O)Oc1ccccc1C(=O)O,12\nLAB-2,Ethanol,CCO,40\n";

function csvFile(content = CSV, name = "plate-7.csv"): File {
  return new File([content], name, { type: "text/csv" });
}

const ORG_ID = "11111111-1111-1111-1111-111111111111"; // the seeded API key's org

/**
 * Answer `POST /uploads` with the preview the mock API builds for this file.
 * Component tests cannot read the multipart file name: under jsdom, Node's
 * fetch serializes jsdom's File without it. The real multipart path is covered
 * by the API's route tests and the Playwright e2e test in a real browser.
 */
function serveUpload(filename: string, content: string): void {
  server.use(
    http.post(`${BASE_URL}/uploads`, () =>
      HttpResponse.json(createUploadPreview(ORG_ID, filename, content), { status: 201 }),
    ),
  );
}

function renderRunTrigger() {
  return renderWithProviders(
    <Routes>
      <Route path="/runs/new" element={<RunTrigger />} />
      <Route path="/datasets/:datasetId" element={<p>Dataset page</p>} />
    </Routes>,
    { route: "/runs/new" },
  );
}

/** Record the body of every `POST /pipelines/run` while delegating to the mock API. */
function captureRuns(): RunPipelineRequest[] {
  const bodies: RunPipelineRequest[] = [];
  server.events.on("request:start", ({ request }) => {
    if (request.method === "POST" && request.url.endsWith("/pipelines/run")) {
      void request
        .clone()
        .json()
        .then((body) => bodies.push(body as RunPipelineRequest));
    }
  });
  return bodies;
}

describe("RunTrigger screen", () => {
  beforeEach(() => {
    signInWithSeededKey();
    serveUpload("plate-7.csv", CSV);
  });

  afterEach(() => {
    server.events.removeAllListeners();
    for (const id of Object.keys(templatesStore)) delete templatesStore[id];
  });

  it("uploads a file, lets the user map columns, and runs it", async () => {
    const runs = captureRuns();
    const user = userEvent.setup();
    renderRunTrigger();

    expect(screen.getByRole("radio", { name: "Upload a file" })).toBeChecked();
    await user.upload(screen.getByLabelText(/csv, tsv, excel/i), csvFile());

    expect(await screen.findByText("plate-7.csv")).toBeInTheDocument();
    expect(screen.getByText(/2 rows · 4 columns/)).toBeInTheDocument();
    expect(screen.getByLabelText("Dataset name (optional)")).toHaveValue("plate-7");
    const start = screen.getByRole("button", { name: /start run/i });
    expect(screen.getByRole("status")).toHaveTextContent(/choose the column that holds the structures/i);
    expect(start).toBeDisabled();

    // Aliased headers are suggested; the structure column is mapped by hand.
    expect(screen.getByLabelText("Role for column compound_id")).toHaveValue("source_record_id");
    await user.selectOptions(screen.getByLabelText("Role for column Structure"), "smiles");
    await user.selectOptions(screen.getByLabelText("Role for column potency"), "activity_value");
    expect(start).toBeEnabled();

    await user.click(start);
    expect(await screen.findByText("Dataset page")).toBeInTheDocument();
    await waitFor(() => expect(runs).toHaveLength(1));
    expect(runs[0]).toMatchObject({
      source: "upload",
      dataset_name: "plate-7",
      column_mapping: {
        compound_id: "source_record_id",
        name: "name",
        Structure: "smiles",
        potency: "activity_value",
      },
    });
  });

  it("flags a role assigned to two columns", async () => {
    const user = userEvent.setup();
    renderRunTrigger();
    await user.upload(screen.getByLabelText(/csv, tsv, excel/i), csvFile());
    await user.selectOptions(await screen.findByLabelText("Role for column Structure"), "smiles");
    await user.selectOptions(screen.getByLabelText("Role for column name"), "smiles");
    expect(screen.getByRole("status")).toHaveTextContent(/one column only: SMILES/);
    expect(screen.getByRole("button", { name: /start run/i })).toBeDisabled();
  });

  it("saves the mapping as a template, which the next upload uses", async () => {
    const user = userEvent.setup();
    renderRunTrigger();
    await user.upload(screen.getByLabelText(/csv, tsv, excel/i), csvFile());
    await user.selectOptions(await screen.findByLabelText("Role for column Structure"), "smiles");
    await user.click(screen.getByRole("checkbox", { name: /save this mapping/i }));
    const start = screen.getByRole("button", { name: /start run/i });
    expect(start).toBeDisabled(); // needs a name
    await user.type(screen.getByLabelText("Mapping name"), "Plate reader");
    await user.click(start);
    await screen.findByText("Dataset page");
    expect(Object.values(templatesStore).map((t) => t.name)).toEqual(["Plate reader"]);
  });

  it("applies a saved mapping to a matching upload and lists it for deletion", async () => {
    templatesStore.t1 = {
      id: "t1",
      org_id: "11111111-1111-1111-1111-111111111111",
      name: "Plate reader",
      mapping: { Structure: "smiles", potency: "activity_value" },
      created_at: "2026-09-26T09:00:00Z",
    };
    const user = userEvent.setup();
    renderRunTrigger();

    const saved = await screen.findByRole("heading", { name: "Saved column mappings" });
    const card = saved.closest("div") as HTMLElement;
    expect(within(card).getByText("Plate reader")).toBeInTheDocument();

    await user.upload(screen.getByLabelText(/csv, tsv, excel/i), csvFile());
    expect(await screen.findByText(/from your saved mapping “Plate reader”/)).toBeInTheDocument();
    expect(screen.getByLabelText("Role for column Structure")).toHaveValue("smiles");
    expect(screen.getByRole("button", { name: /start run/i })).toBeEnabled();

    await user.click(within(card).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(templatesStore.t1).toBeUndefined());
  });

  it("shows why a file was rejected, and lets the user choose another", async () => {
    server.use(
      http.post(
        `${BASE_URL}/uploads`,
        () => HttpResponse.json({ detail: "unsupported file type .pdf" }, { status: 422 }),
        { once: true },
      ),
    );
    const user = userEvent.setup({ applyAccept: false });
    renderRunTrigger();
    await user.upload(screen.getByLabelText(/csv, tsv, excel/i), csvFile("x", "report.pdf"));
    expect(await screen.findByRole("alert")).toHaveTextContent("unsupported file type .pdf");

    await user.upload(screen.getByLabelText(/csv, tsv, excel/i), csvFile());
    expect(await screen.findByText("plate-7.csv")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /choose a different file/i }));
    expect(screen.getByLabelText(/csv, tsv, excel/i)).toBeInTheDocument();
  });

  it("starts a PubChem run from comma-separated CIDs", async () => {
    const runs = captureRuns();
    const user = userEvent.setup();
    renderRunTrigger();
    await user.click(screen.getByRole("radio", { name: "PubChem compounds" }));
    await user.type(screen.getByLabelText(/pubchem cids/i), "2244, 5090");
    await user.click(screen.getByRole("button", { name: /start run/i }));
    expect(await screen.findByText("Dataset page")).toBeInTheDocument();
    await waitFor(() => expect(runs).toEqual([{ source: "pubchem", identifiers: ["2244", "5090"] }]));
  });

  it("shows the reason when a run fails", async () => {
    server.use(
      http.post(`${BASE_URL}/pipelines/run`, () =>
        HttpResponse.json({ detail: "chembl source requires chembl_target" }, { status: 422 }),
      ),
    );
    const user = userEvent.setup();
    renderRunTrigger();
    await user.click(screen.getByRole("radio", { name: "ChEMBL target" }));
    await user.type(screen.getByLabelText("ChEMBL target ID"), "CHEMBL240");
    await user.click(screen.getByRole("button", { name: /start run/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("chembl source requires chembl_target");
  });
});
