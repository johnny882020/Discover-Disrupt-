"""Dependency-injection seams for the API."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from dndlabs.auth.dependencies import get_current_org
from dndlabs.auth.service import AuthService
from dndlabs.core.config import Settings
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import OrgContext
from dndlabs.ingestion.uploads import UploadService
from dndlabs.pipeline.assessment import AssessmentService
from dndlabs.pipeline.exporter import DatasetExporter
from dndlabs.pipeline.orchestrator import PipelineService


@dataclass(frozen=True)
class ApiServices:
    """Everything the routers depend on.

    Attributes:
        repositories: Storage repositories.
        service: Pipeline service.
        exporter: Dataset exporter.
        auth: Auth service.
        uploads: Upload service.
        assessment: Hit-to-lead assessment service.
        settings: Application settings.
    """

    repositories: Repositories
    service: PipelineService
    exporter: DatasetExporter
    auth: AuthService
    uploads: UploadService
    assessment: AssessmentService
    settings: Settings


def get_services(request: Request) -> ApiServices:
    """Return the services attached to the running app.

    Args:
        request: Current request.

    Returns:
        The app's services.
    """
    services: ApiServices = request.app.state.services
    return services


Services = Annotated[ApiServices, Depends(get_services)]
CurrentOrg = Annotated[OrgContext, Depends(get_current_org)]
