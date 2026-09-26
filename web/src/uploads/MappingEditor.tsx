/**
 * Column-mapping step for an uploaded table: a preview of the first rows
 * with a role selector on every column. The column mapped to SMILES is drawn
 * as structures, so a wrong choice is visible at a glance.
 */
import type { ColumnMapping, ColumnRole, UploadPreview } from "../api/types";
import { MoleculeView } from "../design-system/MoleculeView";
import { ROLE_OPTIONS, UNMAPPED_LABEL, mappingProblem } from "./columnRoles";

/** Preview rows shown in the table. */
const SHOWN_ROWS = 8;

interface MappingEditorProps {
  preview: UploadPreview;
  mapping: ColumnMapping;
  onChange: (mapping: ColumnMapping) => void;
}

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function MappingEditor({ preview, mapping, onChange }: MappingEditorProps): React.JSX.Element {
  const problem = mappingProblem(mapping);

  function setRole(column: string, value: string): void {
    const next = { ...mapping };
    if (value === "") {
      delete next[column];
    } else {
      next[column] = value as ColumnRole;
    }
    onChange(next);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="text-sm">
        <p className="font-medium">{preview.upload.filename}</p>
        <p className="text-ink/60 dark:text-paper/60">
          {preview.row_count} rows · {preview.columns.length} columns · {formatSize(preview.upload.size_bytes)}
        </p>
        {preview.template ? (
          <p className="mt-1 text-ink/70 dark:text-paper/70">
            Columns mapped from your saved mapping “{preview.template.name}”.
          </p>
        ) : (
          <p className="mt-1 text-ink/70 dark:text-paper/70">
            We suggested a role for the columns we recognized. Check them before starting the run.
          </p>
        )}
      </div>

      <div className="overflow-x-auto rounded border border-ink/10 dark:border-paper/15">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-ink/15 align-top dark:border-paper/20">
              {preview.columns.map((column) => (
                <th key={column} scope="col" className="min-w-[10rem] p-2 text-left font-normal">
                  <span className="mb-1 block truncate font-medium" title={column}>
                    {column}
                  </span>
                  <select
                    aria-label={`Role for column ${column}`}
                    value={mapping[column] ?? ""}
                    onChange={(e) => setRole(column, e.target.value)}
                    className="w-full rounded border border-ink/15 bg-transparent px-2 py-1 text-xs dark:border-paper/20"
                  >
                    <option value="">{UNMAPPED_LABEL}</option>
                    {ROLE_OPTIONS.map((option) => (
                      <option key={option.role} value={option.role}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.slice(0, SHOWN_ROWS).map((row, index) => (
              <tr key={index} className="border-b border-ink/8 dark:border-paper/10">
                {preview.columns.map((column) => (
                  <td
                    key={column}
                    className={`max-w-[16rem] truncate p-2 ${mapping[column] === "ignore" ? "text-ink/35 dark:text-paper/35" : ""}`}
                    title={row[column]}
                  >
                    {mapping[column] === "smiles" && row[column] ? <MoleculeView smiles={row[column]} /> : row[column]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {preview.row_count > SHOWN_ROWS ? (
        <p className="text-xs text-ink/60 dark:text-paper/60">
          Showing {SHOWN_ROWS} of {preview.row_count} rows.
        </p>
      ) : null}
      {problem ? (
        <p role="status" className="text-sm text-danger">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
