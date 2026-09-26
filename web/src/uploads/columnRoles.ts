/** Column roles for uploaded tables: labels and the rules a mapping must meet. */
import type { ColumnMapping, ColumnRole } from "../api/types";

/** Roles in the order offered to the user, with their labels. */
export const ROLE_OPTIONS: { role: ColumnRole; label: string }[] = [
  { role: "smiles", label: "SMILES" },
  { role: "inchi", label: "InChI" },
  { role: "inchikey", label: "InChIKey" },
  { role: "source_record_id", label: "Compound ID" },
  { role: "name", label: "Name" },
  { role: "target", label: "Target" },
  { role: "assay_type", label: "Assay type" },
  { role: "activity_value", label: "Activity value" },
  { role: "activity_unit", label: "Activity unit" },
  { role: "activity_relation", label: "Activity relation (<, =, >)" },
  { role: "molecular_weight", label: "Molecular weight" },
  { role: "molecular_formula", label: "Molecular formula" },
  { role: "ignore", label: "Ignore this column" },
];

/** Label for columns without a role: their values are kept with each record. */
export const UNMAPPED_LABEL = "Keep as extra data";

const STRUCTURE_ROLES: ColumnRole[] = ["smiles", "inchi"];

/**
 * Why a mapping cannot be used for a run, or `null` if it can. Mirrors the
 * server's rules, which remain authoritative.
 */
export function mappingProblem(mapping: ColumnMapping): string | null {
  const roles = Object.values(mapping).filter((role) => role !== "ignore");
  if (!roles.some((role) => STRUCTURE_ROLES.includes(role))) {
    return "Choose the column that holds the structures (SMILES or InChI).";
  }
  const repeated = roles.filter((role, index) => roles.indexOf(role) !== index);
  if (repeated.length > 0) {
    const labels = [...new Set(repeated)].map((role) => ROLE_OPTIONS.find((o) => o.role === role)?.label ?? role);
    return `Each role can be used for one column only: ${labels.join(", ")}.`;
  }
  return null;
}
