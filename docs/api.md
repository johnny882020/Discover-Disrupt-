# API Reference

Base URL: `http://localhost:8000` locally, `https://dndlabs-api.onrender.com`
on Render. All routes are under `/api/v1` except `/` and `/health` (also
mirrored at `/api/v1/health`). Interactive docs: `/docs` (its **Authorize**
button accepts either credential).

## Authentication

Every `/api/v1/*` route requires one of the credentials below, except the
health routes, `/admin/*` (which uses `X-Admin-Secret`), `POST /auth/login`,
`POST /auth/invitations/preview`, `POST /auth/invitations/accept`,
`POST /auth/password-reset/preview` and `POST /auth/password-reset/accept`:

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
| POST | `/pipelines/run` | Queue a run (202) |
| GET | `/pipelines/runs` | List the calling org's runs, newest first |
| GET | `/pipelines/runs/{id}` | Run status, stage and counts |
| POST | `/pipelines/runs/{id}/cancel` | Cancel a run |

`POST /pipelines/run` body (`SourceSpec`):

```json
{"source": "upload", "upload_id": "…", "column_mapping": {"Compound ID": "source_record_id", "Structure": "smiles", "Activity": "activity_value", "Unit": "activity_unit"}}
{"source": "pubchem", "identifiers": ["2244", "3672"]}
{"source": "chembl", "chembl_target": "CHEMBL204"}
{"source": "csv", "csv_path": "/app/samples/lab_export.csv"}
{"source": "json", "json_path": "/app/samples/upload.json"}
```

`upload_id` comes from `POST /uploads` (below). `csv_path`/`json_path` are
read from the **API server's** filesystem, not the caller's, and are meant
for operators. Every body may also carry `dataset_name`. Returns `202` with the queued `PipelineRun`
(`status: "pending"`, `stage: "queued"`); the API process's run worker
(`pipeline/worker.py`) executes it. Organizations share the worker fairly:
the next run executed is the oldest queued run of the organization with
the fewest runs executing. Poll `GET /pipelines/runs/{id}` (the frontend
does this automatically):

- `status`: `pending` → `running` → `succeeded`, `failed` or `cancelled`.
  A run stopped cleanly (deploy, restart, the free plan's idle shutdown)
  returns to `pending` with its stage and counts kept, and resumes from
  the start.
- `stage`: `queued`, `fetching`, `resolving`, `validating`, `storing`,
  `featurizing`, `enriching`, `done`. A failed run keeps the stage it
  failed in.
- `progress`: counts reached so far — `fetched`, `resolved` (structures
  looked up or read from MOL blocks; updated while resolving), `validated`
  (updated every 500 records while validating), `accepted`, `rejected`,
  `duplicates`, `featurized` (updated every 500 records), `enriched`
  (updated while enriching).
- `attempts`: executions started; increases each time a run resumes.
- `dataset_id` is `null` until the run succeeds.

A run whose worker stopped unexpectedly (crash, kill) is resumed once its
lease expires (`DNDLABS_WORKER_LEASE_SECONDS`, default 120 s). After
`DNDLABS_WORKER_MAX_LOST_LEASES` (default 3) such unexpected stops it
fails with "the run's worker stopped unexpectedly N times; start it
again". Clean stops never count.

`POST /pipelines/runs/{id}/cancel` cancels a queued run at once. A running
run stops at its next checkpoint — between stages, and during resolving,
validating, featurizing and enriching — keeps nothing it stored and ends
`cancelled`. A finished run is returned unchanged.

## Uploads and column mappings

| Method | Path | Purpose |
|---|---|---|
| POST | `/uploads` | Multipart field `file` (CSV, TSV, XLSX, SDF, SMILES or MOL) → `UploadPreview` (201) |
| GET | `/uploads/{id}/preview` | `UploadPreview` for an earlier upload |
| GET | `/mapping-templates` | The org's saved column mappings (`MappingTemplate[]`, by name) |
| POST | `/mapping-templates` | `{"name", "mapping"}` → `MappingTemplate` (201); replaces a template of the same name |
| DELETE | `/mapping-templates/{id}` | Delete a saved mapping (204) |

`UploadPreview` carries the stored `upload` (`id`, `filename`, `format`,
`size_bytes`, `sha256`), its `columns`, the first 20 `rows`, `row_count`,
a `suggested_mapping` and the `template` it came from, if any. The
suggestion comes from the saved template whose columns best match the file's
headers; otherwise from known header names, matched regardless of case,
spacing and punctuation (`Compound ID`, `Canonical SMILES`, `Activity
Value`, `Units`, `Molfile`, `PubChem CID`, …), then from column contents
(SMILES, InChI, MOL blocks, InChIKeys, ChEMBL IDs). Names and PubChem CIDs
are never suggested from contents: a lookup role sends values to PubChem,
so it is always the user's choice.
Units are read from a unit column, not from a header such as `IC50 (nM)`.

A `column_mapping` assigns each column one role: `source_record_id`, `name`,
`smiles`, `inchi`, `mol_block`, `inchikey`, `pubchem_cid`, `chembl_id`,
`lookup_name`, `molecular_formula`, `molecular_weight`, `target`,
`assay_type`, `assay_format`, `control`, `activity_value`,
`activity_unit`, `activity_relation` or `ignore`. A role (other than `ignore`) may be used once, and the mapping
must include a column that identifies the structure:

| Role | Structure from |
|---|---|
| `smiles`, `inchi` | The value itself |
| `mol_block` | The MOL block (V2000/V3000) in the cell, read by RDKit |
| `inchikey` | PubChem lookup by InChIKey |
| `pubchem_cid` | PubChem lookup by CID |
| `chembl_id` | ChEMBL lookup by molecule ID |
| `lookup_name` | PubChem lookup by name (IUPAC, trade or common); a name matching several different compounds is rejected as ambiguous |

A row with SMILES or InChI is never looked up. Otherwise the MOL block is
tried first, then each identifier in the order above until one resolves.
Lookups are batched, throttled to PubChem's 5 requests per second, and
capped at 1,000 distinct identifiers per run
(`DNDLABS_STRUCTURE_LOOKUP_LIMIT`). The quality report gives every
looked-up structure a `structure_lookup` warning naming its source (e.g.
"structure from PubChem CID 2244"). A row that cannot be resolved is
rejected with the reason (not found, ambiguous, service unavailable, over
the limit). Unmapped columns are read but not stored; `ignore`d columns
are dropped.

Two roles describe the measurement's context:

| Role | Accepted values | Stored as |
|---|---|---|
| `assay_format` | `biochemical`, `biochem`, `enzymatic`, `enzyme`, `binding`, `cell free`, `in vitro`; `cell based`, `cellular`, `cell`, `cells`, `whole cell`, `cell assay` | `biochemical` / `cell_based` |
| `control` | `positive`, `positive control`, `pos`, `pc`, `+`; `negative`, `negative control`, `neg`, `nc`, `-`; `no`, `none`, `false`, `0`, `test`, `sample`, `compound` (not a control) | `positive` / `negative` / empty |

Values are matched case-insensitively, with spaces, `_`, `-` and `/`
treated as one separator (`Cell-based`, `cell_based` and `whole-cell` all
match); a lone `+` or `-` is kept as given. Any other value keeps the
record, leaves the field empty and adds an `assay_context` warning
(`validation/assay_context.py`).

Files are limited to 25 MiB and 100,000 rows by default
(`DNDLABS_UPLOAD_MAX_BYTES`, `DNDLABS_UPLOAD_MAX_ROWS`). An SDF's structures
become a `smiles` column, each molecule's title line a `name` column, and
its data fields further columns. A SMILES file (`.smi`, `.smiles`) has one
`SMILES [name]` per line; a MOL file (`.mol`) holds one molecule. Both give
`smiles` and `name` columns. Excel files use the first worksheet, with the
first non-empty row as headers.

## Datasets

| Method | Path | Purpose |
|---|---|---|
| GET | `/datasets` | List the calling org's datasets, newest first |
| GET | `/datasets/{id}` | Dataset + all its records |
| GET | `/datasets/{id}/records?mw_min=&mw_max=&target=&source=&activity_min_nm=&activity_max_nm=&limit=&offset=` | Filtered records |
| GET | `/datasets/{id}/quality-report` | `QualityReport` |
| GET | `/datasets/{id}/assessment` | `DatasetAssessment`: hit/lead potency classes, criteria and per-compound computed properties |
| GET | `/datasets/{id}/enrichment` | `{"enrichment_enabled": bool, "results": EnrichmentResult[]}` |
| GET | `/datasets/{id}/export?format=csv\|jsonl` | Download, fixed column order: the `NormalizedRecord` fields (including `assay_format` and `control` after `assay_type`), then `clogp`, `tpsa`, `hbd`, `hba`, `rotatable_bonds`, `rings`, `qed`, `lipinski_violations`, `alerts` (e.g. `PAINS: quinone_A(370); Brenk: chinone_1`), `potency_class` (the record's own measurement class; the assessment's `potency_classes` count compounds by the majority rule below) |

`EnrichmentResult.status` is one of `enriched`, `skipped_no_key`, `failed`.

### Hit/lead assessment

`DatasetAssessment` judges a dataset the way a hit-to-lead review does.
A dataset may hold one compound several times, once per measurement
context (target, assay type, assay format, control); the assessment
counts `compounds` (distinct structures) out of `measurements` (records).
Control records are left out and counted in `controls`.

- **Potency class** of each measurement's activity value (IC50, Ki, …):
  `optimized` < 100 nM, `lead` < 1 µM, `hit` < 10 µM, `inactive` ≥ 10 µM,
  or `unknown` (no value, or a qualifier that leaves the class open —
  e.g. `> 50` nM, or `< 50000` nM). A compound's class is the most potent
  class that a majority of its measurements reach, so one outlying
  measurement does not promote it. `potency_classes` and `actives` (hits
  or better) count compounds.
- **Per assay format** (`by_format`: `biochemical`, `cell_based`, and
  `null` for measurements without a format), the same compound counts
  from that format's measurements alone, since biochemical and cell-based
  potency are judged separately.
- **Criteria**, each over all compounds, the actives and the five most
  potent compounds (`most_potent_ids`: the record of each one's most
  potent measurement; lower-bound values are not ranked), as
  `{"passing", "evaluated"}`:

  | `criterion` | Met when |
  |---|---|
  | `mw_under_500` | MW < 500 |
  | `clogp_under_5` | cLogP (Crippen) < 5 |
  | `lipinski` | At most one rule-of-five violation: MW > 500, cLogP > 5, NH + OH > 5, N + O > 10 |
  | `rotatable_bonds_under_10` | Fewer than 10 rotatable bonds |
  | `tpsa_under_140` | Polar surface area < 140 Å² |
  | `tpsa_under_90` | Polar surface area < 90 Å² (CNS penetration) |
  | `no_pains_alerts` | No PAINS alert |
  | `no_reactive_metabolite_alerts` | No reactive-metabolite alert |

- **Profiles**: per record, the computed properties (RDKit, from the
  standardized structure; `hbd`/`hba` are Lipinski's NH + OH and N + O
  counts), `lipinski_violations`, `alerts`, `potency_class` and `criteria`.
  A compound without a usable structure has no properties and is not
  evaluated.
- **Alerts** (`StructuralAlert`: `family`, `name`, `atoms`), from three
  families:
  - `pains`: RDKit's 480 PAINS filters (assay-interference compounds);
  - `brenk`: RDKit's 105 Brenk filters (unwanted groups); listed but not
    a criterion, as they include common groups such as phenol esters;
  - `reactive_metabolite`: 15 groups that form reactive metabolites, e.g.
    anilines, nitroaromatics, thiophenes, furans, quinones and Michael
    acceptors.

  `atoms` index the atoms of the record's `canonical_smiles` as RDKit
  parses it, for highlighting.

## Service and health (no auth)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Service name, version, documentation links and endpoint list (`ServiceInfo`); browsers sending `Accept: text/html` get an HTML landing page |
| GET | `/health`, `/api/v1/health` | Liveness: `{"status": "ok"}`. Never touches the database — this is Render's `healthCheckPath` |
| GET | `/api/v1/health/ready` | Readiness: `{"status": "ok", "database": "ok"}`, or `503` with `{"status": "unavailable", "database": "unavailable"}` when the database is unreachable or not at the deployed code's newest migration |

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
| `422` | Invalid request body (e.g. a `SourceSpec` missing the field its source needs, a column mapping without a column that identifies the structure, an invalid email), a password that fails the policy, or an uploaded file that is empty, too large, of an unsupported type or unreadable |
| `429` | Sign-in locked after repeated failures; retry after the `Retry-After` seconds |
| `500` | Internal error (e.g. storage failure); detail is logged, not returned |
