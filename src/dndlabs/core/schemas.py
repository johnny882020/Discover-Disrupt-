"""Shared Pydantic contracts. Frozen by docs/architecture.md.

Every value crossing a module, API, or database boundary is one of these
models. Changing a field here is a contract change: update
docs/architecture.md and flag it explicitly.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def new_id() -> uuid.UUID:
    """Generate a new entity identifier.

    Returns:
        A UUID4.
    """
    return uuid.uuid4()


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Returns:
        The current UTC time.
    """
    return datetime.now(tz=UTC)


class _Contract(BaseModel):
    """Base for all contracts: reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


class SourceType(StrEnum):
    """Supported ingestion sources."""

    PUBCHEM = "pubchem"
    CHEMBL = "chembl"
    CSV = "csv"
    JSON = "json"


# --------------------------------------------------------------------------
# Auth / multi-tenancy
# --------------------------------------------------------------------------


class Organization(_Contract):
    """A customer organization (tenant)."""

    id: uuid.UUID = Field(default_factory=new_id)
    name: str
    created_at: datetime = Field(default_factory=utcnow)
    is_active: bool = True


class ApiKeyCreated(_Contract):
    """One-time reveal of a newly issued API key. Never persisted or re-shown."""

    id: uuid.UUID = Field(default_factory=new_id)
    org_id: uuid.UUID
    raw_key: str
    prefix: str
    created_at: datetime = Field(default_factory=utcnow)


class ApiKeyRecord(_Contract):
    """Persisted view of an API key (hash only, never the raw secret)."""

    id: uuid.UUID
    org_id: uuid.UUID
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class OrgContext(_Contract):
    """Result of authenticating a request. Injected by the auth dependency."""

    org_id: uuid.UUID
    org_name: str
    api_key_id: uuid.UUID


# --------------------------------------------------------------------------
# Ingestion / validation
# --------------------------------------------------------------------------


class SourceSpec(_Contract):
    """What a pipeline run should ingest."""

    source: SourceType
    identifiers: list[str] = Field(default_factory=list)
    csv_path: str | None = None
    json_path: str | None = None
    chembl_target: str | None = None
    dataset_name: str | None = None

    @model_validator(mode="after")
    def _check_inputs(self) -> "SourceSpec":
        """Ensure the spec carries the input its source needs."""
        if self.source is SourceType.PUBCHEM:
            if not self.identifiers:
                raise ValueError("pubchem source requires at least one identifier (CID)")
            bad = [i for i in self.identifiers if not i.strip().isdigit()]
            if bad:
                raise ValueError(f"CIDs must be positive integers, got {bad}")
        elif self.source is SourceType.CHEMBL and not self.chembl_target:
            raise ValueError("chembl source requires chembl_target")
        elif self.source is SourceType.CSV and not self.csv_path:
            raise ValueError("csv source requires csv_path")
        elif self.source is SourceType.JSON and not self.json_path:
            raise ValueError("json source requires json_path")
        return self


class RawRecord(_Contract):
    """Unvalidated connector output. Numeric fields may still be strings."""

    source: SourceType
    source_record_id: str
    name: str | None = None
    smiles: str | None = None
    inchi: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    molecular_weight: str | float | None = None
    target: str | None = None
    assay_type: str | None = None
    activity_value: str | float | None = None
    activity_unit: str | None = None
    activity_relation: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedRecord(_Contract):
    """A validated, normalized, model-ready compound record."""

    id: uuid.UUID = Field(default_factory=new_id)
    dataset_id: uuid.UUID
    record_key: str | None = None
    source: SourceType
    source_record_id: str
    name: str | None = None
    canonical_smiles: str | None = None
    inchi: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    target: str | None = None
    assay_type: str | None = None
    activity_value_nm: float | None = None
    activity_relation: str | None = None


class Severity(StrEnum):
    """Severity of a validation issue."""

    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(_Contract):
    """One data-quality finding for a record."""

    rule: str
    severity: Severity
    source_record_id: str
    field: str | None = None
    message: str


class RuleOutcome(_Contract):
    """Result of applying a record-level validation rule."""

    record: NormalizedRecord
    issues: list[ValidationIssue] = Field(default_factory=list)


class QualityReport(_Contract):
    """Structured data-quality report for one pipeline run."""

    run_id: uuid.UUID
    dataset_id: uuid.UUID | None = None
    total_records: int = Field(ge=0)
    accepted_records: int = Field(ge=0)
    rejected_records: int = Field(ge=0)
    duplicate_records: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    issues_by_rule: dict[str, int] = Field(default_factory=dict)
    issues: list[ValidationIssue] = Field(default_factory=list)
    pass_rate: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utcnow)


class DatasetRuleOutcome(_Contract):
    """Result of applying a dataset-level validation rule."""

    kept: list[NormalizedRecord]
    dropped: list[NormalizedRecord] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)


class ValidationOutcome(_Contract):
    """Output of the validator: accepted records plus the quality report."""

    accepted: list[NormalizedRecord]
    report: QualityReport


# --------------------------------------------------------------------------
# Filtering / preprocessing
# --------------------------------------------------------------------------


class DatasetFilter(_Contract):
    """Query filters over a dataset's normalized records."""

    mw_min: float | None = None
    mw_max: float | None = None
    target: str | None = None
    source: SourceType | None = None
    activity_min_nm: float | None = None
    activity_max_nm: float | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class FeatureVector(_Contract):
    """RDKit-derived descriptors and fingerprint for one normalized record."""

    record_id: uuid.UUID
    descriptors: dict[str, float] = Field(default_factory=dict)
    fingerprint_bits: list[int] = Field(default_factory=list)
    fingerprint_radius: int = 2
    fingerprint_n_bits: int = 2048


# --------------------------------------------------------------------------
# NVIDIA BioNeMo (GenMol) enrichment
# --------------------------------------------------------------------------


class EnrichmentRequest(_Contract):
    """One record submitted for enrichment."""

    record_id: uuid.UUID
    smiles: str


class GeneratedCandidate(_Contract):
    """One GenMol-generated analog and its score."""

    smiles: str
    score: float
    scoring_method: str


EnrichmentStatus = Literal["enriched", "skipped_no_key", "failed"]


class EnrichmentResult(_Contract):
    """Enrichment outcome for one record."""

    record_id: uuid.UUID
    status: EnrichmentStatus
    model_id: str | None = None
    candidates: list[GeneratedCandidate] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Pipeline / datasets
# --------------------------------------------------------------------------


class RunStatus(StrEnum):
    """Lifecycle state of a pipeline run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineRun(_Contract):
    """Metadata of a pipeline run."""

    id: uuid.UUID = Field(default_factory=new_id)
    org_id: uuid.UUID
    spec: SourceSpec
    status: RunStatus = RunStatus.PENDING
    dataset_id: uuid.UUID | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class Dataset(_Contract):
    """Stored dataset metadata."""

    id: uuid.UUID = Field(default_factory=new_id)
    org_id: uuid.UUID
    run_id: uuid.UUID
    name: str
    source: SourceType
    record_count: int = Field(ge=0)
    created_at: datetime = Field(default_factory=utcnow)


class DatasetWithRecords(_Contract):
    """A dataset together with its normalized records."""

    dataset: Dataset
    records: list[NormalizedRecord]


class ExportFormat(StrEnum):
    """Supported model-ready export formats."""

    CSV = "csv"
    JSONL = "jsonl"


class RunResult(_Contract):
    """Everything produced by one successful pipeline run."""

    run: PipelineRun
    dataset: Dataset
    report: QualityReport
