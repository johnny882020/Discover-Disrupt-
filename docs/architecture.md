# D&D Labs — Architecture (Phase 0 contracts)

This document freezes the module boundaries, shared contracts and database
schema for the MVP. Every module depends only on `dndlabs.core`; the
orchestrator (`pipeline/`) and the delivery layers (`api/`, `cli/`) compose the
concrete implementations at the edge. Changing anything in this document is a
contract change and must be flagged, not patched around.

## 1. Layering

```
            ┌──────────┐     ┌──────────┐
            │   api/   │     │   cli/   │      delivery (thin)
            └────┬─────┘     └────┬─────┘
                 └───────┬────────┘
                   ┌─────▼──────┐
                   │ pipeline/  │               orchestration + export + wiring
                   └─────┬──────┘
       ┌─────────────────┼──────────────────┐
┌──────▼──────┐   ┌──────▼──────┐    ┌──────▼──────┐
│ ingestion/  │   │ validation/ │    │  storage/   │   implementations
└──────┬──────┘   └──────┬──────┘    └──────┬──────┘
       └─────────────────┼──────────────────┘
                   ┌─────▼──────┐
                   │   core/    │                config, logging, exceptions,
                   └────────────┘                schemas, protocols
```

Rules:

* `ingestion`, `validation`, `storage` import **only** from `core` (plus third-party libs).
* `pipeline` imports from `core` and wires concrete `ingestion`/`validation`/`storage`
  implementations in a single composition root (`pipeline/factory.py`).
* `api` and `cli` depend on `core` protocols and on `pipeline` services; they never
  touch SQLAlchemy. The API receives its services via FastAPI dependency injection,
  so tests substitute in-memory fakes.
* Every value crossing a module boundary is a Pydantic model from `core.schemas`.

## 2. Data flow of one pipeline run

```
SourceSpec ─► Connector.fetch ─► list[RawRecord] ─► Validator.run ─► ValidationOutcome
                                    │                                 │  ├ accepted: list[NormalizedRecord]
                                    │                                 │  └ report:   QualityReport
                                    ▼                                 ▼
                              RawRecordRepository              DatasetRepository / QualityReportRepository
                                                                      │
                                                                      ▼
                                                        Exporter (CSV / JSONL, model-ready)
```

Run lifecycle: `PENDING → RUNNING → SUCCEEDED | FAILED`. A run that ingests
zero valid records still succeeds (the dataset is empty and the quality report
says why); only infrastructure-level errors (`IngestionError`, `StorageError`,
…) mark it `FAILED` with the error message stored on the run.

## 3. Shared contracts (`dndlabs.core.schemas`)

| Model | Purpose | Key fields |
|---|---|---|
| `SourceType` (enum) | Which connector | `pubchem`, `csv`, `json` |
| `SourceSpec` | What to ingest | `source`, `identifiers: list[str]`, `identifier_type: cid \| name`, `path: str \| None` |
| `RawRecord` | Connector output, **unvalidated** | `source`, `source_record_id`, `name`, `smiles`, `inchi`, `inchikey`, `molecular_formula`, `molecular_weight` (str/float), `activity_type`, `activity_value` (str/float), `activity_unit`, `target`, `extra: dict[str, JsonScalar]` |
| `NormalizedRecord` | Model-ready row | `record_key` (= InChIKey), `source`, `source_record_id`, `name`, `canonical_smiles`, `inchi`, `inchikey`, `molecular_formula`, `molecular_weight: float \| None`, `activity_type`, `activity_value_nm: float \| None`, `target` |
| `Severity` (enum) | Issue severity | `error` (record rejected), `warning` (record kept) |
| `ValidationIssue` | One finding | `rule`, `severity`, `source_record_id`, `field`, `message` |
| `RuleOutcome` | Result of a record rule | `record: NormalizedRecord`, `issues: list[ValidationIssue]` |
| `QualityReport` | Per-run data-quality report | `run_id`, `dataset_id`, `total_records`, `accepted_records`, `rejected_records`, `duplicate_records`, `warning_count`, `error_count`, `issues_by_rule: dict[str,int]`, `issues`, `pass_rate` |
| `ValidationOutcome` | Validator output | `accepted: list[NormalizedRecord]`, `report: QualityReport` |
| `RunStatus` (enum) | Run lifecycle | `pending`, `running`, `succeeded`, `failed` |
| `PipelineRun` | Run metadata | `id`, `spec`, `status`, `created_at`, `finished_at`, `error`, `dataset_id` |
| `Dataset` | Stored dataset metadata | `id`, `run_id`, `name`, `source`, `record_count`, `created_at` |
| `DatasetWithRecords` | Dataset + rows | `dataset`, `records: list[NormalizedRecord]` |
| `ExportFormat` (enum) | Export target | `csv`, `jsonl` |
| `RunResult` | Orchestrator result | `run`, `dataset`, `report`, `export_path` |

IDs are UUID4 strings. Timestamps are timezone-aware UTC.

### Normalization conventions

* `record_key` is the standard InChIKey computed by RDKit from the parsed
  structure (not the value the source claims), so duplicates across sources collide.
* Activity concentrations are normalized to **nanomolar** (`activity_value_nm`).
  Supported units: `M`, `mM`, `uM`/`µM`/`μM`, `nM`, `pM` (case-insensitive for
  the prefix letter only where unambiguous). A value without a unit, or an
  unknown unit, is an error.
* `canonical_smiles` is RDKit canonical isomeric SMILES.

## 4. Protocols (`dndlabs.core.protocols`)

```python
class Connector(Protocol):
    source: SourceType
    def fetch(self, spec: SourceSpec) -> list[RawRecord]: ...

class ValidationRule(Protocol):          # per-record; may normalize fields
    name: str
    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome: ...

class DatasetRule(Protocol):             # whole-dataset (e.g. duplicates)
    name: str
    def apply(self, records: Sequence[NormalizedRecord]) -> DatasetRuleOutcome: ...

class RunRepository(Protocol):
    def create(self, run: PipelineRun) -> PipelineRun: ...
    def update(self, run: PipelineRun) -> PipelineRun: ...
    def get(self, run_id: str) -> PipelineRun: ...          # NotFoundError

class RawRecordRepository(Protocol):
    def add_many(self, run_id: str, records: Sequence[RawRecord]) -> int: ...
    def list_for_run(self, run_id: str) -> list[RawRecord]: ...

class DatasetRepository(Protocol):
    def create(self, dataset: Dataset, records: Sequence[NormalizedRecord]) -> Dataset: ...
    def get(self, dataset_id: str) -> DatasetWithRecords: ...  # NotFoundError
    def list(self) -> list[Dataset]: ...

class QualityReportRepository(Protocol):
    def save(self, report: QualityReport) -> QualityReport: ...
    def get_for_dataset(self, dataset_id: str) -> QualityReport: ...  # NotFoundError
```

`Repositories` is a frozen dataclass bundling the four repositories; it is
the only storage handle `pipeline/`, `api/` and `cli/` see.

Record rules run in a fixed order; each receives the `NormalizedRecord` produced
so far and returns an updated copy plus issues:

1. `schema` — required identifiers present, numeric fields parse.
2. `compound_identity` — SMILES/InChI parse with RDKit, canonicalize, derive
   InChIKey, flag SMILES↔InChI and claimed-vs-computed InChIKey mismatches.
3. `unit_normalization` — activity value + unit → nM.

Then dataset rules: `duplicates` (by `record_key`, first occurrence wins,
later ones are counted as `duplicate_records` and dropped with a warning).

A record with any `error` issue is rejected; warnings are reported but kept.

## 5. Exceptions (`dndlabs.core.exceptions`)

```
DndLabsError
├── ConfigurationError
├── IngestionError
│   └── ConnectorNotFoundError
├── ValidationError            # validation *infrastructure* failure, not a bad record
├── StorageError
│   └── NotFoundError
├── PipelineError
└── ExportError
```

Bad records never raise; they become `ValidationIssue`s.

## 6. Database schema (SQLAlchemy 2.0, Alembic revision `0001`)

```
pipeline_runs
  id            VARCHAR(36) PK
  source        VARCHAR(16)  NOT NULL
  spec          JSON         NOT NULL
  status        VARCHAR(16)  NOT NULL  (indexed)
  error         TEXT         NULL
  dataset_id    VARCHAR(36)  NULL
  created_at    TIMESTAMPTZ  NOT NULL
  finished_at   TIMESTAMPTZ  NULL

raw_records
  id               INTEGER PK autoincrement
  run_id           VARCHAR(36) FK → pipeline_runs.id ON DELETE CASCADE (indexed)
  source           VARCHAR(16) NOT NULL
  source_record_id VARCHAR(255) NOT NULL
  payload          JSON NOT NULL          -- full RawRecord dump (lineage)

datasets
  id            VARCHAR(36) PK
  run_id        VARCHAR(36) FK → pipeline_runs.id ON DELETE CASCADE UNIQUE
  name          VARCHAR(255) NOT NULL
  source        VARCHAR(16)  NOT NULL
  record_count  INTEGER      NOT NULL
  created_at    TIMESTAMPTZ  NOT NULL

normalized_records
  id                INTEGER PK autoincrement
  dataset_id        VARCHAR(36) FK → datasets.id ON DELETE CASCADE (indexed)
  position          INTEGER NOT NULL      -- stable export ordering
  record_key        VARCHAR(27) NOT NULL  (indexed)
  source, source_record_id, name, canonical_smiles, inchi, inchikey,
  molecular_formula, molecular_weight FLOAT, activity_type,
  activity_value_nm FLOAT, target
  UNIQUE (dataset_id, record_key)

quality_reports
  id            INTEGER PK autoincrement
  run_id        VARCHAR(36) FK → pipeline_runs.id ON DELETE CASCADE UNIQUE
  dataset_id    VARCHAR(36) FK → datasets.id ON DELETE CASCADE UNIQUE
  total_records, accepted_records, rejected_records, duplicate_records INTEGER
  pass_rate     FLOAT
  report        JSON NOT NULL          -- full QualityReport dump
  created_at    TIMESTAMPTZ NOT NULL
```

PostgreSQL in Docker, SQLite for local runs and tests (`JSON` maps to `JSONB`-
compatible `JSON` on Postgres and TEXT-backed JSON on SQLite).

## 7. Delivery surfaces

API (FastAPI):

| Method | Path | Returns |
|---|---|---|
| `POST` | `/pipelines/run` | `202` + `PipelineRun` (executed as an in-process background task) |
| `GET` | `/pipelines/runs/{run_id}` | `PipelineRun` |
| `GET` | `/datasets` | `list[Dataset]` |
| `GET` | `/datasets/{dataset_id}` | `DatasetWithRecords` |
| `GET` | `/datasets/{dataset_id}/quality-report` | `QualityReport` |
| `GET` | `/health` | `{"status": "ok"}` |

CLI (`dnd-pipeline`): `run`, `status`, `datasets`, `show`, `report`, `export`, `init-db`.

## 8. Connectors

* **PubChem** (`ingestion/pubchem.py`): PUG REST
  `/compound/cid/{cids}/property/{props}/JSON` (batched, default 100 CIDs per
  call) and `/compound/name/{name}/property/{props}/JSON` (one name per call).
  Retries with exponential backoff on 5xx/`ServerBusy`/transport errors; a 404
  `PUGREST.NotFound` for a name becomes an empty result plus a warning log, not a
  crash. Handles both the legacy (`CanonicalSMILES`/`IsomericSMILES`) and current
  (`SMILES`/`ConnectivitySMILES`) property keys.
* **CSV** (`ingestion/csv_connector.py`): lab-instrument/ELN exports; header
  aliases are case-insensitive (`compound_id`/`id`, `smiles`, `inchi`, `name`,
  `activity_value`/`value`, `activity_unit`/`unit`, …). Unknown columns go into
  `extra`. Missing file / no identifier column → `IngestionError`.
* **JSON** (`ingestion/json_connector.py`): either a top-level list or
  `{"records": [...]}`; each item validated with a Pydantic input model.
* **Stubs**: ChEMBL/UniProt/PDB are documented as future connectors only
  (`ingestion/registry.py` lists them; requesting one raises `ConnectorNotFoundError`).
