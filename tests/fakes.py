"""In-memory fakes of the core protocols for unit tests."""

from collections.abc import Sequence

from dndlabs.core.exceptions import IngestionError, NotFoundError
from dndlabs.core.protocols import Connector, Repositories
from dndlabs.core.schemas import (
    Dataset,
    DatasetWithRecords,
    NormalizedRecord,
    PipelineRun,
    QualityReport,
    RawRecord,
    SourceSpec,
    SourceType,
)


class FakeRuns:
    def __init__(self) -> None:
        self.items: dict[str, PipelineRun] = {}

    def create(self, run: PipelineRun) -> PipelineRun:
        self.items[run.id] = run
        return run

    def update(self, run: PipelineRun) -> PipelineRun:
        if run.id not in self.items:
            raise NotFoundError(run.id)
        self.items[run.id] = run
        return run

    def get(self, run_id: str) -> PipelineRun:
        if run_id not in self.items:
            raise NotFoundError(f"run {run_id} not found")
        return self.items[run_id]


class FakeRaw:
    def __init__(self) -> None:
        self.items: dict[str, list[RawRecord]] = {}

    def add_many(self, run_id: str, records: Sequence[RawRecord]) -> int:
        self.items.setdefault(run_id, []).extend(records)
        return len(records)

    def list_for_run(self, run_id: str) -> list[RawRecord]:
        return list(self.items.get(run_id, []))


class FakeDatasets:
    def __init__(self) -> None:
        self.items: dict[str, DatasetWithRecords] = {}

    def create(self, dataset: Dataset, records: Sequence[NormalizedRecord]) -> Dataset:
        self.items[dataset.id] = DatasetWithRecords(dataset=dataset, records=list(records))
        return dataset

    def get(self, dataset_id: str) -> DatasetWithRecords:
        if dataset_id not in self.items:
            raise NotFoundError(f"dataset {dataset_id} not found")
        return self.items[dataset_id]

    def list(self) -> list[Dataset]:
        return [d.dataset for d in reversed(self.items.values())]


class FakeReports:
    def __init__(self) -> None:
        self.items: dict[str, QualityReport] = {}

    def save(self, report: QualityReport) -> QualityReport:
        assert report.dataset_id
        self.items[report.dataset_id] = report
        return report

    def get_for_dataset(self, dataset_id: str) -> QualityReport:
        if dataset_id not in self.items:
            raise NotFoundError(f"report for {dataset_id} not found")
        return self.items[dataset_id]


def fake_repositories() -> Repositories:
    return Repositories(
        runs=FakeRuns(), raw_records=FakeRaw(), datasets=FakeDatasets(), reports=FakeReports()
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

    def fetch(self, spec: SourceSpec) -> list[RawRecord]:
        self.calls.append(spec)
        if self.error:
            raise IngestionError(self.error)
        return list(self.records)


class DictProvider:
    def __init__(self, *connectors: Connector) -> None:
        self._by_source = {c.source: c for c in connectors}

    def get(self, source: SourceType) -> Connector:
        return self._by_source[source]
