import pytest
from fastapi.testclient import TestClient

from dndlabs.api.app import create_app
from dndlabs.core.config import get_settings
from dndlabs.core.exceptions import ConfigurationError


def test_the_api_refuses_to_start_without_an_admin_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DNDLABS_ADMIN_BOOTSTRAP_SECRET", raising=False)
    monkeypatch.setenv("DNDLABS_DATABASE_URL", "sqlite://")
    monkeypatch.chdir("/")  # no .env file to read one from
    get_settings.cache_clear()
    try:
        with (
            pytest.raises(ConfigurationError, match="ADMIN_BOOTSTRAP_SECRET"),
            TestClient(create_app()),
        ):
            pass
    finally:
        get_settings.cache_clear()
