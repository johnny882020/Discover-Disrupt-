"""Retire the pre-rebuild MVP schema, if present, and ensure the platform schema exists.

The pre-rebuild MVP also used revision id ``0001`` for an unrelated schema
(``pipeline_runs``, ``raw_records``, ``datasets``, ``normalized_records``,
``quality_reports`` — no ``organizations``/``api_keys``/``org_id``). A database
that ran the MVP therefore reports ``0001`` as current, so ``upgrade head``
never applied the platform's own ``0001`` and the platform tables never
existed.

This revision detects that state (``organizations`` missing) and:

- moves every legacy MVP table out of the way without deleting data —
  into a ``legacy_mvp`` schema on PostgreSQL (which also carries their
  indexes, constraints and sequences, avoiding name collisions), or renamed
  to ``legacy_mvp_<table>`` elsewhere;
- then applies the platform schema from revision ``0001``.

On a database where ``0001`` already created the platform schema, it is a
no-op.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_TABLES = (
    "quality_reports",
    "normalized_records",
    "datasets",
    "raw_records",
    "pipeline_runs",
)
LEGACY_SCHEMA = "legacy_mvp"


def _initial_revision() -> ModuleType:
    """Load revision 0001 so its platform-schema DDL can be reused, not duplicated."""
    path = Path(__file__).with_name("0001_initial_schema.py")
    spec = importlib.util.spec_from_file_location("_dndlabs_revision_0001", path)
    if spec is None or spec.loader is None:  # pragma: no cover - file ships with the package
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("organizations"):
        return

    legacy = [t for t in LEGACY_TABLES if inspector.has_table(t)]
    if bind.dialect.name == "postgresql":
        if legacy:
            op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {LEGACY_SCHEMA}"))
        for table in legacy:
            op.execute(sa.text(f"ALTER TABLE {table} SET SCHEMA {LEGACY_SCHEMA}"))
    else:
        for table in legacy:
            for index in inspector.get_indexes(table):
                if index["name"]:
                    op.drop_index(index["name"], table_name=table)
            op.rename_table(table, f"{LEGACY_SCHEMA}_{table}")

    _initial_revision().upgrade()


def downgrade() -> None:
    """No-op: legacy MVP data stays where ``upgrade`` moved it; restore it manually if needed."""
