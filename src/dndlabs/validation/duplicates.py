"""Duplicate detection across a dataset: the same compound in the same measurement context."""

from collections.abc import Sequence

from dndlabs.core.schemas import DatasetRuleOutcome, NormalizedRecord, ValidationIssue
from dndlabs.validation.issues import warning


class DuplicateRule:
    """Drops a record whose compound and measurement context were already seen.

    The compound is the ``record_key`` (standardized InChIKey); the context
    is the target, assay type, assay format and control role
    (:meth:`NormalizedRecord.context_key`). A compound measured in a
    biochemical and a cell-based assay therefore keeps both records.

    The first occurrence in input order is kept; a later duplicate is dropped
    without comparing or merging its activity value. Because the key is the
    standardized InChIKey, salt forms and isotopically labelled forms of one
    compound count as the same compound.

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
        first_seen: dict[tuple[str, str], NormalizedRecord] = {}
        kept: list[NormalizedRecord] = []
        dropped: list[NormalizedRecord] = []
        issues: list[ValidationIssue] = []
        for record in records:
            # A record without a record_key has no identity to compare, so it
            # is always kept (the default rules reject such records earlier).
            key = (record.record_key, record.context_key()) if record.record_key else None
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
                    f"duplicate of {original.source_record_id} "
                    f"(InChIKey {record.record_key}, same target and assay)",
                    "record_key",
                )
            )
        return DatasetRuleOutcome(kept=kept, dropped=dropped, issues=issues)
