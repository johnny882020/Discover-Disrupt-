import uuid

import pytest

from dndlabs.assessment.criteria import assess, compound_profile, majority_class, potency_class
from dndlabs.core.schemas import (
    AlertFamily,
    AssayFormat,
    ControlType,
    Criterion,
    NormalizedRecord,
    PotencyClass,
    SourceType,
    StoredFeatures,
)
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


def _features(record: NormalizedRecord) -> StoredFeatures:
    vector = RdkitFeaturizer().featurize(record)
    return StoredFeatures(record_id=record.id, descriptors=vector.descriptors, alerts=vector.alerts)


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
    profile = compound_profile(record, _features(record))
    assert (profile.hbd, profile.hba) == (1, 4)  # NH+OH and N+O (RDKit's HBA would be 3)
    assert profile.potency_class is PotencyClass.LEAD
    assert profile.lipinski_violations == 0
    assert profile.criteria == dict.fromkeys(Criterion, True)


def test_profile_flags_a_large_compound() -> None:
    record = _record(smiles=CYCLOSPORIN)
    profile = compound_profile(record, _features(record))
    assert profile.lipinski_violations is not None and profile.lipinski_violations >= 2
    assert profile.criteria[Criterion.MW] is False
    assert profile.criteria[Criterion.LIPINSKI] is False
    assert profile.criteria[Criterion.TPSA_CNS] is False


def test_profile_without_descriptors_has_no_criteria() -> None:
    record = _record(20)
    full = _features(record)
    for features in (
        None,
        StoredFeatures(record_id=record.id, descriptors={"molecular_weight": 180.0}, alerts=[]),
        full.model_copy(update={"alerts": None}),  # stored before alerts existed
    ):
        profile = compound_profile(record, features)
        assert profile.criteria == {}
        assert profile.molecular_weight is None
        assert profile.potency_class is PotencyClass.OPTIMIZED


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        ([PotencyClass.HIT, PotencyClass.HIT, PotencyClass.INACTIVE], PotencyClass.HIT),
        ([PotencyClass.LEAD, PotencyClass.INACTIVE], PotencyClass.INACTIVE),  # no majority better
        ([PotencyClass.OPTIMIZED, PotencyClass.LEAD, PotencyClass.HIT], PotencyClass.LEAD),
        ([PotencyClass.UNKNOWN, PotencyClass.HIT], PotencyClass.HIT),  # unknown is not counted
        ([PotencyClass.UNKNOWN], PotencyClass.UNKNOWN),
        ([], PotencyClass.UNKNOWN),
    ],
)
def test_majority_class(classes: list[PotencyClass], expected: PotencyClass) -> None:
    assert majority_class(classes) is expected


def test_assess_summarizes_all_actives_and_most_potent() -> None:
    records = [
        _record(10),
        _record(500),
        _record(5_000),
        _record(50_000),
        _record(),
        _record(3, smiles=CYCLOSPORIN),
    ]
    features = {r.id: _features(r) for r in records}
    del features[records[4].id]  # a compound without computed properties

    result = assess(DATASET, records, features)

    assert (result.compounds, result.measurements, result.controls) == (6, 6, 0)
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


def test_alerts_are_carried_and_judged() -> None:
    quinone = _record(smiles="O=C1C=CC(=O)C=C1")
    profile = compound_profile(quinone, _features(quinone))
    families = {a.family for a in profile.alerts}
    assert {AlertFamily.PAINS, AlertFamily.REACTIVE_METABOLITE} <= families
    assert profile.criteria[Criterion.NO_PAINS] is False
    assert profile.criteria[Criterion.NO_REACTIVE_METABOLITES] is False

    aspirin = _record()
    clean = compound_profile(aspirin, _features(aspirin))
    assert clean.criteria[Criterion.NO_PAINS] is True
    assert clean.criteria[Criterion.NO_REACTIVE_METABOLITES] is True
    assert [a.name for a in clean.alerts] == ["phenol_ester"]  # Brenk only: not a criterion


def _measurement(
    key: str,
    value: float,
    assay_format: AssayFormat | None = None,
    control: ControlType | None = None,
    smiles: str = ASPIRIN,
) -> NormalizedRecord:
    return _record(value, smiles=smiles).model_copy(
        update={"record_key": key, "assay_format": assay_format, "control": control}
    )


def test_compounds_are_classed_by_majority_per_format_and_controls_are_excluded() -> None:
    bio, cell = AssayFormat.BIOCHEMICAL, AssayFormat.CELL_BASED
    records = [
        _measurement("A", 50, bio),  # A: optimized biochemically...
        _measurement("A", 20_000, cell),  # ...but inactive in cells
        _measurement("B", 800, bio),
        _measurement("B", 900, bio),
        _measurement("S", 1, bio, ControlType.POSITIVE, smiles=CYCLOSPORIN),  # a control
    ]
    result = assess(DATASET, records, {r.id: _features(r) for r in records})

    assert (result.compounds, result.measurements, result.controls) == (2, 4, 1)
    # A: one optimized and one inactive measurement, so no majority is better than inactive.
    assert result.potency_classes[PotencyClass.INACTIVE] == 1
    assert result.potency_classes[PotencyClass.LEAD] == 1  # B
    assert result.actives == 1
    formats = {f.assay_format: f for f in result.by_format}
    assert set(formats) == {bio, cell}
    assert (formats[bio].compounds, formats[bio].actives) == (2, 2)
    assert formats[bio].potency_classes[PotencyClass.OPTIMIZED] == 1
    assert (formats[cell].compounds, formats[cell].actives) == (1, 0)
    # The control is the most potent value but is never ranked or assessed.
    assert result.most_potent_ids == [records[0].id, records[2].id]
    mw = next(c for c in result.criteria if c.criterion is Criterion.MW)
    assert (mw.all_compounds.passing, mw.all_compounds.evaluated) == (2, 2)  # per compound
    assert len(result.profiles) == 5  # one per record, controls included
