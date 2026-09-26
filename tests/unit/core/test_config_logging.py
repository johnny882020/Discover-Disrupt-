import json
import logging
from pathlib import Path

import pytest

from dndlabs.core.config import Settings
from dndlabs.core.logging import JsonFormatter, configure_logging, get_logger


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DNDLABS_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("DNDLABS_NVIDIA_NIM_NUM_CANDIDATES", "7")
    settings = Settings()
    assert settings.database_url == "sqlite:///:memory:"
    assert settings.nvidia_nim_num_candidates == 7


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///x.db", "sqlite:///x.db"),
    ],
)
def test_database_url_uses_psycopg_driver(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected


def test_json_formatter_redacts_secrets() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "hello", None, None)
    record.api_key = "supersecretvalue"
    line = json.loads(JsonFormatter().format(record))
    assert line["api_key"] == "supe…"
    assert "supersecretvalue" not in json.dumps(line)


def test_json_formatter_redacts_passwords_and_tokens() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "hello", None, None)
    record.password = "correct horse battery"
    record.new_password = "another long passphrase"
    record.token = "ddl_sess_secretsecretsecret"
    line = json.loads(JsonFormatter().format(record))
    assert line["password"] == line["new_password"] == "…"
    assert line["token"] == "ddl_…"
    assert "secretsecret" not in json.dumps(line)
    assert "horse" not in json.dumps(line)


def test_json_formatter_redacts_bearer_tokens() -> None:
    record = logging.LogRecord(
        "x", logging.INFO, "f", 1, "Authorization: Bearer abc123xyz", None, None
    )
    line = json.loads(JsonFormatter().format(record))
    assert "abc123xyz" not in line["message"]
    assert "Bearer …" in line["message"]


def test_json_formatter_includes_exception() -> None:
    import sys

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord("x", logging.ERROR, "f", 1, "failed", None, sys.exc_info())
    assert "RuntimeError" in json.loads(JsonFormatter().format(record))["exc_info"]


@pytest.mark.parametrize("json_output", [True, False])
def test_configure_logging(json_output: bool) -> None:
    configure_logging("debug", json_output=json_output)
    assert logging.getLogger().level == logging.DEBUG
    assert get_logger("dndlabs.test").name == "dndlabs.test"
    configure_logging("INFO")


def _env_example() -> dict[str, str]:
    path = Path(__file__).parents[3] / ".env.example"
    pairs = (
        line.split("=", 1)
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )
    return {key: value for key, value in pairs}


def test_env_example_documents_exactly_the_settings() -> None:
    documented = set(_env_example())
    settings = {f"DNDLABS_{name.upper()}" for name in Settings.model_fields}
    assert documented - settings == set(), "variables the code does not read"
    assert settings - documented == set(), "settings missing from .env.example"


def test_env_example_values_are_the_real_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _env_example().items():
        monkeypatch.setenv(key, value)
    from_example = Settings(_env_file=None)  # type: ignore[call-arg]
    defaults = Settings.model_construct()
    for name in Settings.model_fields:
        documented, default = getattr(from_example, name), getattr(defaults, name)
        if default is None:  # optional secret: an empty value means "unset"
            assert not documented, name
        else:
            assert documented == default, name
