from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from dndlabs.core.exceptions import StorageError
from dndlabs.storage.database import SessionFactory, create_db_engine, run_migrations
from dndlabs.storage.models import Base


def test_migration_matches_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    engine = create_db_engine(url)
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        migrated = {c["name"] for c in inspector.get_columns(table.name)}
        assert migrated == {c.name for c in table.columns}, table.name
    run_migrations(url)  # idempotent


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
