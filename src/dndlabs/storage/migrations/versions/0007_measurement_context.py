"""Several measurements per compound: assay format, control and context key.

Adds ``normalized_records.assay_format``, ``control`` and ``context_key``
(``""`` for existing rows, which are already unique per compound), and
replaces the unique ``(dataset_id, record_key)`` constraint with
``(dataset_id, record_key, context_key)``: a dataset may hold one record per
compound and measurement context (target, assay type, format, control).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "normalized_records"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns(_TABLE)}
    uniques = {u["name"] for u in inspector.get_unique_constraints(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if "assay_format" not in columns:
            batch.add_column(sa.Column("assay_format", sa.String(16), nullable=True))
        if "control" not in columns:
            batch.add_column(sa.Column("control", sa.String(16), nullable=True))
        if "context_key" not in columns:
            batch.add_column(
                sa.Column("context_key", sa.String(64), nullable=False, server_default="")
            )
        if "uq_dataset_record_key" in uniques:
            batch.drop_constraint("uq_dataset_record_key", type_="unique")
        if "uq_dataset_record_context" not in uniques:
            batch.create_unique_constraint(
                "uq_dataset_record_context", ["dataset_id", "record_key", "context_key"]
            )


def downgrade() -> None:
    # Refuses (unique violation) if a dataset holds several records of one compound.
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint("uq_dataset_record_context", type_="unique")
        batch.create_unique_constraint("uq_dataset_record_key", ["dataset_id", "record_key"])
        batch.drop_column("context_key")
        batch.drop_column("control")
        batch.drop_column("assay_format")
