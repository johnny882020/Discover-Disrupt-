"""Password-reset tokens and revocable invitations.

Adds ``user_invitations.purpose`` (``join`` or ``password_reset``; existing
rows are invitations to join) and ``user_invitations.revoked_at``. Columns
are only added if absent, so a schema built with ``create_all`` and then
stamped (see ``storage.database.run_migrations``) upgrades cleanly.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_invitations")}
    with op.batch_alter_table("user_invitations") as batch:
        if "purpose" not in columns:
            batch.add_column(
                sa.Column("purpose", sa.String(16), nullable=False, server_default="join")
            )
        if "revoked_at" not in columns:
            batch.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_invitations") as batch:
        batch.drop_column("revoked_at")
        batch.drop_column("purpose")
