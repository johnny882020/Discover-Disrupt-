"""RDKit-based featurization of normalized records for ML consumption.

Turns one record's canonical SMILES into a :class:`FeatureVector`: named
descriptors (read by ``assessment/criteria.py`` for the hit-to-lead criteria),
structural alerts (``preprocessing/alerts.py``) and a Morgan fingerprint.
"""

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, Lipinski, rdFingerprintGenerator, rdMolDescriptors

from dndlabs.core.exceptions import ValidationError
from dndlabs.core.schemas import FeatureVector, NormalizedRecord
from dndlabs.preprocessing.alerts import AlertScanner

# RDKit writes parse warnings straight to stderr, bypassing core.logging; an
# unparseable structure is reported by raising ValidationError instead.
RDLogger.DisableLog("rdApp.*")  # type: ignore[attr-defined]

#: Molecular descriptors computed for every record. The names are a stored
#: contract: ``assessment.criteria.REQUIRED_DESCRIPTORS`` reads them back, and
#: vectors stored before a name existed get it recomputed at assessment time.
#: ``logp`` is Crippen's cLogP; ``qed`` is Bickerton's drug-likeness score.
_DESCRIPTORS: dict[str, object] = {
    "molecular_weight": Descriptors.MolWt,  # type: ignore[attr-defined]
    "logp": Descriptors.MolLogP,  # type: ignore[attr-defined]
    "tpsa": Descriptors.TPSA,  # type: ignore[attr-defined]
    "hbd": rdMolDescriptors.CalcNumHBD,
    "hba": rdMolDescriptors.CalcNumHBA,
    "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds,
    "num_rings": rdMolDescriptors.CalcNumRings,
    "qed": Descriptors.qed,
    # Lipinski's rule-of-five counts: donors as NH + OH, acceptors as N + O.
    "nhoh_count": Lipinski.NHOHCount,  # type: ignore[attr-defined]
    "no_count": Lipinski.NOCount,  # type: ignore[attr-defined]
}

#: Descriptor names every feature vector carries.
DESCRIPTOR_NAMES: tuple[str, ...] = tuple(_DESCRIPTORS)


class RdkitFeaturizer:
    """Computes RDKit descriptors, structural alerts and a Morgan (ECFP-style) fingerprint.

    Attributes:
        radius: Morgan fingerprint radius.
        n_bits: Fingerprint bit-vector length.
    """

    # Radius 2 is ECFP4 (bond diameter 4), the usual similarity/ML default;
    # 2048 bits keeps bit collisions low. Both are stored on every vector so a
    # consumer knows how its fingerprint was generated.
    def __init__(self, radius: int = 2, n_bits: int = 2048) -> None:
        """Configure the featurizer.

        Args:
            radius: Morgan fingerprint radius.
            n_bits: Fingerprint bit-vector length.
        """
        self.radius = radius
        self.n_bits = n_bits
        self._generator = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
        self._alerts = AlertScanner()

    def featurize(self, record: NormalizedRecord) -> FeatureVector:
        """Compute descriptors, alerts and a fingerprint for one record.

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
        # Sparse: only the set bit indices are stored (``n_bits`` recovers the vector).
        bits = list(fingerprint.GetOnBits())
        return FeatureVector(
            record_id=record.id,
            descriptors=descriptors,
            alerts=self._alerts.scan(mol),
            fingerprint_bits=bits,
            fingerprint_radius=self.radius,
            fingerprint_n_bits=self.n_bits,
        )
