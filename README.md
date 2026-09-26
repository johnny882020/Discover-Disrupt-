# D&D Labs Platform

Multi-tenant data infrastructure for AI-native drug discovery.

**D&D Labs turns messy chemistry data into clean, model-ready datasets, so
your scientists spend their time on discovery rather than data wrangling.**
Bring in compounds and activity data from public sources like PubChem and
ChEMBL, or upload your own lab exports as CSV or JSON. The platform checks
every record automatically: that each structure is valid, that its
identifiers agree, and that activity values use known units. It converts
all activity values to one standard unit and removes duplicate compounds,
even when different sources describe them differently. Nothing is silently
discarded: a clear quality report explains every record that was rejected
and why, so you can trust what goes into your models. Each accepted
compound comes with ready-to-use molecular descriptors and fingerprints.
Where AI enrichment is enabled, the platform can also suggest new candidate
molecules similar to each compound, using NVIDIA's BioNeMo generative
chemistry models. Download the results with one click in formats your
machine-learning tools already understand. Your organization's data stays
private to your organization. Your team signs in with individual,
invitation-only accounts, and your software can connect directly through
secure API keys.

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

Create an organization, then invite its first admin:

```bash
curl -X POST localhost:8000/api/v1/admin/orgs \
  -H "X-Admin-Secret: dev-admin-secret" \
  -H "content-type: application/json" -d '{"name": "Acme Pharma"}'
# -> {"org_id": "...", "raw_key": "ddl_live_...", ...} — API key, shown once

curl -X POST localhost:8000/api/v1/admin/orgs/<org_id>/invitations \
  -H "X-Admin-Secret: dev-admin-secret" \
  -H "content-type: application/json" -d '{"email": "you@acme.com"}'
# -> {"accept_url": "http://localhost:5173/invite#token=ddl_inv_...", ...}
```

Open the `accept_url`, choose a password, and you are signed in; invite
teammates from the **Team** page. Programs use the API key instead:

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
dnd-pipeline invite-admin <org_id> you@acme.com   # prints a one-time sign-up link
dnd-pipeline run --org-id <org_id> --source pubchem --ids 2244,3672

uvicorn dndlabs.api.app:create_app --factory --reload   # API, locally

cd web && npm ci && npm run dev              # frontend at :5173, mocked API by default
                                             # (mock sign-in: ada@acme.example / correct horse battery)
```

Render deployment: [docs/deployment.md](docs/deployment.md).

## Accounts and access

| Who | Signs in with | Can |
|---|---|---|
| Operator | `X-Admin-Secret` (`DNDLABS_ADMIN_BOOTSTRAP_SECRET`) | Create organizations, issue API keys, invite each organization's first admin |
| Org admin | Email + password | Everything a member can, plus invite colleagues (Team page) and delete the organization's data |
| Org member | Email + password | Run pipelines; view, filter and export the organization's datasets |
| Program | Org API key (`X-API-Key`) | The same as an org admin, over the API |

People join only by invitation: the link they receive works once, expires
after 72 hours, and is where they choose their password. Sessions last 12
hours; five wrong passwords lock an account for 15 minutes. Details:
[Auth](docs/architecture.md#auth).

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
| `DNDLABS_ADMIN_BOOTSTRAP_SECRET` | `change-me-in-production` | Guards the operator endpoints (`/admin/*`: orgs, keys, first-admin invitations) |
| `DNDLABS_FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allow-origin and base URL of invitation links |
| `DNDLABS_SESSION_TTL_HOURS` | `12` | Sign-in session lifetime; see [Auth](docs/architecture.md#auth) for the other account settings |
| `DNDLABS_NVIDIA_NIM_API_KEY` | unset | Enrichment runs but marks every record `skipped_no_key` when unset |

## Development

```bash
pytest --cov=dndlabs                       # backend tests + coverage
DNDLABS_TEST_POSTGRES_URL=postgresql+psycopg://… pytest tests/integration  # migrations on real Postgres
DNDLABS_LIVE_TESTS=1 pytest -m live        # against the real external APIs (opt-in)
ruff check . && ruff format --check . && mypy src/ --strict

cd web && npm run lint && npm run typecheck && npm test -- --run && npm run build
VITE_API_BASE_URL=http://localhost:8000/api/v1 npm run build   # e2e targets the production build
DNDLABS_ADMIN_BOOTSTRAP_SECRET=<API's secret> npx playwright test   # needs the API running on :8000
```

Coding standards and layering rules: [CLAUDE.md](CLAUDE.md).

```text
src/dndlabs/{core,auth,ingestion,validation,filtering,preprocessing,enrichment,pipeline,storage,api,cli}
tests/{unit (mirrors src), integration, live, fixtures}
web/{src (mirrors into web/tests), e2e}
docker/  docs/  scripts/
```

CI (`.github/workflows/ci.yml`) gates every push and PR on four jobs:
`backend` (ruff, mypy `--strict`, pytest — including migrations against a
Postgres 16 service — and `pip-audit`), `frontend` (eslint, `tsc` over
source, tests and configs, vitest, `vite build`, `npm audit`), `docker`
(builds and smoke-tests the images, validates Compose), and `e2e`
(Playwright against the real stack). Dependabot opens weekly update PRs
for pip, npm, GitHub Actions and Docker base images.

## Known limitations

- **NVIDIA enrichment**: request/response contract verified from NVIDIA's
  own source; the hosted base URL is not confirmed against a live endpoint
  — see [docs/nvidia-nim.md](docs/nvidia-nim.md).
- **Accounts are invitation-only, with no email delivery**: an operator
  creates each organization and invites its first admin, and invitation
  links are handed over manually.
- **No password reset or account removal yet**: a user who forgets their
  password cannot recover the account, and members cannot be removed.
- **Sign-in throttling is per account**, not per client IP — see
  [Auth](docs/architecture.md#auth).
- UniProt and PDB are planned sources, not implemented; the API rejects
  them as unknown sources.
- No dependency lockfile — `pip install -e ".[dev]"` installs unpinned
  floor versions (the frontend *is* pinned, via `package-lock.json`).
- No code-level SAST (e.g. `bandit`); dependency scanning covers known-
  vulnerable packages only, not custom code patterns.
- `pip-audit` covers the project's runtime dependencies, not the base
  image's OS packages or bundled tooling; no container image scanning.
- `PRIVACY_POLICY.md` is a draft pending legal review.
