"""Uploaded files and saved column-mapping templates.

Adds ``uploads`` (file content stored in the database, since hosted disks
are ephemeral) and ``mapping_templates``. Tables are only created if absent,
so a schema built with ``create_all`` and then stamped (see
``storage.database.run_migrations``) upgrades cleanly.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_type() -> Any:
    """Return the UUID column type for the active dialect."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    uuid_t = _uuid_type()

    if not inspector.has_table("uploads"):
        op.create_table(
            "uploads",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column(
                "org_id",
                uuid_t,
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("format", sa.String(8), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("data", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_uploads_org_id", "uploads", ["org_id"])

    if not inspector.has_table("mapping_templates"):
        op.create_table(
            "mapping_templates",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column(
                "org_id",
                uuid_t,
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("mapping", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("org_id", "name", name="uq_mapping_templates_org_name"),
        )
        op.create_index("ix_mapping_templates_org_id", "mapping_templates", ["org_id"])


def downgrade() -> None:
    op.drop_table("mapping_templates")
    op.drop_table("uploads")
