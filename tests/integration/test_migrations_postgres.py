"""Migration tests against a real PostgreSQL server — the production dialect.

Skipped unless ``DNDLABS_TEST_POSTGRES_URL`` points at a server the test may
create and drop databases on (CI provides one). SQLite-only migration tests
missed the legacy-schema bug that left production without platform tables.
"""

import os
import uuid
from collections.abc import Callable, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from dndlabs.core.exceptions import StorageError
from dndlabs.storage.database import (
    MIGRATIONS_DIR,
    SessionFactory,
    create_db_engine,
    run_migrations,
)
from dndlabs.storage.repositories import SqlOrganizationRepository, build_sql_repositories
from tests.account_repository_checks import ALL_CHECKS
from tests.conftest import HEAD_REVISION
from tests.legacy_mvp import LEGACY_RUN_ID, apply_legacy_mvp_schema
from tests.upload_repository_checks import UPLOAD_CHECKS

SERVER_URL = os.environ.get("DNDLABS_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(not SERVER_URL, reason="set DNDLABS_TEST_POSTGRES_URL")


def _with_database(url: str, name: str) -> str:
    base, _, query = url.partition("?")
    return f"{base.rsplit('/', 1)[0]}/{name}" + (f"?{query}" if query else "")


@pytest.fixture
def database_url() -> Iterator[str]:
    name = f"dndlabs_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(SERVER_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield _with_database(SERVER_URL, name)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _ping(url: str) -> None:
    engine = create_db_engine(url)
    try:
        SqlOrganizationRepository(SessionFactory(engine), HEAD_REVISION).ping()
    finally:
        engine.dispose()


def test_fresh_database_migrates_to_head(database_url: str) -> None:
    run_migrations(database_url)
    _ping(database_url)
    engine = create_engine(database_url)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == HEAD_REVISION
        )
        assert not conn.execute(
            text("SELECT 1 FROM pg_namespace WHERE nspname = 'legacy_mvp'")
        ).first()
    engine.dispose()


def test_legacy_mvp_database_is_upgraded_and_its_data_preserved(database_url: str) -> None:
    apply_legacy_mvp_schema(database_url)
    with pytest.raises(StorageError, match="organizations"):
        _ping(database_url)  # the production failure mode, reproduced

    run_migrations(database_url)

    _ping(database_url)
    engine = create_engine(database_url)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == HEAD_REVISION
        )
        legacy_ids = conn.execute(text("SELECT id FROM legacy_mvp.pipeline_runs")).scalars()
        assert list(legacy_ids) == [LEGACY_RUN_ID]
    engine.dispose()
    run_migrations(database_url)  # idempotent


FREE_TIER_ORG_ID = "00000000-0000-0000-0000-000000000001"


def test_upgrade_deletes_the_retired_free_tier_org(database_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0002")
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, created_at, is_active) "
                "VALUES (:id, 'Free Tier', now(), true)"
            ),
            {"id": FREE_TIER_ORG_ID},
        )
        conn.execute(
            text(
                "INSERT INTO pipeline_runs (id, org_id, source, status, request_payload, "
                "created_at) VALUES (:run, :org, 'csv', 'failed', '{}', now())"
            ),
            {"run": str(uuid.uuid4()), "org": FREE_TIER_ORG_ID},
        )

    command.upgrade(config, "head")

    with engine.connect() as conn:
        assert not conn.execute(text("SELECT 1 FROM organizations")).first()
        assert not conn.execute(text("SELECT 1 FROM pipeline_runs")).first()
    command.downgrade(config, "0002")
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables"))}
        assert "users" not in tables
    engine.dispose()


def test_readiness_fails_until_the_newest_migration_applies(database_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0004")
    with pytest.raises(StorageError, match=f"revision 0004, expected {HEAD_REVISION}"):
        _ping(database_url)
    run_migrations(database_url)
    _ping(database_url)


def test_vectors_stored_before_0006_read_back_without_alerts(database_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0005")
    org_id, run_id, dataset_id, record_id = (uuid.uuid4() for _ in range(4))
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, created_at, is_active) "
                "VALUES (:o, 'A', now(), true)"
            ),
            {"o": org_id},
        )
        conn.execute(
            text(
                "INSERT INTO pipeline_runs "
                "(id, org_id, source, status, request_payload, created_at) "
                "VALUES (:r, :o, 'csv', 'succeeded', '{}', now())"
            ),
            {"r": run_id, "o": org_id},
        )
        conn.execute(
            text(
                "INSERT INTO datasets (id, org_id, run_id, name, source, record_count, created_at) "
                "VALUES (:d, :o, :r, 'd', 'csv', 1, now())"
            ),
            {"d": dataset_id, "o": org_id, "r": run_id},
        )
        conn.execute(
            text(
                "INSERT INTO normalized_records (id, org_id, dataset_id, record_key, source, "
                "source_record_id, canonical_smiles) VALUES (:id, :o, :d, 'K', 'csv', '1', 'CCO')"
            ),
            {"id": record_id, "o": org_id, "d": dataset_id},
        )
        conn.execute(
            text(
                "INSERT INTO feature_vectors (id, org_id, record_id, descriptors, "
                "fingerprint_bits, fingerprint_radius, fingerprint_n_bits, created_at) "
                "VALUES (:id, :o, :rec, '{\"logp\": 1.0}', '[]', 2, 2048, now())"
            ),
            {"id": uuid.uuid4(), "o": org_id, "rec": record_id},
        )
    engine.dispose()

    run_migrations(database_url)

    engine = create_db_engine(database_url)
    try:
        [stored] = (
            build_sql_repositories(engine).features.features_for(org_id, [record_id]).values()
        )
    finally:
        engine.dispose()
    assert (stored.descriptors, stored.alerts) == ({"logp": 1.0}, None)
    command.downgrade(config, "0005")
    command.upgrade(config, "head")


@pytest.mark.parametrize("check", ALL_CHECKS + UPLOAD_CHECKS, ids=lambda c: c.__name__)
def test_account_repositories_on_postgres(database_url: str, check: Callable[..., None]) -> None:
    run_migrations(database_url)
    engine = create_db_engine(database_url)
    try:
        check(build_sql_repositories(engine))
    finally:
        engine.dispose()
