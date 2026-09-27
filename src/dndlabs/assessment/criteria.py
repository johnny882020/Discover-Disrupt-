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
    AlertFamily,
    AssayFormat,
    CompoundProfile,
    Criterion,
    CriterionShare,
    CriterionSummary,
    DatasetAssessment,
    FormatPotency,
    NormalizedRecord,
    PotencyClass,
    StoredFeatures,
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
    Criterion.NO_PAINS: "No PAINS alerts",
    Criterion.NO_REACTIVE_METABOLITES: "No reactive-metabolite alerts",
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


def compound_profile(record: NormalizedRecord, features: StoredFeatures | None) -> CompoundProfile:
    """Build a compound's profile from its computed descriptors and alerts.

    Args:
        record: The normalized record (for its potency).
        features: Its stored descriptors and alerts, or ``None`` when none
            were computed.

    Returns:
        The profile; criteria are left empty without complete features.
    """
    klass = potency_class(record.activity_value_nm, record.activity_relation)
    if (
        features is None
        or features.alerts is None
        or not features.descriptors.keys() >= REQUIRED_DESCRIPTORS
    ):
        return CompoundProfile(record_id=record.id, potency_class=klass)
    descriptors, alerts = features.descriptors, features.alerts
    families = {alert.family for alert in alerts}
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
        alerts=alerts,
        potency_class=klass,
        criteria={
            Criterion.MW: mw < 500,
            Criterion.CLOGP: clogp < 5,
            Criterion.LIPINSKI: violations <= 1,
            Criterion.ROTATABLE_BONDS: rotatable < 10,
            Criterion.TPSA: tpsa < 140,
            Criterion.TPSA_CNS: tpsa < 90,
            Criterion.NO_PAINS: AlertFamily.PAINS not in families,
            Criterion.NO_REACTIVE_METABOLITES: AlertFamily.REACTIVE_METABOLITE not in families,
        },
    )


#: Potency classes from most to least potent; ``unknown`` is not ranked.
_RANKED = (PotencyClass.OPTIMIZED, PotencyClass.LEAD, PotencyClass.HIT, PotencyClass.INACTIVE)


def majority_class(classes: Sequence[PotencyClass]) -> PotencyClass:
    """The most potent class that the majority of measurements reach.

    The guide judges a compound active when it is active "in the majority of
    assays": with measurements hit, hit and inactive the compound is a hit;
    with lead and inactive it is inactive (no majority is better than that).

    Args:
        classes: The classes of one compound's measurements.

    Returns:
        The compound's class; ``unknown`` if no measurement has a class.
    """
    ranks = [_RANKED.index(c) for c in classes if c in _RANKED]
    for rank, klass in enumerate(_RANKED):
        if sum(1 for r in ranks if r <= rank) * 2 > len(ranks):
            return klass
    return PotencyClass.UNKNOWN


def _ranked_value(record: NormalizedRecord) -> float | None:
    """A record's activity value if it says how potent the compound is (not a lower bound)."""
    if record.activity_value_nm is None or (record.activity_relation or "=") in (">", ">="):
        return None
    return record.activity_value_nm


def _compound_key(record: NormalizedRecord) -> str:
    """The compound a record measures: its InChIKey, else the record itself."""
    return record.record_key or f"record:{record.id}"


def assess(
    dataset_id: uuid.UUID,
    records: Sequence[NormalizedRecord],
    features: Mapping[uuid.UUID, StoredFeatures],
) -> DatasetAssessment:
    """Assess a dataset against the hit-to-lead criteria.

    Control records are counted but not assessed. Each compound's class is
    the majority class of its measurements, overall and per assay format;
    criteria are counted per compound over all compounds, the actives and
    the most potent five (ranked by their best measurement).

    Args:
        dataset_id: The dataset.
        records: Its records (measurements).
        features: Stored descriptors and alerts by record id.

    Returns:
        The assessment, with one profile per record.
    """
    profiles = [compound_profile(r, features.get(r.id)) for r in records]
    by_id = {p.record_id: p for p in profiles}
    tested = [r for r in records if r.control is None]
    compounds: dict[str, list[NormalizedRecord]] = {}
    for record in tested:
        compounds.setdefault(_compound_key(record), []).append(record)

    def overall(members: list[NormalizedRecord]) -> PotencyClass:
        return majority_class([by_id[r.id].potency_class for r in members])

    classes = {key: overall(members) for key, members in compounds.items()}
    # A compound's properties are the same in every record: use its first.
    representative = {key: by_id[members[0].id] for key, members in compounds.items()}
    actives = [key for key, klass in classes.items() if klass in ACTIVE_CLASSES]

    best = {
        key: min(values)
        for key, members in compounds.items()
        if (values := [v for r in members if (v := _ranked_value(r)) is not None])
    }
    top = sorted(best, key=lambda key: best[key])[:MOST_POTENT]
    top_record_ids = [
        min(
            (r for r in compounds[key] if _ranked_value(r) is not None),
            key=lambda r: _ranked_value(r) or 0.0,
        ).id
        for key in top
    ]

    by_format: list[FormatPotency] = []
    for assay_format in (AssayFormat.BIOCHEMICAL, AssayFormat.CELL_BASED, None):
        members_by_compound = {
            key: in_format
            for key, members in compounds.items()
            if (in_format := [r for r in members if r.assay_format is assay_format])
        }
        if not members_by_compound:
            continue
        format_classes = Counter(overall(m) for m in members_by_compound.values())
        by_format.append(
            FormatPotency(
                assay_format=assay_format,
                compounds=len(members_by_compound),
                potency_classes={k: format_classes.get(k, 0) for k in PotencyClass},
                actives=sum(format_classes.get(k, 0) for k in ACTIVE_CLASSES),
            )
        )

    def share(keys: Sequence[str], criterion: Criterion) -> CriterionShare:
        results = [
            representative[k].criteria[criterion]
            for k in keys
            if criterion in representative[k].criteria
        ]
        return CriterionShare(passing=sum(results), evaluated=len(results))

    counts = Counter(classes.values())
    return DatasetAssessment(
        dataset_id=dataset_id,
        compounds=len(compounds),
        measurements=len(tested),
        controls=len(records) - len(tested),
        potency_classes={klass: counts.get(klass, 0) for klass in PotencyClass},
        actives=len(actives),
        by_format=by_format,
        most_potent_ids=top_record_ids,
        criteria=[
            CriterionSummary(
                criterion=criterion,
                label=CRITERION_LABELS[criterion],
                all_compounds=share(list(compounds), criterion),
                actives=share(actives, criterion),
                most_potent=share(top, criterion),
            )
            for criterion in Criterion
        ],
        profiles=profiles,
    )
