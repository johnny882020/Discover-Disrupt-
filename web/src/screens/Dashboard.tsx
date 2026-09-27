/**
 * Dashboard: lists the org's datasets and recent pipeline runs, with where
 * each run stands. The runs list keeps polling while any run is active (see
 * `useRuns`), so this page is also where a user watches runs they left.
 */
import { Link } from "react-router-dom";
import { Badge, type BadgeTone } from "../design-system/Badge";
import { Card } from "../design-system/Card";
import { Table } from "../design-system/Table";
import { useDatasets } from "../hooks/useDatasets";
import { useRuns } from "../hooks/useRunStatus";
import type { PipelineRun, RunStatus } from "../api/types";
import { RUN_STAGES, isAwaitingResume } from "../runs/stages";

const RUN_STATUS_TONE: Record<RunStatus, BadgeTone> = {
  pending: "neutral",
  running: "accent",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
};

const STAGE_LABELS = new Map(RUN_STAGES.map(({ stage, label }) => [stage, label]));

/** Where a run stands: its stage while active, its counts once finished. */
function runProgressText(run: PipelineRun): string {
  // An interrupted run keeps its last stage while it waits, but will start
  // over, so naming that stage would mislead.
  if (isAwaitingResume(run)) {
    return "Waiting to resume";
  }
  if (run.status === "pending" || run.status === "running") {
    return STAGE_LABELS.get(run.stage) ?? run.stage;
  }
  if (run.status === "succeeded") {
    return `${run.progress.accepted} of ${run.progress.fetched} accepted`;
  }
  return run.error ?? "—";
}

export function Dashboard(): React.JSX.Element {
  const datasetsQuery = useDatasets();
  const runsQuery = useRuns();

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-3xl">Dashboard</h1>
        <Link
          to="/runs/new"
          className="rounded bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:bg-accent/90"
        >
          New pipeline run
        </Link>
      </div>

      <Card>
        <h2 className="mb-4 text-lg font-medium">Datasets</h2>
        {datasetsQuery.isLoading ? (
          <p className="text-sm text-ink/60 dark:text-paper/60">Loading datasets…</p>
        ) : datasetsQuery.isError ? (
          <p role="alert" className="text-sm text-danger dark:text-danger-bright">
            Could not load datasets: {datasetsQuery.error.message}
          </p>
        ) : datasetsQuery.data && datasetsQuery.data.length > 0 ? (
          // Both tables scroll inside their card on a phone rather than widening the page.
          <div className="overflow-x-auto">
            <Table
              columns={[
                {
                  key: "name",
                  header: "Name",
                  cell: (d) => (
                    <Link to={`/datasets/${d.id}`} className="text-accent dark:text-accent-bright hover:underline">
                      {d.name}
                    </Link>
                  ),
                },
                { key: "source", header: "Source", cell: (d) => <Badge>{d.source}</Badge> },
                { key: "records", header: "Records", cell: (d) => d.record_count, align: "right" },
                {
                  key: "created",
                  header: "Created",
                  cell: (d) => new Date(d.created_at).toLocaleString(),
                },
              ]}
              rows={datasetsQuery.data}
              getRowKey={(d) => d.id}
            />
          </div>
        ) : (
          <p className="text-sm text-ink/60 dark:text-paper/60">
            No datasets yet. Trigger a pipeline run to ingest your first one.
          </p>
        )}
      </Card>

      <Card>
        <h2 className="mb-4 text-lg font-medium">Recent runs</h2>
        {runsQuery.isLoading ? (
          <p className="text-sm text-ink/60 dark:text-paper/60">Loading runs…</p>
        ) : runsQuery.isError ? (
          <p role="alert" className="text-sm text-danger dark:text-danger-bright">
            Could not load runs: {runsQuery.error.message}
          </p>
        ) : runsQuery.data && runsQuery.data.length > 0 ? (
          <div className="overflow-x-auto">
            <Table
              columns={[
                { key: "source", header: "Source", cell: (r) => <Badge>{r.spec.source}</Badge> },
                {
                  key: "status",
                  header: "Status",
                  cell: (r) => <Badge tone={RUN_STATUS_TONE[r.status]}>{r.status}</Badge>,
                },
                {
                  key: "progress",
                  header: "Progress",
                  cell: (r) => <span className="text-ink/70 dark:text-paper/70">{runProgressText(r)}</span>,
                },
                {
                  key: "dataset",
                  header: "Dataset",
                  cell: (r) =>
                    r.dataset_id ? (
                      <Link to={`/datasets/${r.dataset_id}`} className="text-accent dark:text-accent-bright hover:underline">
                        View dataset
                      </Link>
                    ) : (
                      <span className="text-ink/40 dark:text-paper/40">—</span>
                    ),
                },
                {
                  key: "created",
                  header: "Created",
                  cell: (r) => new Date(r.created_at).toLocaleString(),
                },
              ]}
              rows={runsQuery.data}
              getRowKey={(r) => r.id}
            />
          </div>
        ) : (
          <p className="text-sm text-ink/60 dark:text-paper/60">No pipeline runs yet.</p>
        )}
      </Card>
    </div>
  );
}
