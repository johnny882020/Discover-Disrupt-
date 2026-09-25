# Architecture

This document defines the module boundaries, shared contracts, and database
schema. Changes to anything here are **contract changes**: update this file
and call them out explicitly.

## Layers

```text
      api/ (FastAPI)        cli/ (Typer)        delivery
             └───────┬───────────┘
                 pipeline/                      orchestration, export, wiring
      ┌──────────────┼───────────────┬──────────────┐
 ingestion/     validation/      filtering/   preprocessing/  enrichment/
      └──────────────┼───────────────┴──────────────┘
                   core/                        contracts, protocols, config,
                                                logging, exceptions
                   auth/                        API keys, org multi-tenancy
                   storage/                      SQLAlchemy models, repositories
```

| Rule | Enforced by |
|---|---|
| `ingestion`, `validation`, `filtering`, `preprocessing`, `enrichment`, `auth`, `storage` import only from `core` | Code review |
| Concrete classes are wired only in `pipeline/factory.py` | Composition root |
| `api` and `cli` never touch SQLAlchemy | `Repositories` protocol bundle |
| Values crossing a module boundary are Pydantic models | `core/schemas.py` |
| Every repository method takes an explicit `org_id`, never inferred from a request body | Tenant isolation |

## Pipeline run

```text
SourceSpec → Connector.fetch → RawRecord[]
                                   │
                                   ▼
                             Validator.run → NormalizedRecord[] + QualityReport
                                   │
                   DatasetRepository.create (records persisted — required for the FKs below)
                                   │
                        ┌──────────┴──────────┐
                  Featurizer            EnrichmentService
              (RDKit descriptors)    (GenMol, or skipped)
```

Runs move through `pending → running → succeeded | failed`. Bad records never
fail a run; they are recorded as issues in the quality report. A run is
marked `failed` only on infrastructure errors (ingestion, storage), and the
error message is stored on the run. **Records/dataset must be stored before
feature vectors or enrichment results**, since both reference
`normalized_records.id` by foreign key.

## Contracts (`core/schemas.py`)

| Model | Purpose |
|---|---|
| `Organization` / `ApiKeyCreated` / `ApiKeyRecord` / `OrgContext` | Multi-tenancy: a customer org, a one-time key reveal, its persisted (hashed) form, and the resolved auth context injected per request |
| `SourceSpec` | What to ingest: `source`, `identifiers` (PubChem CIDs), `csv_path`, `json_path`, `chembl_target`, `dataset_name` — validated so each source has what it needs |
| `RawRecord` | Unvalidated connector output; numeric fields may still be strings; unknown fields go into `extra` |
| `NormalizedRecord` | Model-ready row keyed by `record_key` (InChIKey); always carries `dataset_id` |
| `ValidationIssue` | `rule`, `severity` (`error` / `warning`), `source_record_id`, `field`, `message` |
| `QualityReport` | Counts, `issues_by_rule`, `issues` and `pass_rate` for one run |
| `DatasetFilter` | Query filters over a dataset's records (MW range, target, source, activity range, pagination) |
| `FeatureVector` | RDKit descriptors + Morgan fingerprint for one record |
| `EnrichmentRequest` / `GeneratedCandidate` / `EnrichmentResult` | One record submitted for GenMol enrichment, one generated analog, and the per-record outcome (`enriched` / `skipped_no_key` / `failed`) |
| `PipelineRun` | Run metadata: `org_id`, `status`, `error`, `dataset_id`, timestamps |
| `Dataset` / `DatasetWithRecords` | Stored dataset metadata, with or without its records — both `org_id`-scoped |

IDs are UUID4. Timestamps are timezone-aware UTC.

## Protocols (`core/protocols.py`)

```python
class Connector(Protocol):
    source: SourceType

    def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]: ...  # async generator


class ValidationRule(Protocol):
    name: str

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome: ...


class Featurizer(Protocol):
    def featurize(self, record: NormalizedRecord) -> FeatureVector: ...


class EnrichmentClient(Protocol):
    def is_enabled(self) -> bool: ...
    async def enrich_batch(
        self, requests: Sequence[EnrichmentRequest]
    ) -> list[EnrichmentResult]: ...
```

`Connector.fetch` is a plain (non-`async`) method typed to return
`AsyncIterator[RawRecord]` — implementations are async generator functions,
so calling `fetch(spec)` returns an iterator immediately; no `await` before
the `async for`.

Repositories (`OrganizationRepository`, `ApiKeyRepository`, `RunRepository`,
`DatasetRepository`, `QualityReportRepository`, `FeatureRepository`,
`EnrichmentRepository`) are bundled as `Repositories`. Every method on the
org-scoped ones takes `org_id` as an explicit argument — this is the entire
tenant-isolation mechanism; there is no other check. A lookup of a missing
or wrong-org entity raises `NotFoundError`.

## Auth

API-key, not username/password: an admin bootstraps an organization and its
first key (`POST /api/v1/admin/orgs`, guarded by `DNDLABS_ADMIN_BOOTSTRAP_SECRET`,
a separate secret from any org's own key). The raw key is shown exactly once;
only an Argon2 hash and a short lookup `prefix` are stored. Every other
endpoint requires `X-API-Key: <raw_key>`, resolved by `AuthService.resolve`
into an `OrgContext` that every downstream call is scoped by.

## Validation

Record rules run in this order. Each receives the record as the previous
rule left it.

| # | Rule | Errors (record rejected) | Warnings (record kept) |
|---|---|---|---|
| 1 | `schema` | No SMILES or InChI; molecular weight not numeric or ≤ 0 | — |
| 2 | `compound_identity` | Unparsable SMILES or InChI; SMILES and InChI describe different compounds | Supplied InChIKey or formula disagrees with the structure (computed value used) |
| 3 | `unit_normalization` | Value not numeric or negative; missing/unsupported unit; unsupported relation operator | Unit given without a value |

The dataset rule `duplicates` then keeps the first record per `record_key`
and drops the rest with a warning. `record_key` is the InChIKey RDKit
computes from the structure, so duplicates are caught across sources and
SMILES spellings. `activity_value_nm` is in nanomolar; accepted units are
`M`, `mM`, `uM`/`µM`/`μM`, `nM`, `pM` and `mol/L` variants (case-insensitive
except that molar must be uppercase `M`).

## Filtering & preprocessing

`filtering/query.py` translates a `DatasetFilter` into a SQL predicate at the
repository layer (`GET /datasets/{id}/records?mw_min=&target=&...`) —
distinct from validation, which decides correctness, not selection.
`preprocessing/featurize.py` computes RDKit descriptors (MW, LogP, TPSA,
HBD/HBA, rotatable bonds, ring count, QED) and a Morgan fingerprint for every
accepted record with a canonical SMILES, stored in `feature_vectors`.

## NVIDIA BioNeMo enrichment

See [`docs/nvidia-nim.md`](nvidia-nim.md) for the full design and the
research behind it. Summary: for each accepted record, `EnrichmentService`
calls GenMol (a BioNeMo NIM) with the record's canonical SMILES as a seed,
generating scored candidate analogs — property-guided generation, not a
pure embedding lookup (no such small-molecule endpoint exists in NVIDIA's
published blueprints). When `DNDLABS_NVIDIA_NIM_API_KEY` is unset, a
`NullEnrichmentClient` marks every record `skipped_no_key` — enrichment is
explicit or absent, never approximated.

## Connectors

| Source | Module | Notes |
|---|---|---|
| PubChem | `ingestion/pubchem.py` | PUG REST property endpoint. CIDs fetched in batches (default 100). Retries with exponential backoff on 429/5xx/transport errors. |
| ChEMBL | `ingestion/chembl.py` | `/activity.json?target_chembl_id=...`, paginated via `page_meta.next` (its domain-root prefix is stripped before reuse against the client's own `base_url`). |
| CSV | `ingestion/csv_connector.py` | Delimiter sniffed (`,` `;` tab); header aliases case-insensitive; unknown columns go into `extra`. |
| JSON | `ingestion/json_connector.py` | A top-level list, or `{"records": [...]}` with flat scalar values. |
| UniProt, PDB | `ingestion/registry.py` | Planned; requesting one raises `ConnectorNotFoundError`. |

## Exceptions (`core/exceptions.py`)

```text
DndLabsError
├── ConfigurationError
├── IngestionError
│   └── ConnectorNotFoundError
├── ValidationError        # validator failure, not a bad record
├── StorageError
│   └── NotFoundError
├── AuthError
│   └── InvalidApiKeyError
├── PipelineError
├── ExportError
└── EnrichmentError
```

## Database schema (Alembic revision `0001`)

| Table | Key columns | Notes |
|---|---|---|
| `organizations` | `id`, `name`, `is_active` | Tenant root |
| `api_keys` | `org_id`, `prefix` (unique), `hashed_key`, `revoked_at` | Raw key never stored |
| `pipeline_runs` | `org_id`, `source`, `status`, `dataset_id`, `request_payload` (JSON) | |
| `datasets` | `org_id`, `run_id` (unique), `record_count` | One per run |
| `normalized_records` | `org_id`, `dataset_id`, `record_key`, all `NormalizedRecord` fields | Unique `(dataset_id, record_key)` |
| `validation_issues` | `org_id`, `dataset_id`, `severity`, `rule`, `message` | |
| `feature_vectors` | `org_id`, `record_id` (unique), `descriptors` (JSON), `fingerprint_bits` (JSON) | |
| `enrichment_results` | `org_id`, `record_id`, `status`, `candidates` (JSON) | |

`GUID`/`StringArray` custom column types make UUID and array columns native
on PostgreSQL and JSON/TEXT-backed on SQLite, so the same models and
migration run identically against Postgres (Docker/Render) and SQLite
(local dev, tests). `dnd-pipeline init-db` applies migrations; it also
adopts a schema created earlier by `DNDLABS_AUTO_CREATE_SCHEMA=true` (dev
convenience) by stamping revision `0001` before upgrading.

## Frontend

A separate React 18 + TypeScript + Vite SPA under `web/`, deployed as its own
Render Static Site. Talks to the API via `X-API-Key`, held in memory and
`sessionStorage` (not `localStorage`). Built against a mock server (MSW) that
mirrors the real API contract, so it can be developed and demoed without a
running backend, and against the real backend in its own Playwright e2e test.
See `web/src/design-system/tokens.css` for the palette/type/spacing system.
