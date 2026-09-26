"""In-memory fakes of the core protocols for unit tests."""

import uuid
from collections.abc import AsyncIterator, Sequence

from dndlabs.core.exceptions import IngestionError, NotFoundError
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    ApiKeyRecord,
    Dataset,
    DatasetFilter,
    DatasetWithRecords,
    EnrichmentResult,
    FeatureVector,
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    RawRecord,
    SourceSpec,
    SourceType,
)


class FakeOrganizations:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Organization] = {}

    def create(self, org: Organization) -> Organization:
        self.items[org.id] = org
        return org

    def get(self, org_id: uuid.UUID) -> Organization:
        if org_id not in self.items:
            raise NotFoundError(f"organization {org_id} not found")
        return self.items[org_id]

    def ping(self) -> None:
        pass


class FakeApiKeys:
    def __init__(self) -> None:
        self.records: dict[str, ApiKeyRecord] = {}
        self.hashes: dict[str, str] = {}

    def create(self, org_id: uuid.UUID, prefix: str, hashed_key: str) -> ApiKeyRecord:
        record = ApiKeyRecord(id=uuid.uuid4(), org_id=org_id, prefix=prefix, created_at=_now())
        self.records[prefix] = record
        self.hashes[prefix] = hashed_key
        return record

    def get_by_prefix(self, prefix: str) -> ApiKeyRecord | None:
        return self.records.get(prefix)

    def get_hash(self, prefix: str) -> str | None:
        return self.hashes.get(prefix)

    def touch_last_used(self, key_id: uuid.UUID) -> None:
        for prefix, record in self.records.items():
            if record.id == key_id:
                self.records[prefix] = record.model_copy(update={"last_used_at": _now()})

    def revoke(self, org_id: uuid.UUID, key_id: uuid.UUID) -> None:
        for prefix, record in self.records.items():
            if record.id == key_id and record.org_id == org_id:
                self.records[prefix] = record.model_copy(update={"revoked_at": _now()})
                return
        raise NotFoundError(f"api key {key_id} not found for org {org_id}")


def _now():  # type: ignore[no-untyped-def]
    from dndlabs.core.schemas import utcnow

    return utcnow()


class FakeRuns:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, PipelineRun] = {}

    def create(self, run: PipelineRun) -> PipelineRun:
        self.items[run.id] = run
        return run

    def update(self, org_id: uuid.UUID, run: PipelineRun) -> PipelineRun:
        existing = self.items.get(run.id)
        if existing is None or existing.org_id != org_id:
            raise NotFoundError(f"run {run.id} not found for org {org_id}")
        self.items[run.id] = run
        return run

    def get(self, org_id: uuid.UUID, run_id: uuid.UUID) -> PipelineRun:
        run = self.items.get(run_id)
        if run is None or run.org_id != org_id:
            raise NotFoundError(f"run {run_id} not found for org {org_id}")
        return run

    def list_for_org(self, org_id: uuid.UUID) -> list[PipelineRun]:
        return [r for r in self.items.values() if r.org_id == org_id]


class FakeDatasets:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, DatasetWithRecords] = {}

    def create(self, dataset: Dataset, records: Sequence[NormalizedRecord]) -> Dataset:
        self.items[dataset.id] = DatasetWithRecords(dataset=dataset, records=list(records))
        return dataset

    def get(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> DatasetWithRecords:
        item = self.items.get(dataset_id)
        if item is None or item.dataset.org_id != org_id:
            raise NotFoundError(f"dataset {dataset_id} not found for org {org_id}")
        return item

    def list_for_org(self, org_id: uuid.UUID) -> list[Dataset]:
        return [i.dataset for i in self.items.values() if i.dataset.org_id == org_id]

    def filter_records(
        self, org_id: uuid.UUID, dataset_id: uuid.UUID, filters: DatasetFilter
    ) -> list[NormalizedRecord]:
        item = self.get(org_id, dataset_id)
        records = item.records
        if filters.mw_min is not None:
            records = [
                r for r in records if r.molecular_weight and r.molecular_weight >= filters.mw_min
            ]
        if filters.mw_max is not None:
            records = [
                r for r in records if r.molecular_weight and r.molecular_weight <= filters.mw_max
            ]
        if filters.target is not None:
            records = [r for r in records if r.target == filters.target]
        return records[filters.offset : filters.offset + filters.limit]

    def delete_org_data(self, org_id: uuid.UUID) -> int:
        ids = [i for i, d in self.items.items() if d.dataset.org_id == org_id]
        for i in ids:
            del self.items[i]
        return len(ids)


class FakeReports:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, QualityReport] = {}

    def save(self, org_id: uuid.UUID, report: QualityReport) -> QualityReport:
        assert report.dataset_id
        self.items[report.dataset_id] = report
        return report

    def get_for_dataset(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> QualityReport:
        if dataset_id not in self.items:
            raise NotFoundError(f"report for {dataset_id} not found")
        return self.items[dataset_id]


class FakeFeatures:
    def __init__(self) -> None:
        self.items: list[FeatureVector] = []

    def save_many(self, org_id: uuid.UUID, vectors: Sequence[FeatureVector]) -> int:
        self.items.extend(vectors)
        return len(vectors)


class FakeEnrichments:
    def __init__(self) -> None:
        self.items: list[EnrichmentResult] = []

    def save_many(self, org_id: uuid.UUID, results: Sequence[EnrichmentResult]) -> int:
        self.items.extend(results)
        return len(results)

    def get_for_dataset(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> list[EnrichmentResult]:
        return list(self.items)


def fake_repositories() -> Repositories:
    return Repositories(
        organizations=FakeOrganizations(),
        api_keys=FakeApiKeys(),
        runs=FakeRuns(),
        datasets=FakeDatasets(),
        reports=FakeReports(),
        features=FakeFeatures(),
        enrichments=FakeEnrichments(),
    )


class StaticConnector:
    """Returns canned records, or raises if ``error`` is set."""

    def __init__(
        self, source: SourceType, records: list[RawRecord], error: str | None = None
    ) -> None:
        self.source = source
        self.records = records
        self.error = error
        self.calls: list[SourceSpec] = []

    async def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        self.calls.append(spec)
        if self.error:
            raise IngestionError(self.error)
        for record in self.records:
            yield record


class DictProvider:
    def __init__(self, *connectors: object) -> None:
        self._by_source = {c.source: c for c in connectors}  # type: ignore[attr-defined]

    def get(self, source: SourceType) -> object:
        return self._by_source[source]
