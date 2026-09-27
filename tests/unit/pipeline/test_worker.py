import asyncio
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from tests.fakes import DictProvider

from dndlabs.core.exceptions import NotFoundError, PipelineError, StorageError
from dndlabs.core.protocols import EnrichmentClient, Repositories
from dndlabs.core.schemas import (
    EnrichmentRequest,
    EnrichmentResult,
    Organization,
    PipelineRun,
    RawRecord,
    RunStage,
    RunStatus,
    SourceSpec,
    SourceType,
)
from dndlabs.pipeline.orchestrator import PipelineService
from dndlabs.pipeline.worker import RunWorker
from dndlabs.preprocessing.featurize import RdkitFeaturizer
from dndlabs.storage.database import create_db_engine, create_schema
from dndlabs.storage.repositories import build_sql_repositories
from dndlabs.validation.validator import Validator

SPEC = SourceSpec(source=SourceType.CSV, csv_path="lab.csv")
RAWS = [
    RawRecord(source=SourceType.CSV, source_record_id="1", smiles="CCO"),
    RawRecord(source=SourceType.CSV, source_record_id="2", smiles="c1ccccc1O"),
]


class GatedConnector:
    """Yields its records once ``gate`` is set, recording the thread it ran on."""

    source = SourceType.CSV

    def __init__(self, error: str | None = None) -> None:
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.threads: list[str] = []
        self.error = error

    async def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        self.threads.append(threading.current_thread().name)
        self.entered.set()
        assert self.gate.wait(timeout=10), "test never opened the gate"
        if self.error:
            from dndlabs.core.exceptions import IngestionError

            raise IngestionError(self.error)
        for raw in RAWS:
            yield raw


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    create_schema(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def repos(engine: Engine) -> Repositories:
    return build_sql_repositories(engine)


@pytest.fixture
def org(repos: Repositories) -> Organization:
    return repos.organizations.create(Organization(name="Acme"))


def _worker(
    repos: Repositories,
    connector: GatedConnector,
    enrichment: EnrichmentClient | None = None,
    **options: float | str,
) -> RunWorker:
    service = PipelineService(
        DictProvider(connector),
        Validator(),
        repos,
        featurizer=RdkitFeaturizer(),
        enrichment_client=enrichment,
    )
    return RunWorker(service, repos.runs, poll_seconds=0.01, **options)  # type: ignore[arg-type]


def _submit(repos: Repositories, org: Organization) -> PipelineRun:
    return repos.runs.create(PipelineRun(org_id=org.id, spec=SPEC))


async def _until(condition: Callable[[], bool], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


async def test_executes_queued_runs_on_a_worker_thread(
    repos: Repositories, org: Organization
) -> None:
    connector = GatedConnector()
    connector.gate.set()
    runs = [_submit(repos, org) for _ in range(2)]
    await _worker(repos, connector).drain()
    for run in runs:
        finished = repos.runs.get(org.id, run.id)
        assert (finished.status, finished.stage) == (RunStatus.SUCCEEDED, RunStage.DONE)
        assert finished.progress.accepted == 2
    assert all(name.startswith("run-worker") for name in connector.threads)


async def test_the_event_loop_stays_free_while_a_run_executes(
    repos: Repositories, org: Organization
) -> None:
    connector = GatedConnector()
    run = _submit(repos, org)
    worker = _worker(repos, connector)
    await worker.start()
    try:
        await _until(connector.entered.is_set)  # the run is blocked in its thread...
        ticks = 0
        for _ in range(5):  # ...while this loop keeps running
            await asyncio.sleep(0.01)
            ticks += 1
        assert ticks == 5
        connector.gate.set()
        await _until(lambda: repos.runs.get(org.id, run.id).status is RunStatus.SUCCEEDED)
    finally:
        await worker.stop()


async def test_a_held_lease_is_renewed_so_no_other_worker_takes_the_run(
    repos: Repositories, org: Organization
) -> None:
    connector = GatedConnector()
    run = _submit(repos, org)
    worker = _worker(repos, connector, lease_seconds=0.3)
    await worker.start()
    try:
        await _until(connector.entered.is_set)
        await asyncio.sleep(0.6)  # two lease lengths: only renewal keeps it
        assert repos.runs.claim_next("other", 60, max_lost_leases=3) is None
        connector.gate.set()
        await _until(lambda: repos.runs.get(org.id, run.id).status is RunStatus.SUCCEEDED)
    finally:
        await worker.stop()


async def test_a_lost_lease_stops_the_run_at_its_next_stage(
    repos: Repositories, org: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = GatedConnector()
    run = _submit(repos, org)
    worker = _worker(repos, connector, lease_seconds=0.3)
    monkeypatch.setattr(repos.runs, "renew_lease", lambda *_: False)
    claims = iter([repos.runs.claim_next])  # one claim: don't re-take the lapsed run
    monkeypatch.setattr(
        repos.runs, "claim_next", lambda *args: next(claims, lambda *_: None)(*args)
    )
    await worker.start()
    try:
        await _until(connector.entered.is_set)
        await asyncio.sleep(0.2)  # a renewal attempt finds the lease gone
        connector.gate.set()
        await _until(lambda: not worker._active)
    finally:
        await worker.stop()
    stopped = repos.runs.get(org.id, run.id)
    assert (stopped.status, stopped.stage, stopped.error) == (
        RunStatus.RUNNING,
        RunStage.FETCHING,
        None,
    )


async def test_shutdown_releases_a_stopped_run_and_the_next_worker_resumes_it(
    repos: Repositories, org: Organization
) -> None:
    connector = GatedConnector()
    run = _submit(repos, org)
    worker = _worker(repos, connector)
    await worker.start()
    await _until(connector.entered.is_set)
    stopping = asyncio.create_task(worker.stop())
    await asyncio.sleep(0.05)
    connector.gate.set()  # the run finishes fetching, then stops before validating
    await stopping
    released = repos.runs.get(org.id, run.id)
    assert (released.status, released.stage, released.attempts) == (
        RunStatus.PENDING,  # back in the queue, not waiting for a lease to expire
        RunStage.FETCHING,
        1,
    )

    # A clean shutdown never counts against the run, even with a limit of one.
    await _worker(repos, connector, max_lost_leases=1).drain()
    resumed = repos.runs.get(org.id, run.id)
    assert (resumed.status, resumed.attempts, resumed.error) == (RunStatus.SUCCEEDED, 2, None)
    assert [d.run_id for d in repos.datasets.list_for_org(org.id)] == [run.id]


async def test_repeated_clean_shutdowns_never_fail_a_run(
    repos: Repositories, org: Organization
) -> None:
    run = _submit(repos, org)
    for attempt in range(5):  # five deploys in a row, each mid-run
        claimed = repos.runs.claim_next(f"w{attempt}", 60, max_lost_leases=3)
        assert claimed is not None and claimed.id == run.id
        repos.runs.release(run.id, f"w{attempt}")
    connector = GatedConnector()
    connector.gate.set()
    await _worker(repos, connector, max_lost_leases=3).drain()
    finished = repos.runs.get(org.id, run.id)
    assert (finished.status, finished.attempts) == (RunStatus.SUCCEEDED, 6)


async def test_a_run_busy_past_the_grace_period_keeps_its_lease(
    repos: Repositories, org: Organization
) -> None:
    connector = GatedConnector()
    run = _submit(repos, org)
    worker = _worker(repos, connector, shutdown_grace_seconds=0)
    await worker.start()
    await _until(connector.entered.is_set)
    await worker.stop()
    try:
        assert repos.runs.claim_next("other", 60, max_lost_leases=3) is None
    finally:
        connector.gate.set()  # let the abandoned thread finish
    await _until(lambda: repos.runs.get(org.id, run.id).status is not RunStatus.PENDING)


def _crash(repos: Repositories, times: int) -> None:
    """Claim the oldest run ``times`` times, each claimer dying at once (lease 0)."""
    for attempt in range(times):
        assert repos.runs.claim_next(f"crashed-{attempt}", 0, max_lost_leases=3) is not None


async def test_a_run_whose_worker_crashes_twice_still_runs(
    repos: Repositories, org: Organization
) -> None:
    run = _submit(repos, org)
    _crash(repos, 2)  # two claimers die: two lost leases
    connector = GatedConnector()
    connector.gate.set()
    await _worker(repos, connector, max_lost_leases=3).drain()
    finished = repos.runs.get(org.id, run.id)
    assert (finished.status, finished.attempts) == (RunStatus.SUCCEEDED, 3)


async def test_the_third_crash_fails_the_run(repos: Repositories, org: Organization) -> None:
    run = _submit(repos, org)
    _crash(repos, 3)  # the third claimer dies too: that is the third lost lease
    connector = GatedConnector()
    assert await _worker(repos, connector, max_lost_leases=3).run_available() == 0
    failed = repos.runs.get(org.id, run.id)
    assert failed.status is RunStatus.FAILED
    assert failed.error == "the run's worker stopped unexpectedly 3 times; start it again"
    assert (failed.attempts, failed.finished_at is not None) == (3, True)
    assert connector.threads == []


async def test_concurrent_runs_are_shared_between_organizations(
    repos: Repositories, org: Organization
) -> None:
    busy = [_submit(repos, org) for _ in range(3)]  # queued first
    other = repos.organizations.create(Organization(name="Other"))
    quiet = _submit(repos, other)
    connector = GatedConnector()
    worker = _worker(repos, connector, concurrency=2)
    await worker.start()
    try:
        await _until(lambda: len(worker._active) == 2)
        # Not Acme's two oldest: one slot goes to the organization running nothing.
        assert set(worker._active) == {busy[0].id, quiet.id}
        connector.gate.set()
        await _until(
            lambda: all(
                repos.runs.get(r.org_id, r.id).status is RunStatus.SUCCEEDED for r in [*busy, quiet]
            )
        )
    finally:
        await worker.stop()


class GatedEnrichment:
    """A real-looking enrichment client that blocks until ``gate`` is set."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.entered = threading.Event()

    def is_enabled(self) -> bool:
        return True

    async def enrich_batch(self, requests: Sequence[EnrichmentRequest]) -> list[EnrichmentResult]:
        self.entered.set()
        assert self.gate.wait(timeout=10), "test never opened the gate"
        return [EnrichmentResult(record_id=r.record_id, status="enriched") for r in requests]


_ORG_TABLES = (
    "pipeline_runs",
    "datasets",
    "normalized_records",
    "validation_issues",
    "quality_reports",
    "feature_vectors",
    "enrichment_results",
)


def _org_rows(engine: Engine, org_id: uuid.UUID) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            table: conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE org_id = :o"), {"o": str(org_id)}
            ).scalar_one()
            for table in _ORG_TABLES
        }


@pytest.mark.parametrize("stage", ["fetching", "enriching"])
async def test_deleting_the_orgs_data_mid_run_stops_it_and_leaves_nothing(
    repos: Repositories,
    engine: Engine,
    org: Organization,
    stage: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    connector = GatedConnector()
    enrichment = GatedEnrichment()
    if stage == "enriching":
        connector.gate.set()
    run = _submit(repos, org)
    worker = _worker(repos, connector, enrichment)
    await worker.start()
    try:
        gate = connector if stage == "fetching" else enrichment
        await _until(gate.entered.is_set)
        if stage == "enriching":  # the dataset, records and features are stored
            assert _org_rows(engine, org.id)["feature_vectors"] == 2
        repos.datasets.delete_org_data(org.id)  # DELETE /orgs/me/data
        connector.gate.set()
        enrichment.gate.set()
        await _until(lambda: not worker._active)
        assert _org_rows(engine, org.id) == dict.fromkeys(_ORG_TABLES, 0)
        with pytest.raises(NotFoundError):
            repos.runs.get(org.id, run.id)

        # The worker carries on with other organizations' runs.
        other = repos.organizations.create(Organization(name="Other"))
        next_run = _submit(repos, other)
        await _until(lambda: repos.runs.get(other.id, next_run.id).status is RunStatus.SUCCEEDED)
    finally:
        await worker.stop()
    assert "run deleted while executing; stopped" in caplog.messages
    assert "run failed" not in caplog.messages


async def test_run_now_executes_one_run_and_reports_failures(
    repos: Repositories, org: Organization
) -> None:
    connector = GatedConnector()
    connector.gate.set()
    worker = _worker(repos, connector)
    finished = await worker.run_now(_submit(repos, org))
    assert finished.status is RunStatus.SUCCEEDED
    with pytest.raises(PipelineError, match="no longer pending"):
        await worker.run_now(finished)

    broken = GatedConnector(error="source down")
    broken.gate.set()
    with pytest.raises(PipelineError, match="source down"):
        await _worker(repos, broken).run_now(_submit(repos, org))


async def test_a_storage_outage_while_polling_is_retried(
    repos: Repositories, org: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = GatedConnector()
    connector.gate.set()
    run = _submit(repos, org)
    claim_next = repos.runs.claim_next
    failures = iter([StorageError("database restarting")])

    def flaky(*args: object) -> PipelineRun | None:
        for error in failures:
            raise error
        return claim_next(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(repos.runs, "claim_next", flaky)
    worker = _worker(repos, connector)
    await worker.start()
    try:
        await _until(lambda: repos.runs.get(org.id, run.id).status is RunStatus.SUCCEEDED)
    finally:
        await worker.stop()


async def test_worker_ids_are_unique_per_worker(repos: Repositories) -> None:
    connector = GatedConnector()
    assert _worker(repos, connector).worker_id != _worker(repos, connector).worker_id
    assert _worker(repos, connector, worker_id="fixed").worker_id == "fixed"
