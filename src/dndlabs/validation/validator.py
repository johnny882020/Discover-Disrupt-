"""Runs validation rules over raw records and builds the quality report."""

import uuid
from collections import Counter
from collections.abc import Callable, Sequence

from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import ValidationRule
from dndlabs.core.schemas import (
    DatasetRuleOutcome,
    NormalizedRecord,
    QualityReport,
    RawRecord,
    Severity,
    ValidationIssue,
    ValidationOutcome,
)
from dndlabs.validation.assay_context import AssayContextRule
from dndlabs.validation.duplicates import DuplicateRule
from dndlabs.validation.identity import CompoundIdentityRule
from dndlabs.validation.schema import SchemaRule
from dndlabs.validation.standardization import StandardizationRule
from dndlabs.validation.structure_source import StructureSourceRule
from dndlabs.validation.units import UnitNormalizationRule

logger = get_logger(__name__)


def default_record_rules() -> list[ValidationRule]:
    """Return the record rules in their contractual order.

    Compound identity must precede standardization, which works on the
    canonical SMILES identity derives. Structure source runs first so a
    failed lookup's reason heads the record's issues; schema skips that
    case rather than reporting a missing structure twice.

    Returns:
        Structure source, schema, compound identity, standardization, unit
        normalization, then assay context.
    """
    return [
        StructureSourceRule(),
        SchemaRule(),
        CompoundIdentityRule(),
        StandardizationRule(),
        UnitNormalizationRule(),
        AssayContextRule(),
    ]


def seed_record(raw: RawRecord, dataset_id: uuid.UUID) -> NormalizedRecord:
    """Create the initial normalized record that rules refine.

    Args:
        raw: The raw record.
        dataset_id: Dataset the record will belong to (generated ahead of
            storage, since validation runs before a Dataset row exists).

    Returns:
        A normalized record carrying the pass-through fields.
    """
    return NormalizedRecord(
        dataset_id=dataset_id,
        source=raw.source,
        source_record_id=raw.source_record_id,
        name=raw.name,
        molecular_formula=raw.molecular_formula,
        assay_type=raw.assay_type,
        target=raw.target,
    )


class Validator:
    """Applies record rules, then dataset rules, and reports on the result."""

    def __init__(
        self,
        record_rules: Sequence[ValidationRule] | None = None,
        dataset_rules: Sequence[object] | None = None,
        # Matches the orchestrator's _CHUNK: progress writes stay negligible
        # while a stop request is honoured within seconds.
        checkpoint_every: int = 500,
    ) -> None:
        """Configure the validator.

        Args:
            record_rules: Record rules; defaults to :func:`default_record_rules`.
            dataset_rules: Dataset rules; defaults to ``[DuplicateRule()]``.
                An explicit empty sequence disables them (unlike
                ``record_rules``, where an empty sequence means the defaults).
            checkpoint_every: Records between calls to a run's ``checkpoint``.
        """
        self._checkpoint_every = checkpoint_every
        self._record_rules = list(record_rules or default_record_rules())
        self._dataset_rules = list(
            dataset_rules if dataset_rules is not None else [DuplicateRule()]
        )

    def run(
        self,
        run_id: uuid.UUID,
        dataset_id: uuid.UUID,
        raws: Sequence[RawRecord],
        checkpoint: Callable[[int], None] | None = None,
    ) -> ValidationOutcome:
        """Validate and normalize a batch of raw records.

        Args:
            run_id: Run the records belong to (copied into the report).
            dataset_id: Dataset the accepted records will belong to.
            raws: Raw records from a connector.
            checkpoint: Called after every ``checkpoint_every`` records with
                the number validated so far; whatever it raises stops
                validation (a cancelled or interrupted run).

        Returns:
            Accepted records and the quality report.
        """
        issues: list[ValidationIssue] = []
        candidates: list[NormalizedRecord] = []
        rejected = 0
        for done, raw in enumerate(raws, start=1):
            record, record_issues = self._apply_record_rules(raw, dataset_id)
            issues.extend(record_issues)
            # Every rule ran regardless, so a rejected record's report lists
            # all of its problems, not just the first.
            if any(i.severity is Severity.ERROR for i in record_issues):
                rejected += 1
            else:
                candidates.append(record)
            if checkpoint is not None and done % self._checkpoint_every == 0:
                checkpoint(done)

        # Dataset rules see only records that passed every record rule, so a
        # rejected record never counts as the "original" of a duplicate.
        duplicates = 0
        for rule in self._dataset_rules:
            # core.protocols defines no dataset-rule protocol, hence the ignore.
            outcome: DatasetRuleOutcome = rule.apply(candidates)  # type: ignore[attr-defined]
            candidates = outcome.kept
            duplicates += len(outcome.dropped)
            issues.extend(outcome.issues)

        report = build_report(
            run_id, dataset_id, len(raws), len(candidates), rejected, duplicates, issues
        )
        logger.info(
            "validation complete",
            extra={
                "run_id": str(run_id),
                "total": report.total_records,
                "accepted": report.accepted_records,
                "rejected": report.rejected_records,
                "duplicates": report.duplicate_records,
            },
        )
        return ValidationOutcome(accepted=candidates, report=report)

    def _apply_record_rules(
        self, raw: RawRecord, dataset_id: uuid.UUID
    ) -> tuple[NormalizedRecord, list[ValidationIssue]]:
        """Run every record rule, threading the record through."""
        record = seed_record(raw, dataset_id)
        issues: list[ValidationIssue] = []
        for rule in self._record_rules:
            outcome = rule.apply(raw, record)
            record = outcome.record
            issues.extend(outcome.issues)
        return record, issues


def build_report(
    run_id: uuid.UUID,
    dataset_id: uuid.UUID,
    total: int,
    accepted: int,
    rejected: int,
    duplicates: int,
    issues: Sequence[ValidationIssue],
) -> QualityReport:
    """Assemble a :class:`QualityReport` from counts and issues.

    Args:
        run_id: Run identifier.
        dataset_id: Dataset identifier.
        total: Records received.
        accepted: Records in the final dataset.
        rejected: Records with at least one error.
        duplicates: Records dropped as duplicates.
        issues: All issues found.

    Returns:
        The quality report (``pass_rate`` = accepted / total, 0 when empty).
    """
    severities = Counter(i.severity for i in issues)
    return QualityReport(
        run_id=run_id,
        dataset_id=dataset_id,
        total_records=total,
        accepted_records=accepted,
        rejected_records=rejected,
        duplicate_records=duplicates,
        warning_count=severities[Severity.WARNING],
        error_count=severities[Severity.ERROR],
        issues_by_rule=dict(sorted(Counter(i.rule for i in issues).items())),
        issues=list(issues),
        pass_rate=round(accepted / total, 4) if total else 0.0,
    )
