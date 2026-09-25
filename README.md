# D&D Labs — Discover & Disrupt

AI-native data infrastructure for drug discovery. D&D Labs ingests fragmented
chemical and biological data (public databases, lab-instrument/ELN exports,
internal data-lake dumps), validates and normalizes it, and serves it back as
**standardized, model-ready datasets**, each with a data-quality report.

This repository is the MVP: PubChem, CSV and JSON connectors → validation and
normalization → PostgreSQL/SQLite storage → CSV/JSONL export, available through
a CLI (`dnd-pipeline`) and a REST API (FastAPI).

## Architecture

```
 api/ (FastAPI)      cli/ (Typer)            delivery: thin, no SQL
        └──────┬──────────┘
          pipeline/                          orchestrator, exporter, composition root
   ┌───────────┼────────────┐
ingestion/  validation/   storage/           each imports only from core/
   └───────────┼────────────┘
            core/                            config, logging, exceptions,
                                             Pydantic contracts, protocols
```

One run: `SourceSpec → Connector.fetch → RawRecord[] → Validator → NormalizedRecord[] + QualityReport → repositories → export`.

* **Ingestion**: PubChem PUG REST (by CID, batched, or by name, with retry and backoff), CSV lab exports (delimiter sniffing, header aliases), and generic JSON uploads. ChEMBL, UniProt and PDB are documented stubs.
* **Validation**: schema checks; RDKit compound-identity checks (valid SMILES/InChI, SMILES↔InChI agreement, canonical SMILES, InChIKey, formula); concentrations normalized to **nM**; duplicate detection by InChIKey. Bad records become issues in the report instead of crashing the run.
* **Storage**: SQLAlchemy 2.0 plus Alembic, using the repository pattern. Tables hold runs, raw records (for lineage), datasets, normalized records and quality reports.

Full contracts and DB schema: [`docs/architecture.md`](docs/architecture.md). API reference: [`docs/api.md`](docs/api.md).

## 5-minute quickstart

### Option A: Docker (API + Postgres)

```bash
docker compose up --build            # migrates the DB, then serves on :8000
```

In a second terminal:

```bash
# Trigger a PubChem run via the API
curl -s -X POST localhost:8000/pipelines/run \
  -H 'content-type: application/json' \
  -d '{"source": "pubchem", "identifiers": ["2244", "3672", "5090"]}'
# -> {"id": "<run_id>", "status": "pending", ...}

curl -s localhost:8000/pipelines/runs/<run_id>          # -> status, dataset_id
curl -s localhost:8000/datasets/<dataset_id>            # normalized records
curl -s localhost:8000/datasets/<dataset_id>/quality-report
curl -s "localhost:8000/datasets/<dataset_id>/export?format=csv"

# A messy lab export (fixtures are mounted at /app/samples)
curl -s -X POST localhost:8000/pipelines/run -H 'content-type: application/json' \
  -d '{"source": "csv", "path": "/app/samples/lab_export_malformed.csv"}'

# The CLI works inside the container too
docker compose exec api dnd-pipeline run --source pubchem --ids 2244,3672,5090
```

Swagger UI: <http://localhost:8000/docs>.

### Option B: Local (SQLite, no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

dnd-pipeline run --source pubchem --ids 2244,3672,5090
```

Output (JSON logs go to stderr, and the summary goes to stdout):

```
Run 5f0c…
  status   succeeded
  source   pubchem
  dataset  9b1e…
  records  3
  export   exports/9b1e….csv

Quality report
  total records      3
  accepted           3
  rejected (errors)  0
  duplicates         0
  warnings / errors  0 / 0
  pass rate          100.0%
```

To see validation at work:

```bash
dnd-pipeline run --source csv --path tests/fixtures/lab_export_malformed.csv
# 12 records -> 5 accepted, 6 rejected (bad SMILES, unknown unit, non-numeric/negative
# value, missing structure, missing unit), 1 duplicate (same InChIKey, different SMILES)

dnd-pipeline datasets                         # list datasets
dnd-pipeline report <dataset_id>              # full quality report (--json for raw)
dnd-pipeline show <dataset_id> --limit 5      # records as JSON lines
dnd-pipeline export <dataset_id> --format jsonl --output-dir out/
dnd-pipeline status <run_id>
dnd-pipeline run --source pubchem --names aspirin,caffeine
dnd-pipeline run --source json --path tests/fixtures/data_lake_upload.json

uvicorn dndlabs.api.app:create_app --factory --reload   # the API, locally
python scripts/seed_sample_data.py                      # load all sample datasets offline
```

## Configuration

All settings are environment variables (or a `.env` file; see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `DNDLABS_DATABASE_URL` | `sqlite:///./dndlabs.db` | SQLAlchemy URL (`postgresql+psycopg://…` in Docker) |
| `DNDLABS_EXPORT_DIR` | `./exports` | Where run exports are written |
| `DNDLABS_LOG_LEVEL` / `DNDLABS_LOG_JSON` | `INFO` / `true` | Structured logging |
| `DNDLABS_PUBCHEM_BASE_URL` | `https://pubchem.ncbi.nlm.nih.gov/rest/pug` | PUG REST endpoint |
| `DNDLABS_PUBCHEM_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `DNDLABS_PUBCHEM_BATCH_SIZE` | `100` | CIDs per request |
| `DNDLABS_PUBCHEM_MAX_RETRIES` / `DNDLABS_PUBCHEM_BACKOFF_SECONDS` | `3` / `0.5` | Retry policy |
| `DNDLABS_AUTO_CREATE_SCHEMA` | `true` | Create tables on startup (dev); Docker uses Alembic (`dnd-pipeline init-db`) |

## Development

```bash
pytest --cov=dndlabs              # unit and integration tests (PubChem is mocked)
DNDLABS_LIVE_TESTS=1 pytest -m live   # opt-in checks against live PubChem
ruff check . && ruff format --check .
mypy src/                         # strict
python scripts/generate_synthetic_lab_export.py --rows 500 --out big.csv
python scripts/record_pubchem_fixture.py   # re-record PubChem fixtures from the live API
```

Coding standards and layering rules are in [`CLAUDE.md`](CLAUDE.md).

```
src/dndlabs/{core,ingestion,validation,storage,pipeline,api,cli}
tests/{unit (mirrors src), integration, fixtures}
scripts/  docker/  docs/
```

## MVP limitations

* No auth, multi-tenancy or UI. Runs execute in-process (FastAPI background tasks), not on a job queue.
* CSV/JSON `path`s are read from the server's filesystem.
* ChEMBL, UniProt and PDB connectors are stubs (`ingestion/registry.py`).
