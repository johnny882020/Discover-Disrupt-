# API Reference

Base URL: `http://localhost:8000` locally, `https://dndlabs-api.onrender.com`
on Render. All routes are under `/api/v1` except `/` and `/health` (also
mirrored at `/api/v1/health`). Interactive docs: `/docs` (its **Authorize**
button accepts either credential).

## Authentication

Every `/api/v1/*` route requires one of the credentials below, except the
health routes, `/admin/*` (which uses `X-Admin-Secret`), `POST /auth/login`,
`POST /auth/invitations/preview` and `POST /auth/invitations/accept`:

| Header | Credential | Obtained from |
|---|---|---|
| `X-API-Key: ddl_live_…` | Organization API key (acts as `admin`) | `POST /admin/orgs`, `POST /admin/orgs/{org_id}/keys` |
| `Authorization: Bearer ddl_sess_…` | User session token (the user's role) | `POST /auth/login`, `POST /auth/invitations/accept` |

If both are sent, the API key is used. Tokens and keys are returned once and
never again. See [architecture.md#auth](architecture.md#auth) for the
security model.

## Admin (bootstrap, not customer-facing)

Header: `X-Admin-Secret: <DNDLABS_ADMIN_BOOTSTRAP_SECRET>`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/admin/orgs` | `{"name": "Acme"}` → creates an org, returns `ApiKeyCreated` (the raw key, shown once) |
| POST | `/admin/orgs/{org_id}/keys` | Issue an additional key for an existing org |
| POST | `/admin/orgs/{org_id}/invitations` | `{"email": "ada@acme.com"}` → invite the org's first **admin**; returns `InvitationCreated` (`token`, `accept_url`, shown once) |
| POST | `/admin/orgs/{org_id}/password-resets` | `{"email": "ada@acme.com"}` → password-reset link for one of the org's users, for when no admin can sign in; returns `PasswordResetCreated` (`token`, `reset_url`, shown once) |

## Sign-in and accounts

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/login` | none | `{"email", "password"}` → `SessionCreated` (`token`, `expires_at`, `user`, `org_name`) |
| POST | `/auth/logout` | session | End the calling session (204) |
| POST | `/auth/password` | session | `{"current_password", "new_password"}` → 204; ends the user's other sessions |
| POST | `/auth/invitations` | admin | `{"email", "role": "member"\|"admin"}` → `InvitationCreated` (201) |
| GET | `/auth/invitations` | admin | Pending invitations (`Invitation[]`, newest first; never includes tokens) |
| DELETE | `/auth/invitations/{id}` | admin | Revoke a pending invitation; its link stops working (204) |
| POST | `/auth/invitations/preview` | none | `{"token"}` → `InvitationPreview` (`email`, `role`, `org_name`, `expires_at`); does not redeem |
| POST | `/auth/invitations/accept` | none | `{"token", "password"}` → `SessionCreated` (201); creates the account |
| GET | `/auth/members` | admin | The org's users (`User[]`, oldest first) |
| PATCH | `/auth/members/{user_id}` | admin | `{"role": "admin"\|"member"}` → the updated `User` |
| DELETE | `/auth/members/{user_id}` | admin | Remove a member; their account and sessions are deleted (204) |
| POST | `/auth/members/{user_id}/password-reset` | admin | Single-use reset link → `PasswordResetCreated` (201); supersedes the member's earlier unused links |
| POST | `/auth/password-reset/preview` | none | `{"token"}` → `PasswordResetPreview` (`email`, `org_name`, `expires_at`); does not redeem |
| POST | `/auth/password-reset/accept` | none | `{"token", "password"}` → `SessionCreated`; sets the password, clears any lock, ends all other sessions |
| GET | `/auth/whoami` | any | `OrgContext`: `org_id`, `org_name`, `principal` (`api_key`/`user`), `role`, and `api_key_id` or `user_id` + `session_id` + `email` |
| POST | `/auth/keys/revoke` | API key | Revoke the calling key (204) |
| DELETE | `/orgs/me/data` | admin | Privacy: delete all of the calling org's runs, datasets, records, reports and uploaded files (204). The org, its keys, its user accounts and its saved column mappings are kept. |

Invitation and session tokens travel in request bodies and the
`Authorization` header, never in a URL the API receives.

## Pipelines

| Method | Path | Purpose |
|---|---|---|
| POST | `/pipelines/run` | Start a run (202, background) |
| GET | `/pipelines/runs` | List the calling org's runs, newest first |
| GET | `/pipelines/runs/{id}` | Run status |

`POST /pipelines/run` body (`SourceSpec`):

```json
{"source": "upload", "upload_id": "…", "column_mapping": {"Compound ID": "source_record_id", "Structure": "smiles", "IC50 (nM)": "activity_value"}}
{"source": "pubchem", "identifiers": ["2244", "3672"]}
{"source": "chembl", "chembl_target": "CHEMBL204"}
{"source": "csv", "csv_path": "/app/samples/lab_export.csv"}
{"source": "json", "json_path": "/app/samples/upload.json"}
```

`upload_id` comes from `POST /uploads` (below). `csv_path`/`json_path` are
read from the **API server's** filesystem, not the caller's, and are meant
for operators. Every body may also carry `dataset_name`. Returns `202` with a `PipelineRun` (`status: "pending"`);
`dataset_id` is `null` until the run finishes — poll
`GET /pipelines/runs/{id}` (the frontend does this automatically).

## Uploads and column mappings

| Method | Path | Purpose |
|---|---|---|
| POST | `/uploads` | Multipart field `file` (CSV, TSV, XLSX or SDF) → `UploadPreview` (201) |
| GET | `/uploads/{id}/preview` | `UploadPreview` for an earlier upload |
| GET | `/mapping-templates` | The org's saved column mappings (`MappingTemplate[]`, by name) |
| POST | `/mapping-templates` | `{"name", "mapping"}` → `MappingTemplate` (201); replaces a template of the same name |
| DELETE | `/mapping-templates/{id}` | Delete a saved mapping (204) |

`UploadPreview` carries the stored `upload` (`id`, `filename`, `format`,
`size_bytes`, `sha256`), its `columns`, the first 20 `rows`, `row_count`,
a `suggested_mapping` and the `template` it came from, if any. The
suggestion comes from the saved template whose columns best match the file's
headers; otherwise from known header names (e.g. `Canonical SMILES`,
`IC50 (nM)`), then from column contents (SMILES, InChI, InChIKey).

A `column_mapping` assigns each column one role: `source_record_id`, `name`,
`smiles`, `inchi`, `inchikey`, `molecular_formula`, `molecular_weight`,
`target`, `assay_type`, `activity_value`, `activity_unit`,
`activity_relation` or `ignore`. It must include `smiles` or `inchi`, and a
role (other than `ignore`) may be used once. Unmapped columns are kept in
each record's `extra`; `ignore`d ones are dropped.

Files are limited to 25 MiB and 100,000 rows by default
(`DNDLABS_UPLOAD_MAX_BYTES`, `DNDLABS_UPLOAD_MAX_ROWS`). An SDF's structures
become a `smiles` column, each molecule's title line a `name` column, and
its data fields further columns. Excel files use the first worksheet, with the first
non-empty row as headers.

## Datasets

| Method | Path | Purpose |
|---|---|---|
| GET | `/datasets` | List the calling org's datasets, newest first |
| GET | `/datasets/{id}` | Dataset + all its records |
| GET | `/datasets/{id}/records?mw_min=&mw_max=&target=&source=&activity_min_nm=&activity_max_nm=&limit=&offset=` | Filtered records |
| GET | `/datasets/{id}/quality-report` | `QualityReport` |
| GET | `/datasets/{id}/enrichment` | `{"enrichment_enabled": bool, "results": EnrichmentResult[]}` |
| GET | `/datasets/{id}/export?format=csv\|jsonl` | Download, fixed column order |

`EnrichmentResult.status` is one of `enriched`, `skipped_no_key`, `failed`.

## Service and health (no auth)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Service name, version, documentation links and endpoint list (`ServiceInfo`); browsers sending `Accept: text/html` get an HTML landing page |
| GET | `/health`, `/api/v1/health` | Liveness: `{"status": "ok"}`. Never touches the database — this is Render's `healthCheckPath` |
| GET | `/api/v1/health/ready` | Readiness: `{"status": "ok", "database": "ok"}`, or `503` with `{"status": "unavailable", "database": "unavailable"}` when the database is unreachable or unmigrated |

Use `/api/v1/health/ready`, not `/health`, to check that the database is
reachable and migrated.

## Errors

`{"detail": "<message>"}`. Every `500` response body carries a fixed
generic message (`"internal server error"`); the underlying exception is
logged server-side only, never returned to the client.

| Status | Meaning |
|---|---|
| `400` | Invitation or reset token unknown, expired, already used or revoked |
| `401` | Missing, invalid, expired or revoked credential; wrong email or password (always `invalid email or password`); wrong admin secret on `/admin/*`. Carries `WWW-Authenticate: Bearer` |
| `403` | Authenticated but not allowed: managing members, invitations or org data without the `admin` role, removing yourself, revoking a key from a session, signing out with a key, or a wrong current password on `/auth/password` |
| `404` | Unknown run, dataset, upload or mapping template, or one that belongs to a different org |
| `409` | Invitation for an email that is already a member of the org, redemption for an email that already has an account, or a change that would leave the org without an admin |
| `422` | Invalid request body (e.g. a `SourceSpec` missing the field its source needs, a column mapping without a structure column, an invalid email), a password that fails the policy, or an uploaded file that is empty, too large, of an unsupported type or unreadable |
| `429` | Sign-in locked after repeated failures; retry after the `Retry-After` seconds |
| `500` | Internal error (e.g. storage failure); detail is logged, not returned |
