/** ExportPanel: download a dataset as CSV or JSONL. */
import { useState } from "react";
import { useParams } from "react-router-dom";
import type { ExportFormat } from "../api/types";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { useDataset } from "../hooks/useDatasets";
import { useExportDataset } from "../hooks/useExportDataset";

const FORMATS: ExportFormat[] = ["csv", "jsonl"];

export function ExportPanel(): React.JSX.Element {
  const { datasetId } = useParams<{ datasetId: string }>();
  const datasetQuery = useDataset(datasetId);
  const exportMutation = useExportDataset();
  const [format, setFormat] = useState<ExportFormat>("csv");

  if (datasetQuery.isLoading) {
    return <p className="text-sm text-ink/60 dark:text-paper/60">Loading dataset…</p>;
  }

  if (datasetQuery.isError) {
    return (
      <p role="alert" className="text-sm text-danger">
        Could not load this dataset: {datasetQuery.error.message}
      </p>
    );
  }

  const dataset = datasetQuery.data?.dataset;
  if (!dataset) {
    return <p className="text-sm text-ink/60 dark:text-paper/60">Dataset not found.</p>;
  }

  async function handleExport(): Promise<void> {
    if (!dataset) return;
    await exportMutation.mutateAsync({
      datasetId: dataset.id,
      format,
      filename: `${dataset.name.replace(/\s+/g, "_")}.${format === "jsonl" ? "jsonl" : "csv"}`,
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-3xl">Export {dataset.name}</h1>
      <Card className="max-w-md">
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">Format</span>
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value as ExportFormat)}
              className="rounded border border-ink/15 bg-transparent px-3 py-2 text-sm dark:border-paper/20"
            >
              {FORMATS.map((f) => (
                <option key={f} value={f}>
                  {f.toUpperCase()}
                </option>
              ))}
            </select>
          </label>

          {exportMutation.isError ? (
            <p role="alert" className="text-sm text-danger">
              {exportMutation.error instanceof Error
                ? exportMutation.error.message
                : "Export failed. Please try again."}
            </p>
          ) : null}
          {exportMutation.isSuccess ? (
            <p className="text-sm text-success">Download started.</p>
          ) : null}

          <Button onClick={() => void handleExport()} disabled={exportMutation.isPending}>
            {exportMutation.isPending ? "Preparing export…" : `Download ${format.toUpperCase()}`}
          </Button>
        </div>
      </Card>
    </div>
  );
}
