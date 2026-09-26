# D&D Labs Platform

**Multi-tenant data infrastructure for AI-native drug discovery.**

D&D Labs ingests fragmented chemical/biological data — PubChem, ChEMBL, lab
instrument exports, internal data lakes — validates and normalizes it into
standardized, model-ready datasets, and enriches accepted compounds with
AI-generated candidate analogs from NVIDIA's BioNeMo GenMol NIM. Every
organization's data is isolated from every other's behind its own API key.

This is a full rebuild of the project's original single-tenant MVP, adding
the layers a real product needs: a database, authentication, filtering and
preprocessing, a real ChEMBL connector (no longer stubbed), an NVIDIA
BioNeMo enrichment stage, and a proper React frontend — all built and
tested the same way the MVP was: contracts frozen first, then fanned out
into parallel workstreams, gated on tests at every step.

## Architecture

```text
      api/ (FastAPI)        cli/ (Typer)          web/ (React+TS, separate app)
             └───────┬───────────┘                          │
                 pipeline/                          talks to the API only
      ┌──────────────┼───────────────┬──────────────┐
 ingestion/     validation/      filtering/   preprocessing/  enrichment/
      └──────────────┼───────────────┴──────────────┘
              core/  +  auth/  +  storage/
```

`Ingest → Normalize & validate → Featurize → Enrich → Deliver model-ready
data`, all scoped to the authenticated organization. Full contracts, DB
schema and layering rules: [docs/architecture.md](docs/architecture.md).
API reference: [docs/api.md](docs/api.md). NVIDIA integration design and
what's verified vs. guessed: [docs/nvidia-nim.md](docs/nvidia-nim.md).

## Quickstart

### Docker (recommended)

```bash
docker compose up --build
```

- API: <http://localhost:8000> (docs at `/docs`)
- Frontend: <http://localhost:5173>

Fastest path: open <http://localhost:5173> and enter the shared password
`freetier2026` (see `DNDLABS_FREE_TIER_SHARED_PASSWORD` below — **temporary
and insecure**, replace with real per-org keys before onboarding customers).

Or bootstrap a real, isolated organization:

```bash
curl -X POST localhost:8000/api/v1/admin/orgs \
  -H "X-Admin-Secret: dev-admin-secret" \
  -H "content-type: application/json" -d '{"name": "Acme Pharma"}'
# -> {"raw_key": "ddl_live_...", ...} — copy raw_key, shown once
```

Open <http://localhost:5173>, paste the key, and use the app — or drive it
by hand:

```bash
KEY="ddl_live_..."
curl -X POST localhost:8000/api/v1/pipelines/run -H "X-API-Key: $KEY" \
  -H "content-type: application/json" \
  -d '{"source": "pubchem", "identifiers": ["2244", "3672"]}'
# -> {"id": "<run_id>", "status": "pending", ...}

curl localhost:8000/api/v1/pipelines/runs/<run_id> -H "X-API-Key: $KEY"
curl localhost:8000/api/v1/datasets/<dataset_id> -H "X-API-Key: $KEY"
curl localhost:8000/api/v1/datasets/<dataset_id>/quality-report -H "X-API-Key: $KEY"
```

### Local (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
dnd-pipeline init-db
dnd-pipeline bootstrap-org "Acme Pharma"      # prints org_id and api_key
dnd-pipeline run --org-id <org_id> --source pubchem --ids 2244,3672
dnd-pipeline datasets --org-id <org_id>
dnd-pipeline report --org-id <org_id> <dataset_id>

uvicorn dndlabs.api.app:create_app --factory --reload   # the API, locally

cd web && npm ci && npm run dev              # frontend at :5173, mocked API by default
```

Deploying to Render: [docs/deployment.md](docs/deployment.md).

## What validation catches

```bash
dnd-pipeline run --org-id <org_id> --source csv --path tests/fixtures/lab_export_malformed.csv
# 5 records -> 3 accepted, 2 rejected (bad SMILES, missing structure)
```

Every rejection is a `ValidationIssue` (rule, field, message) in the
`QualityReport` — nothing crashes on bad data.

## Configuration

`DNDLABS_*` environment variables (see [.env.example](.env.example)); key
ones:

| Variable | Default | Purpose |
|---|---|---|
| `DNDLABS_DATABASE_URL` | `sqlite:///./dndlabs.db` | `postgresql+psycopg://…` in Docker/Render |
| `DNDLABS_ADMIN_BOOTSTRAP_SECRET` | `change-me-in-production` | Guards `POST /admin/orgs` |
| `DNDLABS_FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allow-origin |
| `DNDLABS_NVIDIA_NIM_API_KEY` | unset | Enrichment runs but marks every record `skipped_no_key` when unset |
| `DNDLABS_FREE_TIER_SHARED_PASSWORD` | `freetier2026` | **Temporary, insecure.** One password authenticates as one shared identity, no per-org key needed. Clear it once real org keys are in use — see [docs/architecture.md](docs/architecture.md#auth) |

Frontend build-time: `VITE_API_BASE_URL` (see `web/.env.example`).

## Development

```bash
pytest --cov=dndlabs                       # 167 tests, 96% coverage (PubChem/ChEMBL/GenMol mocked)
DNDLABS_LIVE_TESTS=1 pytest -m live        # against the real APIs
ruff check . && ruff format --check . && mypy src/

cd web && npm run lint && npm run typecheck && npm test -- --run && npm run build
npx playwright test                        # e2e; needs PLAYWRIGHT_BASE_URL pointed at a real backend
```

Coding standards and layering rules: [CLAUDE.md](CLAUDE.md).

```
src/dndlabs/{core,auth,ingestion,validation,filtering,preprocessing,enrichment,pipeline,storage,api,cli}
tests/{unit (mirrors src), integration, live, fixtures}
web/{src (mirrors into web/tests), e2e}
docker/  docs/  scripts/
```

## Status / known limitations

- **NVIDIA enrichment**: the request/response contract is verified from
  NVIDIA's own source (not guessed); the exact *hosted* base URL is not
  (this build environment cannot reach any NVIDIA domain) — see
  [docs/nvidia-nim.md](docs/nvidia-nim.md) before relying on it live.
- **No self-service signup**: an operator bootstraps each organization via
  the admin-secret-protected endpoint (matches the pitch's sales-assisted,
  10–30-account model).
- UniProt and PDB connectors are documented stubs (`ingestion/registry.py`).
- `PRIVACY_POLICY.md` is a draft pending legal review — see the file for
  what it does and doesn't cover.
- **No dependency lockfile**: `pip install -e ".[dev]"` and `npm ci` (against
  `package-lock.json`, so the frontend *is* pinned) install unpinned
  backend floor versions; a `requirements`/`uv.lock`-style pin for the
  backend is worth adding for fully reproducible CI installs.
- **Dependency scanning is informational, not gating**: `pip-audit` and
  `npm audit --audit-level=high` run in CI (`continue-on-error: true`).
  Current known findings — `cryptography`/`pip`/`setuptools` transitive
  versions on the backend, `react-router` (moderate open-redirect) and
  `vite`/`esbuild` dev-server tooling on the frontend — need a deliberate,
  tested upgrade (`react-router` in particular is a breaking major-version
  bump) before promoting these scans to a hard gate.
- **No code-level SAST** (e.g. `bandit`): dependency scanning covers known-
  vulnerable packages, not custom code patterns.
- **Playwright e2e runs manually only**, not gated in CI — it needs a real
  Postgres and a built frontend in the CI runner, which isn't set up yet.
- No Dependabot/Renovate config for automated dependency-update PRs.
