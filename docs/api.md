# D&D Labs API

Base URL (docker-compose): `http://localhost:8000`. Interactive docs:
`/docs` (Swagger UI) and `/openapi.json`. No authentication (MVP).

All request and response bodies are the Pydantic contracts in
`dndlabs.core.schemas` (see `docs/architecture.md`).

## `POST /pipelines/run`

Start a pipeline run. The run executes in-process as a background task;
the response is returned immediately with status `pending`.

Body: `SourceSpec`

```json
{"source": "pubchem", "identifiers": ["2244", "3672", "5090"]}
{"source": "pubchem", "identifiers": ["aspirin", "caffeine"], "identifier_type": "name"}
{"source": "csv",  "path": "/app/samples/lab_export_malformed.csv", "dataset_name": "lab-42"}
{"source": "json", "path": "/app/samples/data_lake_upload.json"}
```

`path` is a path **on the API server** (in docker-compose, `tests/fixtures`
is mounted read-only at `/app/samples`).

Responses: `202` → `PipelineRun`; `422` for invalid specs (e.g. no
identifiers, non-numeric CIDs, unknown source).

## `GET /pipelines/runs/{run_id}`

`200` → `PipelineRun`:

```json
{
  "id": "0ae63889-…",
  "spec": {"source": "csv", "path": "…", "identifiers": [], "identifier_type": "cid", "dataset_name": null},
  "status": "succeeded",
  "created_at": "2026-09-25T13:28:10.525475Z",
  "finished_at": "2026-09-25T13:28:10.598683Z",
  "error": null,
  "dataset_id": "52ada1e5-…"
}
```

`status` is one of `pending`, `running`, `succeeded`, `failed`; on failure
`error` holds the reason (e.g. `PubChem unreachable: …`). `404` if unknown.

## `GET /datasets`

`200` → `list[Dataset]`, newest first.

## `GET /datasets/{dataset_id}`

`200` → `DatasetWithRecords` (`dataset` metadata + `records`, each a
`NormalizedRecord`: `record_key` (InChIKey), `canonical_smiles`, `inchi`,
`inchikey`, `molecular_formula`, `molecular_weight`, `activity_type`,
`activity_value_nm`, `target`, plus source lineage). `404` if unknown.

## `GET /datasets/{dataset_id}/quality-report`

`200` → `QualityReport`:

```json
{
  "run_id": "…", "dataset_id": "…",
  "total_records": 12, "accepted_records": 5, "rejected_records": 6, "duplicate_records": 1,
  "warning_count": 1, "error_count": 6,
  "issues_by_rule": {"compound_identity": 1, "duplicates": 1, "schema": 1, "unit_normalization": 4},
  "issues": [
    {"rule": "compound_identity", "severity": "error", "source_record_id": "LAB-005",
     "field": "smiles", "message": "invalid SMILES: 'C1CC('"}
  ],
  "pass_rate": 0.4167,
  "created_at": "…"
}
```

## `GET /datasets/{dataset_id}/export?format=csv|jsonl`

Downloads the model-ready dataset (`text/csv` or `application/x-ndjson`)
with a fixed column order (`dndlabs.pipeline.exporter.EXPORT_COLUMNS`).

## `GET /health`

`200` → `{"status": "ok"}`.

## Error format

Errors use FastAPI's shape: `{"detail": "..."}`. `404` not found, `422`
invalid input, `500` other domain errors (e.g. storage failures).
