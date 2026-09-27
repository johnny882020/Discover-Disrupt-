from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from tests.conftest import HEAD_REVISION
from tests.legacy_mvp import LEGACY_RUN_ID, apply_legacy_mvp_schema

from dndlabs.core.exceptions import StorageError
from dndlabs.storage.database import (
    MIGRATIONS_DIR,
    SessionFactory,
    create_db_engine,
    create_schema,
    head_revision,
    run_migrations,
)
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
    SqlOrganizationRepository(SessionFactory(engine), HEAD_REVISION).ping()
    run_migrations(url)  # idempotent


def test_migrations_recover_stale_version_with_no_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'stale.db'}"
    engine = create_db_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0001')"))
    engine.dispose()

    run_migrations(url)

    SqlOrganizationRepository(SessionFactory(create_db_engine(url)), HEAD_REVISION).ping()


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


def test_head_revision_is_the_newest_migration() -> None:
    assert head_revision() == HEAD_REVISION


def test_ping_requires_the_schema_at_the_expected_revision(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'behind.db'}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0004")
    repo = SqlOrganizationRepository(SessionFactory(create_db_engine(url)), HEAD_REVISION)

    with pytest.raises(StorageError, match=f"revision 0004, expected {HEAD_REVISION}"):
        repo.ping()  # a deploy whose newest migration never applied

    run_migrations(url)
    repo.ping()


def test_ping_without_an_expected_revision_accepts_a_create_all_schema() -> None:
    engine = create_db_engine("sqlite://")
    create_schema(engine)
    SqlOrganizationRepository(SessionFactory(engine)).ping()
    with pytest.raises(StorageError, match="alembic_version"):
        SqlOrganizationRepository(SessionFactory(engine), HEAD_REVISION).ping()


def test_0009_adds_rate_limits_and_drops_the_account_lock_reversibly(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'r.db'}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0008")
    engine = create_db_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, created_at, is_active) "
                "VALUES ('00000000-0000-0000-0000-00000000000a', 'A', '2026-01-01', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, org_id, email, password_hash, role, created_at, "
                "password_changed_at, failed_login_count, locked_until) VALUES "
                "('00000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000a', "
                "'ada@acme.com', 'h', 'admin', '2026-01-01', '2026-01-01', 3, '2030-01-01')"
            )
        )

    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert "rate_limits" in inspector.get_table_names()
    assert {"failed_login_count", "locked_until"}.isdisjoint(
        c["name"] for c in inspector.get_columns("users")
    )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT email FROM users")).scalar_one() == "ada@acme.com"

    command.downgrade(config, "0008")
    inspector = inspect(engine)
    assert "rate_limits" not in inspector.get_table_names()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT failed_login_count, locked_until FROM users")).one() == (
            0,
            None,
        )
    command.upgrade(config, "head")
    engine.dispose()
