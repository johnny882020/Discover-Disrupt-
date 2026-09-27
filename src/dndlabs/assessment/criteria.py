"""Hit-to-lead criteria: potency classes and computed-property thresholds.

The thresholds are the ones commonly used to judge a small-molecule hit or
lead series (e.g. Mount Sinai Innovation Partners' hit-to-lead assessment
guide): hits are active below 10 µM and leads below 1 µM (ideally 100 nM);
MW < 500, clogP < 5, Lipinski's rule of five, fewer than 10 rotatable bonds
and a polar surface area below 140 Å² (90 Å² to reach the CNS). The guide
applies them to all compounds tested, to the actives, and to the five most
potent compounds, so each criterion is summarized over those three groups.
"""

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence

from dndlabs.core.schemas import (
    ACTIVE_CLASSES,
    CompoundProfile,
    Criterion,
    CriterionShare,
    CriterionSummary,
    DatasetAssessment,
    NormalizedRecord,
    PotencyClass,
)

#: Upper bounds (nM, exclusive) of each potency class, most potent first.
POTENCY_BOUNDS: tuple[tuple[PotencyClass, float], ...] = (
    (PotencyClass.OPTIMIZED, 100.0),
    (PotencyClass.LEAD, 1_000.0),
    (PotencyClass.HIT, 10_000.0),
)
#: How many of the most potent compounds the guide looks at.
MOST_POTENT = 5

CRITERION_LABELS: dict[Criterion, str] = {
    Criterion.MW: "MW < 500",
    Criterion.CLOGP: "cLogP < 5",
    Criterion.LIPINSKI: "Lipinski's rule of five (≤ 1 violation)",
    Criterion.ROTATABLE_BONDS: "Rotatable bonds < 10",
    Criterion.TPSA: "Polar surface area < 140 Å²",
    Criterion.TPSA_CNS: "Polar surface area < 90 Å² (CNS)",
}

#: Descriptors a profile needs (names as the featurizer stores them).
REQUIRED_DESCRIPTORS = frozenset(
    {"molecular_weight", "logp", "tpsa", "nhoh_count", "no_count", "rotatable_bonds"}
)


def potency_class(value_nm: float | None, relation: str | None) -> PotencyClass:
    """Classify an activity value (IC50, Ki, …) in nM.

    ``<`` and ``<=`` give an upper bound: the class is the one that bound
    guarantees. ``>`` and ``>=`` give a lower bound, which only proves
    inactivity when it is at least 10 µM.

    Args:
        value_nm: The activity value in nM.
        relation: Its qualifier (``=``, ``<``, ``<=``, ``>``, ``>=``).

    Returns:
        The potency class.
    """
    if value_nm is None:
        return PotencyClass.UNKNOWN
    relation = relation or "="
    if relation in (">", ">="):
        inactive_from = POTENCY_BOUNDS[-1][1]
        return PotencyClass.INACTIVE if value_nm >= inactive_from else PotencyClass.UNKNOWN
    for klass, bound in POTENCY_BOUNDS:
        # "< bound" guarantees the class; an exact value must be strictly below.
        if value_nm < bound or (relation == "<" and value_nm == bound):
            return klass
    # Above 10 µM: inactive if exact; an upper bound this high proves nothing.
    return PotencyClass.INACTIVE if relation == "=" else PotencyClass.UNKNOWN


def compound_profile(
    record: NormalizedRecord, descriptors: Mapping[str, float] | None
) -> CompoundProfile:
    """Build a compound's profile from its computed descriptors.

    Args:
        record: The normalized record (for its potency).
        descriptors: Its descriptors, as the featurizer stores them, or
            ``None`` when none were computed.

    Returns:
        The profile; property criteria are left empty without descriptors.
    """
    klass = potency_class(record.activity_value_nm, record.activity_relation)
    if descriptors is None or not descriptors.keys() >= REQUIRED_DESCRIPTORS:
        return CompoundProfile(record_id=record.id, potency_class=klass)
    mw = descriptors["molecular_weight"]
    clogp = descriptors["logp"]
    tpsa = descriptors["tpsa"]
    hbd = int(descriptors["nhoh_count"])
    hba = int(descriptors["no_count"])
    rotatable = int(descriptors["rotatable_bonds"])
    violations = sum((mw > 500, clogp > 5, hbd > 5, hba > 10))
    return CompoundProfile(
        record_id=record.id,
        molecular_weight=mw,
        clogp=clogp,
        tpsa=tpsa,
        hbd=hbd,
        hba=hba,
        rotatable_bonds=rotatable,
        rings=int(descriptors["num_rings"]) if "num_rings" in descriptors else None,
        qed=descriptors.get("qed"),
        lipinski_violations=violations,
        potency_class=klass,
        criteria={
            Criterion.MW: mw < 500,
            Criterion.CLOGP: clogp < 5,
            Criterion.LIPINSKI: violations <= 1,
            Criterion.ROTATABLE_BONDS: rotatable < 10,
            Criterion.TPSA: tpsa < 140,
            Criterion.TPSA_CNS: tpsa < 90,
        },
    )


def most_potent(
    records: Sequence[NormalizedRecord], count: int = MOST_POTENT
) -> list[NormalizedRecord]:
    """The ``count`` compounds with the lowest activity values.

    Lower-bound values (``>``, ``>=``) are left out: they do not say how potent
    a compound is.

    Args:
        records: The dataset's records.
        count: How many to return.

    Returns:
        The most potent records, most potent first.
    """
    ranked = [
        r
        for r in records
        if r.activity_value_nm is not None and (r.activity_relation or "=") not in (">", ">=")
    ]
    return sorted(ranked, key=lambda r: r.activity_value_nm or 0.0)[:count]


def assess(
    dataset_id: uuid.UUID,
    records: Sequence[NormalizedRecord],
    descriptors: Mapping[uuid.UUID, Mapping[str, float]],
) -> DatasetAssessment:
    """Assess a dataset against the hit-to-lead criteria.

    Args:
        dataset_id: The dataset.
        records: Its records.
        descriptors: Computed descriptors by record id.

    Returns:
        Potency classes, the criteria over all compounds, the actives and the
        most potent compounds, and every compound's profile.
    """
    profiles = [compound_profile(r, descriptors.get(r.id)) for r in records]
    by_id = {p.record_id: p for p in profiles}
    actives = [p for p in profiles if p.potency_class in ACTIVE_CLASSES]
    top = [by_id[r.id] for r in most_potent(records)]
    classes = Counter(p.potency_class for p in profiles)

    def share(group: Sequence[CompoundProfile], criterion: Criterion) -> CriterionShare:
        results = [p.criteria[criterion] for p in group if criterion in p.criteria]
        return CriterionShare(passing=sum(results), evaluated=len(results))

    return DatasetAssessment(
        dataset_id=dataset_id,
        compounds=len(profiles),
        potency_classes={klass: classes.get(klass, 0) for klass in PotencyClass},
        actives=len(actives),
        most_potent_ids=[p.record_id for p in top],
        criteria=[
            CriterionSummary(
                criterion=criterion,
                label=CRITERION_LABELS[criterion],
                all_compounds=share(profiles, criterion),
                actives=share(actives, criterion),
                most_potent=share(top, criterion),
            )
            for criterion in Criterion
        ],
        profiles=profiles,
    )
