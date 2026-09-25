# D&D Labs

**Data infrastructure for AI-driven drug discovery.**

D&D Labs turns fragmented chemical data (public databases, lab-instrument
exports, internal data lakes) into standardized, validated, model-ready
datasets, each shipped with a data-quality report.

[![CI](https://github.com/johnny882020/Discover-Disrupt-/actions/workflows/ci.yml/badge.svg)](https://github.com/johnny882020/Discover-Disrupt-/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/johnny882020/Discover-Disrupt-)

## Features

| Stage | What it does |
|---|---|
| **Ingest** | PubChem PUG REST (by CID or name), CSV lab/ELN exports, generic JSON uploads |
| **Validate** | Required fields, RDKit structure checks (SMILES/InChI), duplicate detection by InChIKey |
| **Normalize** | Canonical SMILES, InChI/InChIKey, formula, activity values converted to nM |
| **Store** | PostgreSQL (Docker) or SQLite, with Alembic migrations and raw-record lineage |
| **Serve** | REST API, CLI, and CSV/JSONL export with a fixed schema |

## Quickstart

### Docker

```bash
docker compose up --build
```

The API starts on <http://localhost:8000> (interactive docs at `/docs`).

```bash
curl -X POST localhost:8000/pipelines/run \
  -H 'content-type: application/json' \
  -d '{"source": "pubchem", "identifiers": ["2244", "3672", "5090"]}'

curl localhost:8000/pipelines/runs/<run_id>                 # status and dataset_id
curl localhost:8000/datasets/<dataset_id>                   # normalized records
curl localhost:8000/datasets/<dataset_id>/quality-report    # data-quality report
```

### Render

To deploy the API and a managed PostgreSQL database, use the **Deploy to
Render** button above. It reads the Blueprint in `render.yaml`. See
[docs/deployment.md](docs/deployment.md). After deploying, run:

```bash
python scripts/smoke_test.py https://<service>.onrender.com
```

### Local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
dnd-pipeline run --source pubchem --ids 2244,3672,5090
```

```text
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

To see validation catch bad data, run the bundled malformed lab export:

```bash
dnd-pipeline run --source csv --path tests/fixtures/lab_export_malformed.csv
# 12 records → 5 accepted, 6 rejected, 1 duplicate
```

## CLI

| Command | Description |
|---|---|
| `dnd-pipeline run --source {pubchem,csv,json} …` | Ingest, validate, store and export a dataset |
| `dnd-pipeline status <run_id>` | Show run status |
| `dnd-pipeline datasets` | List datasets |
| `dnd-pipeline show <dataset_id>` | Print records as JSON lines |
| `dnd-pipeline report <dataset_id> [--json]` | Print the quality report |
| `dnd-pipeline export <dataset_id> --format {csv,jsonl}` | Write the dataset to a file |
| `dnd-pipeline init-db` | Apply database migrations |

Run `dnd-pipeline <command> --help` for all options.

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/pipelines/run` | Start a run (returns `202`) |
| `GET` | `/pipelines/runs/{run_id}` | Run status |
| `GET` | `/datasets` | List datasets |
| `GET` | `/datasets/{id}` | Dataset with records |
| `GET` | `/datasets/{id}/quality-report` | Quality report |
| `GET` | `/datasets/{id}/export?format=csv\|jsonl` | Download dataset |
| `GET` | `/` | Landing page (browsers) or service info as JSON |
| `GET` | `/health` | Health check |

See [docs/api.md](docs/api.md) for request and response details. The sample
files are built into the Docker image at `/app/samples/`, so a CSV run can use
`"path": "/app/samples/lab_export_malformed.csv"`.

## Architecture

```text
   api/          cli/          delivery
      └─── pipeline/ ───┘      orchestration, export
ingestion/  validation/  storage/
              core/            contracts, config, logging, errors
```

Implementation modules depend only on `core/`, which holds the shared Pydantic
contracts and protocols. See [docs/architecture.md](docs/architecture.md).

## Configuration

Settings are read from `DNDLABS_*` environment variables or a `.env` file
(see [.env.example](.env.example)).

| Variable | Default |
|---|---|
| `DNDLABS_DATABASE_URL` | `sqlite:///./dndlabs.db` |
| `DNDLABS_EXPORT_DIR` | `./exports` |
| `DNDLABS_LOG_LEVEL` | `INFO` |
| `DNDLABS_LOG_JSON` | `true` |
| `DNDLABS_PUBCHEM_BASE_URL` | `https://pubchem.ncbi.nlm.nih.gov/rest/pug` |
| `DNDLABS_PUBCHEM_TIMEOUT_SECONDS` | `30` |
| `DNDLABS_PUBCHEM_BATCH_SIZE` | `100` |
| `DNDLABS_PUBCHEM_MAX_RETRIES` | `3` |
| `DNDLABS_PUBCHEM_BACKOFF_SECONDS` | `0.5` |
| `DNDLABS_AUTO_CREATE_SCHEMA` | `true` |

## Development

```bash
pytest --cov=dndlabs                   # full suite (PubChem mocked)
DNDLABS_LIVE_TESTS=1 pytest -m live    # against live PubChem
ruff check . && ruff format --check .
mypy src/
```

Helper scripts live in `scripts/`:

- `smoke_test.py <base_url>`: end-to-end check of a running deployment
- `seed_sample_data.py`: load the sample datasets
- `generate_synthetic_lab_export.py`: create test CSVs with injected defects
- `record_pubchem_fixture.py`: refresh the PubChem test fixtures

Contributor guidelines are in [CLAUDE.md](CLAUDE.md).

## Roadmap

- ChEMBL, UniProt and PDB connectors (currently stubs)
- Authentication and multi-tenancy
- A dedicated job queue in place of in-process background tasks
