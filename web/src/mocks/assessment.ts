/**
 * Mock `GET /datasets/{id}/assessment`: potency classes follow the API's
 * rules; every mock compound is aspirin, so its computed properties are
 * aspirin's.
 */
import type {
  CompoundProfile,
  Criterion,
  CriterionShare,
  DatasetAssessment,
  NormalizedRecord,
  PotencyClass,
} from "../api/types";

const LABELS: Record<Criterion, string> = {
  mw_under_500: "MW < 500",
  clogp_under_5: "cLogP < 5",
  lipinski: "Lipinski's rule of five (≤ 1 violation)",
  rotatable_bonds_under_10: "Rotatable bonds < 10",
  tpsa_under_140: "Polar surface area < 140 Å²",
  tpsa_under_90: "Polar surface area < 90 Å² (CNS)",
};
const ALL_PASS = Object.fromEntries(Object.keys(LABELS).map((c) => [c, true])) as Record<Criterion, boolean>;
const ACTIVE: PotencyClass[] = ["optimized", "lead", "hit"];

function potencyClass(value: number | null, relation: string | null): PotencyClass {
  if (value === null) return "unknown";
  if (relation === ">" || relation === ">=") return value >= 10_000 ? "inactive" : "unknown";
  if (value < 100 || (relation === "<" && value === 100)) return "optimized";
  if (value < 1_000 || (relation === "<" && value === 1_000)) return "lead";
  if (value < 10_000 || (relation === "<" && value === 10_000)) return "hit";
  return relation === "=" || relation === null ? "inactive" : "unknown";
}

function profile(record: NormalizedRecord): CompoundProfile {
  return {
    record_id: record.id,
    molecular_weight: 180.16,
    clogp: 1.31,
    tpsa: 63.6,
    hbd: 1,
    hba: 4,
    rotatable_bonds: 2,
    rings: 1,
    qed: 0.55,
    lipinski_violations: 0,
    potency_class: potencyClass(record.activity_value_nm, record.activity_relation),
    criteria: ALL_PASS,
  };
}

function share(group: CompoundProfile[], criterion: Criterion): CriterionShare {
  const evaluated = group.filter((p) => p.criteria[criterion] !== undefined);
  return { passing: evaluated.filter((p) => p.criteria[criterion]).length, evaluated: evaluated.length };
}

export function buildAssessment(datasetId: string, records: NormalizedRecord[]): DatasetAssessment {
  const profiles = records.map(profile);
  const actives = profiles.filter((p) => ACTIVE.includes(p.potency_class));
  const ranked = records
    .filter((r) => r.activity_value_nm !== null && r.activity_relation !== ">" && r.activity_relation !== ">=")
    .sort((a, b) => (a.activity_value_nm ?? 0) - (b.activity_value_nm ?? 0))
    .slice(0, 5)
    .map((r) => r.id);
  const top = profiles.filter((p) => ranked.includes(p.record_id));
  const classes = { optimized: 0, lead: 0, hit: 0, inactive: 0, unknown: 0 } as Record<PotencyClass, number>;
  for (const p of profiles) classes[p.potency_class] += 1;
  return {
    dataset_id: datasetId,
    compounds: profiles.length,
    potency_classes: classes,
    actives: actives.length,
    most_potent_ids: ranked,
    criteria: (Object.keys(LABELS) as Criterion[]).map((criterion) => ({
      criterion,
      label: LABELS[criterion],
      all_compounds: share(profiles, criterion),
      actives: share(actives, criterion),
      most_potent: share(top, criterion),
    })),
    profiles,
  };
}
