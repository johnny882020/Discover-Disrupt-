/**
 * Seed data for the MSW mock server: a couple of fake orgs, API keys,
 * datasets, records, and pipeline runs, kept in memory for the lifetime of
 * the tab (or the test process).
 */
import type {
  Dataset,
  EnrichmentResult,
  NormalizedRecord,
  OrgContext,
  PipelineRun,
  QualityReport,
  ValidationIssue,
} from "../api/types";

export const SEED_API_KEYS: Record<string, OrgContext> = {
  "dnd_live_acme0000000000000000000000": {
    org_id: "11111111-1111-1111-1111-111111111111",
    org_name: "Acme Therapeutics",
    api_key_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  },
  "dnd_live_helix0000000000000000000000": {
    org_id: "22222222-2222-2222-2222-222222222222",
    org_name: "Helix Biosciences",
    api_key_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
  },
};

const ACME_ORG = SEED_API_KEYS["dnd_live_acme0000000000000000000000"].org_id;

function makeRecord(
  datasetId: string,
  index: number,
  overrides: Partial<NormalizedRecord> = {},
): NormalizedRecord {
  return {
    id: `record-${datasetId}-${index}`,
    dataset_id: datasetId,
    record_key: `key-${index}`,
    source: "pubchem",
    source_record_id: `CID${1000 + index}`,
    name: `Compound ${index}`,
    canonical_smiles: "CC(=O)Oc1ccccc1C(=O)O",
    inchi: "InChI=1S/C9H8O4/c1-6(10)11-8-5-3-2-4-7(8)9(12)13/h2-5H,1H3,(H,12,13)",
    inchikey: "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
    molecular_formula: "C9H8O4",
    molecular_weight: 180.16 + index,
    target: index % 2 === 0 ? "COX-2" : "COX-1",
    assay_type: "IC50",
    activity_value_nm: 50 + index * 10,
    activity_relation: "=",
    ...overrides,
  };
}

export const DATASET_ASPIRIN: Dataset = {
  id: "dataset-aspirin",
  org_id: ACME_ORG,
  run_id: "run-aspirin",
  name: "Aspirin analogs (PubChem)",
  source: "pubchem",
  record_count: 8,
  created_at: "2026-09-20T14:00:00Z",
};

export const DATASET_EMPTY: Dataset = {
  id: "dataset-empty",
  org_id: ACME_ORG,
  run_id: "run-empty",
  name: "COX-2 CSV upload",
  source: "csv",
  record_count: 0,
  created_at: "2026-09-22T09:30:00Z",
};

export const RECORDS_ASPIRIN: NormalizedRecord[] = Array.from({ length: 8 }, (_, i) =>
  makeRecord(DATASET_ASPIRIN.id, i),
);

export const RUN_SUCCEEDED: PipelineRun = {
  id: "run-aspirin",
  org_id: ACME_ORG,
  spec: {
    source: "pubchem",
    identifiers: ["2244"],
    csv_path: null,
    json_path: null,
    chembl_target: null,
    dataset_name: "Aspirin analogs (PubChem)",
  },
  status: "succeeded",
  dataset_id: DATASET_ASPIRIN.id,
  error: null,
  created_at: "2026-09-20T13:58:00Z",
  finished_at: "2026-09-20T14:00:00Z",
};

export const RUN_EMPTY: PipelineRun = {
  id: "run-empty",
  org_id: ACME_ORG,
  spec: {
    source: "csv",
    identifiers: [],
    csv_path: "uploads/cox2.csv",
    json_path: null,
    chembl_target: null,
    dataset_name: "COX-2 CSV upload",
  },
  status: "succeeded",
  dataset_id: DATASET_EMPTY.id,
  error: null,
  created_at: "2026-09-22T09:28:00Z",
  finished_at: "2026-09-22T09:30:00Z",
};

export const runsStore: PipelineRun[] = [RUN_SUCCEEDED, RUN_EMPTY];
export const datasetsStore: Dataset[] = [DATASET_ASPIRIN, DATASET_EMPTY];
export const recordsStore: Record<string, NormalizedRecord[]> = {
  [DATASET_ASPIRIN.id]: RECORDS_ASPIRIN,
  [DATASET_EMPTY.id]: [],
};

const ISSUES_ASPIRIN: ValidationIssue[] = [
  {
    rule: "molecular_weight_range",
    severity: "warning",
    source_record_id: "CID1003",
    field: "molecular_weight",
    message: "Molecular weight is unusually high for this target class.",
  },
  {
    rule: "missing_inchikey",
    severity: "error",
    source_record_id: "CID1007",
    field: "inchikey",
    message: "Record is missing an InChIKey and could not be deduplicated.",
  },
];

export const QUALITY_REPORTS: Record<string, QualityReport> = {
  [DATASET_ASPIRIN.id]: {
    run_id: RUN_SUCCEEDED.id,
    dataset_id: DATASET_ASPIRIN.id,
    total_records: 10,
    accepted_records: 8,
    rejected_records: 2,
    duplicate_records: 1,
    warning_count: 1,
    error_count: 1,
    issues_by_rule: { molecular_weight_range: 1, missing_inchikey: 1 },
    issues: ISSUES_ASPIRIN,
    pass_rate: 0.8,
    created_at: "2026-09-20T14:00:05Z",
  },
  [DATASET_EMPTY.id]: {
    run_id: RUN_EMPTY.id,
    dataset_id: DATASET_EMPTY.id,
    total_records: 0,
    accepted_records: 0,
    rejected_records: 0,
    duplicate_records: 0,
    warning_count: 0,
    error_count: 0,
    issues_by_rule: {},
    issues: [],
    pass_rate: 0,
    created_at: "2026-09-22T09:30:05Z",
  },
};

export const ENRICHMENT_RESULTS: Record<string, EnrichmentResult[]> = {
  [DATASET_ASPIRIN.id]: [
    {
      record_id: RECORDS_ASPIRIN[0].id,
      status: "enriched",
      model_id: "genmol-v1",
      candidates: [
        { smiles: "CC(=O)Oc1ccccc1C(=O)OC", score: 0.91, scoring_method: "qed" },
        { smiles: "CC(=O)Oc1ccc(F)cc1C(=O)O", score: 0.87, scoring_method: "qed" },
      ],
      error: null,
      created_at: "2026-09-20T14:05:00Z",
    },
    {
      record_id: RECORDS_ASPIRIN[1].id,
      status: "skipped_no_key",
      model_id: null,
      candidates: null,
      error: null,
      created_at: "2026-09-20T14:05:00Z",
    },
  ],
  [DATASET_EMPTY.id]: [],
};
