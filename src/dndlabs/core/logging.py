"""Structured logging with secret redaction."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}
_SECRET_KEYS = {"api_key", "raw_key", "hashed_key", "nvidia_nim_api_key", "admin_bootstrap_secret",
                "authorization", "x-api-key"}  # fmt: skip
_BEARER_RE = re.compile(r"(Bearer\s+)\S+", re.IGNORECASE)


def _redact(key: str, value: Any) -> Any:
    """Redact a value whose key name suggests it holds a secret."""
    if isinstance(value, str) and key.lower() in _SECRET_KEYS:
        return f"{value[:4]}…" if len(value) > 8 else "…"
    if isinstance(value, str):
        return _BEARER_RE.sub(r"\1…", value)
    return value


class JsonFormatter(logging.Formatter):
    """Format log records as single-line, secret-redacted JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a log record to JSON.

        Args:
            record: The record to format.

        Returns:
            A JSON string.
        """
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact("message", record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = _redact(key, value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure the root logger once for the process.

    Args:
        level: Log level name, e.g. ``"INFO"``.
        json_output: Use :class:`JsonFormatter` when true, plain text otherwise.
    """
    handler = logging.StreamHandler(sys.stderr)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    """Return a module logger.

    Args:
        name: Logger name, conventionally ``__name__``.

    Returns:
        A standard library logger.
    """
    return logging.getLogger(name)
