# Contributor Guide

D&D Labs is a multi-tenant data platform for AI-native drug discovery.
Read [docs/architecture.md](docs/architecture.md) before changing code.

## Commands

```bash
pip install -e ".[dev]"
pytest --cov=dndlabs                      # backend tests + coverage
ruff check . && ruff format --check .
mypy src/                                 # strict
DNDLABS_LIVE_TESTS=1 pytest -m live       # live PubChem/ChEMBL/GenMol (opt-in)

cd web && npm ci
npm run lint && npm run typecheck && npm test -- --run && npm run build
npx playwright test                       # e2e, needs a real backend at PLAYWRIGHT_BASE_URL

docker compose up --build                 # full stack locally
```

## Layering

- `core/` — contracts, protocols, config, logging, exceptions. Imports nothing internal.
- `auth/`, `ingestion/`, `validation/`, `filtering/`, `preprocessing/`, `enrichment/`, `storage/` import only from `core/`.
- `pipeline/` orchestrates a run; `pipeline/factory.py` is the only place concrete classes are wired together.
- `api/`, `cli/` are thin layers over `pipeline/` and `core` protocols — never import SQLAlchemy directly.
- `web/` is a separate React+TS app; it imports nothing from `src/dndlabs`, only the HTTP API.

## Standards

- **Types:** annotate every signature; `mypy --strict` passes on `src/`. Frontend: `tsc --noEmit` under `strict`.
- **Docs:** Google-style docstrings on every module, class and public function.
- **Boundaries:** values crossing modules, the API or the database are Pydantic models from `core.schemas`, never raw dicts.
- **Tenant isolation:** every org-scoped repository method takes `org_id` explicitly, derived server-side from the authenticated key — never accepted from a request body or query param.
- **Data access:** only through repositories; SQLAlchemy sessions stay inside `storage/`.
- **Errors:** raise subclasses of `DndLabsError`; no bare `except:`. A bad record becomes a `ValidationIssue`, not an exception. A failed enrichment call becomes `status="failed"`, never raised into the pipeline. An exception's own message never reaches an API client (`api/errors.py` returns a fixed generic `500` body and logs the detail server-side) — don't put anything client-relevant in an exception message that isn't already a mapped 4xx.
- **Logging:** `core.logging.get_logger`, never `print()`. It redacts secret-shaped fields and `Bearer` tokens — don't work around that.
- **Config:** `core.config.Settings` (`DNDLABS_*` env vars) only. No hardcoded values or committed secrets.
- **Storage ordering:** a dataset's records must be persisted before any feature vector or enrichment result that references them (foreign key) — see `pipeline/orchestrator.py`'s stage order.
- **Tests:** ship with the code in the same commit. `tests/unit/` mirrors `src/dndlabs/` 1:1; `web/tests/` mirrors `web/src/`.
- **Contracts:** changes to `core/schemas.py`, `core/protocols.py` or the DB schema update `docs/architecture.md` and get a new Alembic revision; NVIDIA contract changes update `docs/nvidia-nim.md`.
