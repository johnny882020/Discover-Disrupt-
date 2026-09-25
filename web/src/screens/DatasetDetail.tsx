/** DatasetDetail: dataset metadata, its records, and links to reports/export. */
import { Link, useParams } from "react-router-dom";
import { Badge } from "../design-system/Badge";
import { Card } from "../design-system/Card";
import { MoleculeView } from "../design-system/MoleculeView";
import { Table } from "../design-system/Table";
import { useDataset } from "../hooks/useDatasets";

export function DatasetDetail(): React.JSX.Element {
  const { datasetId } = useParams<{ datasetId: string }>();
  const query = useDataset(datasetId);

  if (query.isLoading) {
    return <p className="text-sm text-ink/60 dark:text-paper/60">Loading dataset…</p>;
  }

  if (query.isError) {
    return (
      <p role="alert" className="text-sm text-danger">
        Could not load this dataset: {query.error.message}
      </p>
    );
  }

  if (!query.data) {
    return <p className="text-sm text-ink/60 dark:text-paper/60">Dataset not found.</p>;
  }

  const { dataset, records } = query.data;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-display text-3xl">{dataset.name}</h1>
          <p className="mt-1 text-sm text-ink/60 dark:text-paper/60">
            <Badge>{dataset.source}</Badge> · {dataset.record_count} records · created{" "}
            {new Date(dataset.created_at).toLocaleString()}
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to={`/datasets/${dataset.id}/quality-report`}
            className="rounded border border-ink/20 px-4 py-2 text-sm font-medium hover:bg-ink/5 dark:border-paper/25 dark:hover:bg-paper/10"
          >
            Quality report
          </Link>
          <Link
            to={`/datasets/${dataset.id}/export`}
            className="rounded bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:bg-accent/90"
          >
            Export
          </Link>
        </div>
      </div>

      <Card>
        <h2 className="mb-4 text-lg font-medium">Records</h2>
        {records.length === 0 ? (
          <p className="text-sm text-ink/60 dark:text-paper/60">
            This dataset has no records yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table
              columns={[
                { key: "name", header: "Name", cell: (r) => r.name ?? r.source_record_id },
                {
                  key: "structure",
                  header: "Structure",
                  cell: (r) => <MoleculeView smiles={r.canonical_smiles} />,
                },
                {
                  key: "mw",
                  header: "MW",
                  align: "right",
                  cell: (r) => (r.molecular_weight !== null ? r.molecular_weight.toFixed(2) : "—"),
                },
                { key: "target", header: "Target", cell: (r) => r.target ?? "—" },
                {
                  key: "activity",
                  header: "Activity (nM)",
                  align: "right",
                  cell: (r) =>
                    r.activity_value_nm !== null
                      ? `${r.activity_relation ?? ""}${r.activity_value_nm}`
                      : "—",
                },
              ]}
              rows={records}
              getRowKey={(r) => r.id}
            />
          </div>
        )}
      </Card>
    </div>
  );
}
