"""Reproduce the pre-rebuild MVP database state for migration regression tests."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from tests.conftest import FIXTURES

LEGACY_RUN_ID = "legacy-run-1"


def apply_legacy_mvp_schema(url: str) -> None:
    """Apply the MVP's own revision ``0001`` to ``url`` and insert one legacy row.

    The result matches what production databases carried: the MVP schema,
    ``alembic_version = '0001'``, and no platform tables.
    """
    config = Config()
    config.set_main_option("script_location", str(FIXTURES / "legacy_mvp_alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO pipeline_runs (id, source, spec, status, created_at) "
                "VALUES (:id, 'csv', '{}', 'succeeded', CURRENT_TIMESTAMP)"
            ),
            {"id": LEGACY_RUN_ID},
        )
    engine.dispose()
