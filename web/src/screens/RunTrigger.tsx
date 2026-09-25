/** RunTrigger: form to kick off a new pipeline run against any source. */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import type { SourceType } from "../api/types";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { useTriggerRun } from "../hooks/useRunStatus";

const SOURCES: SourceType[] = ["pubchem", "chembl", "csv", "json"];

export function RunTrigger(): React.JSX.Element {
  const navigate = useNavigate();
  const triggerRun = useTriggerRun();
  const [source, setSource] = useState<SourceType>("csv");
  const [datasetName, setDatasetName] = useState("");
  const [identifiers, setIdentifiers] = useState("");
  const [csvPath, setCsvPath] = useState("");
  const [jsonPath, setJsonPath] = useState("");
  const [chemblTarget, setChemblTarget] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setFormError(null);
    try {
      const run = await triggerRun.mutateAsync({
        source,
        dataset_name: datasetName || undefined,
        identifiers:
          source === "pubchem"
            ? identifiers
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
            : undefined,
        csv_path: source === "csv" ? csvPath || undefined : undefined,
        json_path: source === "json" ? jsonPath || undefined : undefined,
        chembl_target: source === "chembl" ? chemblTarget || undefined : undefined,
      });
      navigate(`/datasets/${run.dataset_id ?? ""}`);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not start the run. Please try again.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-3xl">New pipeline run</h1>
      <Card className="max-w-xl">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">Source</span>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value as SourceType)}
              className="rounded border border-ink/15 bg-transparent px-3 py-2 text-sm dark:border-paper/20"
            >
              {SOURCES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">Dataset name (optional)</span>
            <input
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
              className="rounded border border-ink/15 bg-transparent px-3 py-2 text-sm dark:border-paper/20"
            />
          </label>

          {source === "pubchem" ? (
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">PubChem CIDs (comma-separated)</span>
              <input
                value={identifiers}
                onChange={(e) => setIdentifiers(e.target.value)}
                placeholder="2244, 5090"
                className="rounded border border-ink/15 bg-transparent px-3 py-2 text-sm dark:border-paper/20"
              />
            </label>
          ) : null}

          {source === "chembl" ? (
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">ChEMBL target</span>
              <input
                value={chemblTarget}
                onChange={(e) => setChemblTarget(e.target.value)}
                placeholder="CHEMBL240"
                className="rounded border border-ink/15 bg-transparent px-3 py-2 text-sm dark:border-paper/20"
              />
            </label>
          ) : null}

          {source === "csv" ? (
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">CSV path</span>
              <input
                value={csvPath}
                onChange={(e) => setCsvPath(e.target.value)}
                placeholder="uploads/compounds.csv"
                className="rounded border border-ink/15 bg-transparent px-3 py-2 text-sm dark:border-paper/20"
              />
            </label>
          ) : null}

          {source === "json" ? (
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">JSON path</span>
              <input
                value={jsonPath}
                onChange={(e) => setJsonPath(e.target.value)}
                placeholder="uploads/compounds.json"
                className="rounded border border-ink/15 bg-transparent px-3 py-2 text-sm dark:border-paper/20"
              />
            </label>
          ) : null}

          {formError ? (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          ) : null}

          <Button type="submit" disabled={triggerRun.isPending}>
            {triggerRun.isPending ? "Starting run…" : "Start run"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
