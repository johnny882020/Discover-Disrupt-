"""Thin typed wrapper around the RDKit calls used by validation.

RDKit ships only partial type information; confining it to this module keeps
``mypy --strict`` meaningful everywhere else.
"""

from chembl_structure_pipeline import standardizer  # type: ignore[import-untyped]
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdMolDescriptors

RDLogger.DisableLog("rdApp.*")  # type: ignore[attr-defined]


class Molecule:
    """An opaque parsed molecule."""

    def __init__(self, mol: object) -> None:
        """Wrap an RDKit ``Mol``.

        Args:
            mol: The RDKit molecule.
        """
        self._mol = mol

    @property
    def inchikey(self) -> str:
        """Standard InChIKey."""
        return str(Chem.MolToInchiKey(self._mol))  # type: ignore[no-untyped-call]

    @property
    def inchi(self) -> str:
        """Standard InChI."""
        return str(Chem.MolToInchi(self._mol))  # type: ignore[no-untyped-call]

    @property
    def canonical_smiles(self) -> str:
        """RDKit canonical isomeric SMILES."""
        return str(Chem.MolToSmiles(self._mol))

    @property
    def formula(self) -> str:
        """Molecular formula in Hill order."""
        return str(rdMolDescriptors.CalcMolFormula(self._mol))

    @property
    def fragment_count(self) -> int:
        """Number of disconnected components (e.g. 2 for a salt)."""
        return len(Chem.GetMolFrags(self._mol))

    def standardized_parent(self) -> "Molecule":
        """Apply the ChEMBL Structure Pipeline and return the parent structure.

        Standardizes the molecule (normalizes functional-group
        representations, neutralizes charges where possible) and strips
        salts and solvents. A structure made only of salt/solvent components
        is returned standardized but otherwise unchanged.

        Returns:
            The standardized parent molecule.
        """
        standardized = standardizer.standardize_mol(self._mol)
        parent, _excluded = standardizer.get_parent_mol(standardized)
        return Molecule(parent)

    @property
    def average_weight(self) -> float:
        """Average molecular weight (g/mol), rounded to 3 decimals."""
        return round(float(Descriptors.MolWt(self._mol)), 3)  # type: ignore[attr-defined]


def from_smiles(smiles: str) -> Molecule | None:
    """Parse a SMILES string.

    Args:
        smiles: SMILES text.

    Returns:
        The molecule, or ``None`` if the SMILES is invalid.
    """
    mol = Chem.MolFromSmiles(smiles.strip())
    return Molecule(mol) if mol is not None else None


def from_inchi(inchi: str) -> Molecule | None:
    """Parse an InChI string.

    Args:
        inchi: InChI text (must start with ``InChI=``).

    Returns:
        The molecule, or ``None`` if the InChI is invalid.
    """
    mol = Chem.MolFromInchi(inchi.strip())  # type: ignore[no-untyped-call]
    return Molecule(mol) if mol is not None else None
