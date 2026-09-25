"""SQLAlchemy ORM models. Internal to the storage package."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class RunRow(Base):
    """A pipeline run."""

    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RawRecordRow(Base):
    """A raw record kept for lineage."""

    __tablename__ = "raw_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    source_record_id: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class DatasetRow(Base):
    """A normalized dataset produced by one run."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16))
    record_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NormalizedRecordRow(Base):
    """A normalized, model-ready record."""

    __tablename__ = "normalized_records"
    __table_args__ = (UniqueConstraint("dataset_id", "record_key", name="uq_dataset_record_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    record_key: Mapped[str] = mapped_column(String(27), index=True)
    source: Mapped[str] = mapped_column(String(16))
    source_record_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchi: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchikey: Mapped[str | None] = mapped_column(String(27), nullable=True)
    molecular_formula: Mapped[str | None] = mapped_column(String(255), nullable=True)
    molecular_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activity_value_nm: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)


class QualityReportRow(Base):
    """A per-run data-quality report."""

    __tablename__ = "quality_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="CASCADE"), unique=True
    )
    total_records: Mapped[int] = mapped_column(Integer)
    accepted_records: Mapped[int] = mapped_column(Integer)
    rejected_records: Mapped[int] = mapped_column(Integer)
    duplicate_records: Mapped[int] = mapped_column(Integer)
    pass_rate: Mapped[float] = mapped_column(Float)
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
