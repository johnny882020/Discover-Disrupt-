"""Initial schema: runs, raw records, datasets, normalized records, quality reports.

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("dataset_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])

    op.create_table(
        "raw_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_raw_records_run_id", "raw_records", ["run_id"])

    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "normalized_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("record_key", sa.String(27), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("canonical_smiles", sa.Text(), nullable=True),
        sa.Column("inchi", sa.Text(), nullable=True),
        sa.Column("inchikey", sa.String(27), nullable=True),
        sa.Column("molecular_formula", sa.String(255), nullable=True),
        sa.Column("molecular_weight", sa.Float(), nullable=True),
        sa.Column("activity_type", sa.String(64), nullable=True),
        sa.Column("activity_value_nm", sa.Float(), nullable=True),
        sa.Column("target", sa.String(255), nullable=True),
        sa.UniqueConstraint("dataset_id", "record_key", name="uq_dataset_record_key"),
    )
    op.create_index("ix_normalized_records_dataset_id", "normalized_records", ["dataset_id"])
    op.create_index("ix_normalized_records_record_key", "normalized_records", ["record_key"])

    op.create_table(
        "quality_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("total_records", sa.Integer(), nullable=False),
        sa.Column("accepted_records", sa.Integer(), nullable=False),
        sa.Column("rejected_records", sa.Integer(), nullable=False),
        sa.Column("duplicate_records", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("quality_reports")
    op.drop_index("ix_normalized_records_record_key", table_name="normalized_records")
    op.drop_index("ix_normalized_records_dataset_id", table_name="normalized_records")
    op.drop_table("normalized_records")
    op.drop_table("datasets")
    op.drop_index("ix_raw_records_run_id", table_name="raw_records")
    op.drop_table("raw_records")
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
