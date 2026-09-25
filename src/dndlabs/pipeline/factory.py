"""Composition root: builds concrete services from settings."""

from dataclasses import dataclass

import httpx
from sqlalchemy import Engine

from dndlabs.core.config import Settings
from dndlabs.core.protocols import Repositories
from dndlabs.ingestion.csv_connector import CsvConnector
from dndlabs.ingestion.json_connector import JsonConnector
from dndlabs.ingestion.pubchem import PubChemConnector, build_pubchem_client
from dndlabs.ingestion.registry import ConnectorRegistry
from dndlabs.pipeline.exporter import DatasetExporter
from dndlabs.pipeline.orchestrator import PipelineService
from dndlabs.storage.database import create_db_engine, create_schema, run_migrations
from dndlabs.storage.repositories import build_sql_repositories
from dndlabs.validation.validator import Validator


@dataclass(frozen=True)
class Container:
    """Fully wired application services.

    Attributes:
        settings: Settings used to build the container.
        repositories: Storage repositories.
        service: Pipeline service.
        exporter: Dataset exporter.
    """

    settings: Settings
    repositories: Repositories
    service: PipelineService
    exporter: DatasetExporter
    _engine: Engine
    _http: httpx.Client

    def close(self) -> None:
        """Release the HTTP client and database connections."""
        self._http.close()
        self._engine.dispose()


def build_container(
    settings: Settings, pubchem_transport: httpx.BaseTransport | None = None
) -> Container:
    """Build all services from settings.

    Args:
        settings: Application settings.
        pubchem_transport: Optional HTTP transport override (tests, recording).

    Returns:
        The wired container.
    """
    engine = create_db_engine(settings.database_url)
    if settings.auto_create_schema:
        create_schema(engine)
    repositories = build_sql_repositories(engine)
    http = build_pubchem_client(
        settings.pubchem_base_url, settings.pubchem_timeout_seconds, pubchem_transport
    )
    connectors = ConnectorRegistry(
        [
            PubChemConnector(
                http,
                batch_size=settings.pubchem_batch_size,
                max_retries=settings.pubchem_max_retries,
                backoff_seconds=settings.pubchem_backoff_seconds,
            ),
            CsvConnector(),
            JsonConnector(),
        ]
    )
    exporter = DatasetExporter()
    service = PipelineService(
        connectors=connectors,
        validator=Validator(),
        repositories=repositories,
        exporter=exporter,
        export_dir=settings.export_dir,
    )
    return Container(
        settings=settings,
        repositories=repositories,
        service=service,
        exporter=exporter,
        _engine=engine,
        _http=http,
    )


def migrate(settings: Settings) -> None:
    """Apply database migrations for the configured database.

    Args:
        settings: Application settings.
    """
    run_migrations(settings.database_url)
