"""RDKit-based featurization of normalized records for ML consumption."""

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdFingerprintGenerator, rdMolDescriptors

from dndlabs.core.exceptions import ValidationError
from dndlabs.core.schemas import FeatureVector, NormalizedRecord

RDLogger.DisableLog("rdApp.*")  # type: ignore[attr-defined]

#: Molecular descriptors computed for every record.
_DESCRIPTORS: dict[str, object] = {
    "molecular_weight": Descriptors.MolWt,  # type: ignore[attr-defined]
    "logp": Descriptors.MolLogP,  # type: ignore[attr-defined]
    "tpsa": Descriptors.TPSA,  # type: ignore[attr-defined]
    "hbd": rdMolDescriptors.CalcNumHBD,
    "hba": rdMolDescriptors.CalcNumHBA,
    "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds,
    "num_rings": rdMolDescriptors.CalcNumRings,
    "qed": Descriptors.qed,
}


class RdkitFeaturizer:
    """Computes RDKit descriptors and a Morgan (ECFP-style) fingerprint.

    Attributes:
        radius: Morgan fingerprint radius.
        n_bits: Fingerprint bit-vector length.
    """

    def __init__(self, radius: int = 2, n_bits: int = 2048) -> None:
        """Configure the featurizer.

        Args:
            radius: Morgan fingerprint radius.
            n_bits: Fingerprint bit-vector length.
        """
        self.radius = radius
        self.n_bits = n_bits
        self._generator = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)

    def featurize(self, record: NormalizedRecord) -> FeatureVector:
        """Compute descriptors and a fingerprint for one record.

        Args:
            record: A normalized record with a valid canonical SMILES.

        Returns:
            The feature vector.

        Raises:
            ValidationError: If the record has no parseable SMILES.
        """
        if not record.canonical_smiles:
            raise ValidationError(f"record {record.id} has no canonical SMILES to featurize")
        mol = Chem.MolFromSmiles(record.canonical_smiles)
        if mol is None:
            raise ValidationError(f"record {record.id}: unparseable SMILES for featurization")
        descriptors = {name: round(float(fn(mol)), 4) for name, fn in _DESCRIPTORS.items()}  # type: ignore[operator]
        fingerprint = self._generator.GetFingerprint(mol)
        bits = list(fingerprint.GetOnBits())
        return FeatureVector(
            record_id=record.id,
            descriptors=descriptors,
            fingerprint_bits=bits,
            fingerprint_radius=self.radius,
            fingerprint_n_bits=self.n_bits,
        )
