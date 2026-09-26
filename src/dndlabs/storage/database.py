"""Engine/session creation and schema management."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from dndlabs.core.exceptions import StorageError
from dndlabs.core.logging import get_logger
from dndlabs.storage.models import Base

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Conservative for Render's free Postgres plan, which caps total connections
# in the low double digits; a single worker should never need more than
# this even under load, and pool_recycle avoids relying solely on
# pool_pre_ping to detect connections the server has idle-closed.
_POSTGRES_POOL_SIZE = 3
_POSTGRES_MAX_OVERFLOW = 2
_POSTGRES_POOL_RECYCLE_SECONDS = 300


def create_db_engine(url: str) -> Engine:
    """Create a SQLAlchemy engine for ``url``.

    Args:
        url: SQLAlchemy database URL.

    Returns:
        A configured engine.
    """
    if url.startswith("sqlite"):
        kwargs: dict[str, object] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in {"sqlite://", "sqlite+pysqlite://"}:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)
        event.listen(engine, "connect", _enable_sqlite_fks)
        return engine
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=_POSTGRES_POOL_SIZE,
        max_overflow=_POSTGRES_MAX_OVERFLOW,
        pool_recycle=_POSTGRES_POOL_RECYCLE_SECONDS,
    )


def _enable_sqlite_fks(dbapi_connection: object, _record: object) -> None:
    """Turn on SQLite foreign-key enforcement for a new connection."""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_schema(engine: Engine) -> None:
    """Create all tables that do not exist yet (dev/test convenience).

    Args:
        engine: Target engine.
    """
    Base.metadata.create_all(engine)


def run_migrations(url: str) -> None:
    """Upgrade the database at ``url`` to the latest Alembic revision.

    Args:
        url: SQLAlchemy database URL.

    Raises:
        StorageError: If the migration fails.
    """
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    try:
        if _created_without_alembic(url):
            logger.warning(
                "migration_stamp_shortcut",
                extra={
                    "detail": (
                        "schema exists without alembic_version; stamping 0001 "
                        "and skipping migrations 0001 would otherwise apply — "
                        "verify the schema actually matches revision 0001"
                    )
                },
            )
            command.stamp(config, "0001")
        command.upgrade(config, "head")
    except SQLAlchemyError as exc:
        raise StorageError(f"migration failed: {exc}") from exc


def _created_without_alembic(url: str) -> bool:
    """Return True if the schema exists but Alembic has never been run on it."""
    engine = create_db_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    return "organizations" in tables and "alembic_version" not in tables


class SessionFactory:
    """Produces transactional sessions; the only way repositories reach the DB."""

    def __init__(self, engine: Engine) -> None:
        """Bind the factory to an engine.

        Args:
            engine: Engine to open sessions on.
        """
        self._maker = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Open a session, commit on success and roll back on error.

        Yields:
            An open session.

        Raises:
            StorageError: If the database raises an error.
        """
        session = self._maker()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(str(exc)) from exc
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
