import json
import logging

import pytest

from dndlabs.core.config import Settings
from dndlabs.core.logging import JsonFormatter, configure_logging, get_logger


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DNDLABS_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("DNDLABS_PUBCHEM_BATCH_SIZE", "7")
    settings = Settings()
    assert settings.database_url == "sqlite:///:memory:"
    assert settings.pubchem_batch_size == 7


def test_json_formatter_includes_extra() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "hello %s", ("world",), None)
    record.run_id = "abc"
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "hello world"
    assert line["run_id"] == "abc"
    assert line["level"] == "INFO"


def test_json_formatter_includes_exception() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, "f", 1, "failed", None, sys.exc_info())
    assert "RuntimeError" in json.loads(JsonFormatter().format(record))["exc_info"]


@pytest.mark.parametrize("json_output", [True, False])
def test_configure_logging(json_output: bool) -> None:
    configure_logging("debug", json_output=json_output)
    assert logging.getLogger().level == logging.DEBUG
    assert get_logger("dndlabs.test").name == "dndlabs.test"
    configure_logging("INFO")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///x.db", "sqlite:///x.db"),
    ],
)
def test_database_url_uses_psycopg_driver(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected
