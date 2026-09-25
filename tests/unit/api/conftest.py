from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dndlabs.api.app import create_app
from dndlabs.api.dependencies import ApiServices
from dndlabs.core.schemas import RawRecord, SourceType
from dndlabs.pipeline.exporter import DatasetExporter
from dndlabs.pipeline.orchestrator import PipelineService
from dndlabs.validation.validator import Validator
from tests.fakes import DictProvider, StaticConnector, fake_repositories

ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"


@pytest.fixture
def services() -> ApiServices:
    repos = fake_repositories()
    pubchem = StaticConnector(
        SourceType.PUBCHEM,
        [
            RawRecord(
                source=SourceType.PUBCHEM, source_record_id="2244", name="Aspirin", smiles=ASPIRIN
            )
        ],
    )
    broken = StaticConnector(SourceType.CSV, [], error="cannot parse CSV")
    runner = PipelineService(DictProvider(pubchem, broken), Validator(), repos)
    return ApiServices(repositories=repos, runner=runner, renderer=DatasetExporter())


@pytest.fixture
def client(services: ApiServices) -> Iterator[TestClient]:
    with TestClient(create_app(services)) as c:
        yield c
