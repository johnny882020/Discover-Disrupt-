/** DatasetDetail: dataset metadata, hit/lead criteria, its records, and links to reports/export. */
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { AlertFamily, CompoundProfile } from "../api/types";
import { AlertBadges } from "../assessment/AlertBadges";
import { highlightedAtoms } from "../assessment/alerts";
import { HitLeadPanel } from "../assessment/HitLeadPanel";
import { potencyInfo } from "../assessment/potency";
import { Badge } from "../design-system/Badge";
import { Card } from "../design-system/Card";
import { MoleculeView } from "../design-system/MoleculeView";
import { Table } from "../design-system/Table";
import { useAssessment } from "../hooks/useAssessment";
import { useDataset } from "../hooks/useDatasets";

/** A computed value to `digits` decimals, or a dash when there is none. */
function num(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

export function DatasetDetail(): React.JSX.Element {
  const { datasetId } = useParams<{ datasetId: string }>();
  const query = useDataset(datasetId);
  const assessment = useAssessment(datasetId);
  const [hidden, setHidden] = useState<ReadonlySet<AlertFamily>>(new Set());

  function toggleHidden(family: AlertFamily, hide: boolean): void {
    setHidden((current) => {
      const next = new Set(current);
      if (hide) next.add(family);
      else next.delete(family);
      return next;
    });
  }

  if (query.isLoading) {
    return <p className="text-sm text-ink/60 dark:text-paper/60">Loading dataset…</p>;
  }

  if (query.isError) {
    return (
      <p role="alert" className="text-sm text-danger dark:text-danger-bright">
        Could not load this dataset: {query.error.message}
      </p>
    );
  }

  if (!query.data) {
    return <p className="text-sm text-ink/60 dark:text-paper/60">Dataset not found.</p>;
  }

  const { dataset, records } = query.data;
  const profiles = new Map<string, CompoundProfile>(
    (assessment.data?.profiles ?? []).map((profile) => [profile.record_id, profile]),
  );
  // Hiding alert families filters the loaded records client-side: the
  // assessment already carries every compound's alerts.
  const shown = records.filter(
    (r) => !(profiles.get(r.id)?.alerts ?? []).some((alert) => hidden.has(alert.family)),
  );

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

      {assessment.data && records.length > 0 ? <HitLeadPanel assessment={assessment.data} /> : null}
      {assessment.isError ? (
        <p role="alert" className="text-sm text-danger dark:text-danger-bright">
          Could not assess this dataset: {assessment.error.message}
        </p>
      ) : null}

      <Card>
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-medium">Records</h2>
          {records.length > 0 ? (
            <div className="flex flex-wrap gap-4 text-sm">
              {(
                [
                  ["pains", "Hide PAINS"],
                  ["reactive_metabolite", "Hide reactive-metabolite alerts"],
                ] as const
              ).map(([family, label]) => (
                <label key={family} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={hidden.has(family)}
                    onChange={(event) => toggleHidden(family, event.target.checked)}
                  />
                  {label}
                </label>
              ))}
              {shown.length < records.length ? (
                <span className="text-ink/60 dark:text-paper/60">
                  Showing {shown.length} of {records.length}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        {records.length === 0 ? (
          <p className="text-sm text-ink/60 dark:text-paper/60">
            This dataset has no records yet.
          </p>
        ) : (
          // Many columns: scroll inside the card rather than widening the page.
          <div className="overflow-x-auto">
            <Table
              columns={[
                { key: "name", header: "Name", cell: (r) => r.name ?? r.source_record_id },
                {
                  key: "structure",
                  header: "Structure",
                  cell: (r) => (
                    <MoleculeView
                      smiles={r.canonical_smiles}
                      highlightAtoms={highlightedAtoms(profiles.get(r.id)?.alerts ?? [])}
                    />
                  ),
                },
                {
                  key: "mw",
                  header: "MW",
                  align: "right",
                  cell: (r) => (r.molecular_weight !== null ? r.molecular_weight.toFixed(2) : "—"),
                },
                { key: "target", header: "Target", cell: (r) => r.target ?? "—" },
                {
                  key: "assay",
                  header: "Assay",
                  cell: (r) => (
                    <span className="flex flex-col gap-1">
                      <span>
                        {[r.assay_type, r.assay_format === "cell_based" ? "cell-based" : r.assay_format]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </span>
                      {r.control ? <Badge>{r.control === "positive" ? "Positive control" : "Negative control"}</Badge> : null}
                    </span>
                  ),
                },
                {
                  key: "activity",
                  header: "Activity (nM)",
                  align: "right",
                  cell: (r) =>
                    r.activity_value_nm !== null
                      ? `${r.activity_relation ?? ""}${r.activity_value_nm}`
                      : "—",
                },
                {
                  key: "potency",
                  header: "Potency",
                  cell: (r) => {
                    const info = potencyInfo(profiles.get(r.id)?.potency_class ?? "unknown");
                    return info.potency === "unknown" ? "—" : <Badge tone={info.tone}>{info.label}</Badge>;
                  },
                },
                { key: "clogp", header: "cLogP", align: "right", cell: (r) => num(profiles.get(r.id)?.clogp, 2) },
                { key: "tpsa", header: "TPSA", align: "right", cell: (r) => num(profiles.get(r.id)?.tpsa, 1) },
                { key: "hbd", header: "HBD", align: "right", cell: (r) => num(profiles.get(r.id)?.hbd) },
                { key: "hba", header: "HBA", align: "right", cell: (r) => num(profiles.get(r.id)?.hba) },
                {
                  key: "rotb",
                  header: "Rot. bonds",
                  align: "right",
                  cell: (r) => num(profiles.get(r.id)?.rotatable_bonds),
                },
                { key: "qed", header: "QED", align: "right", cell: (r) => num(profiles.get(r.id)?.qed, 2) },
                {
                  key: "ro5",
                  header: "Ro5 violations",
                  align: "right",
                  cell: (r) => num(profiles.get(r.id)?.lipinski_violations),
                },
                {
                  key: "alerts",
                  header: "Alerts",
                  cell: (r) => {
                    const profile = profiles.get(r.id);
                    return profile ? <AlertBadges alerts={profile.alerts} /> : "—";
                  },
                },
              ]}
              rows={shown}
              getRowKey={(r) => r.id}
            />
          </div>
        )}
      </Card>
    </div>
  );
}
