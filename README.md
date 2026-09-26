# D&D Labs Platform

Multi-tenant data infrastructure for AI-native drug discovery.

D&D Labs ingests chemical/biological data from external sources and lab
exports, validates and normalizes it into standardized, model-ready
datasets, and optionally enriches accepted compounds with AI-generated
candidate analogs via NVIDIA BioNeMo. Every organization's data is isolated
behind its own API key.

```text
Ingest → Validate & normalize → Featurize → Enrich → Deliver model-ready data
```

**Stack:** FastAPI + SQLAlchemy 2.0 + Alembic (Postgres/SQLite) on the
backend; React 18 + TypeScript + Vite on the frontend; deployed to Render
via `render.yaml`.

**Reference docs:**
[Architecture](docs/architecture.md) ·
[API](docs/api.md) ·
[Deployment](docs/deployment.md) ·
[NVIDIA integration](docs/nvidia-nim.md) ·
[Contributor guide](CLAUDE.md)

## Quickstart

### Docker Compose

```bash
docker compose up --build
```

- API: `http://localhost:8000` (interactive docs at `/docs`)
- Frontend: `http://localhost:5173`

Sign in immediately with the shared free-tier credential
(`DNDLABS_FREE_TIER_SHARED_PASSWORD`, default `freetier2026`) — see
[Auth](docs/architecture.md#auth) for what this is and its limits — or
bootstrap a real, isolated organization:

```bash
curl -X POST localhost:8000/api/v1/admin/orgs \
  -H "X-Admin-Secret: dev-admin-secret" \
  -H "content-type: application/json" -d '{"name": "Acme Pharma"}'
# -> {"raw_key": "ddl_live_...", ...} — shown once, save it now
```

Paste the key into the frontend, or drive the API directly:

```bash
KEY="ddl_live_..."
curl -X POST localhost:8000/api/v1/pipelines/run -H "X-API-Key: $KEY" \
  -H "content-type: application/json" \
  -d '{"source": "pubchem", "identifiers": ["2244", "3672"]}'

curl localhost:8000/api/v1/pipelines/runs/<run_id> -H "X-API-Key: $KEY"
curl localhost:8000/api/v1/datasets/<dataset_id>/quality-report -H "X-API-Key: $KEY"
```

### Without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
dnd-pipeline init-db
dnd-pipeline bootstrap-org "Acme Pharma"      # prints org_id and api_key
dnd-pipeline run --org-id <org_id> --source pubchem --ids 2244,3672

uvicorn dndlabs.api.app:create_app --factory --reload   # API, locally

cd web && npm ci && npm run dev              # frontend at :5173, mocked API by default
```

Render deployment: [docs/deployment.md](docs/deployment.md).

## Validation, by example

```bash
dnd-pipeline run --org-id <org_id> --source csv --path tests/fixtures/lab_export_malformed.csv
# 5 records -> 3 accepted, 2 rejected (invalid SMILES, missing structure)
```

Every rejection is a `ValidationIssue` (rule, field, message) attached to
the run's `QualityReport`. Malformed input never crashes a run.

## Configuration

Full list: [`.env.example`](.env.example). The variables that matter most:

| Variable | Default | Purpose |
|---|---|---|
| `DNDLABS_DATABASE_URL` | `sqlite:///./dndlabs.db` | `postgresql+psycopg://…` in Docker/Render |
| `DNDLABS_ADMIN_BOOTSTRAP_SECRET` | `change-me-in-production` | Guards `POST /admin/orgs` |
| `DNDLABS_FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allow-origin |
| `DNDLABS_NVIDIA_NIM_API_KEY` | unset | Enrichment runs but marks every record `skipped_no_key` when unset |
| `DNDLABS_FREE_TIER_SHARED_PASSWORD` | `freetier2026` | **Temporary, insecure.** Single shared login, no database dependency. Clear it before onboarding real customers — see [Auth](docs/architecture.md#auth) |

## Development

```bash
pytest --cov=dndlabs                       # backend: 190 tests, 97% coverage
DNDLABS_LIVE_TESTS=1 pytest -m live        # against the real external APIs (opt-in)
ruff check . && ruff format --check . && mypy src/ --strict

cd web && npm run lint && npm run typecheck && npm test -- --run && npm run build
npx playwright test                        # e2e; needs PLAYWRIGHT_BASE_URL pointed at a real backend
```

Coding standards and layering rules: [CLAUDE.md](CLAUDE.md).

```text
src/dndlabs/{core,auth,ingestion,validation,filtering,preprocessing,enrichment,pipeline,storage,api,cli}
tests/{unit (mirrors src), integration, live, fixtures}
web/{src (mirrors into web/tests), e2e}
docker/  docs/  scripts/
```

CI (`.github/workflows/ci.yml`) runs three jobs on every push and PR:
`backend` (ruff, mypy `--strict`, pytest), `docker` (builds and
smoke-tests the API image), and `frontend` (eslint, `tsc`, vitest, `vite
build`). Dependency scans (`pip-audit`, `npm audit`) run informationally;
see Known limitations.

## Known limitations

- **NVIDIA enrichment**: request/response contract verified from NVIDIA's
  own source; the hosted base URL is not confirmed against a live endpoint
  — see [docs/nvidia-nim.md](docs/nvidia-nim.md).
- **No self-service signup**: an operator bootstraps each organization via
  the admin-secret-protected endpoint.
- **`DNDLABS_FREE_TIER_SHARED_PASSWORD`** trades tenant isolation for
  operational simplicity while enabled — see
  [Auth](docs/architecture.md#auth).
- UniProt and PDB connectors are stubs (`ingestion/registry.py`); calling
  them raises `ConnectorNotFoundError`.
- No dependency lockfile — `pip install -e ".[dev]"` installs unpinned
  floor versions (the frontend *is* pinned, via `package-lock.json`).
- Dependency scanning is informational, not a merge gate. Current known
  findings (`react-router` moderate open-redirect; `vite`/`esbuild`
  dev-server tooling; transitive `cryptography`/`pip`/`setuptools`
  versions) need a deliberate, tested upgrade before promotion to a hard
  gate — `react-router` in particular is a breaking major-version bump.
- No code-level SAST (e.g. `bandit`); dependency scanning covers known-
  vulnerable packages only, not custom code patterns.
- Playwright e2e runs manually, not gated in CI (needs a real Postgres and
  a built frontend in the runner).
- No Dependabot/Renovate config.
- `PRIVACY_POLICY.md` is a draft pending legal review.
