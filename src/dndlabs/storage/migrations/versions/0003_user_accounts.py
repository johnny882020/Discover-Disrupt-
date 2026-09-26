"""User accounts: users, sign-in sessions and invitations; retire the shared free-tier org.

Adds the tables behind invitation-based user sign-in (docs/architecture.md#auth)
and deletes the fixed organization that the removed shared-password login
authenticated as, together with everything it owned. That tenant was reachable
by anyone who knew a published password, and nothing can authenticate as it
any more.

Tables are only created if absent: a database built with
``Base.metadata.create_all`` (``DNDLABS_AUTO_CREATE_SCHEMA``) and later put
under Alembic is stamped at ``0001`` by ``storage.database.run_migrations``
and then upgraded, so it may already have them.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The organization the removed shared-password login used.
FREE_TIER_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Children before parents, so the delete is FK-safe even where the database
# does not enforce ON DELETE CASCADE (SQLite without the foreign_keys pragma).
_ORG_SCOPED_TABLES = (
    "enrichment_results",
    "feature_vectors",
    "validation_issues",
    "quality_reports",
    "normalized_records",
    "datasets",
    "pipeline_runs",
    "api_keys",
)


def _uuid_type() -> Any:
    """Return the UUID column type for the active dialect."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    uuid_t = _uuid_type()

    if not inspector.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column(
                "org_id",
                uuid_t,
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("email", sa.String(320), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_users_org_id", "users", ["org_id"])

    if not inspector.has_table("user_sessions"):
        op.create_table(
            "user_sessions",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column(
                "user_id", uuid_t, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "org_id",
                uuid_t,
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
        op.create_index("ix_user_sessions_org_id", "user_sessions", ["org_id"])
        op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    if not inspector.has_table("user_invitations"):
        op.create_table(
            "user_invitations",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column(
                "org_id",
                uuid_t,
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column(
                "created_by", uuid_t, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_user_invitations_org_id", "user_invitations", ["org_id"])

    _delete_free_tier_org(bind)


def _delete_free_tier_org(bind: sa.engine.Connection) -> None:
    """Delete the shared free-tier organization and every row it owns."""
    org_id: Any = FREE_TIER_ORG_ID if bind.dialect.name == "postgresql" else str(FREE_TIER_ORG_ID)
    for table in _ORG_SCOPED_TABLES:
        bind.execute(sa.text(f"DELETE FROM {table} WHERE org_id = :org_id"), {"org_id": org_id})
    bind.execute(sa.text("DELETE FROM organizations WHERE id = :org_id"), {"org_id": org_id})


def downgrade() -> None:
    """Drop the account tables. The deleted free-tier organization is not restored."""
    op.drop_table("user_invitations")
    op.drop_table("user_sessions")
    op.drop_table("users")
