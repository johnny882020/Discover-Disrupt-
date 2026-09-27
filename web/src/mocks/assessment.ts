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
  no_pains_alerts: "No PAINS alerts",
  no_reactive_metabolite_alerts: "No reactive-metabolite alerts",
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
    // Aspirin's one alert, as RDKit's Brenk catalog reports it.
    alerts: [{ family: "brenk", name: "phenol_ester", atoms: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] }],
    potency_class: potencyClass(record.activity_value_nm, record.activity_relation),
    criteria: ALL_PASS,
  };
}

function share(group: CompoundProfile[], criterion: Criterion): CriterionShare {
  const evaluated = group.filter((p) => p.criteria[criterion] !== undefined);
  return { passing: evaluated.filter((p) => p.criteria[criterion]).length, evaluated: evaluated.length };
}

const RANKED: PotencyClass[] = ["optimized", "lead", "hit", "inactive"];

/** The most potent class the majority of measurements reach (as the API computes it). */
function majorityClass(classes: PotencyClass[]): PotencyClass {
  const ranks = classes.filter((c) => RANKED.includes(c)).map((c) => RANKED.indexOf(c));
  for (let rank = 0; rank < RANKED.length; rank += 1) {
    if (ranks.filter((r) => r <= rank).length * 2 > ranks.length) return RANKED[rank];
  }
  return "unknown";
}

function classCounts(classes: PotencyClass[]): Record<PotencyClass, number> {
  const counts = { optimized: 0, lead: 0, hit: 0, inactive: 0, unknown: 0 } as Record<PotencyClass, number>;
  for (const klass of classes) counts[klass] += 1;
  return counts;
}

export function buildAssessment(datasetId: string, records: NormalizedRecord[]): DatasetAssessment {
  const profiles = records.map(profile);
  const byId = new Map(profiles.map((p) => [p.record_id, p]));
  const tested = records.filter((r) => r.control === null);
  const compounds = new Map<string, NormalizedRecord[]>();
  for (const r of tested) {
    const key = r.record_key ?? `record:${r.id}`;
    compounds.set(key, [...(compounds.get(key) ?? []), r]);
  }
  const overall = (members: NormalizedRecord[]) =>
    majorityClass(members.map((m) => byId.get(m.id)?.potency_class ?? "unknown"));
  const classes = new Map([...compounds].map(([key, members]) => [key, overall(members)]));
  const representative = new Map([...compounds].map(([key, members]) => [key, byId.get(members[0].id)!]));
  const actives = [...classes].filter(([, c]) => ACTIVE.includes(c)).map(([key]) => key);
  const ranked = (r: NormalizedRecord) =>
    r.activity_value_nm !== null && r.activity_relation !== ">" && r.activity_relation !== ">=";
  const best = [...compounds]
    .map(([key, members]) => {
      const values = members.filter(ranked).sort((a, b) => (a.activity_value_nm ?? 0) - (b.activity_value_nm ?? 0));
      return { key, record: values[0] };
    })
    .filter((b) => b.record !== undefined)
    .sort((a, b) => (a.record.activity_value_nm ?? 0) - (b.record.activity_value_nm ?? 0))
    .slice(0, 5);
  const byFormat = (["biochemical", "cell_based", null] as const)
    .map((assayFormat) => {
      const inFormat = [...compounds]
        .map(([, members]) => members.filter((m) => m.assay_format === assayFormat))
        .filter((members) => members.length > 0)
        .map(overall);
      const counts = classCounts(inFormat);
      return {
        assay_format: assayFormat,
        compounds: inFormat.length,
        potency_classes: counts,
        actives: ACTIVE.reduce((sum, c) => sum + counts[c], 0),
      };
    })
    .filter((f) => f.compounds > 0);
  const group = (keys: string[]) => keys.map((key) => representative.get(key)!);
  return {
    dataset_id: datasetId,
    compounds: compounds.size,
    measurements: tested.length,
    controls: records.length - tested.length,
    potency_classes: classCounts([...classes.values()]),
    actives: actives.length,
    by_format: byFormat,
    most_potent_ids: best.map((b) => b.record.id),
    criteria: (Object.keys(LABELS) as Criterion[]).map((criterion) => ({
      criterion,
      label: LABELS[criterion],
      all_compounds: share(group([...compounds.keys()]), criterion),
      actives: share(group(actives), criterion),
      most_potent: share(group(best.map((b) => b.key)), criterion),
    })),
    profiles,
  };
}
