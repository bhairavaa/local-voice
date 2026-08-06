"""Response and request models for the engine HTTP API.

These models are the source of truth for the TypeScript client: ``--export-openapi`` writes
the schema to ``schema/openapi.json``, and ``openapi-typescript`` turns that into
``ui/src/services/generated/engine.ts``, so the contract cannot drift between the two
languages.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.adapters.enhancement.profiles import EnhancementProfile
from app.pipeline.dictation import DictationState


class HealthResponse(BaseModel):
    """Liveness report for the engine process."""

    status: Literal["ok"] = Field(description="Always 'ok'; failures surface as HTTP errors.")
    version: str = Field(description="Engine package version.")
    process_id: int = Field(description="Operating system process identifier of the engine.")
    uptime_seconds: float = Field(description="Seconds since the engine finished starting.")


class AudioDeviceResponse(BaseModel):
    """One microphone available on this machine."""

    index: int
    name: str
    max_input_channels: int
    is_default: bool


class CapabilitiesResponse(BaseModel):
    """What this engine can currently do, for the interface to reflect in its controls."""

    speech_model: str = Field(description="Whisper model in use.")
    speech_model_loaded: bool = Field(description="Whether the model is resident in memory.")
    enhancement_enabled: bool = Field(description="Whether text cleanup is switched on.")
    enhancement_available: bool = Field(
        description="Whether the local text model can currently be reached."
    )
    enhancement_model: str = Field(description="Text model name, whether or not it is reachable.")
    profiles: list[EnhancementProfile] = Field(description="Selectable cleanup profiles.")
    input_devices: list[AudioDeviceResponse] = Field(description="Available microphones.")


class DictationStateResponse(BaseModel):
    """Whether a recording is in progress."""

    state: DictationState


class StopDictationRequest(BaseModel):
    """Options applied when finishing a recording."""

    profile: EnhancementProfile | None = Field(
        default=None,
        description="Cleanup profile to apply. Defaults to the configured profile.",
    )


class DictationResultResponse(BaseModel):
    """The text produced by one dictation, with the timings behind it."""

    text: str = Field(description="Final text: cleaned up when that succeeded, raw otherwise.")
    raw_text: str = Field(description="Transcript exactly as the speech model produced it.")
    was_enhanced: bool = Field(description="Whether cleanup changed the transcript.")
    enhancement_error: str | None = Field(
        default=None,
        description=(
            "Why cleanup was skipped, when it failed. The raw transcript is still returned."
        ),
    )
    language: str
    model: str
    audio_seconds: float
    speech_seconds: float
    transcribe_seconds: float
    enhance_seconds: float
    stopped_because: str = Field(description="Why recording ended.")
