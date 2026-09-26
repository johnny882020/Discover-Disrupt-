"""SQLAlchemy ORM models. Internal to the storage package."""

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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class GUID(TypeDecorator[uuid.UUID]):
    """UUID column that's native on Postgres and TEXT-backed on SQLite."""

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
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvitationRow(Base):
    """A single-use invitation, stored by the SHA-256 digest of its token."""

    __tablename__ = "user_invitations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunRow(Base):
    """A pipeline run."""

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatasetRow(Base):
    """A normalized dataset produced by one run."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
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
    __table_args__ = (UniqueConstraint("dataset_id", "record_key", name="uq_dataset_record_key"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
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
    descriptors: Mapped[dict[str, Any]] = mapped_column(JSON)
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
