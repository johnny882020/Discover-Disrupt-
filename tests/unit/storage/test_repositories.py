import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from tests.account_repository_checks import ALL_CHECKS

from dndlabs.core.exceptions import NotFoundError, StorageError
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    Dataset,
    DatasetFilter,
    EnrichmentResult,
    FeatureVector,
    GeneratedCandidate,
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    RunStatus,
    Severity,
    SourceSpec,
    SourceType,
    ValidationIssue,
)
from dndlabs.storage.database import create_db_engine
from dndlabs.storage.repositories import build_sql_repositories


def _org(repos: Repositories, name: str = "Acme") -> Organization:
    return repos.organizations.create(Organization(name=name))


def _run(org_id: uuid.UUID) -> PipelineRun:
    return PipelineRun(org_id=org_id, spec=SourceSpec(source=SourceType.PUBCHEM, identifiers=["1"]))


def _record(dataset_id: uuid.UUID, key: str, sid: str = "1") -> NormalizedRecord:
    return NormalizedRecord(
        dataset_id=dataset_id,
        record_key=key,
        source=SourceType.PUBCHEM,
        source_record_id=sid,
        canonical_smiles="CC(=O)Oc1ccccc1C(=O)O",
        inchikey=key,
        molecular_weight=180.16,
    )


def test_organization_roundtrip(repos: Repositories) -> None:
    org = _org(repos)
    assert repos.organizations.get(org.id) == org
    with pytest.raises(NotFoundError):
        repos.organizations.get(uuid.uuid4())


def test_ping_succeeds_against_a_migrated_database(repos: Repositories) -> None:
    repos.organizations.ping()  # must not raise


def test_ping_fails_against_a_database_with_no_schema() -> None:
    # No create_schema() call: mirrors an unmigrated database.
    unmigrated = build_sql_repositories(create_db_engine("sqlite:///:memory:"))
    with pytest.raises(StorageError):
        unmigrated.organizations.ping()


def test_run_create_get_update(repos: Repositories) -> None:
    org = _org(repos)
    run = repos.runs.create(_run(org.id))
    assert repos.runs.get(org.id, run.id) == run
    done = run.model_copy(update={"status": RunStatus.SUCCEEDED, "finished_at": datetime.now(UTC)})
    repos.runs.update(org.id, done)
    assert repos.runs.get(org.id, run.id).status is RunStatus.SUCCEEDED


def test_run_scoped_to_org(repos: Repositories) -> None:
    org_a, org_b = _org(repos, "A"), _org(repos, "B")
    run = repos.runs.create(_run(org_a.id))
    with pytest.raises(NotFoundError):
        repos.runs.get(org_b.id, run.id)
    with pytest.raises(NotFoundError):
        repos.runs.update(org_b.id, run)


def test_dataset_roundtrip_and_listing(repos: Repositories) -> None:
    org = _org(repos)
    run = repos.runs.create(_run(org.id))
    dataset_id = uuid.uuid4()
    records = [_record(dataset_id, "A" * 27, "1"), _record(dataset_id, "B" * 27, "2")]
    ds = repos.datasets.create(
        Dataset(
            id=dataset_id,
            org_id=org.id,
            run_id=run.id,
            name="demo",
            source=SourceType.PUBCHEM,
            record_count=2,
        ),
        records,
    )
    fetched = repos.datasets.get(org.id, ds.id)
    assert fetched.dataset == ds
    assert len(fetched.records) == 2
    assert [d.id for d in repos.datasets.list_for_org(org.id)] == [ds.id]


def test_dataset_scoped_to_org(repos: Repositories) -> None:
    org_a, org_b = _org(repos, "A"), _org(repos, "B")
    run = repos.runs.create(_run(org_a.id))
    dataset_id = uuid.uuid4()
    ds = repos.datasets.create(
        Dataset(
            id=dataset_id,
            org_id=org_a.id,
            run_id=run.id,
            name="d",
            source=SourceType.PUBCHEM,
            record_count=0,
        ),
        [],
    )
    with pytest.raises(NotFoundError):
        repos.datasets.get(org_b.id, ds.id)
    assert repos.datasets.list_for_org(org_b.id) == []


def test_dataset_rejects_record_without_key(repos: Repositories) -> None:
    org = _org(repos)
    run = repos.runs.create(_run(org.id))
    dataset_id = uuid.uuid4()
    bad = _record(dataset_id, "A" * 27).model_copy(update={"record_key": None})
    with pytest.raises(StorageError, match="record_key"):
        repos.datasets.create(
            Dataset(
                id=dataset_id,
                org_id=org.id,
                run_id=run.id,
                name="d",
                source=SourceType.PUBCHEM,
                record_count=1,
            ),
            [bad],
        )


def test_filter_records_by_molecular_weight(repos: Repositories) -> None:
    org = _org(repos)
    run = repos.runs.create(_run(org.id))
    dataset_id = uuid.uuid4()
    light = _record(dataset_id, "A" * 27, "1").model_copy(update={"molecular_weight": 50.0})
    heavy = _record(dataset_id, "B" * 27, "2").model_copy(update={"molecular_weight": 500.0})
    repos.datasets.create(
        Dataset(
            id=dataset_id,
            org_id=org.id,
            run_id=run.id,
            name="d",
            source=SourceType.PUBCHEM,
            record_count=2,
        ),
        [light, heavy],
    )
    result = repos.datasets.filter_records(org.id, dataset_id, DatasetFilter(mw_min=100))
    assert [r.source_record_id for r in result] == ["2"]


def test_delete_org_data_removes_everything(repos: Repositories) -> None:
    org = _org(repos)
    run = repos.runs.create(_run(org.id))
    dataset_id = uuid.uuid4()
    records = [_record(dataset_id, "A" * 27)]
    repos.datasets.create(
        Dataset(
            id=dataset_id,
            org_id=org.id,
            run_id=run.id,
            name="d",
            source=SourceType.PUBCHEM,
            record_count=1,
        ),
        records,
    )
    repos.reports.save(
        org.id,
        QualityReport(
            run_id=run.id,
            dataset_id=dataset_id,
            total_records=1,
            accepted_records=1,
            rejected_records=0,
            duplicate_records=0,
            warning_count=0,
            error_count=0,
            pass_rate=1.0,
        ),
    )
    repos.features.save_many(
        org.id,
        [FeatureVector(record_id=records[0].id, descriptors={"mw": 1.0}, fingerprint_bits=[1])],
    )
    repos.enrichments.save_many(
        org.id,
        [
            EnrichmentResult(
                record_id=records[0].id,
                status="enriched",
                model_id="genmol",
                candidates=[GeneratedCandidate(smiles="C", score=0.5, scoring_method="QED")],
            )
        ],
    )
    deleted = repos.datasets.delete_org_data(org.id)
    assert deleted == 1
    assert repos.datasets.list_for_org(org.id) == []
    with pytest.raises(NotFoundError):
        repos.datasets.get(org.id, dataset_id)


def test_quality_report_roundtrip(repos: Repositories) -> None:
    org = _org(repos)
    run = repos.runs.create(_run(org.id))
    dataset_id = uuid.uuid4()
    repos.datasets.create(
        Dataset(
            id=dataset_id,
            org_id=org.id,
            run_id=run.id,
            name="d",
            source=SourceType.PUBCHEM,
            record_count=0,
        ),
        [],
    )
    report = QualityReport(
        run_id=run.id,
        dataset_id=dataset_id,
        total_records=2,
        accepted_records=1,
        rejected_records=1,
        duplicate_records=0,
        warning_count=0,
        error_count=1,
        issues_by_rule={"schema": 1},
        issues=[
            ValidationIssue(
                rule="schema", severity=Severity.ERROR, source_record_id="2", message="bad"
            )
        ],
        pass_rate=0.5,
    )
    repos.reports.save(org.id, report)
    assert repos.reports.get_for_dataset(org.id, dataset_id) == report


def test_quality_report_requires_dataset(repos: Repositories) -> None:
    report = QualityReport(
        run_id=uuid.uuid4(),
        total_records=0,
        accepted_records=0,
        rejected_records=0,
        duplicate_records=0,
        warning_count=0,
        error_count=0,
        pass_rate=0.0,
    )
    with pytest.raises(StorageError):
        repos.reports.save(uuid.uuid4(), report)


def test_api_key_repository_lifecycle(repos: Repositories) -> None:
    org = _org(repos)
    record = repos.api_keys.create(org.id, "ddl_live_abc", "hashed")
    assert repos.api_keys.get_by_prefix("ddl_live_abc") == record
    repos.api_keys.touch_last_used(record.id)
    fetched = repos.api_keys.get_by_prefix("ddl_live_abc")
    assert fetched is not None and fetched.last_used_at is not None
    repos.api_keys.revoke(org.id, record.id)
    assert repos.api_keys.get_by_prefix("ddl_live_abc").revoked_at is not None  # type: ignore[union-attr]
    with pytest.raises(NotFoundError):
        repos.api_keys.revoke(uuid.uuid4(), record.id)


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda c: c.__name__)
def test_account_repositories(repos: Repositories, check: Callable[[Repositories], None]) -> None:
    check(repos)
