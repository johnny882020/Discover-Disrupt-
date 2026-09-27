"""Structural alerts on feature vectors.

Adds ``feature_vectors.alerts`` (JSON, nullable). Existing rows keep NULL,
meaning "not computed"; the assessment computes their alerts when read.
Added only if absent, so a schema built with ``create_all`` and then
stamped upgrades cleanly.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("feature_vectors")}
    if "alerts" not in columns:
        with op.batch_alter_table("feature_vectors") as batch:
            batch.add_column(sa.Column("alerts", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("feature_vectors") as batch:
        batch.drop_column("alerts")
