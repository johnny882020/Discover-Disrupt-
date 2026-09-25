"""Shared Pydantic contracts that cross module boundaries.

These models are frozen by ``docs/architecture.md``; changing them is a
contract change that affects every layer.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonScalar = str | int | float | bool | None


def new_id() -> str:
    """Generate a new entity identifier.

    Returns:
        A UUID4 string.
    """
    return str(uuid.uuid4())


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
    CSV = "csv"
    JSON = "json"


class IdentifierType(StrEnum):
    """How PubChem identifiers in a :class:`SourceSpec` are interpreted."""

    CID = "cid"
    NAME = "name"


class SourceSpec(_Contract):
    """Describes what a pipeline run should ingest.

    Attributes:
        source: Connector to use.
        identifiers: PubChem CIDs or names (PubChem only).
        identifier_type: Whether ``identifiers`` are CIDs or names.
        path: Local file path (CSV/JSON only).
        dataset_name: Optional human-readable dataset name.
    """

    source: SourceType
    identifiers: list[str] = Field(default_factory=list)
    identifier_type: IdentifierType = IdentifierType.CID
    path: str | None = None
    dataset_name: str | None = None

    @model_validator(mode="after")
    def _check_inputs(self) -> "SourceSpec":
        """Ensure the spec carries the inputs its source needs."""
        if self.source is SourceType.PUBCHEM:
            if not self.identifiers:
                raise ValueError("pubchem source requires at least one identifier")
            if self.identifier_type is IdentifierType.CID:
                bad = [i for i in self.identifiers if not i.strip().isdigit()]
                if bad:
                    raise ValueError(f"CIDs must be positive integers, got {bad}")
        elif not self.path:
            raise ValueError(f"{self.source.value} source requires a path")
        return self


class RawRecord(_Contract):
    """A single unvalidated record as produced by a connector.

    Values are kept as close to the source as possible; numeric fields may
    still be strings because validation has not run yet.
    """

    source: SourceType
    source_record_id: str
    name: str | None = None
    smiles: str | None = None
    inchi: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    molecular_weight: str | float | None = None
    activity_type: str | None = None
    activity_value: str | float | None = None
    activity_unit: str | None = None
    target: str | None = None
    extra: dict[str, JsonScalar] = Field(default_factory=dict)


class NormalizedRecord(_Contract):
    """A validated, normalized, model-ready compound record."""

    record_key: str | None = None
    source: SourceType
    source_record_id: str
    name: str | None = None
    canonical_smiles: str | None = None
    inchi: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    activity_type: str | None = None
    activity_value_nm: float | None = None
    target: str | None = None


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


class DatasetRuleOutcome(_Contract):
    """Result of applying a dataset-level validation rule.

    Attributes:
        kept: Records that survive the rule, in input order.
        dropped: Records removed by the rule.
        issues: Findings raised by the rule.
    """

    kept: list[NormalizedRecord]
    dropped: list[NormalizedRecord] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)


class QualityReport(_Contract):
    """Structured data-quality report for one pipeline run."""

    run_id: str
    dataset_id: str | None = None
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


class ValidationOutcome(_Contract):
    """Output of the validator: accepted records plus the quality report."""

    accepted: list[NormalizedRecord]
    report: QualityReport


class RunStatus(StrEnum):
    """Lifecycle state of a pipeline run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineRun(_Contract):
    """Metadata of a pipeline run."""

    id: str = Field(default_factory=new_id)
    spec: SourceSpec
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    error: str | None = None
    dataset_id: str | None = None


class Dataset(_Contract):
    """Metadata of a stored, normalized dataset."""

    id: str = Field(default_factory=new_id)
    run_id: str
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
    export_path: Path | None = None
