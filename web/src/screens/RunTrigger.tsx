/**
 * RunTrigger: start a pipeline run from an uploaded file (upload → map
 * columns → run), a list of PubChem CIDs, or a ChEMBL target. Polls the run
 * and opens its dataset when it succeeds.
 */
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import type { ColumnMapping, RunPipelineRequest, UploadPreview } from "../api/types";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { FileDrop } from "../design-system/FileDrop";
import { TextField } from "../design-system/TextField";
import { useRun, useTriggerRun } from "../hooks/useRunStatus";
import { useDeleteTemplate, useMappingTemplates, useSaveTemplate, useUploadFile } from "../hooks/useUploads";
import { MappingEditor } from "../uploads/MappingEditor";
import { mappingProblem } from "../uploads/columnRoles";

type Source = "upload" | "pubchem" | "chembl";

const SOURCE_LABELS: Record<Source, string> = {
  upload: "Upload a file",
  pubchem: "PubChem compounds",
  chembl: "ChEMBL target",
};

const ACCEPTED_FILES = ".csv,.tsv,.tab,.txt,.xlsx,.sdf,.sd";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function baseName(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

function SavedMappings(): React.JSX.Element | null {
  const templates = useMappingTemplates();
  const remove = useDeleteTemplate();
  if (!templates.data || templates.data.length === 0) {
    return null;
  }
  return (
    <Card className="max-w-3xl">
      <div className="flex flex-col gap-2 text-sm">
        <h2 className="font-display text-xl">Saved column mappings</h2>
        <p className="text-ink/60 dark:text-paper/60">
          Applied automatically to uploads whose headers include a mapping&apos;s columns.
        </p>
        <ul className="flex flex-col divide-y divide-ink/8 dark:divide-paper/10">
          {templates.data.map((template) => (
            <li key={template.id} className="flex items-center justify-between py-2">
              <span>
                {template.name}{" "}
                <span className="text-ink/50 dark:text-paper/50">
                  ({Object.keys(template.mapping).length} columns)
                </span>
              </span>
              <Button
                type="button"
                variant="ghost"
                disabled={remove.isPending}
                onClick={() => remove.mutate(template.id)}
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

export function RunTrigger(): React.JSX.Element {
  const navigate = useNavigate();
  const triggerRun = useTriggerRun();
  const uploadFile = useUploadFile();
  const saveTemplate = useSaveTemplate();
  const [source, setSource] = useState<Source>("upload");
  const [datasetName, setDatasetName] = useState("");
  const [identifiers, setIdentifiers] = useState("");
  const [chemblTarget, setChemblTarget] = useState("");
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping>({});
  const [saveMapping, setSaveMapping] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  // The POST only returns the *submitted* run (status pending/running,
  // dataset_id still null) — the pipeline finishes in the background.
  // Poll the run's own status until it's terminal before navigating.
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const pendingRun = useRun(pendingRunId ?? undefined);

  useEffect(() => {
    if (!pendingRun.data) {
      return;
    }
    if (pendingRun.data.status === "succeeded") {
      navigate(`/datasets/${pendingRun.data.dataset_id ?? ""}`);
    } else if (pendingRun.data.status === "failed") {
      setFormError(pendingRun.data.error ?? "The run failed.");
      setPendingRunId(null);
    }
  }, [pendingRun.data, navigate]);

  function handleFile(file: File): void {
    setFormError(null);
    uploadFile.mutate(file, {
      onSuccess: (uploaded) => {
        setPreview(uploaded);
        setMapping(uploaded.suggested_mapping);
        setDatasetName((current) => current || baseName(uploaded.upload.filename));
      },
    });
  }

  function resetUpload(): void {
    setPreview(null);
    setMapping({});
    setSaveMapping(false);
    uploadFile.reset();
  }

  function buildRequest(): RunPipelineRequest | null {
    const dataset_name = datasetName.trim() || undefined;
    if (source === "upload") {
      return preview ? { source, upload_id: preview.upload.id, column_mapping: mapping, dataset_name } : null;
    }
    if (source === "pubchem") {
      const cids = identifiers
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      return { source, identifiers: cids, dataset_name };
    }
    return { source, chembl_target: chemblTarget.trim(), dataset_name };
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setFormError(null);
    const request = buildRequest();
    if (!request) {
      return;
    }
    try {
      if (source === "upload" && saveMapping) {
        await saveTemplate.mutateAsync({ name: templateName.trim(), mapping });
      }
      const run = await triggerRun.mutateAsync(request);
      setPendingRunId(run.id);
    } catch (err) {
      setFormError(errorMessage(err, "Could not start the run. Please try again."));
    }
  }

  const isWaiting = pendingRunId !== null;
  const busy = triggerRun.isPending || saveTemplate.isPending || isWaiting;
  const uploadReady = preview !== null && mappingProblem(mapping) === null;
  const canSubmit =
    source === "upload"
      ? uploadReady && (!saveMapping || templateName.trim() !== "")
      : source === "pubchem"
        ? identifiers.trim() !== ""
        : chemblTarget.trim() !== "";

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-3xl">New pipeline run</h1>
      <Card className="max-w-3xl">
        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <fieldset className="flex flex-col gap-2 text-sm">
            <legend className="mb-1 font-medium">Source</legend>
            <div className="flex flex-wrap gap-4">
              {(Object.keys(SOURCE_LABELS) as Source[]).map((option) => (
                <label key={option} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="source"
                    value={option}
                    checked={source === option}
                    onChange={() => setSource(option)}
                  />
                  {SOURCE_LABELS[option]}
                </label>
              ))}
            </div>
          </fieldset>

          {source === "upload" && !preview ? (
            <div className="flex flex-col gap-2">
              <FileDrop
                accept={ACCEPTED_FILES}
                hint="CSV, TSV, Excel (.xlsx) or SD file, up to 25 MB"
                disabled={uploadFile.isPending}
                onFile={handleFile}
              />
              {uploadFile.isPending ? (
                <p role="status" className="text-sm text-ink/60 dark:text-paper/60">
                  Reading your file…
                </p>
              ) : null}
              {uploadFile.isError ? (
                <p role="alert" className="text-sm text-danger">
                  {errorMessage(uploadFile.error, "The file could not be uploaded.")}
                </p>
              ) : null}
            </div>
          ) : null}

          {source === "upload" && preview ? (
            <div className="flex flex-col gap-3">
              <MappingEditor preview={preview} mapping={mapping} onChange={setMapping} />
              <div className="flex flex-wrap items-center gap-4 text-sm">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={saveMapping} onChange={(e) => setSaveMapping(e.target.checked)} />
                  Save this mapping for future uploads
                </label>
                <button type="button" onClick={resetUpload} className="text-ink/60 hover:text-accent dark:text-paper/60">
                  Choose a different file
                </button>
              </div>
              {saveMapping ? (
                <div className="sm:max-w-sm">
                  <TextField
                    label="Mapping name"
                    name="template-name"
                    required
                    placeholder="e.g. Plate reader export"
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                  />
                </div>
              ) : null}
            </div>
          ) : null}

          {source === "pubchem" ? (
            <TextField
              label="PubChem CIDs (comma-separated)"
              name="identifiers"
              placeholder="2244, 5090"
              value={identifiers}
              onChange={(e) => setIdentifiers(e.target.value)}
            />
          ) : null}

          {source === "chembl" ? (
            <TextField
              label="ChEMBL target ID"
              name="chembl-target"
              placeholder="CHEMBL240"
              value={chemblTarget}
              onChange={(e) => setChemblTarget(e.target.value)}
            />
          ) : null}

          <div className="sm:max-w-sm">
            <TextField
              label="Dataset name (optional)"
              name="dataset-name"
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
            />
          </div>

          {formError ? (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          ) : null}

          <div>
            <Button type="submit" disabled={busy || !canSubmit}>
              {busy ? "Running…" : "Start run"}
            </Button>
          </div>
        </form>
      </Card>
      {source === "upload" ? <SavedMappings /> : null}
    </div>
  );
}
