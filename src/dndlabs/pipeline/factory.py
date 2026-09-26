"""Composition root: builds concrete services from settings."""

from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import Engine

from dndlabs.auth.service import AuthPolicy, AuthService
from dndlabs.core.config import Settings
from dndlabs.core.protocols import EnrichmentClient, Repositories
from dndlabs.enrichment.client import HttpGenMolClient, build_nim_client
from dndlabs.enrichment.null_client import NullEnrichmentClient
from dndlabs.ingestion.chembl import ChemblConnector, build_chembl_client
from dndlabs.ingestion.csv_connector import CsvConnector
from dndlabs.ingestion.json_connector import JsonConnector
from dndlabs.ingestion.pubchem import PubChemConnector, build_pubchem_client
from dndlabs.ingestion.registry import ConnectorRegistry
from dndlabs.pipeline.exporter import DatasetExporter
from dndlabs.pipeline.orchestrator import PipelineService
from dndlabs.preprocessing.featurize import RdkitFeaturizer
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
        auth: Auth service.
    """

    settings: Settings
    repositories: Repositories
    service: PipelineService
    exporter: DatasetExporter
    auth: AuthService
    _engine: Engine
    _http_clients: tuple[httpx.Client, ...]

    def close(self) -> None:
        """Release HTTP clients and database connections."""
        for client in self._http_clients:
            client.close()
        self._engine.dispose()


def build_container(
    settings: Settings,
    pubchem_transport: httpx.BaseTransport | None = None,
    chembl_transport: httpx.BaseTransport | None = None,
) -> Container:
    """Build all services from settings.

    Args:
        settings: Application settings.
        pubchem_transport: Optional HTTP transport override (tests, recording).
        chembl_transport: Optional HTTP transport override (tests, recording).

    Returns:
        The wired container.
    """
    engine = create_db_engine(settings.database_url)
    if settings.auto_create_schema:
        create_schema(engine)
    repositories = build_sql_repositories(engine)

    pubchem_http = build_pubchem_client(
        settings.pubchem_base_url, settings.pubchem_timeout_seconds, pubchem_transport
    )
    chembl_http = build_chembl_client(
        settings.chembl_base_url, settings.chembl_timeout_seconds, chembl_transport
    )
    http_clients = [pubchem_http, chembl_http]

    enrichment_client: EnrichmentClient
    if settings.nvidia_nim_api_key:
        nim_http = build_nim_client(
            settings.nvidia_nim_base_url,
            settings.nvidia_nim_api_key,
            settings.nvidia_nim_timeout_seconds,
        )
        http_clients.append(nim_http)
        enrichment_client = HttpGenMolClient(
            nim_http,
            num_candidates=settings.nvidia_nim_num_candidates,
            scoring=settings.nvidia_nim_scoring,
        )
    else:
        enrichment_client = NullEnrichmentClient()

    connectors = ConnectorRegistry(
        [
            PubChemConnector(
                pubchem_http,
                batch_size=settings.pubchem_batch_size,
                max_retries=settings.pubchem_max_retries,
                backoff_seconds=settings.pubchem_backoff_seconds,
            ),
            ChemblConnector(
                chembl_http,
                page_size=settings.chembl_page_size,
                max_retries=settings.chembl_max_retries,
                backoff_seconds=settings.chembl_backoff_seconds,
            ),
            CsvConnector(),
            JsonConnector(),
        ]
    )
    service = PipelineService(
        connectors=connectors,
        validator=Validator(),
        repositories=repositories,
        featurizer=RdkitFeaturizer(),
        enrichment_client=enrichment_client,
    )
    return Container(
        settings=settings,
        repositories=repositories,
        service=service,
        exporter=DatasetExporter(),
        auth=AuthService(repositories, auth_policy(settings)),
        _engine=engine,
        _http_clients=tuple(http_clients),
    )


def auth_policy(settings: Settings) -> AuthPolicy:
    """Build the user-authentication policy from settings.

    Args:
        settings: Application settings.

    Returns:
        The policy.
    """
    return AuthPolicy(
        session_ttl=timedelta(hours=settings.session_ttl_hours),
        invitation_ttl=timedelta(hours=settings.invitation_ttl_hours),
        max_login_attempts=settings.login_max_attempts,
        lockout=timedelta(minutes=settings.login_lockout_minutes),
        password_min_length=settings.password_min_length,
        frontend_origin=settings.frontend_origin,
    )


def migrate(settings: Settings) -> None:
    """Apply database migrations for the configured database.

    Args:
        settings: Application settings.
    """
    run_migrations(settings.database_url)
