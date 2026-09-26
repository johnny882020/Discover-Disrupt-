/**
 * TypeScript mirrors of the backend's Pydantic contracts.
 *
 * These types must stay in sync with `src/dndlabs/core/schemas.py`. Do not
 * hand-roll ad-hoc shapes elsewhere in the app; import from here so the
 * frontend and backend contracts drift together, not apart.
 */

/** Supported ingestion sources. */
export type SourceType = "pubchem" | "chembl" | "csv" | "json";

/** Supported model-ready export formats. */
export type ExportFormat = "csv" | "jsonl";

/** Lifecycle state of a pipeline run. */
export type RunStatus = "pending" | "running" | "succeeded" | "failed";

/** Severity of a validation issue. */
export type Severity = "error" | "warning";

/** Outcome of one enrichment attempt. */
export type EnrichmentStatus = "enriched" | "skipped_no_key" | "failed";

/** Result of authenticating a request with an API key. */
export interface OrgContext {
  org_id: string;
  org_name: string;
  api_key_id: string;
}

/** What a pipeline run should ingest. */
export interface SourceSpec {
  source: SourceType;
  identifiers: string[];
  csv_path: string | null;
  json_path: string | null;
  chembl_target: string | null;
  dataset_name: string | null;
}

/** Body of a `POST /pipelines/run` request. */
export interface RunPipelineRequest {
  source: SourceType;
  identifiers?: string[];
  csv_path?: string;
  json_path?: string;
  chembl_target?: string;
  dataset_name?: string;
}

/** Metadata of a pipeline run. */
export interface PipelineRun {
  id: string;
  org_id: string;
  spec: SourceSpec;
  status: RunStatus;
  dataset_id: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

/** Stored dataset metadata. */
export interface Dataset {
  id: string;
  org_id: string;
  run_id: string;
  name: string;
  source: SourceType;
  record_count: number;
  created_at: string;
}

/** A validated, normalized, model-ready compound record. */
export interface NormalizedRecord {
  id: string;
  dataset_id: string;
  record_key: string | null;
  source: SourceType;
  source_record_id: string;
  name: string | null;
  canonical_smiles: string | null;
  inchi: string | null;
  inchikey: string | null;
  molecular_formula: string | null;
  molecular_weight: number | null;
  target: string | null;
  assay_type: string | null;
  activity_value_nm: number | null;
  activity_relation: string | null;
}

/** A dataset together with its normalized records. */
export interface DatasetWithRecords {
  dataset: Dataset;
  records: NormalizedRecord[];
}

/** Query filters over a dataset's normalized records. */
export interface DatasetFilter {
  mw_min?: number;
  mw_max?: number;
  target?: string;
  source?: SourceType;
  activity_min_nm?: number;
  activity_max_nm?: number;
  limit?: number;
  offset?: number;
}

/** One data-quality finding for a record. */
export interface ValidationIssue {
  rule: string;
  severity: Severity;
  source_record_id: string;
  field: string | null;
  message: string;
}

/** Structured data-quality report for one pipeline run. */
export interface QualityReport {
  run_id: string;
  dataset_id: string | null;
  total_records: number;
  accepted_records: number;
  rejected_records: number;
  duplicate_records: number;
  warning_count: number;
  error_count: number;
  issues_by_rule: Record<string, number>;
  issues: ValidationIssue[];
  pass_rate: number;
  created_at: string;
}

/** One GenMol-generated analog and its score. */
export interface GeneratedCandidate {
  smiles: string;
  score: number;
  scoring_method: string;
}

/** Enrichment outcome for one record. */
export interface EnrichmentResult {
  record_id: string;
  status: EnrichmentStatus;
  model_id: string | null;
  candidates: GeneratedCandidate[] | null;
  error: string | null;
  created_at: string;
}

/** Response of `GET /datasets/{id}/enrichment`. */
export interface EnrichmentResponse {
  enrichment_enabled: boolean;
  results: EnrichmentResult[];
}

/** One entry of FastAPI's request-validation error list (HTTP 422). */
export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/**
 * Shape of an API error body. Domain errors (401/404/500) carry a string;
 * request-validation errors (422) carry FastAPI's list of items.
 */
export interface ApiErrorBody {
  detail: string | ValidationErrorItem[];
}

/** Response of `GET /health`. */
export interface HealthResponse {
  status: "ok";
}
