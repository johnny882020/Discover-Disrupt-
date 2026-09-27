"""SQLAlchemy ORM models: the relational schema. Internal to the storage package.

Nothing outside ``storage/`` imports these; repositories convert rows to
``core.schemas`` contracts at the boundary. The schema must run on both
PostgreSQL (production) and SQLite (development, tests), hence the portable
column types below. Alembic migrations, not these classes, build the
deployed schema (``create_all`` is a development convenience), so a change
here needs a new revision too.

Every tenant-owned table carries its own indexed ``org_id``, even where it
is implied by a parent (records, issues, reports, features, enrichments), so
repositories can filter by org directly without joining upwards.
Child rows reference their parents with ``ON DELETE CASCADE``; repositories
still delete children first explicitly, which works whether or not cascade
is enforced.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.expression import false
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class GUID(TypeDecorator[uuid.UUID]):
    """UUID column that's native on Postgres and TEXT-backed on SQLite.

    SQLite has no UUID type; storing the 36-character canonical string keeps
    ids readable and comparable there.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        """Use the native UUID type on Postgres, TEXT elsewhere."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        """Coerce Python values to what the underlying column expects."""
        if value is None:
            return None
        value = uuid.UUID(value) if not isinstance(value, uuid.UUID) else value
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        """Coerce stored values back to ``uuid.UUID``."""
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


class StringArray(TypeDecorator[list[str]]):
    """String-array column that's native on Postgres and JSON-backed on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        """Use the native ARRAY type on Postgres, JSON elsewhere."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String()))
        return dialect.type_descriptor(JSON())


class OrganizationRow(Base):
    """A customer organization (tenant)."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True)


class ApiKeyRow(Base):
    """A hashed API key belonging to an organization."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # The non-secret prefix is the lookup key (unique); only the Argon2 hash
    # of the full key is stored.
    prefix: Mapped[str] = mapped_column(String(32), unique=True)
    hashed_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserRow(Base):
    """A person who signs in to an organization."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # 320 = RFC 5321's maximum address length. Unique across all orgs:
    # sign-in is by email alone.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSessionRow(Base):
    """A sign-in session, stored by the SHA-256 digest of its bearer token."""

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # SHA-256 hex digest (64 chars); the bearer token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Indexed for the expired-session sweep (delete_expired).
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvitationRow(Base):
    """A single-use account token (join or password reset), stored by the SHA-256 of its token."""

    __tablename__ = "user_invitations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(16), default="join")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # SET NULL: deleting the inviting user keeps the invitation's history.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UploadRow(Base):
    """An uploaded file, stored in the database (hosted disks are ephemeral)."""

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MappingTemplateRow(Base):
    """A saved column mapping for uploads, unique by name within an organization."""

    __tablename__ = "mapping_templates"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_mapping_templates_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    # JSON: a free-form header -> ColumnRole map, only ever read whole.
    mapping: Mapped[dict[str, str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunRow(Base):
    """A pipeline run, and its place in the run queue (status, lease, counters)."""

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    stage: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    # JSON: RunProgress counts, read and written whole, never queried.
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Queue-internal, not part of PipelineRun: how many times a worker lost the
    # run by stopping unexpectedly (lease expired). Clean shutdowns release the
    # run instead, so only real crashes count towards failing it.
    lost_leases: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cancel_requested: Mapped[bool] = mapped_column(default=False, server_default=false())
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # No foreign key: the enforced link is datasets.run_id; a second one in
    # this direction would make the two tables reference each other.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The run's SourceSpec as JSON, re-validated into the contract on read.
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatasetRow(Base):
    """A normalized dataset produced by one run."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # Unique: a run produces at most one dataset.
    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NormalizedRecordRow(Base):
    """A normalized, model-ready record."""

    __tablename__ = "normalized_records"
    # One record per compound and measurement context (NormalizedRecord.context_key).
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "record_key", "context_key", name="uq_dataset_record_context"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    # record_key and inchikey are InChIKeys: always exactly 27 characters.
    record_key: Mapped[str | None] = mapped_column(String(27), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16))
    source_record_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchi: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchikey: Mapped[str | None] = mapped_column(String(27), nullable=True)
    molecular_formula: Mapped[str | None] = mapped_column(String(255), nullable=True)
    molecular_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assay_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assay_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    control: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # "" (no context) or a SHA-256 hex digest; see NormalizedRecord.context_key.
    # Not NULL, so the unique constraint above also applies to context-free
    # records (NULLs never collide in a unique constraint).
    context_key: Mapped[str] = mapped_column(String(64), default="", server_default="")
    activity_value_nm: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_relation: Mapped[str | None] = mapped_column(String(4), nullable=True)


class ValidationIssueRow(Base):
    """A validation finding recorded against a dataset."""

    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    source_record_id: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    rule: Mapped[str] = mapped_column(String(64))
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text)


class QualityReportRow(Base):
    """A per-run data-quality report."""

    __tablename__ = "quality_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("datasets.id", ondelete="CASCADE"), unique=True
    )
    total_records: Mapped[int] = mapped_column(Integer)
    accepted_records: Mapped[int] = mapped_column(Integer)
    rejected_records: Mapped[int] = mapped_column(Integer)
    duplicate_records: Mapped[int] = mapped_column(Integer)
    pass_rate: Mapped[float] = mapped_column(Float)
    # The full QualityReport as JSON (the source of truth when reading it
    # back); the columns above duplicate its headline numbers.
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FeatureVectorRow(Base):
    """A computed feature vector for one normalized record."""

    __tablename__ = "feature_vectors"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), index=True)
    record_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("normalized_records.id", ondelete="CASCADE"), unique=True
    )
    # JSON (like the fingerprint bits): read whole per record, never
    # filtered on in SQL.
    descriptors: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Structural alerts; NULL for vectors stored before alerts were computed.
    alerts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    fingerprint_bits: Mapped[list[int]] = mapped_column(JSON)
    fingerprint_radius: Mapped[int] = mapped_column(Integer)
    fingerprint_n_bits: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnrichmentResultRow(Base):
    """An enrichment outcome for one normalized record."""

    __tablename__ = "enrichment_results"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), index=True)
    record_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("normalized_records.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
