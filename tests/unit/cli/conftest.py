from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from dndlabs.cli import main as cli_main
from dndlabs.core.config import Settings, get_settings
from dndlabs.core.schemas import ExportFormat
from dndlabs.pipeline.factory import Container, build_container
from tests.conftest import FIXTURES


def pubchem_handler(request: httpx.Request) -> httpx.Response:
    if "/compound/name/" in request.url.path and "aspirin" not in request.url.path:
        return httpx.Response(404, content=(FIXTURES / "pubchem_not_found.json").read_bytes())
    if "/compound/name/" in request.url.path:
        return httpx.Response(200, content=(FIXTURES / "pubchem_name_aspirin.json").read_bytes())
    return httpx.Response(200, content=(FIXTURES / "pubchem_properties_12.json").read_bytes())


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the CLI at a temp SQLite DB and a mocked PubChem."""
    monkeypatch.setenv("DNDLABS_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("DNDLABS_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("DNDLABS_LOG_LEVEL", "WARNING")
    get_settings.cache_clear()

    def factory(settings: Settings, fmt: ExportFormat) -> Container:
        return build_container(
            settings, pubchem_transport=httpx.MockTransport(pubchem_handler), export_format=fmt
        )

    monkeypatch.setattr(cli_main, "container_factory", factory)
    yield tmp_path
    get_settings.cache_clear()
