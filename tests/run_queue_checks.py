"""Behavioural checks for the run queue, shared by the SQLite and PostgreSQL suites."""

import uuid
from collections.abc import Callable

from sqlalchemy import select

from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    Dataset,
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    RunProgress,
    RunStage,
    RunStatus,
    SourceSpec,
    SourceType,
)
from dndlabs.storage.models import RunRow


def _queue(repos: Repositories, name: str = "Acme") -> tuple[Organization, list[PipelineRun]]:
    """An org with three pending runs, oldest first."""
    org = repos.organizations.create(Organization(name=name))
    spec = SourceSpec(source=SourceType.PUBCHEM, identifiers=["1"])
    return org, [repos.runs.create(PipelineRun(org_id=org.id, spec=spec)) for _ in range(3)]


def check_claims_oldest_first_and_never_twice(repos: Repositories) -> None:
    _, runs = _queue(repos)
    first = repos.runs.claim_next("w1", 60, max_lost_leases=3)
    second = repos.runs.claim_next("w2", 60, max_lost_leases=3)
    assert first is not None and second is not None
    assert [first.id, second.id] == [runs[0].id, runs[1].id]
    assert (first.status, first.attempts) == (RunStatus.RUNNING, 1)
    assert first.started_at is not None
    third = repos.runs.claim_next("w1", 60, max_lost_leases=3)
    assert third is not None and third.id == runs[2].id
    assert repos.runs.claim_next("w1", 60, max_lost_leases=3) is None


def check_expired_lease_is_resumed_and_exhausted_run_fails(repos: Repositories) -> None:
    org, [run, *others] = _queue(repos)
    for other in others:
        repos.runs.request_cancel(org.id, other.id)
    claimed = repos.runs.claim_next("w1", 0, max_lost_leases=3)  # lease expires at once
    assert claimed is not None and claimed.id == run.id
    assert _lost_leases(repos, run) == 0  # a pending run's claim loses nothing
    assert not repos.runs.renew_lease(run.id, "w2", 60)  # not w2's lease
    assert repos.runs.fail_exhausted(max_lost_leases=3) == []  # first crash: resumed
    resumed = repos.runs.claim_next("w2", 0, max_lost_leases=3)
    assert resumed is not None and (resumed.id, resumed.attempts) == (run.id, 2)
    assert _lost_leases(repos, run) == 1
    assert not repos.runs.renew_lease(run.id, "w1", 60)  # w1 lost it to w2
    assert repos.runs.fail_exhausted(max_lost_leases=3) == []  # second crash: resumed
    again = repos.runs.claim_next("w3", 0, max_lost_leases=3)
    assert again is not None and (again.attempts, _lost_leases(repos, run)) == (3, 2)
    _store_output(repos, org, run)  # the crashed attempt got as far as storing
    # The third crash fails the run instead: it is never claimed again.
    assert repos.runs.claim_next("w4", 60, max_lost_leases=3) is None
    [failed] = repos.runs.fail_exhausted(max_lost_leases=3)
    assert failed.id == run.id and failed.status is RunStatus.FAILED
    assert failed.error == "the run's worker stopped unexpectedly 3 times; start it again"
    assert failed.finished_at is not None and failed.attempts == 3
    assert repos.runs.fail_exhausted(max_lost_leases=3) == []
    assert repos.datasets.list_for_org(org.id) == []  # a failed run keeps no output


def check_renewed_and_released_leases(repos: Repositories) -> None:
    org, [run, *_] = _queue(repos)
    claimed = repos.runs.claim_next("w1", 0, max_lost_leases=3)
    assert claimed is not None
    assert repos.runs.renew_lease(run.id, "w1", 60)  # renewed: no longer claimable
    assert repos.runs.claim_next("w2", 60, max_lost_leases=3) != claimed  # takes the next run
    progress = RunProgress(fetched=5, validated=2)
    repos.runs.update(
        org.id, claimed.model_copy(update={"stage": RunStage.VALIDATING, "progress": progress})
    )
    _store_output(repos, org, run)  # the stopped attempt's partial output
    repos.runs.release(run.id, "someone-else")  # not their run: nothing happens
    assert repos.runs.get(org.id, run.id).status is RunStatus.RUNNING
    assert len(repos.datasets.list_for_org(org.id)) == 1
    repos.runs.release(run.id, "w1")  # shutting down: back to the queue at once
    assert repos.datasets.list_for_org(org.id) == []  # a pending run holds no output
    released = repos.runs.get(org.id, run.id)
    assert (released.status, released.stage, released.progress, released.attempts) == (
        RunStatus.PENDING,
        RunStage.VALIDATING,
        progress,
        1,
    )
    assert not repos.runs.renew_lease(run.id, "w1", 60)  # w1 no longer holds it
    resumed = repos.runs.claim_next("w3", 60, max_lost_leases=1)  # even a limit of 1
    assert resumed is not None and (resumed.id, resumed.attempts) == (run.id, 2)
    assert _lost_leases(repos, run) == 0  # a clean release never counts


def check_fair_share_between_organizations(repos: Repositories) -> None:
    busy, busy_runs = _queue(repos, "Busy")  # three runs, all older than quiet's
    quiet, quiet_runs = _queue(repos, "Quiet")
    order = [repos.runs.claim_next(f"w{i}", 60, max_lost_leases=3) for i in range(6)]
    claimed = [(run.org_id, run.id) for run in order if run is not None]
    # Each claim goes to the org with the fewest runs executing, oldest first on a tie.
    assert claimed == [
        (busy.id, busy_runs[0].id),
        (quiet.id, quiet_runs[0].id),
        (busy.id, busy_runs[1].id),
        (quiet.id, quiet_runs[1].id),
        (busy.id, busy_runs[2].id),
        (quiet.id, quiet_runs[2].id),
    ]
    assert repos.runs.claim_next("w", 60, max_lost_leases=3) is None
    # A run whose lease expired no longer counts as executing for its org.
    spec = SourceSpec(source=SourceType.CSV, csv_path="x.csv")
    crashed_org, later_org = (
        repos.organizations.create(Organization(name=n)) for n in ("Crashed", "Later")
    )
    crashed = repos.runs.create(PipelineRun(org_id=crashed_org.id, spec=spec))
    later = repos.runs.create(PipelineRun(org_id=later_org.id, spec=spec))
    lapsed = repos.runs.claim_next("w", 0, max_lost_leases=3)  # its worker dies at once
    assert lapsed is not None and lapsed.id == crashed.id
    resumed = repos.runs.claim_next("w", 60, max_lost_leases=3)
    assert resumed is not None and resumed.id == crashed.id  # older, and Crashed runs nothing
    last = repos.runs.claim_next("w", 60, max_lost_leases=3)
    assert last is not None and last.id == later.id


def check_cancel(repos: Repositories) -> None:
    org, [pending, running, _] = _queue(repos)
    cancelled = repos.runs.request_cancel(org.id, pending.id)
    assert cancelled.status is RunStatus.CANCELLED and cancelled.finished_at is not None
    claimed = repos.runs.claim_next("w1", 60, max_lost_leases=3)
    assert claimed is not None and claimed.id == running.id  # the cancelled run is skipped
    requested = repos.runs.request_cancel(org.id, running.id)
    assert requested.status is RunStatus.RUNNING and requested.cancel_requested
    # The executing worker's own updates never clear the request.
    updated = repos.runs.update(org.id, claimed.model_copy(update={"stage": RunStage.STORING}))
    assert updated.cancel_requested and updated.stage is RunStage.STORING
    finished = repos.runs.update(org.id, updated.model_copy(update={"status": RunStatus.CANCELLED}))
    assert repos.runs.request_cancel(org.id, running.id) == finished  # finished: unchanged


def check_release_honours_a_requested_cancel(repos: Repositories) -> None:
    org, [run, *_] = _queue(repos)
    claimed = repos.runs.claim_next("w1", 60, max_lost_leases=3)
    assert claimed is not None and claimed.id == run.id
    repos.runs.request_cancel(org.id, run.id)
    repos.runs.release(run.id, "w1")  # stopped at shutdown before reaching a checkpoint
    released = repos.runs.get(org.id, run.id)
    assert released.status is RunStatus.CANCELLED and released.finished_at is not None
    claimed_ids = set()
    while (next_run := repos.runs.claim_next("w2", 60, max_lost_leases=3)) is not None:
        claimed_ids.add(next_run.id)
    assert run.id not in claimed_ids and len(claimed_ids) == 2  # never restarted


def check_progress_roundtrip_and_claim_of_one_run(repos: Repositories) -> None:
    org, [run, *_] = _queue(repos)
    other = repos.organizations.create(Organization(name="OtherCo"))
    assert repos.runs.claim(other.id, run.id, "cli", 60) is None  # another org's run
    claimed = repos.runs.claim(org.id, run.id, "cli", 60)
    assert claimed is not None and claimed.status is RunStatus.RUNNING
    assert repos.runs.claim(org.id, run.id, "cli", 60) is None  # no longer pending
    progress = RunProgress(fetched=10, resolved=2, accepted=7, rejected=2, duplicates=1)
    repos.runs.update(
        org.id, claimed.model_copy(update={"stage": RunStage.VALIDATING, "progress": progress})
    )
    stored = repos.runs.get(org.id, run.id)
    assert (stored.stage, stored.progress, stored.attempts) == (RunStage.VALIDATING, progress, 1)


def check_delete_for_run(repos: Repositories) -> None:
    org, [run, other_run, _] = _queue(repos)
    datasets = [_store_output(repos, org, r) for r in (run, other_run)]
    stranger = uuid.uuid4()
    assert not repos.datasets.delete_for_run(stranger, run.id)  # scoped by org
    assert repos.datasets.delete_for_run(org.id, run.id)
    assert not repos.datasets.delete_for_run(org.id, run.id)
    assert [d.id for d in repos.datasets.list_for_org(org.id)] == [datasets[1].id]
    assert repos.reports.get_for_dataset(org.id, datasets[1].id).run_id == other_run.id


def _store_output(repos: Repositories, org: Organization, run: PipelineRun) -> Dataset:
    """Store a one-record dataset and its quality report as ``run``'s output."""
    dataset = Dataset(
        org_id=org.id, run_id=run.id, name="d", source=SourceType.PUBCHEM, record_count=1
    )
    record = NormalizedRecord(
        dataset_id=dataset.id,
        record_key="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",  # ethanol
        source=SourceType.PUBCHEM,
        source_record_id="1",
        canonical_smiles="CCO",
    )
    repos.datasets.create(dataset, [record])
    repos.reports.save(
        org.id,
        QualityReport(
            run_id=run.id,
            dataset_id=dataset.id,
            total_records=1,
            accepted_records=1,
            rejected_records=0,
            duplicate_records=0,
            warning_count=0,
            error_count=0,
            pass_rate=1.0,
        ),
    )
    return dataset


def _lost_leases(repos: Repositories, run: PipelineRun) -> int:
    """The queue-internal lost-lease count, which the run contract does not carry."""
    with repos.runs._sessions.transaction() as session:  # type: ignore[attr-defined]
        value = session.scalar(select(RunRow.lost_leases).where(RunRow.id == run.id))
    assert isinstance(value, int)
    return value


RUN_QUEUE_CHECKS: list[Callable[[Repositories], None]] = [
    check_claims_oldest_first_and_never_twice,
    check_expired_lease_is_resumed_and_exhausted_run_fails,
    check_renewed_and_released_leases,
    check_fair_share_between_organizations,
    check_cancel,
    check_release_honours_a_requested_cancel,
    check_progress_roundtrip_and_claim_of_one_run,
    check_delete_for_run,
]
