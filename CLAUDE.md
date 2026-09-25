# Contributor Guide

D&D Labs is data infrastructure for drug discovery. Read
[docs/architecture.md](docs/architecture.md) before changing code.

## Commands

```bash
pip install -e ".[dev]"
pytest --cov=dndlabs                      # tests and coverage
ruff check . && ruff format --check .     # lint and format
mypy src/                                 # strict type-check
DNDLABS_LIVE_TESTS=1 pytest -m live       # live PubChem (opt-in)
uvicorn dndlabs.api.app:create_app --factory --reload
docker compose up --build
```

For deployment (Render Blueprint in `render.yaml`), see [docs/deployment.md](docs/deployment.md).

## Layering

- `core/` holds contracts, protocols, config, logging and exceptions. It imports nothing internal.
- `ingestion/`, `validation/` and `storage/` import only from `core/`.
- `pipeline/` orchestrates the run. `pipeline/factory.py` is the only place concrete classes are wired together.
- `api/` and `cli/` are thin layers over `pipeline/` and the `core` protocols. They never import SQLAlchemy.

## Standards

- **Types:** annotate every signature; `mypy --strict` must pass on `src/`.
- **Docs:** Google-style docstrings on every module, class and public function.
- **Boundaries:** values crossing modules, the API or the database are Pydantic models from `core.schemas`, never raw dicts.
- **Data access:** only through repositories; SQLAlchemy sessions stay inside `storage/`.
- **Errors:** raise subclasses of `DndLabsError`; no bare `except:`. Report a bad record as a `ValidationIssue`, not an exception.
- **Logging:** use `core.logging.get_logger`, never `print()`. The CLI writes user output with `typer.echo`.
- **Config:** use `core.config.Settings` (`DNDLABS_*` env vars). Don't hardcode values or commit secrets.
- **Tests:** ship with the code in the same commit. `tests/unit/` mirrors `src/dndlabs/`.
- **Contracts:** changes to `core/schemas.py`, `core/protocols.py` or the DB schema must update `docs/architecture.md`, and DB changes need a new Alembic revision.
