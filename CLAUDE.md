# CLAUDE.md — D&D Labs

AI-native data infrastructure for drug discovery. Contracts and module
boundaries are frozen in `docs/architecture.md`; read it before changing code.

## Commands

```bash
pip install -e ".[dev]"          # install
pytest --cov=dndlabs             # full test suite with coverage
ruff check . && ruff format --check .
mypy src/                        # strict
dnd-pipeline --help              # CLI
uvicorn dndlabs.api.app:create_app --factory --reload   # API
docker compose up --build        # API + Postgres
```

Live PubChem tests are opt-in: `DNDLABS_LIVE_TESTS=1 pytest -m live`.

## Layering (enforced by review)

- `core/` — config, logging, exceptions, Pydantic contracts, protocols. Depends on nothing internal.
- `ingestion/`, `validation/`, `storage/` — import **only** from `core/`.
- `pipeline/` — orchestrator, exporter, and the composition root (`pipeline/factory.py`).
- `api/`, `cli/` — thin delivery layers over `pipeline/` services and `core` protocols. Never import SQLAlchemy.

## Coding standards (non-negotiable)

- Type hints on every function/method signature; `mypy --strict` passes on `src/`.
- Every module, class, and public function has a Google-style docstring.
- All boundaries (API requests/responses, connector outputs, DB rows) are Pydantic models from `core.schemas`; no raw dicts crossing a module boundary.
- Repository pattern for all DB access; SQLAlchemy sessions never leave `storage/`.
- Raise from the `DndLabsError` hierarchy (`core/exceptions.py`); never a bare `except:`; bad records become `ValidationIssue`s, not exceptions.
- Structured logging via `dndlabs.core.logging.get_logger` — no `print()` (the CLI uses `typer.echo` for user output).
- Config only via `dndlabs.core.config.Settings` (`DNDLABS_*` env vars); no hardcoded values or secrets.
- Small, single-responsibility functions; composition over inheritance.
- Every module ships with tests in the same commit; `tests/unit/` mirrors `src/dndlabs/` 1:1.
- Contract changes (`core/schemas.py`, `core/protocols.py`, DB schema) must update `docs/architecture.md` and be called out explicitly.
