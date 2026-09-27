"""Run worker: executes queued pipeline runs inside the API process.

Runs are queued in ``pipeline_runs`` (see :class:`~dndlabs.core.protocols.RunRepository`).
The worker polls for the next runnable run (fair share between
organizations, then oldest first), claims it under a lease and executes it
on a worker thread, so CPU-heavy stages (RDKit) never block the API's event
loop. While a run executes, its lease is renewed every third of its length,
so two renewals can fail (a slow or restarting database) before another
worker may take the run over.

If the process dies (crash, kill, hang), the lease expires and the next
worker to poll resumes the run from the start (the orchestrator deletes the
previous attempt's partial output). Each such lost lease is counted; the
``max_lost_leases``-th fails the run, so a run that crashes its worker every
time cannot crash-loop the service forever.

On shutdown the worker asks its runs to stop at their next checkpoint and
releases each one once it has stopped: the run goes back to ``pending`` and
the next process claims it at once, without counting a lost lease. A run
still busy when the grace period ends keeps its lease until it expires, so it
is never executed twice at once.
"""

import asyncio
import os
import socket
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from dndlabs.core.exceptions import (
    DndLabsError,
    PipelineError,
    RunDeletedError,
    RunInterruptedError,
)
from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import RunRepository
from dndlabs.core.schemas import PipelineRun
from dndlabs.pipeline.orchestrator import PipelineService

logger = get_logger(__name__)


def _default_worker_id() -> str:
    """A worker id unique to this process: host, pid and a random suffix."""
    return f"{socket.gethostname()[:32]}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


class RunWorker:
    """Claims queued runs and executes them with a renewed lease.

    Attributes:
        worker_id: This worker's identity in run leases.
    """

    def __init__(
        self,
        service: PipelineService,
        runs: RunRepository,
        *,
        poll_seconds: float = 2.0,
        lease_seconds: float = 120.0,
        max_lost_leases: int = 3,
        concurrency: int = 1,
        shutdown_grace_seconds: float = 20.0,
        worker_id: str | None = None,
    ) -> None:
        """Configure the worker.

        Args:
            service: Executes runs.
            runs: The run queue.
            poll_seconds: Pause between polls when nothing is runnable.
            lease_seconds: Lease length; renewed every third of it.
            max_lost_leases: Unexpected worker stops (expired leases) that
                fail a run; 3 means the third one fails it.
            concurrency: Runs executed at the same time.
            shutdown_grace_seconds: How long shutdown waits for runs to stop.
            worker_id: Identity in leases; unique per process by default.
        """
        self.worker_id = worker_id or _default_worker_id()
        self._service = service
        self._runs = runs
        self._poll = poll_seconds
        self._lease = lease_seconds
        self._max_lost_leases = max_lost_leases
        self._concurrency = concurrency
        self._grace = shutdown_grace_seconds
        self._stopping = threading.Event()
        self._executor = ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="run-worker"
        )
        self._active: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._loop_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start polling in the background of the running event loop."""
        self._loop_task = asyncio.create_task(self._poll_forever(), name="run-worker")
        logger.info("run worker started", extra={"worker_id": self.worker_id})

    async def stop(self) -> None:
        """Stop polling, let active runs reach a checkpoint, release their leases."""
        self._stopping.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        active = dict(self._active)
        if active:
            await asyncio.wait(active.values(), timeout=self._grace)
        for run_id, task in active.items():
            if task.done():  # stopped at a checkpoint: hand it back, uncounted
                await asyncio.to_thread(self._runs.release, run_id, self.worker_id)
            else:
                logger.warning(
                    "run still busy at shutdown; it resumes when its lease expires",
                    extra={"run_id": str(run_id)},
                )
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("run worker stopped", extra={"worker_id": self.worker_id})

    async def run_available(self) -> int:
        """Fail exhausted runs, then start runnable runs up to the concurrency limit.

        Returns:
            The number of runs started.
        """
        # Failed first, so claim_next never has to consider them.
        for failed in await asyncio.to_thread(self._runs.fail_exhausted, self._max_lost_leases):
            logger.error(
                "run failed: its worker stopped unexpectedly too often",
                extra={"run_id": str(failed.id), "attempts": failed.attempts},
            )
        started = 0
        while len(self._active) < self._concurrency and not self._stopping.is_set():
            run = await asyncio.to_thread(
                self._runs.claim_next, self.worker_id, self._lease, self._max_lost_leases
            )
            if run is None:
                break
            self._start(run)
            started += 1
        return started

    async def drain(self) -> None:
        """Run everything runnable, and wait until no run is active."""
        while await self.run_available() or self._active:
            if self._active:
                await asyncio.wait(list(self._active.values()))

    async def run_now(self, run: PipelineRun) -> PipelineRun:
        """Claim one pending run and execute it to completion (the CLI's path).

        Args:
            run: A pending run.

        Returns:
            The finished run.

        Raises:
            PipelineError: If the run is no longer pending, failed, or was
                deleted while executing.
        """
        claimed = await asyncio.to_thread(
            self._runs.claim, run.org_id, run.id, self.worker_id, self._lease
        )
        if claimed is None:
            raise PipelineError(f"run {run.id} is no longer pending")
        failure: list[BaseException] = []
        await self._execute(claimed, failure.append)
        if failure:
            raise failure[0]
        return await asyncio.to_thread(self._runs.get, run.org_id, run.id)

    def _start(self, run: PipelineRun) -> None:
        """Execute ``run`` as a tracked background task."""
        task = asyncio.create_task(self._execute(run), name=f"run-{run.id}")
        self._active[run.id] = task
        task.add_done_callback(lambda _: self._active.pop(run.id, None))

    async def _poll_forever(self) -> None:
        """Poll for runs until stopped; a storage outage is logged and retried."""
        while not self._stopping.is_set():
            try:
                started = await self.run_available()
            except DndLabsError:
                logger.exception("run worker poll failed; retrying")
                started = 0
            if not started:
                await asyncio.sleep(self._poll)

    async def _execute(
        self, run: PipelineRun, on_failure: Callable[[BaseException], None] | None = None
    ) -> None:
        """Execute a claimed run on a worker thread, renewing its lease meanwhile."""
        lost = threading.Event()

        def interrupted() -> bool:
            return self._stopping.is_set() or lost.is_set()

        def execute() -> None:
            asyncio.run(self._service.execute(run.org_id, run.id, interrupted))

        future = asyncio.get_running_loop().run_in_executor(self._executor, execute)
        while not future.done():
            # Renew at a third of the lease: two renewals may fail before it
            # expires and another worker takes the run over.
            await asyncio.wait({future}, timeout=self._lease / 3)
            if future.done():
                break
            try:
                renewed = await asyncio.to_thread(
                    self._runs.renew_lease, run.id, self.worker_id, self._lease
                )
            except DndLabsError:
                logger.exception("lease renewal failed; retrying", extra={"run_id": str(run.id)})
                continue
            if not renewed:  # another worker took it over, or the run was deleted
                logger.warning("lease lost; stopping the run", extra={"run_id": str(run.id)})
                lost.set()
        try:
            future.result()
        except RunInterruptedError:
            pass  # logged by the service; the queue resumes it
        except RunDeletedError as exc:  # logged by the service; nothing left to do
            if on_failure is not None:
                on_failure(exc)
        except DndLabsError as exc:  # already recorded on the run by the service
            logger.error("run failed", extra={"run_id": str(run.id), "error": str(exc)})
            if on_failure is not None:
                on_failure(exc)
