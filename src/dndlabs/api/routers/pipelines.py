"""Pipeline run endpoints."""

import uuid

from fastapi import APIRouter, BackgroundTasks, status

from dndlabs.api.dependencies import CurrentOrg, Services
from dndlabs.core.schemas import PipelineRun, SourceSpec

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_pipeline(
    spec: SourceSpec, background: BackgroundTasks, org: CurrentOrg, services: Services
) -> PipelineRun:
    """Start a pipeline run in the background.

    Args:
        spec: What to ingest.
        background: FastAPI background task queue.
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The pending run; poll ``GET /pipelines/runs/{id}`` for completion.
    """
    run = services.service.submit(org.org_id, spec)
    background.add_task(services.service.execute_in_background, org.org_id, run.id)
    return run


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
