import uuid

import pytest

from dndlabs.core.exceptions import ValidationError
from dndlabs.core.schemas import NormalizedRecord, SourceType
from dndlabs.preprocessing.featurize import RdkitFeaturizer

DATASET_ID = uuid.uuid4()


def _record(smiles: str | None) -> NormalizedRecord:
    return NormalizedRecord(
        dataset_id=DATASET_ID, source=SourceType.CSV, source_record_id="1", canonical_smiles=smiles
    )


def test_featurize_aspirin() -> None:
    featurizer = RdkitFeaturizer()
    vector = featurizer.featurize(_record("CC(=O)Oc1ccccc1C(=O)O"))
    assert vector.descriptors["molecular_weight"] == pytest.approx(180.16, abs=0.01)
    assert 0.0 <= vector.descriptors["qed"] <= 1.0
    assert len(vector.fingerprint_bits) > 0
    assert vector.fingerprint_radius == 2
    assert vector.fingerprint_n_bits == 2048


def test_custom_fingerprint_params() -> None:
    featurizer = RdkitFeaturizer(radius=3, n_bits=1024)
    vector = featurizer.featurize(_record("CCO"))
    assert vector.fingerprint_radius == 3
    assert vector.fingerprint_n_bits == 1024
    assert all(b < 1024 for b in vector.fingerprint_bits)


def test_no_smiles_raises() -> None:
    with pytest.raises(ValidationError, match="no canonical SMILES"):
        RdkitFeaturizer().featurize(_record(None))


def test_unparseable_smiles_raises() -> None:
    with pytest.raises(ValidationError, match="unparseable"):
        RdkitFeaturizer().featurize(_record("not a molecule"))
