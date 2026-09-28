"""Shared Pydantic contracts. Frozen by docs/architecture.md.

Every value crossing a module, API, or database boundary is one of these
models. Changing a field here is a contract change: update
docs/architecture.md and flag it explicitly.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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
    """Base for all contracts: reject unknown fields.

    Forbidding extras makes a misspelt or unexpected field (in a request
    body, or a stored JSON column read back) an error instead of silently
    dropped data; a request body carrying a field its contract does not
    declare, such as an ``org_id`` the server derives itself, is rejected.
    """

    model_config = ConfigDict(extra="forbid")


class SourceType(StrEnum):
    """Supported ingestion sources."""

    PUBCHEM = "pubchem"
    CHEMBL = "chembl"
    CSV = "csv"
    JSON = "json"
    UPLOAD = "upload"


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


class Role(StrEnum):
    """What an authenticated principal may do within its organization."""

    ADMIN = "admin"
    MEMBER = "member"


class PrincipalType(StrEnum):
    """Which kind of credential authenticated a request."""

    API_KEY = "api_key"
    USER = "user"


class OrgContext(_Contract):
    """Result of authenticating a request. Injected by the auth dependency.

    Exactly one of ``api_key_id`` (``principal="api_key"``) or ``user_id`` +
    ``session_id`` (``principal="user"``) is set. API keys act with the
    ``admin`` role.
    """

    org_id: uuid.UUID
    org_name: str
    principal: PrincipalType
    role: Role
    api_key_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    email: str | None = None


def normalize_email(email: str) -> str:
    """Canonicalize an email address for storage and lookup.

    Args:
        email: A syntactically valid address.

    Returns:
        The address, stripped and lowercased, so sign-in is case-insensitive.
    """
    return email.strip().lower()


class _EmailContract(_Contract):
    """Base for contracts carrying an ``email``, normalized on input."""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalize(cls, email: str) -> str:
        """Store and compare addresses case-insensitively."""
        return normalize_email(email)


class User(_EmailContract):
    """A person who signs in to an organization with an email and password."""

    id: uuid.UUID = Field(default_factory=new_id)
    org_id: uuid.UUID
    role: Role = Role.MEMBER
    created_at: datetime = Field(default_factory=utcnow)


class UserCredentials(_Contract):
    """A user plus the secret state sign-in needs. Internal to auth; never returned by the API."""

    user: User
    password_hash: str


class UserSession(_Contract):
    """Persisted view of a sign-in session (the token's hash only, never the token)."""

    id: uuid.UUID = Field(default_factory=new_id)
    user_id: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    revoked_at: datetime | None = None


class InvitationPurpose(StrEnum):
    """What redeeming a single-use account token does."""

    JOIN = "join"
    PASSWORD_RESET = "password_reset"


class Invitation(_EmailContract):
    """Persisted view of a single-use account token (token hash only).

    ``purpose="join"`` creates an account; ``purpose="password_reset"`` sets
    a new password on the existing account with this email in ``org_id``.
    """

    id: uuid.UUID = Field(default_factory=new_id)
    org_id: uuid.UUID
    role: Role
    purpose: InvitationPurpose = InvitationPurpose.JOIN
    created_by: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None


class LoginRequest(_EmailContract):
    """Sign-in with an email and password."""

    password: str = Field(min_length=1, max_length=1024)


class SessionCreated(_Contract):
    """One-time reveal of a new session token, returned on sign-in or invitation acceptance."""

    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: User
    org_name: str


class InvitationCreate(_EmailContract):
    """Invite someone to the caller's organization."""

    role: Role = Role.MEMBER


class InvitationCreated(_Contract):
    """One-time reveal of an invitation token and the link that redeems it."""

    id: uuid.UUID
    email: str
    role: Role
    expires_at: datetime
    token: str
    accept_url: str


class AdminInvitationCreate(_EmailContract):
    """Operator bootstrap: invite an organization's first admin."""


class InvitationToken(_Contract):
    """An invitation token, sent in a request body (never in a URL)."""

    token: str = Field(min_length=1, max_length=256)


class InvitationPreview(_Contract):
    """What an invitation grants, shown before the invitee chooses a password."""

    email: str
    role: Role
    org_name: str
    expires_at: datetime


class MemberUpdate(_Contract):
    """Change a member's role."""

    role: Role


class PasswordResetRequest(_EmailContract):
    """Operator bootstrap: issue a password-reset link for an organization's user."""


class PasswordResetCreated(_Contract):
    """One-time reveal of a password-reset token and the link that redeems it."""

    email: str
    expires_at: datetime
    token: str
    reset_url: str


class PasswordResetPreview(_Contract):
    """Whose password a reset link sets, shown before the new password is chosen."""

    email: str
    org_name: str
    expires_at: datetime


class InvitationAccept(_Contract):
    """Redeem an invitation by choosing a password."""

    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(_Contract):
    """Change the signed-in user's password."""

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


# --------------------------------------------------------------------------
# Ingestion / validation
# --------------------------------------------------------------------------


class ColumnRole(StrEnum):
    """What a column of an uploaded table holds (a ``RawRecord`` field, or ``ignore``).

    Columns without a role are kept on each record as ``extra`` data.
    """

    SOURCE_RECORD_ID = "source_record_id"
    NAME = "name"
    SMILES = "smiles"
    INCHI = "inchi"
    MOL_BLOCK = "mol_block"
    INCHIKEY = "inchikey"
    PUBCHEM_CID = "pubchem_cid"
    CHEMBL_ID = "chembl_id"
    LOOKUP_NAME = "lookup_name"
    MOLECULAR_FORMULA = "molecular_formula"
    MOLECULAR_WEIGHT = "molecular_weight"
    TARGET = "target"
    ASSAY_TYPE = "assay_type"
    ASSAY_FORMAT = "assay_format"
    CONTROL = "control"
    ACTIVITY_VALUE = "activity_value"
    ACTIVITY_UNIT = "activity_unit"
    ACTIVITY_RELATION = "activity_relation"
    IGNORE = "ignore"


#: Roles that identify a structure; an upload's mapping needs at least one.
#: SMILES, InChI and MOL blocks are read directly; the others are looked up
#: in PubChem or ChEMBL (see :data:`LOOKUP_ROLES`).
STRUCTURE_ROLES = frozenset(
    {
        ColumnRole.SMILES,
        ColumnRole.INCHI,
        ColumnRole.MOL_BLOCK,
        ColumnRole.INCHIKEY,
        ColumnRole.PUBCHEM_CID,
        ColumnRole.CHEMBL_ID,
        ColumnRole.LOOKUP_NAME,
    }
)

#: Structure roles whose values are sent to PubChem or ChEMBL to find the
#: structure, so only when the user maps a column to one of them.
LOOKUP_ROLES = frozenset(
    {ColumnRole.INCHIKEY, ColumnRole.PUBCHEM_CID, ColumnRole.CHEMBL_ID, ColumnRole.LOOKUP_NAME}
)


class SourceSpec(_Contract):
    """What a pipeline run should ingest."""

    source: SourceType
    identifiers: list[str] = Field(default_factory=list)
    csv_path: str | None = None
    json_path: str | None = None
    chembl_target: str | None = None
    upload_id: uuid.UUID | None = None
    column_mapping: dict[str, ColumnRole] | None = None
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
        elif self.source is SourceType.UPLOAD:
            if self.upload_id is None or not self.column_mapping:
                raise ValueError("upload source requires upload_id and column_mapping")
            _check_mapping(self.column_mapping)
        return self


def _check_mapping(mapping: dict[str, ColumnRole]) -> None:
    """Require a structure column and at most one column per role."""
    roles = [role for role in mapping.values() if role is not ColumnRole.IGNORE]
    if not STRUCTURE_ROLES.intersection(roles):
        raise ValueError(
            "column_mapping needs a column that identifies the structure: SMILES, InChI, "
            "MOL block, InChIKey, PubChem CID, ChEMBL ID or a name to look up"
        )
    repeated = sorted({role.value for role in roles if roles.count(role) > 1})
    if repeated:
        raise ValueError(f"each role can be assigned to one column only: {repeated}")


class UploadFormat(StrEnum):
    """File formats accepted for upload."""

    CSV = "csv"
    TSV = "tsv"
    XLSX = "xlsx"
    SDF = "sdf"
    SMI = "smi"
    MOL = "mol"


class Upload(_Contract):
    """Metadata of a file an organization uploaded (its bytes are stored separately)."""

    id: uuid.UUID = Field(default_factory=new_id)
    org_id: uuid.UUID
    filename: str
    format: UploadFormat
    size_bytes: int
    sha256: str
    created_at: datetime = Field(default_factory=utcnow)


class MappingTemplateCreate(_Contract):
    """Save a column mapping for reuse with files that share its headers."""

    name: str = Field(min_length=1, max_length=100)
    mapping: dict[str, ColumnRole] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "MappingTemplateCreate":
        """Apply the same rules as a run's column mapping."""
        _check_mapping(self.mapping)
        return self


class MappingTemplate(_Contract):
    """A saved, reusable column mapping, keyed by column header."""

    id: uuid.UUID = Field(default_factory=new_id)
    org_id: uuid.UUID
    name: str
    mapping: dict[str, ColumnRole]
    created_at: datetime = Field(default_factory=utcnow)


class UploadPreview(_Contract):
    """An uploaded table's columns, first rows and suggested column mapping."""

    upload: Upload
    columns: list[str]
    rows: list[dict[str, str]]
    row_count: int
    suggested_mapping: dict[str, ColumnRole]
    template: MappingTemplate | None = None


class RawRecord(_Contract):
    """Unvalidated connector output. Numeric fields may still be strings.

    A record identifies its structure by ``smiles``, ``inchi`` or
    ``mol_block``, or by an identifier (``inchikey``, ``pubchem_cid``,
    ``chembl_id``, ``lookup_name``) that structure resolution looks up before
    validation. Resolution records where the structure came from in
    ``structure_source``, or why none was found in ``structure_error``.
    """

    source: SourceType
    source_record_id: str
    name: str | None = None
    smiles: str | None = None
    inchi: str | None = None
    mol_block: str | None = None
    inchikey: str | None = None
    pubchem_cid: str | None = None
    chembl_id: str | None = None
    lookup_name: str | None = None
    structure_source: str | None = None
    structure_error: str | None = None
    molecular_formula: str | None = None
    molecular_weight: str | float | None = None
    target: str | None = None
    assay_type: str | None = None
    assay_format: str | None = None
    control: str | None = None
    activity_value: str | float | None = None
    activity_unit: str | None = None
    activity_relation: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AssayFormat(StrEnum):
    """Whether a measurement comes from an isolated-target or a cellular assay."""

    BIOCHEMICAL = "biochemical"
    CELL_BASED = "cell_based"


class ControlType(StrEnum):
    """A reference compound's role in its assay."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class NormalizedRecord(_Contract):
    """A validated, normalized, model-ready measurement of a compound.

    ``record_key`` identifies the compound (standardized InChIKey); a dataset
    can hold several records of one compound, one per measurement context
    (see :meth:`context_key`).
    """

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
    assay_format: AssayFormat | None = None
    control: ControlType | None = None
    activity_value_nm: float | None = None
    activity_relation: str | None = None

    def context_key(self) -> str:
        """Identify the measurement context: target, assay type, format and control.

        Two records of the same compound (``record_key``) are duplicates only
        when their contexts match, so a compound can hold, say, a biochemical
        and a cell-based result.

        Returns:
            ``""`` when the record has no context at all, else a stable
            SHA-256 hex digest of the context.
        """
        parts = (
            (self.target or "").strip().lower(),
            (self.assay_type or "").strip().lower(),
            self.assay_format.value if self.assay_format else "",
            self.control.value if self.control else "",
        )
        if not any(parts):
            return ""
        # Joined with the ASCII unit separator rather than a printable
        # character, so field boundaries stay unambiguous. The 64-char hex
        # digest fits ``normalized_records.context_key`` (String(64)).
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


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


class AlertFamily(StrEnum):
    """Source of a structural alert."""

    PAINS = "pains"
    BRENK = "brenk"
    REACTIVE_METABOLITE = "reactive_metabolite"


class StructuralAlert(_Contract):
    """A substructure flagged as a liability, with the atoms it matched.

    ``atoms`` index the atoms of the record's canonical SMILES as RDKit (and
    RDKit.js) parse it, so a depiction can highlight them.
    """

    family: AlertFamily
    name: str
    atoms: list[int] = Field(default_factory=list)


class FeatureVector(_Contract):
    """RDKit-derived descriptors, structural alerts and fingerprint for one record."""

    record_id: uuid.UUID
    descriptors: dict[str, float] = Field(default_factory=dict)
    alerts: list[StructuralAlert] = Field(default_factory=list)
    fingerprint_bits: list[int] = Field(default_factory=list)
    fingerprint_radius: int = 2
    fingerprint_n_bits: int = 2048


class StoredFeatures(_Contract):
    """A record's stored descriptors and alerts (``None``: not yet computed)."""

    record_id: uuid.UUID
    descriptors: dict[str, float] = Field(default_factory=dict)
    alerts: list[StructuralAlert] | None = None


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
    CANCELLED = "cancelled"


#: States a run never leaves.
FINISHED_STATUSES = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED})


class RunStage(StrEnum):
    """The pipeline stage a run is in, in execution order."""

    QUEUED = "queued"
    FETCHING = "fetching"
    RESOLVING = "resolving"
    VALIDATING = "validating"
    STORING = "storing"
    FEATURIZING = "featurizing"
    ENRICHING = "enriching"
    DONE = "done"


class RunProgress(_Contract):
    """Record counts a run has reached so far.

    Attributes:
        fetched: Records read from the source.
        resolved: Structures resolved from MOL blocks or looked-up identifiers.
        validated: Records validated so far (while validating).
        accepted: Records that passed validation.
        rejected: Records with at least one error.
        duplicates: Records dropped as duplicates.
        featurized: Records with stored features.
        enriched: Records with an enrichment result.
    """

    fetched: int = Field(default=0, ge=0)
    resolved: int = Field(default=0, ge=0)
    validated: int = Field(default=0, ge=0)
    accepted: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)
    duplicates: int = Field(default=0, ge=0)
    featurized: int = Field(default=0, ge=0)
    enriched: int = Field(default=0, ge=0)


class PipelineRun(_Contract):
    """Metadata of a pipeline run.

    Runs are queued when submitted and executed by a worker; ``attempts``
    counts executions started, since a run interrupted by a restart is
    resumed from the beginning.
    """

    id: uuid.UUID = Field(default_factory=new_id)
    org_id: uuid.UUID
    spec: SourceSpec
    status: RunStatus = RunStatus.PENDING
    stage: RunStage = RunStage.QUEUED
    progress: RunProgress = Field(default_factory=RunProgress)
    attempts: int = Field(default=0, ge=0)
    cancel_requested: bool = False
    dataset_id: uuid.UUID | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
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


# --------------------------------------------------------------------------
# Hit/lead assessment
# --------------------------------------------------------------------------


class PotencyClass(StrEnum):
    """Hit-to-lead potency class of a compound's activity value.

    ``optimized`` < 100 nM, ``lead`` < 1 µM, ``hit`` < 10 µM, ``inactive``
    ≥ 10 µM; ``unknown`` when the value is missing or its qualifier leaves the
    class open (e.g. "> 50 nM").
    """

    OPTIMIZED = "optimized"
    LEAD = "lead"
    HIT = "hit"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


#: Potency classes that make a compound "active" in the hit phase (< 10 µM).
ACTIVE_CLASSES = frozenset({PotencyClass.OPTIMIZED, PotencyClass.LEAD, PotencyClass.HIT})


class Criterion(StrEnum):
    """A computed hit-to-lead property criterion."""

    MW = "mw_under_500"
    CLOGP = "clogp_under_5"
    LIPINSKI = "lipinski"
    ROTATABLE_BONDS = "rotatable_bonds_under_10"
    TPSA = "tpsa_under_140"
    TPSA_CNS = "tpsa_under_90"
    NO_PAINS = "no_pains_alerts"
    NO_REACTIVE_METABOLITES = "no_reactive_metabolite_alerts"


class CompoundProfile(_Contract):
    """Computed properties of one compound and the criteria it meets.

    Properties are computed with RDKit from the standardized structure;
    ``hbd``/``hba`` use Lipinski's definitions (NH + OH count, N + O count).
    ``criteria`` is empty (no criterion is a key) when the compound lacks
    complete computed properties; otherwise it holds every criterion.
    """

    record_id: uuid.UUID
    molecular_weight: float | None = None
    clogp: float | None = None
    tpsa: float | None = None
    hbd: int | None = None
    hba: int | None = None
    rotatable_bonds: int | None = None
    rings: int | None = None
    qed: float | None = None
    lipinski_violations: int | None = None
    alerts: list[StructuralAlert] = Field(default_factory=list)
    potency_class: PotencyClass = PotencyClass.UNKNOWN
    criteria: dict[Criterion, bool] = Field(default_factory=dict)


class CriterionShare(_Contract):
    """How many compounds of a group meet a criterion."""

    passing: int
    evaluated: int


class CriterionSummary(_Contract):
    """A criterion evaluated over the groups the hit-to-lead guide uses."""

    criterion: Criterion
    label: str
    all_compounds: CriterionShare
    actives: CriterionShare
    most_potent: CriterionShare


class FormatPotency(_Contract):
    """Potency of the compounds measured in one assay format (``None``: not given)."""

    assay_format: AssayFormat | None
    compounds: int
    potency_classes: dict[PotencyClass, int]
    actives: int


class DatasetAssessment(_Contract):
    """Hit-to-lead view of a dataset: potency classes, criteria, per-record profiles.

    Counts are per compound (``record_key``), control records excluded; a
    compound's potency class is the one met by the majority of its
    measurements. ``profiles`` has one entry per record (measurement).
    """

    dataset_id: uuid.UUID
    compounds: int
    measurements: int
    controls: int
    potency_classes: dict[PotencyClass, int]
    actives: int
    by_format: list[FormatPotency]
    most_potent_ids: list[uuid.UUID]
    criteria: list[CriterionSummary]
    profiles: list[CompoundProfile]


class ExportFormat(StrEnum):
    """Supported model-ready export formats."""

    CSV = "csv"
    JSONL = "jsonl"


class RunResult(_Contract):
    """Everything produced by one successful pipeline run."""

    run: PipelineRun
    dataset: Dataset
    report: QualityReport
