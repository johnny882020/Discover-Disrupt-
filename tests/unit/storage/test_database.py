from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from tests.conftest import HEAD_REVISION
from tests.legacy_mvp import LEGACY_RUN_ID, apply_legacy_mvp_schema

from dndlabs.core.exceptions import StorageError
from dndlabs.storage.database import SessionFactory, create_db_engine, create_schema, run_migrations
from dndlabs.storage.models import Base
from dndlabs.storage.repositories import SqlOrganizationRepository


def test_migration_matches_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    engine = create_db_engine(url)
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        migrated = {c["name"] for c in inspector.get_columns(table.name)}
        assert migrated == {c.name for c in table.columns}, table.name
    run_migrations(url)  # idempotent


def test_migrations_adopt_schema_created_without_alembic(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'adopt.db'}"
    engine = create_db_engine(url)
    create_schema(engine)
    engine.dispose()
    run_migrations(url)
    engine = create_db_engine(url)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == HEAD_REVISION
        )


def test_migrations_retire_legacy_mvp_schema_without_losing_its_data(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    apply_legacy_mvp_schema(url)

    run_migrations(url)

    engine = create_db_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {t.name for t in Base.metadata.sorted_tables} <= tables
    assert "legacy_mvp_raw_records" in tables
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == HEAD_REVISION
        )
        legacy_ids = conn.execute(text("SELECT id FROM legacy_mvp_pipeline_runs")).scalars()
        assert list(legacy_ids) == [LEGACY_RUN_ID]
    SqlOrganizationRepository(SessionFactory(engine)).ping()
    run_migrations(url)  # idempotent


def test_migrations_recover_stale_version_with_no_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'stale.db'}"
    engine = create_db_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0001')"))
    engine.dispose()

    run_migrations(url)

    SqlOrganizationRepository(SessionFactory(create_db_engine(url))).ping()


def test_session_rolls_back_on_error() -> None:
    engine = create_db_engine("sqlite:///:memory:")
    sessions = SessionFactory(engine)
    with sessions.transaction() as session:
        session.execute(text("CREATE TABLE t (x INTEGER)"))
    with pytest.raises(RuntimeError), sessions.transaction() as session:
        session.execute(text("INSERT INTO t VALUES (1)"))
        raise RuntimeError("boom")
    with pytest.raises(StorageError), sessions.transaction() as session:
        session.execute(text("SELECT * FROM missing"))
    with sessions.transaction() as session:
        assert session.execute(text("SELECT count(*) FROM t")).scalar_one() == 0


def test_non_sqlite_engine_is_lazy() -> None:
    engine = create_db_engine("postgresql+psycopg://u:p@localhost:1/db")
    assert engine.dialect.name == "postgresql"
