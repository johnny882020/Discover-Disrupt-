"""Compound-identity rule: parse, canonicalize and cross-check structures with RDKit."""

from collections.abc import Callable

from dndlabs.core.schemas import NormalizedRecord, RawRecord, RuleOutcome, ValidationIssue
from dndlabs.validation.chem import Molecule, from_inchi, from_smiles
from dndlabs.validation.issues import error, warning

_Parser = Callable[[str], Molecule | None]


class CompoundIdentityRule:
    """Validates SMILES/InChI and derives canonical identifiers.

    * Invalid SMILES or InChI → error.
    * SMILES and InChI describing different compounds → error.
    * Claimed InChIKey or formula disagreeing with the structure → warning
      (the computed value wins).
    * Missing formula / molecular weight are filled in from the structure.

    Attributes:
        name: Rule name used in reports.
    """

    name = "compound_identity"

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome:
        """Parse and canonicalize the record's structure.

        Args:
            raw: The raw record.
            record: The record built so far.

        Returns:
            The record with canonical identifiers set, plus any issues.
        """
        issues: list[ValidationIssue] = []
        smiles_mol = self._parse(raw.smiles, from_smiles, "smiles", record, issues)
        inchi_mol = self._parse(raw.inchi, from_inchi, "inchi", record, issues)
        mol = smiles_mol or inchi_mol
        if mol is None or issues:
            return RuleOutcome(record=record, issues=issues)

        key = mol.inchikey
        if smiles_mol is not None and inchi_mol is not None and inchi_mol.inchikey != key:
            issues.append(
                error(self.name, record, "SMILES and InChI describe different compounds", "inchi")
            )
            return RuleOutcome(record=record, issues=issues)
        if raw.inchikey and raw.inchikey.strip().upper() != key:
            issues.append(
                warning(
                    self.name,
                    record,
                    f"claimed InChIKey {raw.inchikey} != computed {key}; using computed",
                    "inchikey",
                )
            )
        formula = mol.formula
        if raw.molecular_formula and raw.molecular_formula.replace(" ", "") != formula:
            issues.append(
                warning(
                    self.name,
                    record,
                    f"claimed formula {raw.molecular_formula} != computed {formula}",
                    "molecular_formula",
                )
            )
        updated = record.model_copy(
            update={
                "record_key": key,
                "inchikey": key,
                "canonical_smiles": mol.canonical_smiles,
                "inchi": mol.inchi,
                "molecular_formula": formula,
                "molecular_weight": record.molecular_weight or mol.average_weight,
            }
        )
        return RuleOutcome(record=updated, issues=issues)

    def _parse(
        self,
        text: str | None,
        parser: _Parser,
        field: str,
        record: NormalizedRecord,
        issues: list[ValidationIssue],
    ) -> Molecule | None:
        """Parse one identifier, appending an error issue if it is invalid."""
        if not text:
            return None
        mol = parser(text)
        if mol is None:
            issues.append(error(self.name, record, f"invalid {field.upper()}: {text!r}", field))
        return mol
