import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PipelineRun } from "../../src/api/types";
import { RUN_SUCCEEDED } from "../../src/mocks/data";
import { RunProgress } from "../../src/runs/RunProgress";

const RUNNING: PipelineRun = {
  ...RUN_SUCCEEDED,
  status: "running",
  stage: "validating",
  progress: { fetched: 10, resolved: 2, validated: 0, accepted: 0, rejected: 0, duplicates: 0, featurized: 0, enriched: 0 },
  dataset_id: null,
  finished_at: null,
};

describe("RunProgress", () => {
  it("marks finished, current and upcoming stages", () => {
    render(<RunProgress run={RUNNING} />);
    const steps = within(screen.getByRole("list", { name: "Run progress" })).getAllByRole("listitem");
    expect(steps).toHaveLength(8);
    expect(steps[1]).toHaveTextContent("Reading the source(complete)");
    const current = steps.find((step) => step.getAttribute("aria-current") === "step");
    expect(current).toHaveTextContent("Validating and standardizing(in progress)");
    expect(steps[7]).toHaveTextContent("Done(not started)");
    expect(screen.getByRole("status")).toHaveTextContent("10 read · 2 structures looked up");
  });

  it("shows every stage complete once the run succeeded", () => {
    render(<RunProgress run={RUN_SUCCEEDED} />);
    const steps = within(screen.getByRole("list", { name: "Run progress" })).getAllByRole("listitem");
    expect(steps.every((step) => step.textContent?.endsWith("(complete)"))).toBe(true);
  });

  it("says when a run was resumed or is being cancelled", () => {
    render(<RunProgress run={{ ...RUNNING, attempts: 2, cancel_requested: true }} />);
    expect(screen.getByText("Resumed after an interruption (attempt 2).")).toBeInTheDocument();
    expect(screen.getByText("Cancelling at the end of this stage…")).toBeInTheDocument();
  });

  it("goes back to Queued while an interrupted run waits to resume", () => {
    // The API keeps the stage and counts the interrupted attempt reached.
    render(<RunProgress run={{ ...RUNNING, status: "pending", attempts: 1 }} />);
    const steps = within(screen.getByRole("list", { name: "Run progress" })).getAllByRole("listitem");
    const current = steps.filter((step) => step.getAttribute("aria-current") === "step");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Queued(in progress)");
    expect(steps.slice(1).every((step) => step.textContent?.endsWith("(not started)"))).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waiting to resume after an interruption — it restarts from the beginning.",
    );
    expect(screen.queryByText(/10 read/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Resumed after an interruption/)).not.toBeInTheDocument();
  });

  it("does not call a run that has never started a resumption", () => {
    render(<RunProgress run={{ ...RUNNING, status: "pending", stage: "queued", attempts: 0 }} />);
    expect(screen.queryByText(/Waiting to resume/)).not.toBeInTheDocument();
  });
});
