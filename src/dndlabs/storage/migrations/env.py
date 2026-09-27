"""Alembic environment for D&D Labs migrations.

Run by ``storage.database.run_migrations`` (which sets the database URL on
the config) or by the ``alembic`` command, which falls back to
``Settings.database_url``.
"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from dndlabs.core.config import get_settings
from dndlabs.storage.models import Base

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    """Return the URL set on the Alembic config, falling back to settings."""
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    """Emit migration SQL without a database connection."""
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    # NullPool: a migration is a one-off, so its connection is closed rather
    # than kept pooled.
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
