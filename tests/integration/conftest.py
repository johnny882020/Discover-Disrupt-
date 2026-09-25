from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from dndlabs.core.config import Settings
from dndlabs.pipeline.factory import Container, build_container, migrate
from tests.conftest import FIXTURES


def recorded_pubchem(request: httpx.Request) -> httpx.Response:
    """Serve the recorded 12-CID PUG REST response for any CID property request."""
    assert "/compound/cid/" in request.url.path
    return httpx.Response(200, content=(FIXTURES / "pubchem_properties_12.json").read_bytes())


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'e2e.db'}",
        export_dir=tmp_path / "exports",
        auto_create_schema=False,  # exercise the real Alembic migration
    )


@pytest.fixture
def container(settings: Settings) -> Iterator[Container]:
    migrate(settings)
    c = build_container(settings, pubchem_transport=httpx.MockTransport(recorded_pubchem))
    yield c
    c.close()
