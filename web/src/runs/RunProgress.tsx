/**
 * RunProgress: a live stepper showing which pipeline stage a run is in, with
 * its counts so far and any interruption or cancellation in flight.
 *
 * It only renders what it is given; polling lives in `useRun`.
 */
import type { PipelineRun } from "../api/types";
import { RUN_STAGES, isAwaitingResume, progressSummary } from "./stages";

const STAGE_INDEX = new Map(RUN_STAGES.map(({ stage }, index) => [stage, index]));

type StepState = "complete" | "current" | "upcoming";

function stepState(index: number, current: number, finished: boolean): StepState {
  // A succeeded run's last stage ("Done") is complete rather than current, so
  // the whole list reads as finished.
  if (index < current || (finished && index === current)) {
    return "complete";
  }
  return index === current ? "current" : "upcoming";
}

const MARKER: Record<StepState, string> = {
  complete: "bg-accent border-accent",
  current: "border-accent animate-pulse",
  upcoming: "border-ink/25 dark:border-paper/25",
};

export function RunProgress({ run }: { run: PipelineRun }): React.JSX.Element {
  const resuming = isAwaitingResume(run);
  // A run waiting to resume still reports the stage it was interrupted in,
  // but it restarts from the beginning. Drawing that stage as current (or the
  // ones before it as complete) would promise progress that will be redone,
  // so the stepper goes back to Queued: Queued is current, every later stage
  // is not started, and the status line below says why.
  const current = resuming ? 0 : (STAGE_INDEX.get(run.stage) ?? 0);
  const finished = run.status === "succeeded";
  const summary = progressSummary(run);
  return (
    <div className="flex flex-col gap-3">
      <ol aria-label="Run progress" className="flex flex-col gap-2 text-sm">
        {RUN_STAGES.map(({ stage, label }, index) => {
          const state = stepState(index, current, finished);
          return (
            <li
              key={stage}
              aria-current={state === "current" ? "step" : undefined}
              className={`flex items-center gap-3 ${state === "upcoming" ? "text-ink/50 dark:text-paper/50" : ""}`}
            >
              <span aria-hidden="true" className={`h-3 w-3 shrink-0 rounded-full border-2 ${MARKER[state]}`} />
              <span className={state === "current" ? "font-medium" : undefined}>{label}</span>
              {/* The marker is decorative; state is spelled out for screen readers. */}
              <span className="sr-only">
                {state === "complete" ? "(complete)" : state === "current" ? "(in progress)" : "(not started)"}
              </span>
            </li>
          );
        })}
      </ol>
      {resuming ? (
        <p role="status" className="text-sm text-ink/70 dark:text-paper/70">
          Waiting to resume after an interruption — it restarts from the beginning.
        </p>
      ) : summary ? (
        <p role="status" className="text-sm text-ink/70 dark:text-paper/70">
          {summary}
        </p>
      ) : null}
      {/* `attempts` counts executions started, so a second one means this run
          was interrupted and picked up again. Not shown while it waits to
          resume: the line above already says so. */}
      {run.attempts > 1 && !resuming ? (
        <p className="text-sm text-ink/60 dark:text-paper/60">
          Resumed after an interruption (attempt {run.attempts}).
        </p>
      ) : null}
      {/* The worker only acts on a cancellation at its next checkpoint (a
          stage boundary, or a count update within a long stage), so a
          running run keeps going briefly after the request. */}
      {run.cancel_requested && run.status === "running" ? (
        <p className="text-sm text-ink/60 dark:text-paper/60">Cancelling at the end of this stage…</p>
      ) : null}
    </div>
  );
}
