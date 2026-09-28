"""A real API (migrated SQLite, real services) served in-process for script tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dndlabs.api.app import create_app
from dndlabs.api.dependencies import ApiServices
from dndlabs.core.config import Settings
from dndlabs.pipeline.factory import Container, build_container, migrate

ADMIN_SECRET = "script-tests-admin-secret-0123456789"


@pytest.fixture
def container(tmp_path: Path) -> Iterator[Container]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        auto_create_schema=False,
        admin_bootstrap_secret=ADMIN_SECRET,
    )
    migrate(settings)
    built = build_container(settings)
    yield built
    built.close()


@pytest.fixture
def app(container: Container) -> FastAPI:
    return create_app(
        ApiServices(
            repositories=container.repositories,
            service=container.service,
            exporter=container.exporter,
            auth=container.auth,
            uploads=container.uploads,
            assessment=container.assessment,
            settings=container.settings,
            worker=container.worker,
        )
    )


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
