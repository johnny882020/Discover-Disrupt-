from collections.abc import Iterator
from pathlib import Path

import pytest

from dndlabs.cli import main as cli_main
from dndlabs.core.config import Settings, get_settings
from dndlabs.pipeline.factory import Container, build_container


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("DNDLABS_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("DNDLABS_LOG_LEVEL", "WARNING")
    get_settings.cache_clear()

    def factory(settings: Settings) -> Container:
        return build_container(settings)

    monkeypatch.setattr(cli_main, "container_factory", factory)
    yield tmp_path
    get_settings.cache_clear()
