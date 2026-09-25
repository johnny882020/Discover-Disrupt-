/** Dashboard: lists datasets and recent pipeline runs for the org. */
import { Link } from "react-router-dom";
import { Badge, type BadgeTone } from "../design-system/Badge";
import { Card } from "../design-system/Card";
import { Table } from "../design-system/Table";
import { useDatasets } from "../hooks/useDatasets";
import { useRuns } from "../hooks/useRunStatus";
import type { RunStatus } from "../api/types";

const RUN_STATUS_TONE: Record<RunStatus, BadgeTone> = {
  pending: "neutral",
  running: "accent",
  succeeded: "success",
  failed: "danger",
};

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
          <p role="alert" className="text-sm text-danger">
            Could not load datasets: {datasetsQuery.error.message}
          </p>
        ) : datasetsQuery.data && datasetsQuery.data.length > 0 ? (
          <Table
            columns={[
              {
                key: "name",
                header: "Name",
                cell: (d) => (
                  <Link to={`/datasets/${d.id}`} className="text-accent hover:underline">
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
          <p role="alert" className="text-sm text-danger">
            Could not load runs: {runsQuery.error.message}
          </p>
        ) : runsQuery.data && runsQuery.data.length > 0 ? (
          <Table
            columns={[
              { key: "source", header: "Source", cell: (r) => <Badge>{r.spec.source}</Badge> },
              {
                key: "status",
                header: "Status",
                cell: (r) => <Badge tone={RUN_STATUS_TONE[r.status]}>{r.status}</Badge>,
              },
              {
                key: "dataset",
                header: "Dataset",
                cell: (r) =>
                  r.dataset_id ? (
                    <Link to={`/datasets/${r.dataset_id}`} className="text-accent hover:underline">
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
        ) : (
          <p className="text-sm text-ink/60 dark:text-paper/60">No pipeline runs yet.</p>
        )}
      </Card>
    </div>
  );
}
