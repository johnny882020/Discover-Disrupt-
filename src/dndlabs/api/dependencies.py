"""Dependency-injection seams for the API."""

from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import DatasetWithRecords, ExportFormat, PipelineRun, SourceSpec


class PipelineRunner(Protocol):
    """The subset of the pipeline service the API needs."""

    def submit(self, spec: SourceSpec) -> PipelineRun:
        """Register a pending run.

        Args:
            spec: What to ingest.

        Returns:
            The pending run.
        """
        ...

    def execute_in_background(self, run_id: str) -> None:
        """Execute a run without raising.

        Args:
            run_id: Run to execute.
        """
        ...


class DatasetRenderer(Protocol):
    """Serializes datasets for download."""

    def render(self, dataset: DatasetWithRecords, fmt: ExportFormat) -> str:
        """Render a dataset.

        Args:
            dataset: Dataset to render.
            fmt: Output format.

        Returns:
            Serialized dataset.
        """
        ...


@dataclass(frozen=True)
class ApiServices:
    """Everything the routers depend on.

    Attributes:
        repositories: Storage repositories.
        runner: Pipeline runner.
        renderer: Dataset renderer.
    """

    repositories: Repositories
    runner: PipelineRunner
    renderer: DatasetRenderer


def get_services(request: Request) -> ApiServices:
    """Return the services attached to the running app.

    Args:
        request: Current request.

    Returns:
        The app's services.
    """
    services: ApiServices = request.app.state.services
    return services
