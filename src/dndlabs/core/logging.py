"""Structured logging with secret redaction.

Every module logs through :func:`get_logger`; :func:`configure_logging`
installs one stderr handler whose formatter, :class:`JsonFormatter` (the
default) or :class:`PlainFormatter`, redacts secret-shaped fields and
``Bearer`` tokens before anything is written. Redaction is by key name, so pass credentials
under their usual names (``api_key``, ``token``, ``password``...), never
under a neutral key.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# Standard LogRecord attributes; anything else on a record came from ``extra``.
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}
# Values under these keys keep a 4-character hint (e.g. a key's type prefix).
_SECRET_KEYS = {"api_key", "raw_key", "hashed_key", "nvidia_nim_api_key", "admin_bootstrap_secret",
                "authorization", "x-api-key", "x-admin-secret", "token", "token_hash"}  # fmt: skip
# Values under these keys are redacted entirely: even a prefix of a password leaks it.
_PASSWORD_KEYS = {"password", "current_password", "new_password", "password_hash"}
# Catches tokens embedded in free text (e.g. a logged header or message).
_BEARER_RE = re.compile(r"(Bearer\s+)\S+", re.IGNORECASE)


def _redact(key: str, value: Any) -> Any:
    """Redact a value whose key name suggests it holds a secret.

    Only strings are redacted; a secret must never be logged inside a nested
    structure, where its key would not be inspected.
    """
    if isinstance(value, str) and key.lower() in _PASSWORD_KEYS:
        return "…"
    if isinstance(value, str) and key.lower() in _SECRET_KEYS:
        return f"{value[:4]}…" if len(value) > 8 else "…"
    if isinstance(value, str):
        return _BEARER_RE.sub(r"\1…", value)
    return value


def _redacted_message(record: logging.LogRecord) -> str:
    """Return the record's formatted message with embedded tokens redacted."""
    message: str = _redact("message", record.getMessage())
    return message


def _redacted_extras(record: logging.LogRecord) -> dict[str, Any]:
    """Return the record's ``extra`` fields, each passed through :func:`_redact`.

    Shared by both formatters so plain-text and JSON output redact exactly
    the same things.
    """
    return {
        key: _redact(key, value)
        for key, value in record.__dict__.items()
        if key not in _RESERVED and not key.startswith("_")
    }


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
            "message": _redacted_message(record),
        }
        payload.update(_redacted_extras(record))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class PlainFormatter(logging.Formatter):
    """Format log records as human-readable, secret-redacted text lines.

    ``time LEVEL logger: message key=value ...``. Plain text is meant for
    local reading, but it is still a setting (``DNDLABS_LOG_JSON=false``)
    that can reach a deployed container, so it redacts like the JSON output.
    """

    def __init__(self) -> None:
        """Use the ``time LEVEL logger: message`` layout."""
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802 - stdlib override
        """Render the layout with the redacted message and extra fields.

        Args:
            record: The record to format; ``asctime`` is already set on it.

        Returns:
            The formatted line, without the traceback (added by the base class).
        """
        # Format a copy so the record other handlers see stays untouched.
        redacted = logging.makeLogRecord(record.__dict__)
        redacted.message = _redacted_message(record)
        line = super().formatMessage(redacted)
        extras = _redacted_extras(record)
        if extras:
            line += " " + " ".join(f"{key}={value}" for key, value in extras.items())
        return line


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure the root logger once for the process.

    Args:
        level: Log level name, e.g. ``"INFO"``.
        json_output: Use :class:`JsonFormatter` when true,
            :class:`PlainFormatter` otherwise.
    """
    # Replaces (not appends to) the root handlers, so calling this again
    # never duplicates output.
    handler = logging.StreamHandler(sys.stderr)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(PlainFormatter())
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
