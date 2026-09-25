"""Initial schema: organizations, api_keys, runs, datasets, records, reports, features, enrichment.

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_type() -> Any:
    """Return the UUID column type for the active dialect."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def upgrade() -> None:
    uuid_t = _uuid_type()

    op.create_table(
        "organizations",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column(
            "org_id", uuid_t, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("prefix", sa.String(32), nullable=False, unique=True),
        sa.Column("hashed_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])

    op.create_table(
        "pipeline_runs",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column(
            "org_id", uuid_t, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("dataset_id", uuid_t, nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pipeline_runs_org_id", "pipeline_runs", ["org_id"])
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])

    op.create_table(
        "datasets",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column(
            "org_id", uuid_t, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "run_id",
            uuid_t,
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_datasets_org_id", "datasets", ["org_id"])

    op.create_table(
        "normalized_records",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column("org_id", uuid_t, nullable=False),
        sa.Column(
            "dataset_id", uuid_t, sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("record_key", sa.String(27), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("canonical_smiles", sa.Text(), nullable=True),
        sa.Column("inchi", sa.Text(), nullable=True),
        sa.Column("inchikey", sa.String(27), nullable=True),
        sa.Column("molecular_formula", sa.String(255), nullable=True),
        sa.Column("molecular_weight", sa.Float(), nullable=True),
        sa.Column("target", sa.String(255), nullable=True),
        sa.Column("assay_type", sa.String(64), nullable=True),
        sa.Column("activity_value_nm", sa.Float(), nullable=True),
        sa.Column("activity_relation", sa.String(4), nullable=True),
        sa.UniqueConstraint("dataset_id", "record_key", name="uq_dataset_record_key"),
    )
    op.create_index("ix_normalized_records_org_id", "normalized_records", ["org_id"])
    op.create_index("ix_normalized_records_dataset_id", "normalized_records", ["dataset_id"])
    op.create_index("ix_normalized_records_record_key", "normalized_records", ["record_key"])

    op.create_table(
        "validation_issues",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", uuid_t, nullable=False),
        sa.Column(
            "dataset_id", uuid_t, sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("rule", sa.String(64), nullable=False),
        sa.Column("field", sa.String(64), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_validation_issues_org_id", "validation_issues", ["org_id"])
    op.create_index("ix_validation_issues_dataset_id", "validation_issues", ["dataset_id"])
    op.create_index("ix_validation_issues_severity", "validation_issues", ["severity"])

    op.create_table(
        "quality_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", uuid_t, nullable=False),
        sa.Column(
            "run_id",
            uuid_t,
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "dataset_id",
            uuid_t,
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
    op.create_index("ix_quality_reports_org_id", "quality_reports", ["org_id"])

    op.create_table(
        "feature_vectors",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column("org_id", uuid_t, nullable=False),
        sa.Column(
            "record_id",
            uuid_t,
            sa.ForeignKey("normalized_records.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("descriptors", sa.JSON(), nullable=False),
        sa.Column("fingerprint_bits", sa.JSON(), nullable=False),
        sa.Column("fingerprint_radius", sa.Integer(), nullable=False),
        sa.Column("fingerprint_n_bits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feature_vectors_org_id", "feature_vectors", ["org_id"])

    op.create_table(
        "enrichment_results",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column("org_id", uuid_t, nullable=False),
        sa.Column(
            "record_id",
            uuid_t,
            sa.ForeignKey("normalized_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_enrichment_results_org_id", "enrichment_results", ["org_id"])
    op.create_index("ix_enrichment_results_record_id", "enrichment_results", ["record_id"])
    op.create_index("ix_enrichment_results_status", "enrichment_results", ["status"])


def downgrade() -> None:
    op.drop_table("enrichment_results")
    op.drop_table("feature_vectors")
    op.drop_table("quality_reports")
    op.drop_table("validation_issues")
    op.drop_table("normalized_records")
    op.drop_table("datasets")
    op.drop_table("pipeline_runs")
    op.drop_table("api_keys")
    op.drop_table("organizations")
