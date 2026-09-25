"""Runs validation rules over raw records and builds the quality report."""

import uuid
from collections import Counter
from collections.abc import Sequence

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
from dndlabs.validation.duplicates import DuplicateRule
from dndlabs.validation.identity import CompoundIdentityRule
from dndlabs.validation.schema import SchemaRule
from dndlabs.validation.units import UnitNormalizationRule

logger = get_logger(__name__)


def default_record_rules() -> list[ValidationRule]:
    """Return the record rules in their contractual order.

    Returns:
        Schema, compound identity, then unit normalization.
    """
    return [SchemaRule(), CompoundIdentityRule(), UnitNormalizationRule()]


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
    ) -> None:
        """Configure the validator.

        Args:
            record_rules: Record rules; defaults to :func:`default_record_rules`.
            dataset_rules: Dataset rules; defaults to ``[DuplicateRule()]``.
        """
        self._record_rules = list(record_rules or default_record_rules())
        self._dataset_rules = list(
            dataset_rules if dataset_rules is not None else [DuplicateRule()]
        )

    def run(
        self, run_id: uuid.UUID, dataset_id: uuid.UUID, raws: Sequence[RawRecord]
    ) -> ValidationOutcome:
        """Validate and normalize a batch of raw records.

        Args:
            run_id: Run the records belong to (copied into the report).
            dataset_id: Dataset the accepted records will belong to.
            raws: Raw records from a connector.

        Returns:
            Accepted records and the quality report.
        """
        issues: list[ValidationIssue] = []
        candidates: list[NormalizedRecord] = []
        rejected = 0
        for raw in raws:
            record, record_issues = self._apply_record_rules(raw, dataset_id)
            issues.extend(record_issues)
            if any(i.severity is Severity.ERROR for i in record_issues):
                rejected += 1
            else:
                candidates.append(record)

        duplicates = 0
        for rule in self._dataset_rules:
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
