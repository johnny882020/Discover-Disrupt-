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

/** What an authenticated principal may do within its organization. */
export type Role = "admin" | "member";

/** Which kind of credential authenticated a request. */
export type PrincipalType = "api_key" | "user";

/**
 * Result of authenticating a request (`GET /auth/whoami`). Exactly one of
 * `api_key_id` (principal `api_key`) or `user_id` + `session_id` (principal
 * `user`) is set; API keys act with the `admin` role.
 */
export interface OrgContext {
  org_id: string;
  org_name: string;
  principal: PrincipalType;
  role: Role;
  api_key_id: string | null;
  user_id: string | null;
  session_id: string | null;
  email: string | null;
}

/** A person who signs in to an organization. */
export interface User {
  id: string;
  org_id: string;
  email: string;
  role: Role;
  created_at: string;
}

/** Body of `POST /auth/login`. */
export interface LoginRequest {
  email: string;
  password: string;
}

/** A new sign-in session: the bearer token is shown only in this response. */
export interface SessionCreated {
  token: string;
  token_type: "bearer";
  expires_at: string;
  user: User;
  org_name: string;
}

/** Body of `POST /auth/invitations`. */
export interface InvitationCreate {
  email: string;
  role: Role;
}

/** A new invitation: the token and link are shown only in this response. */
export interface InvitationCreated {
  id: string;
  email: string;
  role: Role;
  expires_at: string;
  token: string;
  accept_url: string;
}

/** What an invitation grants (`POST /auth/invitations/preview`). */
export interface InvitationPreview {
  email: string;
  role: Role;
  org_name: string;
  expires_at: string;
}

/** Body of `POST /auth/invitations/accept`. */
export interface InvitationAccept {
  token: string;
  password: string;
}

/** Body of `POST /auth/password`. */
export interface PasswordChange {
  current_password: string;
  new_password: string;
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
