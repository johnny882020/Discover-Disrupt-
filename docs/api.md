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

## Sign-in and accounts

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/login` | none | `{"email", "password"}` → `SessionCreated` (`token`, `expires_at`, `user`, `org_name`) |
| POST | `/auth/logout` | session | End the calling session (204) |
| POST | `/auth/password` | session | `{"current_password", "new_password"}` → 204; ends the user's other sessions |
| POST | `/auth/invitations` | admin | `{"email", "role": "member"\|"admin"}` → `InvitationCreated` (201) |
| POST | `/auth/invitations/preview` | none | `{"token"}` → `InvitationPreview` (`email`, `role`, `org_name`, `expires_at`); does not redeem |
| POST | `/auth/invitations/accept` | none | `{"token", "password"}` → `SessionCreated` (201); creates the account |
| GET | `/auth/whoami` | any | `OrgContext`: `org_id`, `org_name`, `principal` (`api_key`/`user`), `role`, and `api_key_id` or `user_id` + `session_id` + `email` |
| POST | `/auth/keys/revoke` | API key | Revoke the calling key (204) |
| DELETE | `/orgs/me/data` | admin | Privacy: delete all of the calling org's runs/datasets/records/reports (204). The org, its keys and its user accounts are kept. |

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
{"source": "pubchem", "identifiers": ["2244", "3672"]}
{"source": "chembl", "chembl_target": "CHEMBL204"}
{"source": "csv", "csv_path": "/app/samples/lab_export.csv"}
{"source": "json", "json_path": "/app/samples/upload.json"}
```

`csv_path`/`json_path` are read from the **API server's** filesystem, not
the caller's. Returns `202` with a `PipelineRun` (`status: "pending"`);
`dataset_id` is `null` until the run finishes — poll
`GET /pipelines/runs/{id}` (the frontend does this automatically).

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
| `400` | Invitation token unknown, expired or already used |
| `401` | Missing, invalid, expired or revoked credential; wrong email or password (always `invalid email or password`); wrong admin secret on `/admin/*`. Carries `WWW-Authenticate: Bearer` |
| `403` | Authenticated but not allowed: inviting or deleting org data without the `admin` role, revoking a key from a session, signing out with a key, or a wrong current password on `/auth/password` |
| `404` | Unknown run/dataset, or one that belongs to a different org |
| `409` | Invitation for an email that is already a member of the org, or redemption for an email that already has an account |
| `422` | Invalid request body (e.g. a `SourceSpec` missing the field its source needs, an invalid email), or a password that fails the policy |
| `429` | Sign-in locked after repeated failures; retry after the `Retry-After` seconds |
| `500` | Internal error (e.g. storage failure); detail is logged, not returned |
