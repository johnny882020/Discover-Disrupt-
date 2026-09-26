# D&D Labs Platform

[![CI](https://github.com/johnny882020/Discover-Disrupt-/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/johnny882020/Discover-Disrupt-/actions/workflows/ci.yml)

Multi-tenant data infrastructure for AI-native drug discovery.

D&D Labs turns fragmented chemistry data into clean, validated, model-ready
datasets, so scientists spend their time on discovery rather than data
wrangling. Every record is checked, standardized and explained — nothing is
silently discarded — and each organization's data stays private to it.

```text
Ingest → Validate & normalize → Featurize → Enrich → Deliver model-ready data
```

## Features

- **Ingestion** from PubChem, ChEMBL and lab exports (CSV, JSON).
- **Validation and normalization:** structure and identifier checks, activity
  values converted to nanomolar, duplicates removed across sources.
- **Quality reports** that explain every rejected record.
- **Featurization:** RDKit descriptors and Morgan fingerprints per compound.
- **AI enrichment (optional):** candidate analogs from NVIDIA BioNeMo GenMol.
- **Export** to CSV or JSON Lines.
- **Multi-tenant access:** invitation-based user accounts for people, API
  keys for programs, strict per-organization data isolation.

## Quick start

```bash
docker compose up --build   # API on :8000 (docs at /docs), web app on :5173
```

Create an organization and invite its first admin:

```bash
API=http://localhost:8000/api/v1
curl -X POST $API/admin/orgs -H "X-Admin-Secret: dev-admin-secret" \
  -H "content-type: application/json" -d '{"name": "Acme Pharma"}'
curl -X POST $API/admin/orgs/<org_id>/invitations -H "X-Admin-Secret: dev-admin-secret" \
  -H "content-type: application/json" -d '{"email": "you@acme.com"}'
```

Open the returned `accept_url`, choose a password, and you are signed in.
Production deployment and onboarding: [docs/deployment.md](docs/deployment.md).

## Documentation

| Document | Contents |
|---|---|
| [Architecture](docs/architecture.md) | Module boundaries, contracts, authentication, database schema |
| [API reference](docs/api.md) | Endpoints, authentication headers, error codes |
| [Deployment](docs/deployment.md) | Render, onboarding, configuration, local development, CI, known limitations |
| [NVIDIA integration](docs/nvidia-nim.md) | GenMol enrichment contract and status |
| [Contributing](CLAUDE.md) | Commands, layering rules, coding standards |
| [Privacy policy](PRIVACY_POLICY.md) | Draft, pending legal review |

## Development

```bash
pip install -e ".[dev]"
pytest --cov=dndlabs && ruff check . && ruff format --check . && mypy src/

cd web && npm ci
npm run lint && npm run typecheck && npm test -- --run && npm run build
```

The full command list — PostgreSQL migration tests, live API tests and
Playwright end-to-end tests — is in [CLAUDE.md](CLAUDE.md). CI runs all of
them on every pull request.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, RDKit ·
React 18, TypeScript, Vite · Docker, Render.

## Status

- The hosted NVIDIA GenMol endpoint is not yet verified against a live key.
- Accounts are invitation-only, with no email delivery or password reset yet.
- The privacy policy is a draft pending legal review.

See [Known limitations](docs/deployment.md#known-limitations) for the full list.

## License

Proprietary. All rights reserved.
