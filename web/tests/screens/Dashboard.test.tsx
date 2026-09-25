import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { setStoredApiKey } from "../../src/api/client";
import { server } from "../../src/mocks/server";
import { Dashboard } from "../../src/screens/Dashboard";
import { renderWithProviders, SEEDED_API_KEY } from "../test-utils";

const BASE = "*/api/v1";

describe("Dashboard", () => {
  beforeEach(() => {
    setStoredApiKey(SEEDED_API_KEY);
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
