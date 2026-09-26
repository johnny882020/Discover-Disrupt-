from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from tests.fakes import DictProvider, StaticConnector, fake_repositories

from dndlabs.api.app import create_app
from dndlabs.api.dependencies import ApiServices
from dndlabs.auth.service import AuthService
from dndlabs.core.config import Settings
from dndlabs.core.schemas import ApiKeyCreated, Organization, RawRecord, SourceType
from dndlabs.pipeline.exporter import DatasetExporter
from dndlabs.pipeline.orchestrator import PipelineService
from dndlabs.preprocessing.featurize import RdkitFeaturizer
from dndlabs.validation.validator import Validator

ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"


@pytest.fixture
def services() -> ApiServices:
    repos = fake_repositories()
    good = StaticConnector(
        SourceType.CSV,
        [RawRecord(source=SourceType.CSV, source_record_id="1", name="Aspirin", smiles=ASPIRIN)],
    )
    broken = StaticConnector(SourceType.JSON, [], error="cannot parse JSON")
    runner = PipelineService(
        DictProvider(good, broken), Validator(), repos, featurizer=RdkitFeaturizer()
    )
    auth = AuthService(repos)
    return ApiServices(
        repositories=repos,
        service=runner,
        exporter=DatasetExporter(),
        auth=auth,
        settings=Settings(
            admin_bootstrap_secret="test-admin-secret", frontend_origin="http://localhost:5173"
        ),
    )


@pytest.fixture
def client(services: ApiServices) -> Iterator[TestClient]:
    with TestClient(create_app(services)) as c:
        yield c


@pytest.fixture
def org_key(services: ApiServices) -> ApiKeyCreated:
    org = services.repositories.organizations.create(Organization(name="Acme"))
    return services.auth.issue_key(org)


@pytest.fixture
def auth_headers(org_key: ApiKeyCreated) -> dict[str, str]:
    return {"X-API-Key": org_key.raw_key}
