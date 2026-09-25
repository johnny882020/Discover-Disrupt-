"""Pipeline run endpoints."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status

from dndlabs.api.dependencies import ApiServices, get_services
from dndlabs.core.schemas import PipelineRun, SourceSpec

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

Services = Annotated[ApiServices, Depends(get_services)]


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_pipeline(spec: SourceSpec, background: BackgroundTasks, services: Services) -> PipelineRun:
    """Start a pipeline run in the background.

    Args:
        spec: What to ingest.
        background: FastAPI background task queue.
        services: Injected services.

    Returns:
        The pending run; poll ``GET /pipelines/runs/{id}`` for completion.
    """
    run = services.runner.submit(spec)
    background.add_task(services.runner.execute_in_background, run.id)
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: str, services: Services) -> PipelineRun:
    """Return a run's status.

    Args:
        run_id: Run identifier.
        services: Injected services.

    Returns:
        The run, including ``dataset_id`` once it has succeeded.
    """
    return services.repositories.runs.get(run_id)
