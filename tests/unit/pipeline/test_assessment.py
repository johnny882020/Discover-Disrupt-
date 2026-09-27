import uuid

import pytest
from tests.fakes import fake_repositories

from dndlabs.core.exceptions import NotFoundError
from dndlabs.core.schemas import (
    Dataset,
    FeatureVector,
    NormalizedRecord,
    Organization,
    PipelineRun,
    SourceSpec,
    SourceType,
    StoredFeatures,
)
from dndlabs.pipeline.assessment import AssessmentService
from dndlabs.preprocessing.featurize import RdkitFeaturizer


def _dataset(
    smiles: list[str | None],
) -> tuple[AssessmentService, uuid.UUID, uuid.UUID, list[NormalizedRecord]]:
    repos = fake_repositories()
    org = repos.organizations.create(Organization(name="Acme"))
    run = repos.runs.create(
        PipelineRun(org_id=org.id, spec=SourceSpec(source=SourceType.PUBCHEM, identifiers=["1"]))
    )
    dataset_id = uuid.uuid4()
    records = [
        NormalizedRecord(
            dataset_id=dataset_id,
            record_key=f"K{i}",
            source=SourceType.CSV,
            source_record_id=str(i),
            canonical_smiles=s,
        )
        for i, s in enumerate(smiles)
    ]
    repos.datasets.create(
        Dataset(
            id=dataset_id,
            org_id=org.id,
            run_id=run.id,
            name="d",
            source=SourceType.CSV,
            record_count=len(records),
        ),
        records,
    )
    # A vector stored before the Lipinski counts existed.
    repos.features.save_many(
        org.id,
        [FeatureVector(record_id=records[0].id, descriptors={"molecular_weight": 180.16})],
    )
    return AssessmentService(repos, RdkitFeaturizer()), org.id, dataset_id, records


def test_older_vectors_are_completed_from_the_structure() -> None:
    service, org_id, dataset_id, _ = _dataset(["CC(=O)Oc1ccccc1C(=O)O"])
    [profile] = service.assess(org_id, dataset_id).profiles
    assert (profile.hbd, profile.hba) == (1, 4)


def test_records_without_a_usable_structure_keep_empty_properties() -> None:
    service, org_id, dataset_id, records = _dataset(["CCO", None, "C1CC("])
    profiles = {p.record_id: p for p in service.assess(org_id, dataset_id).profiles}
    assert profiles[records[0].id].clogp is not None
    assert profiles[records[1].id].criteria == {}
    assert profiles[records[2].id].criteria == {}


def test_other_orgs_cannot_assess_the_dataset() -> None:
    service, _, dataset_id, _ = _dataset(["CCO"])
    with pytest.raises(NotFoundError):
        service.assess(uuid.uuid4(), dataset_id)


def test_vectors_without_alerts_get_them_computed(monkeypatch: pytest.MonkeyPatch) -> None:
    service, org_id, dataset_id, _ = _dataset(["O=C1C=CC(=O)C=C1"])
    repos = service._repos
    stored = repos.features.features_for

    def before_alerts_existed(
        org: uuid.UUID, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, StoredFeatures]:
        return {k: v.model_copy(update={"alerts": None}) for k, v in stored(org, ids).items()}

    monkeypatch.setattr(repos.features, "features_for", before_alerts_existed)
    [profile] = service.assess(org_id, dataset_id).profiles
    assert {a.family.value for a in profile.alerts} >= {"pains", "reactive_metabolite"}
