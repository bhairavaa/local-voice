"""Structured logging configuration.

Every record is written to stderr. Stdout is reserved exclusively for the startup handshake
line consumed by the desktop shell, and must never carry log output.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from app.config.settings import LoggingSettings, LogLevel
from app.observability.redaction import REDACTED, Sensitive

_LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
_LOG_FILE_BACKUP_COUNT = 3

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# Third-party libraries that log routine activity at INFO. Left alone they bury the engine's
# own records: httpx emits a line per request, and the model downloader one per file.
_NOISY_LIBRARIES = (
    "httpx",
    "httpcore",
    "huggingface_hub",
    "faster_whisper",
    "filelock",
    "urllib3",
)

_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def _extras(record: logging.LogRecord, *, reveal_sensitive: bool) -> dict[str, Any]:
    """Collect caller-supplied ``extra=`` fields, applying the redaction policy."""
    collected: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
            continue
        if isinstance(value, Sensitive):
            collected[key] = value.reveal() if reveal_sensitive else REDACTED
        else:
            collected[key] = value
    return collected


class StructuredFormatter(logging.Formatter):
    """Renders records as single-line JSON objects."""

    def __init__(self, *, reveal_sensitive: bool) -> None:
        super().__init__()
        self._reveal_sensitive = reveal_sensitive

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_extras(record, reveal_sensitive=self._reveal_sensitive))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Renders records in a compact form intended for a developer's terminal."""

    def __init__(self, *, reveal_sensitive: bool) -> None:
        super().__init__(fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        self._reveal_sensitive = reveal_sensitive

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = _extras(record, reveal_sensitive=self._reveal_sensitive)
        if not extras:
            return base
        rendered = " ".join(f"{key}={value!r}" for key, value in sorted(extras.items()))
        return f"{base} [{rendered}]"


def _build_formatter(settings: LoggingSettings) -> logging.Formatter:
    reveal = settings.transcripts_permitted
    if settings.format == "console":
        return ConsoleFormatter(reveal_sensitive=reveal)
    return StructuredFormatter(reveal_sensitive=reveal)


def configure_logging(settings: LoggingSettings) -> None:
    """Install handlers on the root logger, replacing any existing configuration."""
    formatter = _build_formatter(settings)

    handlers: list[logging.Handler] = []

    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)

    if settings.file is not None:
        settings.file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.file,
            maxBytes=_LOG_FILE_MAX_BYTES,
            backupCount=_LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
        existing.close()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(settings.level.value)

    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # Raise their floor rather than silencing them, so genuine warnings still get through.
    # Asking for DEBUG explicitly means wanting everything, including theirs.
    if settings.level is not LogLevel.DEBUG:
        for name in _NOISY_LIBRARIES:
            logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return the logger for a module."""
    return logging.getLogger(name)
