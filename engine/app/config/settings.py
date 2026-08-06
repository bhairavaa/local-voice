"""Layered configuration.

Precedence, highest first: constructor arguments (CLI) > environment (``LAA_``) > TOML file
> declared defaults. Nested values use a double underscore, e.g. ``LAA_LOGGING__LEVEL=DEBUG``.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from app.adapters.speech.catalogue import WhisperModel
from app.config import paths
from app.domain.audio import WHISPER_SAMPLE_RATE

CONFIG_FILE_ENV_VAR = "LAA_CONFIG_FILE"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

EPHEMERAL_PORT = 0

# The product transcribes English only; the shipped models are the English-only variants.
TRANSCRIPTION_LANGUAGE = "en"

# Origins the desktop webview loads from. The engine and the interface are different origins --
# the interface is served by the webview, the engine listens on an ephemeral port -- so the
# browser applies CORS, and requests carrying an Authorization header are preflighted. Without
# these, every call from the interface fails with a bare "Failed to fetch".
DEFAULT_ALLOWED_ORIGINS = (
    "http://tauri.localhost",  # packaged webview on Windows
    "tauri://localhost",  # packaged webview on macOS and Linux
    "http://localhost:5173",  # Vite dev server
    "http://127.0.0.1:5173",
)


class Environment(StrEnum):
    """Deployment profile controlling developer-facing conveniences."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Severity threshold for emitted records."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ServerSettings(BaseModel):
    """HTTP listener configuration."""

    host: str = "127.0.0.1"
    port: int = Field(default=EPHEMERAL_PORT, ge=0, le=65535)
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS

    @field_validator("allowed_origins")
    @classmethod
    def _reject_wildcard(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """A wildcard would let any page a browser visits reach the engine's port.

        The bearer token would still stop it doing anything, but there is no reason to widen
        the surface: the webview's origins are known ahead of time.
        """
        if "*" in value:
            raise ValueError(
                "allowed_origins must name the webview's origins explicitly; '*' is refused"
            )
        return value

    @field_validator("host")
    @classmethod
    def _reject_non_loopback(cls, value: str) -> str:
        """Prevent the engine from ever being exposed beyond the local machine."""
        if value not in LOOPBACK_HOSTS:
            raise ValueError(
                f"host must be one of {sorted(LOOPBACK_HOSTS)}; "
                f"the engine is never permitted to listen off-machine (got {value!r})"
            )
        return value


class LoggingSettings(BaseModel):
    """Structured logging configuration."""

    level: LogLevel = LogLevel.INFO
    format: Literal["json", "console"] = "json"
    file: Path | None = None
    include_transcripts: bool = False

    @property
    def transcripts_permitted(self) -> bool:
        """Whether transcribed speech may be written to logs.

        Requires an explicit opt-in *and* DEBUG severity, so a stray level change cannot
        silently start persisting what the user dictated.
        """
        return self.include_transcripts and self.level is LogLevel.DEBUG


class PathSettings(BaseModel):
    """Filesystem locations, overridable for development and testing."""

    data_dir: Path = Field(default_factory=paths.data_dir)
    cache_dir: Path = Field(default_factory=paths.cache_dir)
    models_dir: Path = Field(default_factory=paths.models_dir)
    log_dir: Path = Field(default_factory=paths.log_dir)

    def ensure_exist(self) -> None:
        """Create every configured directory if it is missing."""
        for directory in (self.data_dir, self.cache_dir, self.models_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)


class RuntimeSettings(BaseModel):
    """Process lifecycle configuration."""

    parent_pid: int | None = Field(default=None, ge=1)
    parent_poll_seconds: float = Field(default=2.0, gt=0)
    shutdown_grace_seconds: float = Field(default=5.0, gt=0)


class AudioSettings(BaseModel):
    """Microphone capture and endpointing."""

    sample_rate: int = Field(default=WHISPER_SAMPLE_RATE, ge=8_000, le=192_000)
    input_device: int | None = Field(default=None, ge=0)
    block_duration_ms: int = Field(default=30, ge=10, le=100)
    max_recording_seconds: float = Field(default=600.0, gt=0)

    activation_rms: float = Field(default=0.008, gt=0, lt=1)

    # Deliberately generous. Auto-stop is a convenience, not the primary control: the hotkey
    # ends a recording instantly, so the cost of waiting too long is small while the cost of
    # stopping too early is a lost sentence. 1.2s cut people off while they were thinking.
    silence_seconds: float = Field(default=3.0, gt=0)

    minimum_speech_seconds: float = Field(default=0.35, ge=0)

    # Endpointing adapts to the room. Measured on a laptop microphone where a fixed gate let
    # background noise repeatedly reset the silence timer, turning a two second utterance into
    # a twenty-eight second recording.
    calibration_seconds: float = Field(default=0.4, ge=0)
    noise_multiplier: float = Field(default=3.0, ge=1.0)
    max_activation_boost: float = Field(default=8.0, ge=1.0)
    confirm_blocks: int = Field(default=3, ge=1)
    release_ratio: float = Field(default=0.5, gt=0, le=1)

    queue_capacity_blocks: int = Field(default=512, ge=16)

    @field_validator("sample_rate")
    @classmethod
    def _warn_on_non_whisper_rate(cls, value: int) -> int:
        """Speech models resample internally; capturing off-rate only loses quality."""
        if value != WHISPER_SAMPLE_RATE and value % WHISPER_SAMPLE_RATE != 0:
            raise ValueError(
                f"sample_rate should be {WHISPER_SAMPLE_RATE} or a multiple of it so audio can "
                f"be downsampled exactly for the speech model (got {value})"
            )
        return value

    @property
    def block_frames(self) -> int:
        """Frames per capture callback."""
        return int(self.sample_rate * self.block_duration_ms / 1000)


class SpeechSettings(BaseModel):
    """Speech recognition.

    This product transcribes English only, so the language is fixed rather than detected.
    Skipping detection also removes a step from every transcription.

    ``small.en`` is the default because it was measured, not assumed. On the reference machine
    (i5-1335U, CPU only) it transcribes twenty seconds of audio in 2.3 seconds, so a thirty
    second thought comes back in about four. That is fast enough not to be felt, and it is
    noticeably more accurate than ``base.en`` -- which matters more for dictation than the
    remaining fraction of a second would.

    The cost is a 480 MB download on first run. Machines that cannot spare it should set
    ``base.en``; ``laa-benchmark`` will say which is the better choice on a given machine.
    """

    model: WhisperModel = WhisperModel.SMALL_EN
    device: Literal["auto", "cpu", "cuda"] = "auto"
    compute_type: str = "int8"
    cpu_threads: int = Field(default=0, ge=0)
    beam_size: int = Field(default=1, ge=1, le=10)
    vad_filter: bool = True
    allow_downloads: bool = True
    warm_up_on_start: bool = True

    @property
    def language(self) -> str:
        """The only language these models are trained for."""
        return TRANSCRIPTION_LANGUAGE


class EnhancementSettings(BaseModel):
    """Local language model used to clean up transcripts.

    Disabled by default. It requires a separate Ollama installation and several hundred
    megabytes of resident memory on top of the speech model, so it must be an informed choice
    rather than something that silently fails on a constrained machine.
    """

    enabled: bool = False
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:3b-instruct"
    profile: str = "general"
    timeout_seconds: float = Field(default=30.0, gt=0)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_input_characters: int = Field(default=8_000, gt=0)

    @field_validator("base_url")
    @classmethod
    def _reject_non_loopback(cls, value: str) -> str:
        """The text model must be local; sending transcripts off-machine defeats the product."""
        host = urlparse(value).hostname
        if host not in LOOPBACK_HOSTS:
            raise ValueError(
                f"base_url must point at {sorted(LOOPBACK_HOSTS)}; transcripts are never sent "
                f"off this machine (got {value!r})"
            )
        return value


class Settings(BaseSettings):
    """Root configuration object for the engine process."""

    model_config = SettingsConfigDict(
        env_prefix="LAA_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.PRODUCTION
    server: ServerSettings = Field(default_factory=ServerSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    enhancement: EnhancementSettings = Field(default_factory=EnhancementSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order configuration sources from highest to lowest precedence."""
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=config_file_path()),
        )


def config_file_path() -> Path:
    """Resolve the TOML configuration file, honouring an environment override."""
    override = os.environ.get(CONFIG_FILE_ENV_VAR)
    if override:
        return Path(override)
    return paths.config_dir() / "config.toml"
