from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dndlabs.api.app import create_app
from dndlabs.core.config import get_settings


def test_app_builds_services_from_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DNDLABS_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("DNDLABS_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("DNDLABS_LOG_JSON", "false")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/datasets").json() == []
            assert client.get("/openapi.json").json()["info"]["title"] == "D&D Labs Data API"
    finally:
        get_settings.cache_clear()
