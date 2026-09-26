"""Standardization rule: reduce each structure to its standardized parent."""

from dndlabs.core.schemas import NormalizedRecord, RawRecord, RuleOutcome, ValidationIssue
from dndlabs.validation.chem import from_smiles
from dndlabs.validation.issues import warning


class StandardizationRule:
    """Standardizes structures with the ChEMBL Structure Pipeline.

    Runs after ``compound_identity``, on the canonical SMILES it derived:

    * salts and solvents are stripped, charges neutralized and functional
      groups normalized, so a compound and its salt forms share one
      ``record_key`` (and are therefore de-duplicated);
    * identifiers, formula and molecular weight are recomputed for the
      parent, and a warning records the structure as submitted;
    * a structure that is still multi-component after standardization
      (a mixture) is kept, with a warning.

    Records without a canonical structure (rejected by an earlier rule) are
    passed through unchanged.

    Attributes:
        name: Rule name used in reports.
    """

    name = "standardization"

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome:
        """Replace the record's structure with its standardized parent.

        Args:
            raw: The raw record (unused; the identity rule already parsed it).
            record: The record built so far.

        Returns:
            The standardized record, plus any warnings.
        """
        if record.canonical_smiles is None:
            return RuleOutcome(record=record)
        mol = from_smiles(record.canonical_smiles)
        if mol is None:  # pragma: no cover - identity produced this SMILES itself
            return RuleOutcome(record=record)

        parent = mol.standardized_parent()
        issues: list[ValidationIssue] = []
        updated = record
        if parent.canonical_smiles != record.canonical_smiles:
            issues.append(
                warning(
                    self.name,
                    record,
                    f"standardized {record.canonical_smiles} to parent structure "
                    f"{parent.canonical_smiles} (salts/solvents removed, charges "
                    "neutralized); identifiers and molecular weight recomputed",
                    "smiles",
                )
            )
            updated = record.model_copy(
                update={
                    "record_key": parent.inchikey,
                    "inchikey": parent.inchikey,
                    "canonical_smiles": parent.canonical_smiles,
                    "inchi": parent.inchi,
                    "molecular_formula": parent.formula,
                    "molecular_weight": parent.average_weight,
                }
            )
        if parent.fragment_count > 1:
            issues.append(
                warning(
                    self.name,
                    record,
                    f"structure has {parent.fragment_count} components after "
                    "standardization (a mixture); kept as submitted",
                    "smiles",
                )
            )
        return RuleOutcome(record=updated, issues=issues)
