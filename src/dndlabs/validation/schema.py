"""Schema rule: required identifiers and parseable numeric fields."""

from dndlabs.core.schemas import NormalizedRecord, RawRecord, RuleOutcome, ValidationIssue
from dndlabs.validation.issues import error, parse_number


class SchemaRule:
    """Checks that a record has a structure identifier and a sane molecular weight.

    Attributes:
        name: Rule name used in reports.
    """

    name = "schema"

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome:
        """Validate required fields and parse molecular weight.

        Args:
            raw: The raw record.
            record: The record built so far.

        Returns:
            The record with ``molecular_weight`` parsed, plus any issues.
        """
        issues: list[ValidationIssue] = []
        if not raw.smiles and not raw.inchi:
            issues.append(error(self.name, record, "record has neither SMILES nor InChI", "smiles"))
        try:
            weight = parse_number(raw.molecular_weight)
        except ValueError:
            issues.append(
                error(
                    self.name,
                    record,
                    f"molecular weight {raw.molecular_weight!r} is not numeric",
                    "molecular_weight",
                )
            )
            weight = None
        if weight is not None and weight <= 0:
            issues.append(
                error(
                    self.name, record, f"molecular weight {weight} must be > 0", "molecular_weight"
                )
            )
            weight = None
        return RuleOutcome(
            record=record.model_copy(update={"molecular_weight": weight}), issues=issues
        )
