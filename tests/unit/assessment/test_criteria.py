import uuid

import pytest

from dndlabs.assessment.criteria import assess, compound_profile, most_potent, potency_class
from dndlabs.core.schemas import Criterion, NormalizedRecord, PotencyClass, SourceType
from dndlabs.preprocessing.featurize import RdkitFeaturizer

DATASET = uuid.uuid4()
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
#: Cyclosporin A: MW ~1203, far outside the rule of five.
CYCLOSPORIN = (
    "CCC1C(=O)N(CC(=O)N(C(C(=O)NC(C(=O)N(C(C(=O)NC(C(=O)NC(C(=O)N(C(C(=O)N(C(C(=O)N(C(C(=O)"
    "N(C(C(=O)N1)C(C(C)CC=CC)O)C)C(C)C)C)CC(C)C)C)CC(C)C)C)C)C)CC(C)C)C)C(C)C)CC(C)C)C)C"
)


def _record(
    value: float | None = None, relation: str = "=", smiles: str = ASPIRIN
) -> NormalizedRecord:
    return NormalizedRecord(
        dataset_id=DATASET,
        source=SourceType.CSV,
        source_record_id=str(uuid.uuid4()),
        canonical_smiles=smiles,
        activity_value_nm=value,
        activity_relation=relation if value is not None else None,
    )


def _descriptors(record: NormalizedRecord) -> dict[str, float]:
    return RdkitFeaturizer().featurize(record).descriptors


@pytest.mark.parametrize(
    ("value", "relation", "expected"),
    [
        (None, None, PotencyClass.UNKNOWN),
        (50, "=", PotencyClass.OPTIMIZED),
        (100, "=", PotencyClass.LEAD),  # the bounds are exclusive: 100 nM is not < 100 nM
        (100, "<", PotencyClass.OPTIMIZED),  # "< 100 nM" guarantees it
        (100, "<=", PotencyClass.LEAD),
        (999, "=", PotencyClass.LEAD),
        (9_999, "=", PotencyClass.HIT),
        (10_000, "=", PotencyClass.INACTIVE),
        (10_000, "<", PotencyClass.HIT),
        (50_000, "<", PotencyClass.UNKNOWN),  # could be anything below 50 µM
        (50, ">", PotencyClass.UNKNOWN),  # only a lower bound
        (10_000, ">=", PotencyClass.INACTIVE),
        (20_000, ">", PotencyClass.INACTIVE),
    ],
)
def test_potency_class(value: float | None, relation: str | None, expected: PotencyClass) -> None:
    assert potency_class(value, relation) is expected


def test_profile_uses_lipinski_counts_and_evaluates_every_criterion() -> None:
    record = _record(250)
    profile = compound_profile(record, _descriptors(record))
    assert (profile.hbd, profile.hba) == (1, 4)  # NH+OH and N+O (RDKit's HBA would be 3)
    assert profile.potency_class is PotencyClass.LEAD
    assert profile.lipinski_violations == 0
    assert profile.criteria == dict.fromkeys(Criterion, True)


def test_profile_flags_a_large_compound() -> None:
    record = _record(smiles=CYCLOSPORIN)
    profile = compound_profile(record, _descriptors(record))
    assert profile.lipinski_violations is not None and profile.lipinski_violations >= 2
    assert profile.criteria[Criterion.MW] is False
    assert profile.criteria[Criterion.LIPINSKI] is False
    assert profile.criteria[Criterion.TPSA_CNS] is False


def test_profile_without_descriptors_has_no_criteria() -> None:
    record = _record(20)
    for descriptors in (None, {"molecular_weight": 180.0}):
        profile = compound_profile(record, descriptors)
        assert profile.criteria == {}
        assert profile.molecular_weight is None
        assert profile.potency_class is PotencyClass.OPTIMIZED


def test_most_potent_ranks_by_value_and_skips_lower_bounds() -> None:
    records = [
        _record(v, r) for v, r in [(900, "="), (5, ">"), (40, "<"), (7_000, "="), (None, "=")]
    ]
    assert [r.activity_value_nm for r in most_potent(records, count=2)] == [40, 900]


def test_assess_summarizes_all_actives_and_most_potent() -> None:
    records = [
        _record(10),
        _record(500),
        _record(5_000),
        _record(50_000),
        _record(),
        _record(3, smiles=CYCLOSPORIN),
    ]
    descriptors = {r.id: _descriptors(r) for r in records}
    del descriptors[records[4].id]  # a compound without computed properties

    result = assess(DATASET, records, descriptors)

    assert result.compounds == 6
    assert result.actives == 4
    assert result.potency_classes == {
        PotencyClass.OPTIMIZED: 2,
        PotencyClass.LEAD: 1,
        PotencyClass.HIT: 1,
        PotencyClass.INACTIVE: 1,
        PotencyClass.UNKNOWN: 1,
    }
    assert result.most_potent_ids == [records[i].id for i in (5, 0, 1, 2, 3)]
    mw = next(c for c in result.criteria if c.criterion is Criterion.MW)
    assert mw.label == "MW < 500"
    assert (mw.all_compounds.passing, mw.all_compounds.evaluated) == (4, 5)
    assert (mw.actives.passing, mw.actives.evaluated) == (3, 4)
    assert (mw.most_potent.passing, mw.most_potent.evaluated) == (4, 5)
    assert [p.record_id for p in result.profiles] == [r.id for r in records]
