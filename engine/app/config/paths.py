"""Per-platform filesystem locations for engine state.

Model weights live under the data directory rather than the cache directory: clearing a
cache is expected to be harmless, but re-downloading weights requires network access the
application otherwise never uses.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "LocalAIAssistant"

_dirs = PlatformDirs(appname=APP_NAME, appauthor=False, roaming=False)


def config_dir() -> Path:
    """Directory holding user-editable configuration files."""
    return Path(_dirs.user_config_dir)


def data_dir() -> Path:
    """Directory holding durable state that must survive a cache wipe."""
    return Path(_dirs.user_data_dir)


def cache_dir() -> Path:
    """Directory holding regenerable intermediate artifacts."""
    return Path(_dirs.user_cache_dir)


def log_dir() -> Path:
    """Directory holding rotated log files."""
    return Path(_dirs.user_log_dir)


def models_dir() -> Path:
    """Directory holding downloaded model weights."""
    return data_dir() / "models"
