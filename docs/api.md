# API Reference

Base URL: `http://localhost:8000` locally, `https://dndlabs-api.onrender.com`
on Render. All routes are under `/api/v1` except `/health` and `/` (also
mirrored at the bare root). Interactive docs: `/docs`. Auth header on every
`/api/v1/*` route except `/api/v1/admin/*`: `X-API-Key: <key>`.

## Admin (bootstrap, not customer-facing)

Header: `X-Admin-Secret: <DNDLABS_ADMIN_BOOTSTRAP_SECRET>`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/admin/orgs` | `{"name": "Acme"}` → creates an org, returns `ApiKeyCreated` (the raw key, shown once) |
| POST | `/admin/orgs/{org_id}/keys` | Issue an additional key for an existing org |

## Auth (self-service)

| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/whoami` | Resolve the calling key's org — used by the frontend's key-entry screen |
| POST | `/auth/keys/revoke` | Revoke the calling key (204) |
| DELETE | `/orgs/me/data` | Privacy: delete all of the calling org's runs/datasets/records/reports (204). The org and its keys are kept. |

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
| `401` | Missing, invalid or revoked API key (or wrong admin secret on `/admin/*`) |
| `404` | Unknown run/dataset, or one that belongs to a different org |
| `422` | Invalid request body (e.g. a `SourceSpec` missing the field its source needs) |
| `500` | Internal error (e.g. storage failure); detail is logged, not returned |
