import { describe, expect, it } from "vitest";
import type { PipelineRun } from "../../src/api/types";
import { RUN_SUCCEEDED } from "../../src/mocks/data";
import { RUN_STAGES, isAwaitingResume, progressSummary } from "../../src/runs/stages";

function withProgress(progress: Partial<PipelineRun["progress"]>): PipelineRun {
  return {
    ...RUN_SUCCEEDED,
    progress: { fetched: 0, resolved: 0, validated: 0, accepted: 0, rejected: 0, duplicates: 0, featurized: 0, enriched: 0, ...progress },
  };
}

describe("run stages", () => {
  it("lists every backend stage once, in execution order", () => {
    expect(RUN_STAGES.map((s) => s.stage)).toEqual([
      "queued",
      "fetching",
      "resolving",
      "validating",
      "storing",
      "featurizing",
      "enriching",
      "done",
    ]);
  });

  it("counts records validated so far while validating", () => {
    const validating = { ...withProgress({ fetched: 3000, validated: 1500 }), stage: "validating" as const };
    expect(progressSummary(validating)).toBe("3000 read · 1500 of 3000 validated");
    expect(progressSummary({ ...validating, stage: "storing" })).toBe("3000 read");
  });

  it("summarizes only the counts reached so far", () => {
    expect(progressSummary(withProgress({}))).toBeNull();
    expect(progressSummary(withProgress({ fetched: 12 }))).toBe("12 read");
    expect(
      progressSummary(withProgress({ fetched: 12, resolved: 3, accepted: 9, rejected: 2, duplicates: 1, featurized: 9 })),
    ).toBe("12 read · 3 structures looked up · 9 accepted · 2 rejected · 1 duplicates · 9 with properties");
  });

  it("recognizes a run waiting to resume, and hides its discarded counts", () => {
    const interrupted: PipelineRun = { ...withProgress({ fetched: 12 }), status: "pending", stage: "validating", attempts: 1 };
    expect(isAwaitingResume(interrupted)).toBe(true);
    expect(progressSummary(interrupted)).toBeNull();
    expect(isAwaitingResume({ ...interrupted, attempts: 0, stage: "queued" })).toBe(false);
    expect(isAwaitingResume({ ...interrupted, status: "running" })).toBe(false);
  });
});
