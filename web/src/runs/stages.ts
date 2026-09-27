/**
 * Run stages as users see them, and plain-language readings of a run's state.
 *
 * The labels here are shared by the run stepper and the dashboard's Progress
 * column so both describe a stage in the same words.
 */
import type { PipelineRun, RunStage } from "../api/types";

/** The stages a user sees, in execution order, with what each one does. */
export const RUN_STAGES: { stage: RunStage; label: string }[] = [
  { stage: "queued", label: "Queued" },
  { stage: "fetching", label: "Reading the source" },
  { stage: "resolving", label: "Looking up structures" },
  { stage: "validating", label: "Validating and standardizing" },
  { stage: "storing", label: "Saving the dataset" },
  { stage: "featurizing", label: "Computing properties and alerts" },
  { stage: "enriching", label: "Enrichment" },
  { stage: "done", label: "Done" },
];

/**
 * Whether a run was stopped cleanly mid-run (deploy, restart, idle shutdown)
 * and is queued to run again.
 *
 * The API puts such a run back to `pending` but keeps the stage, counts and
 * `attempts` it had reached, so `attempts > 0` is what tells it apart from a
 * run that has never started. It restarts from the beginning, not from the
 * kept stage.
 */
export function isAwaitingResume(run: PipelineRun): boolean {
  return run.status === "pending" && run.attempts > 0;
}

/** A plain-language summary of the counts reached so far. */
export function progressSummary(run: PipelineRun): string | null {
  // The counts of an interrupted attempt are discarded when the run starts
  // over; showing them would suggest work that will be redone.
  if (isAwaitingResume(run)) {
    return null;
  }
  const { fetched, resolved, validated, accepted, rejected, duplicates, featurized } = run.progress;
  if (fetched === 0) {
    return null;
  }
  const parts = [`${fetched} read`];
  if (resolved > 0) {
    parts.push(`${resolved} structures looked up`);
  }
  if (run.stage === "validating" && validated > 0) {
    parts.push(`${validated} of ${fetched} validated`);
  }
  if (accepted + rejected > 0) {
    parts.push(`${accepted} accepted`, `${rejected} rejected`);
  }
  if (duplicates > 0) {
    parts.push(`${duplicates} duplicates`);
  }
  if (featurized > 0) {
    parts.push(`${featurized} with properties`);
  }
  return parts.join(" · ");
}
