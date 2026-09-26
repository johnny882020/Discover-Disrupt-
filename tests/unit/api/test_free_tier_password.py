from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from tests.fakes import fake_repositories

from dndlabs.api.app import create_app
from dndlabs.api.dependencies import ApiServices
from dndlabs.auth.service import AuthService
from dndlabs.core.config import Settings
from dndlabs.ingestion.registry import ConnectorRegistry
from dndlabs.pipeline.exporter import DatasetExporter
from dndlabs.pipeline.orchestrator import PipelineService
from dndlabs.preprocessing.featurize import RdkitFeaturizer
from dndlabs.validation.validator import Validator

SHARED = {"X-API-Key": "freetier2026"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    repos = fake_repositories()
    services = ApiServices(
        repositories=repos,
        service=PipelineService(
            connectors=ConnectorRegistry([]),
            validator=Validator(),
            repositories=repos,
            featurizer=RdkitFeaturizer(),
        ),
        exporter=DatasetExporter(),
        auth=AuthService(repos.organizations, repos.api_keys, shared_password="freetier2026"),
        settings=Settings(
            admin_bootstrap_secret="test-admin-secret",
            frontend_origin="http://localhost:5173",
            free_tier_shared_password="freetier2026",
        ),
    )
    with TestClient(create_app(services)) as c:
        yield c


def test_shared_password_authenticates(client: TestClient) -> None:
    response = client.get("/api/v1/auth/whoami", headers=SHARED)
    assert response.status_code == 200
    assert response.json()["org_name"] == "Free Tier (shared, insecure)"


def test_wrong_password_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/auth/whoami", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_shared_password_cannot_revoke_itself(client: TestClient) -> None:
    response = client.post("/api/v1/auth/keys/revoke", headers=SHARED)
    assert response.status_code == 401
