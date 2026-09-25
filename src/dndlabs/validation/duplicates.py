"""Duplicate detection across a dataset by canonical identifier."""

from collections.abc import Sequence

from dndlabs.core.schemas import DatasetRuleOutcome, NormalizedRecord, ValidationIssue
from dndlabs.validation.issues import warning


class DuplicateRule:
    """Drops records whose ``record_key`` (InChIKey) was already seen.

    Attributes:
        name: Rule name used in reports.
    """

    name = "duplicates"

    def apply(self, records: Sequence[NormalizedRecord]) -> DatasetRuleOutcome:
        """Deduplicate records.

        Args:
            records: Records that passed all record-level rules.

        Returns:
            Kept and dropped records with one warning per duplicate.
        """
        first_seen: dict[str, NormalizedRecord] = {}
        kept: list[NormalizedRecord] = []
        dropped: list[NormalizedRecord] = []
        issues: list[ValidationIssue] = []
        for record in records:
            key = record.record_key
            original = first_seen.get(key) if key else None
            if original is None:
                if key:
                    first_seen[key] = record
                kept.append(record)
                continue
            dropped.append(record)
            issues.append(
                warning(
                    self.name,
                    record,
                    f"duplicate of {original.source_record_id} (InChIKey {key})",
                    "record_key",
                )
            )
        return DatasetRuleOutcome(kept=kept, dropped=dropped, issues=issues)
