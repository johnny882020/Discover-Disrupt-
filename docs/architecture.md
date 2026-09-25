# Architecture

This document defines the module boundaries, shared contracts, and database
schema. Changes to anything here are **contract changes**: update this file
and call them out in the PR.

## Layers

```text
      api/ (FastAPI)        cli/ (Typer)        delivery
             └───────┬───────────┘
                 pipeline/                      orchestration, export, wiring
      ┌──────────────┼──────────────┐
 ingestion/     validation/      storage/       implementations
      └──────────────┼──────────────┘
                   core/                        contracts, protocols, config,
                                                logging, exceptions
```

| Rule | Enforced by |
|---|---|
| `ingestion`, `validation` and `storage` import only from `core` | Code review |
| Concrete classes are wired only in `pipeline/factory.py` | Composition root |
| `api` and `cli` never touch SQLAlchemy | `Repositories` protocol bundle |
| Values crossing a module boundary are Pydantic models | `core/schemas.py` |

## Pipeline run

```text
SourceSpec → Connector.fetch → RawRecord[] ──→ RawRecordRepository (lineage)
                                   │
                                   ▼
                             Validator.run
                     ┌─────────────┴─────────────┐
            NormalizedRecord[]             QualityReport
                     │                           │
          DatasetRepository              QualityReportRepository
                     │
          Exporter (CSV / JSONL)
```

Runs move through `pending → running → succeeded | failed`. Bad records never
fail a run; they are recorded as issues in the quality report. A run is marked
`failed` only on infrastructure errors (ingestion, storage, export), and the
error message is stored on the run.

## Contracts (`core/schemas.py`)

| Model | Purpose |
|---|---|
| `SourceSpec` | What to ingest: `source`, `identifiers`, `identifier_type`, `path`, `dataset_name` |
| `RawRecord` | Unvalidated connector output; numeric fields may still be strings; unknown fields go into `extra` |
| `NormalizedRecord` | Model-ready row keyed by `record_key` (InChIKey) |
| `ValidationIssue` | `rule`, `severity` (`error` / `warning`), `source_record_id`, `field`, `message` |
| `RuleOutcome` / `DatasetRuleOutcome` | Results of record-level and dataset-level rules |
| `QualityReport` | Counts, `issues_by_rule`, `issues` and `pass_rate` for one run |
| `PipelineRun` | Run metadata: `status`, `error`, `dataset_id` and timestamps |
| `Dataset` / `DatasetWithRecords` | Stored dataset metadata, with or without its records |
| `RunResult` | Orchestrator output: run, dataset, report and export path |

IDs are UUID4 strings. Timestamps are timezone-aware UTC.

## Protocols (`core/protocols.py`)

```python
class Connector(Protocol):
    source: SourceType
    def fetch(self, spec: SourceSpec) -> list[RawRecord]: ...

class ValidationRule(Protocol):
    name: str
    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome: ...

class DatasetRule(Protocol):
    name: str
    def apply(self, records: Sequence[NormalizedRecord]) -> DatasetRuleOutcome: ...
```

There are four repositories, `RunRepository`, `RawRecordRepository`,
`DatasetRepository` and `QualityReportRepository`, bundled together as
`Repositories`. A lookup of a missing entity raises `NotFoundError`.

## Validation

Record rules run in this order. Each rule receives the record as the previous
rule left it.

| # | Rule | Errors (record rejected) | Warnings (record kept) |
|---|---|---|---|
| 1 | `schema` | No SMILES or InChI; molecular weight not numeric or ≤ 0 | — |
| 2 | `compound_identity` | Unparsable SMILES or InChI; SMILES and InChI describe different compounds | Supplied InChIKey or formula disagrees with the structure (the computed value is used) |
| 3 | `unit_normalization` | Value not numeric or negative; missing or unsupported unit | Unit given without a value |

The dataset rule `duplicates` then keeps the first record for each
`record_key` and drops the later ones with a warning.

**Normalization conventions**

- `record_key` is the InChIKey that RDKit computes from the structure, so
  duplicates are caught across sources and SMILES spellings.
- `canonical_smiles` is RDKit canonical isomeric SMILES. A missing formula or
  molecular weight is computed from the structure.
- `activity_value_nm` is in nanomolar. Accepted units are `M`, `mM`, `uM` /
  `µM` / `μM`, `nM`, `pM` and `mol/L` variants. Unit matching is
  case-insensitive, except that molar must be written as uppercase `M`.

## Connectors

| Source | Module | Notes |
|---|---|---|
| PubChem | `ingestion/pubchem.py` | PUG REST property endpoints. CIDs are fetched in batches (default 100); names are resolved one per call. Retries with exponential backoff on 429, 5xx and transport errors. An unknown name is skipped with a warning. Accepts both current and legacy SMILES keys. |
| CSV | `ingestion/csv_connector.py` | Delimiter is sniffed (`,` `;` tab); header aliases are case-insensitive; unknown columns go into `extra`. Raises `IngestionError` for a missing file, ragged rows, or no SMILES/InChI column. |
| JSON | `ingestion/json_connector.py` | A top-level list, or `{"records": [...]}` with flat scalar values. |
| ChEMBL, UniProt, PDB | `ingestion/registry.py` | Planned; requesting one raises `ConnectorNotFoundError`. |

## Exceptions (`core/exceptions.py`)

```text
DndLabsError
├── ConfigurationError
├── IngestionError
│   └── ConnectorNotFoundError
├── ValidationError        # validator failure, not a bad record
├── StorageError
│   └── NotFoundError
├── PipelineError
└── ExportError
```

## Database schema (Alembic revision `0001`)

| Table | Key columns | Constraints |
|---|---|---|
| `pipeline_runs` | `id`, `source`, `spec` (JSON), `status`, `error`, `dataset_id`, `created_at`, `finished_at` | Index on `status` |
| `raw_records` | `run_id`, `source`, `source_record_id`, `payload` (JSON) | FK → runs, cascade |
| `datasets` | `id`, `run_id`, `name`, `source`, `record_count`, `created_at` | One per run |
| `normalized_records` | `dataset_id`, `position`, `record_key`, plus all `NormalizedRecord` fields | Unique `(dataset_id, record_key)` |
| `quality_reports` | `run_id`, `dataset_id`, summary counts, `pass_rate`, `report` (JSON) | One per run and per dataset |

PostgreSQL runs in Docker; tests and local runs use SQLite.
`dnd-pipeline init-db` applies migrations. It also adopts a schema created
earlier by `DNDLABS_AUTO_CREATE_SCHEMA`.
