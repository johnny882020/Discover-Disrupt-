"""Brute-force limits counted in the database; per-account lockout removed.

Adds ``rate_limits``: one fixed-window counter per bucket (``bucket``
primary key, ``window_start``, ``count``, ``expires_at`` indexed for the
expired-counter sweep). Buckets hold digests of client IPs and emails,
never the raw values.

Drops ``users.failed_login_count`` and ``users.locked_until``. The
per-account lock they implemented revealed which emails had accounts (only
real accounts could lock, and a locked sign-in skipped password hashing);
sign-in is now limited per email bucket, which unknown emails fill exactly
like known ones. Existing locks are discarded with the columns: at most one
lockout period of protection is lost, and the new limits apply at once.

API-key prefixes grow from 3 to 12 random characters; ``api_keys.prefix``
(``String(32)``) already fits them, so no column change is needed.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "rate_limits"
_INDEX = "ix_rate_limits_expires_at"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # Only if absent, like 0003 and 0005: a schema built by create_all and
    # stamped at 0001 already has the table.
    if _TABLE not in inspector.get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("bucket", sa.String(160), primary_key=True),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(_INDEX, _TABLE, ["expires_at"])
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "locked_until" in user_columns:
            batch.drop_column("locked_until")
        if "failed_login_count" in user_columns:
            batch.drop_column("failed_login_count")


def downgrade() -> None:
    # Every account comes back unlocked with no recorded failures.
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
