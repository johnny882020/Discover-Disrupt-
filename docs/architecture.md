# Architecture

Module boundaries, shared contracts, and database schema. Anything in this
document is a **contract**: changing it is a contract change, called out
explicitly in the PR that makes it.

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

Runs move through `pending → running → succeeded | failed`. A bad record
never fails a run; it is recorded as a `ValidationIssue` on the quality
report. A run is marked `failed` only on infrastructure errors (ingestion,
storage), with the error persisted on the run row.

Ordering constraint: the dataset and its records must be persisted before
any feature vector or enrichment result, since both reference
`normalized_records.id` by foreign key. Enforced by stage order in
`pipeline/orchestrator.py`.

## Contracts (`core/schemas.py`)

| Model | Purpose |
|---|---|
| `Organization` / `ApiKeyCreated` / `ApiKeyRecord` / `OrgContext` | Tenant, one-time key reveal, its persisted (hashed) form, resolved auth context per request |
| `SourceSpec` | Ingest request: `source`, `identifiers` (PubChem CIDs), `csv_path`, `json_path`, `chembl_target`, `dataset_name` — cross-validated per source |
| `RawRecord` | Unvalidated connector output; numeric fields may still be strings; unknown fields go into `extra` |
| `NormalizedRecord` | Model-ready row keyed by `record_key` (InChIKey); always carries `dataset_id` |
| `ValidationIssue` | `rule`, `severity` (`error` / `warning`), `source_record_id`, `field`, `message` |
| `QualityReport` | Counts, `issues_by_rule`, `issues`, `pass_rate` for one run |
| `DatasetFilter` | Record query filters (MW range, target, source, activity range, pagination) |
| `FeatureVector` | RDKit descriptors + Morgan fingerprint for one record |
| `EnrichmentRequest` / `GeneratedCandidate` / `EnrichmentResult` | One record submitted for GenMol enrichment, one generated analog, per-record outcome (`enriched` / `skipped_no_key` / `failed`) |
| `PipelineRun` | `org_id`, `status`, `error`, `dataset_id`, timestamps |
| `Dataset` / `DatasetWithRecords` | Stored dataset metadata, with or without records — both `org_id`-scoped |

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
`AsyncIterator[RawRecord]`: implementations are async generator functions,
so `fetch(spec)` returns an iterator immediately, with no `await` before
the `async for`.

Repositories (`OrganizationRepository`, `ApiKeyRepository`, `RunRepository`,
`DatasetRepository`, `QualityReportRepository`, `FeatureRepository`,
`EnrichmentRepository`) are bundled as `Repositories`. Every org-scoped
method takes `org_id` explicitly — the entire tenant-isolation mechanism;
there is no other check. A lookup of a missing or wrong-org entity raises
`NotFoundError`.

`OrganizationRepository.ping()` is the exception: it exists only for the
readiness probe (below), not for business logic.

## Auth

API-key, not username/password. An admin bootstraps an organization and its
first key (`POST /api/v1/admin/orgs`, guarded by
`DNDLABS_ADMIN_BOOTSTRAP_SECRET` — distinct from any org's own key). The raw
key is returned once; only an Argon2 hash and a short lookup `prefix` are
stored. Every other endpoint requires `X-API-Key: <raw_key>`, resolved by
`AuthService.resolve` into an `OrgContext` that scopes every downstream call.

**Free-tier shared password.** If `DNDLABS_FREE_TIER_SHARED_PASSWORD` is
set (default `freetier2026`), that exact value authenticates as one fixed
identity (`auth.service.FREE_TIER_ORG_ID`) — no per-org key, and
deliberately no database lookup, so it authenticates even if the database
is unreachable or unmigrated. It cannot be revoked, and every caller who
knows the password shares one identity and one dataset.

This is a temporary operational convenience for a single-operator
deployment, not a tenant boundary: while it is set, isolation holds between
the shared identity and any other org's real key, but not between users of
the shared password itself. Clear the variable before onboarding any
customer who needs their data isolated from other users of this value.

## Validation

Record rules run in order; each receives the record as the previous rule
left it.

| # | Rule | Errors (record rejected) | Warnings (record kept) |
|---|---|---|---|
| 1 | `schema` | No SMILES or InChI; molecular weight not numeric or ≤ 0 | — |
| 2 | `compound_identity` | Unparsable SMILES/InChI; SMILES and InChI describe different compounds | Supplied InChIKey/formula disagrees with the structure (computed value used) |
| 3 | `unit_normalization` | Value not numeric or negative; missing/unsupported unit; unsupported relation operator | Unit given without a value |

The dataset-level `duplicates` rule then keeps the first record per
`record_key` and drops the rest with a warning. `record_key` is the
InChIKey RDKit computes from the structure, so duplicates are caught across
sources and SMILES spellings. `activity_value_nm` is normalized to
nanomolar; accepted units are `M`, `mM`, `uM`/`µM`/`μM`, `nM`, `pM` and
`mol/L` variants (case-insensitive except molar, which must be `M`).

## Filtering & preprocessing

`filtering/query.py` translates a `DatasetFilter` into a SQL predicate at
the repository layer (`GET /datasets/{id}/records?mw_min=&target=&...`) —
selection, distinct from validation's correctness checks.
`preprocessing/featurize.py` computes RDKit descriptors (MW, LogP, TPSA,
HBD/HBA, rotatable bonds, ring count, QED) and a Morgan fingerprint for
every accepted record with a canonical SMILES, stored in `feature_vectors`.

## NVIDIA BioNeMo enrichment

See [`docs/nvidia-nim.md`](nvidia-nim.md) for the full contract and its
verification status. Summary: for each accepted record, `EnrichmentService`
calls GenMol (a BioNeMo NIM) with the record's canonical SMILES as a seed,
generating scored candidate analogs — property-guided generation, not an
embedding lookup (no such small-molecule endpoint exists in NVIDIA's
published blueprints). Without `DNDLABS_NVIDIA_NIM_API_KEY`, a
`NullEnrichmentClient` marks every record `skipped_no_key`; enrichment is
explicit or absent, never approximated.

## Connectors

| Source | Module | Notes |
|---|---|---|
| PubChem | `ingestion/pubchem.py` | PUG REST property endpoint. CIDs batched (default 100). Exponential backoff on 429/5xx/transport errors. |
| ChEMBL | `ingestion/chembl.py` | `/activity.json?target_chembl_id=...`, paginated via `page_meta.next` (domain-root prefix stripped before reuse against the client's own `base_url`). Same backoff pattern as PubChem. |
| CSV | `ingestion/csv_connector.py` | Delimiter sniffed (`,` `;` tab); header aliases case-insensitive; unknown columns go into `extra`. |
| JSON | `ingestion/json_connector.py` | A top-level list, or `{"records": [...]}` with flat scalar values. |
| UniProt, PDB | `ingestion/registry.py` | Stubs; requesting one raises `ConnectorNotFoundError`. |

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

Every `DndLabsError` maps to an HTTP status in `api/errors.py`; the
exception's own message is never returned to the client for the generic
(`DndLabsError`) case or for anything outside this hierarchy — see
[docs/api.md#errors](api.md#errors).

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
(local dev, tests).

`dnd-pipeline init-db` applies migrations. If it finds a schema created by
`DNDLABS_AUTO_CREATE_SCHEMA=true` (dev convenience) with no
`alembic_version` table, it stamps revision `0001` before upgrading, and
logs a `WARNING` (`migration_stamp_shortcut`) — that path assumes the
existing schema actually matches `0001`; verify it does before relying on
the stamp.

## Readiness vs. liveness

`GET /health` never touches the database — pure liveness, safe for a
platform health check to gate restarts on.
`GET /api/v1/health/ready` does, via `OrganizationRepository.ping()`, and
returns `503` if the database is unreachable or unmigrated. The two are
deliberately different endpoints: a broken database must not restart an
otherwise-healthy process, but it must be possible to detect from outside
without reading logs. See [docs/api.md](api.md#health).

## Connection pooling

`storage/database.py`'s `create_db_engine` sets `pool_size=3,
max_overflow=2, pool_recycle=300` for Postgres — conservative by design,
sized for Render's free-tier connection cap; a single worker does not need
more even under load.

## Frontend

A separate React 18 + TypeScript + Vite SPA under `web/`, deployed as its
own Render Static Site. Talks to the API via `X-API-Key`, held in memory
and `sessionStorage` (never `localStorage`). Built against a mock server
(MSW) mirroring the real API contract for backend-independent development,
and exercised against the real backend by its own Playwright e2e test. See
`web/src/design-system/tokens.css` for the palette/type/spacing system.
