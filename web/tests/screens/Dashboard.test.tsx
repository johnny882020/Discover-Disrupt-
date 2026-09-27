import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { RUN_SUCCEEDED } from "../../src/mocks/data";
import { server } from "../../src/mocks/server";
import { Dashboard } from "../../src/screens/Dashboard";
import { renderWithProviders, signInWithSeededKey } from "../test-utils";

const BASE = "*/api/v1";

describe("Dashboard", () => {
  beforeEach(() => {
    signInWithSeededKey();
  });

  it("shows a loading state before data arrives", () => {
    renderWithProviders(<Dashboard />);
    expect(screen.getAllByText(/loading/i).length).toBeGreaterThan(0);
  });

  it("renders the populated datasets and runs tables", async () => {
    renderWithProviders(<Dashboard />);

    expect(await screen.findByText("Aspirin analogs (PubChem)")).toBeInTheDocument();
    expect(screen.getByText("COX-2 CSV upload")).toBeInTheDocument();
  });

  it("shows each run's stage while active and its counts once finished", async () => {
    server.use(
      http.get(`${BASE}/pipelines/runs`, () =>
        HttpResponse.json([
          { ...RUN_SUCCEEDED, id: "run-live", status: "running", stage: "featurizing", dataset_id: null },
          RUN_SUCCEEDED,
          { ...RUN_SUCCEEDED, id: "run-bad", status: "failed", stage: "fetching", error: "source down" },
          { ...RUN_SUCCEEDED, id: "run-queued", status: "pending", stage: "queued", attempts: 0, dataset_id: null },
        ]),
      ),
    );
    renderWithProviders(<Dashboard />);
    expect(await screen.findByText("Computing properties and alerts")).toBeInTheDocument();
    expect(screen.getByText("8 of 8 accepted")).toBeInTheDocument();
    expect(screen.getByText("source down")).toBeInTheDocument();
    expect(screen.getByText("Queued")).toBeInTheDocument();
  });

  it("says an interrupted run is waiting to resume rather than naming its old stage", async () => {
    server.use(
      http.get(`${BASE}/pipelines/runs`, () =>
        HttpResponse.json([
          { ...RUN_SUCCEEDED, id: "run-resume", status: "pending", stage: "validating", attempts: 1, dataset_id: null },
        ]),
      ),
    );
    renderWithProviders(<Dashboard />);
    expect(await screen.findByText("Waiting to resume")).toBeInTheDocument();
    expect(screen.queryByText("Validating and standardizing")).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no datasets or runs", async () => {
    server.use(
      http.get(`${BASE}/datasets`, () => HttpResponse.json([])),
      http.get(`${BASE}/pipelines/runs`, () => HttpResponse.json([])),
    );

    renderWithProviders(<Dashboard />);

    expect(await screen.findByText(/no datasets yet/i)).toBeInTheDocument();
    expect(await screen.findByText(/no pipeline runs yet/i)).toBeInTheDocument();
  });

  it("shows an error state when the datasets request fails", async () => {
    server.use(
      http.get(`${BASE}/datasets`, () =>
        HttpResponse.json({ detail: "Something went wrong." }, { status: 500 }),
      ),
    );

    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText(/could not load datasets/i)).toBeInTheDocument();
    });
  });
});
