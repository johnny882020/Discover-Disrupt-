"""Pipeline run endpoints: queue a run, list and poll runs, request cancellation."""

import uuid

from fastapi import APIRouter, status

from dndlabs.api.dependencies import CurrentOrg, Services
from dndlabs.core.schemas import PipelineRun, SourceSpec

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_pipeline(spec: SourceSpec, org: CurrentOrg, services: Services) -> PipelineRun:
    """Queue a pipeline run; the API's run worker executes it.

    Only queues (hence 202): a run calls external sources and can be slow,
    so it must not hold the request open. The worker started in the app's
    lifespan claims it under a renewed lease, so a run whose worker dies is
    picked up again (up to ``worker_max_lost_leases`` times) rather than lost.

    Args:
        spec: What to ingest.
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The pending run; poll ``GET /pipelines/runs/{id}`` for its stage,
        counts and outcome.
    """
    return services.service.submit(org.org_id, spec)


@router.get("/runs")
def list_runs(org: CurrentOrg, services: Services) -> list[PipelineRun]:
    """List runs for the calling organization, newest first.

    Args:
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The runs.
    """
    return services.repositories.runs.list_for_org(org.org_id)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, org: CurrentOrg, services: Services) -> PipelineRun:
    """Return a run's status.

    Args:
        run_id: Run identifier.
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The run, including ``dataset_id`` once it has succeeded.
    """
    return services.repositories.runs.get(org.org_id, run_id)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: uuid.UUID, org: CurrentOrg, services: Services) -> PipelineRun:
    """Cancel a run: a queued one at once, a running one at its next checkpoint.

    A running run stops at its next checkpoint and keeps nothing it stored;
    a finished run is returned unchanged.

    Args:
        run_id: Run identifier.
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The run after the request.
    """
    return services.repositories.runs.request_cancel(org.org_id, run_id)
