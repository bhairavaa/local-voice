"""Assembly of the long-lived services the API depends on.

Built once at startup and handed to handlers through the engine context, so nothing reaches
for module-level state and every dependency can be substituted in a test.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.audio.devices import DeviceRegistry
from app.adapters.audio.microphone import MicrophoneSource
from app.adapters.enhancement.ollama import OllamaEnhancer, PassthroughEnhancer
from app.adapters.speech.transcriber import WhisperTranscriber
from app.config.settings import Settings
from app.domain.ports import AudioSource, TextEnhancer, Transcriber
from app.observability.logging import get_logger
from app.pipeline.dictation import DictationService

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Services:
    """The engine's collaborators."""

    dictation: DictationService
    devices: DeviceRegistry
    transcriber: Transcriber
    enhancer: TextEnhancer

    async def aclose(self) -> None:
        """Release anything holding a connection or a device."""
        close = getattr(self.enhancer, "aclose", None)
        if close is not None:
            await close()


def build_services(settings: Settings) -> Services:
    """Wire the adapters together for a given configuration."""
    devices = DeviceRegistry()
    transcriber = WhisperTranscriber(settings.speech, settings.paths)

    enhancer: TextEnhancer = (
        OllamaEnhancer(settings.enhancement)
        if settings.enhancement.enabled
        else PassthroughEnhancer()
    )

    def new_source() -> AudioSource:
        # A fresh source per recording: a microphone stream is consumed once and closing it
        # is what releases the device.
        return MicrophoneSource(settings.audio, registry=devices)

    dictation = DictationService(new_source, transcriber, enhancer, settings)

    logger.info(
        "services ready",
        extra={
            "speech_model": str(settings.speech.model),
            "enhancement_enabled": settings.enhancement.enabled,
        },
    )
    return Services(
        dictation=dictation,
        devices=devices,
        transcriber=transcriber,
        enhancer=enhancer,
    )
