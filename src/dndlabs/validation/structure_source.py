"""Structure-source rule: reports where a looked-up structure came from, or why none was found."""

from dndlabs.core.schemas import NormalizedRecord, RawRecord, RuleOutcome, ValidationIssue
from dndlabs.validation.issues import error, warning


class StructureSourceRule:
    """Turns structure resolution's outcome into validation issues.

    A structure found by looking up an identifier (InChIKey, PubChem CID,
    ChEMBL ID, name) is kept with a warning naming its source, so it is never
    mistaken for one the user supplied. A record whose structure could not be
    found is rejected with the reason.

    Attributes:
        name: Rule name used in reports.
    """

    name = "structure_lookup"

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome:
        """Report the record's structure resolution.

        Args:
            raw: The raw record, after structure resolution.
            record: The record built so far.

        Returns:
            The record unchanged, plus any issue.
        """
        issues: list[ValidationIssue] = []
        if raw.structure_error:
            issues.append(error(self.name, record, raw.structure_error, "smiles"))
        elif raw.structure_source:
            issues.append(
                warning(self.name, record, f"structure from {raw.structure_source}", "smiles")
            )
        return RuleOutcome(record=record, issues=issues)
