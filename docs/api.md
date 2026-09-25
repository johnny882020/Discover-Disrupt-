# API Reference

Base URL: `http://localhost:8000` locally, or `https://<service>.onrender.com` on Render. The OpenAPI schema is at `/openapi.json`
and interactive docs at `/docs`. The API has no authentication yet.

Schemas are defined in [`dndlabs.core.schemas`](../src/dndlabs/core/schemas.py).

## Pipelines

### `POST /pipelines/run`

Starts a pipeline run in the background and returns immediately.

**Body:** `SourceSpec`

| Field | Type | Notes |
|---|---|---|
| `source` | `pubchem` \| `csv` \| `json` | Required |
| `identifiers` | `string[]` | PubChem CIDs or names |
| `identifier_type` | `cid` \| `name` | Default `cid` |
| `path` | `string` | Server-side file path (csv/json) |
| `dataset_name` | `string` | Optional |

```json
{"source": "pubchem", "identifiers": ["2244", "3672"]}
{"source": "pubchem", "identifiers": ["aspirin"], "identifier_type": "name"}
{"source": "csv", "path": "/app/samples/lab_export_malformed.csv"}
```

The Docker image (local and Render) includes `tests/fixtures/` at `/app/samples/`.

**Responses:** `202` returns a `PipelineRun`; `422` means the spec is invalid.

### `GET /pipelines/runs/{run_id}`

Returns a `PipelineRun`, or `404` if the run doesn't exist.

```json
{
  "id": "0ae63889-…",
  "status": "succeeded",
  "dataset_id": "52ada1e5-…",
  "error": null,
  "created_at": "2026-09-25T13:28:10Z",
  "finished_at": "2026-09-25T13:28:10Z",
  "spec": {"source": "csv", "path": "…"}
}
```

`status` is `pending`, `running`, `succeeded` or `failed`. On failure,
`error` holds the reason.

## Datasets

### `GET /datasets`

Returns `Dataset[]`, newest first.

### `GET /datasets/{dataset_id}`

Returns a `DatasetWithRecords` (dataset metadata plus normalized records),
or `404`.

| Record field | Description |
|---|---|
| `record_key` | InChIKey computed from the structure (deduplication key) |
| `canonical_smiles`, `inchi`, `inchikey` | Canonical identifiers from RDKit |
| `molecular_formula`, `molecular_weight` | Computed if not supplied |
| `activity_type`, `activity_value_nm`, `target` | Activity, normalized to nM |
| `source`, `source_record_id`, `name` | Where the record came from |

### `GET /datasets/{dataset_id}/quality-report`

Returns a `QualityReport`, or `404`.

```json
{
  "total_records": 12,
  "accepted_records": 5,
  "rejected_records": 6,
  "duplicate_records": 1,
  "warning_count": 1,
  "error_count": 6,
  "pass_rate": 0.4167,
  "issues_by_rule": {"compound_identity": 1, "duplicates": 1, "schema": 1, "unit_normalization": 4},
  "issues": [
    {"rule": "compound_identity", "severity": "error", "source_record_id": "LAB-005",
     "field": "smiles", "message": "invalid SMILES: 'C1CC('"}
  ]
}
```

A record with any `error` is rejected. Records with only `warning`s are kept.

### `GET /datasets/{dataset_id}/export`

Downloads the dataset with a fixed column order.

| Query | Values | Content type |
|---|---|---|
| `format` | `csv` (default) | `text/csv` |
| | `jsonl` | `application/x-ndjson` |

## Service

### `GET /`

Returns the service name, version, documentation links and every endpoint.
Start here after a deploy.

```json
{
  "name": "D&D Labs Data API",
  "version": "0.1.0",
  "docs": "/docs",
  "health": "/health",
  "endpoints": ["POST /pipelines/run", "GET /pipelines/runs/{run_id}", "GET /datasets", "..."]
}
```

### `GET /health`

Returns `{"status": "ok"}`. Render uses it as the health check.

## Errors

Errors return `{"detail": "<message>"}`.

| Status | Meaning |
|---|---|
| `404` | Unknown path, run or dataset |
| `422` | Invalid request or unusable source |
| `500` | Internal error (e.g. storage failure) |
