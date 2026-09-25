from pathlib import Path

import httpx

from dndlabs.core.config import Settings
from dndlabs.core.schemas import RunStatus, SourceSpec, SourceType
from dndlabs.pipeline.factory import build_container, migrate
from tests.conftest import FIXTURES


def test_container_runs_pubchem_with_injected_transport(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=(FIXTURES / "pubchem_name_aspirin.json").read_bytes())

    settings = Settings(database_url="sqlite:///:memory:", export_dir=tmp_path)
    container = build_container(settings, pubchem_transport=httpx.MockTransport(handler))
    try:
        result = container.service.run(SourceSpec(source=SourceType.PUBCHEM, identifiers=["2244"]))
        assert result.run.status is RunStatus.SUCCEEDED
        assert container.repositories.datasets.get(result.dataset.id).records[0].name == "Aspirin"
    finally:
        container.close()


def test_migrate(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    migrate(Settings(database_url=f"sqlite:///{db}"))
    assert db.exists()
