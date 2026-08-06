"""Turning a live audio source into one finished recording.

This is the first orchestration step: it owns *when* to stop, which is the part the audio
adapter deliberately knows nothing about.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from app.config.settings import AudioSettings
from app.domain.audio import AudioChunk, AudioFormat
from app.domain.buffer import AudioBuffer
from app.domain.ports import AudioSource
from app.domain.vad import SilenceDetector, SpeechState, VadThresholds
from app.observability.logging import get_logger

logger = get_logger(__name__)


class StopReason(Enum):
    """Why recording finished."""

    SILENCE = "silence"
    """The speaker stopped talking."""

    REQUESTED = "requested"
    """The user pressed the hotkey again, or the caller cancelled."""

    MAX_DURATION = "max_duration"
    """The configured ceiling was reached."""

    SOURCE_ENDED = "source_ended"
    """The audio source ran out, which for a file means end of input."""


@dataclass(frozen=True, slots=True, eq=False)
class Recording:
    """A completed capture, ready to be transcribed."""

    audio: AudioChunk
    speech_seconds: float
    stopped_because: StopReason

    @property
    def has_speech(self) -> bool:
        return self.speech_seconds > 0.0


def thresholds_from(settings: AudioSettings) -> VadThresholds:
    """Build endpointing thresholds from configuration."""
    return VadThresholds(
        activation_rms=settings.activation_rms,
        silence_seconds=settings.silence_seconds,
        minimum_speech_seconds=settings.minimum_speech_seconds,
        calibration_seconds=settings.calibration_seconds,
        noise_multiplier=settings.noise_multiplier,
        max_activation_boost=settings.max_activation_boost,
        confirm_blocks=settings.confirm_blocks,
    )


class RecordingService:
    """Records until the speaker stops, the caller asks it to, or the ceiling is hit."""

    def __init__(self, source: AudioSource, settings: AudioSettings) -> None:
        self._source = source
        self._settings = settings
        self._audio_format = AudioFormat(sample_rate=settings.sample_rate, channels=1)

    async def record(self, stop: asyncio.Event | None = None) -> Recording:
        """Capture one utterance.

        ``stop`` lets a caller end the recording early -- the push-to-talk case, where the user
        presses the hotkey again rather than waiting for silence to be detected.
        """
        buffer = AudioBuffer(self._audio_format, self._settings.max_recording_seconds)
        detector = SilenceDetector(thresholds_from(self._settings))
        reason = StopReason.SOURCE_ENDED

        stream = self._source.stream()
        try:
            async for chunk in stream:
                if stop is not None and stop.is_set():
                    reason = StopReason.REQUESTED
                    break

                if not buffer.append(chunk):
                    reason = StopReason.MAX_DURATION
                    logger.warning(
                        "recording reached its ceiling",
                        extra={"max_seconds": self._settings.max_recording_seconds},
                    )
                    break

                if detector.observe(chunk) is SpeechState.ENDED:
                    reason = StopReason.SILENCE
                    break
        finally:
            await stream.aclose()

        recording = Recording(
            audio=buffer.collect(),
            speech_seconds=detector.speech_seconds,
            stopped_because=reason,
        )

        logger.info(
            "recording finished",
            extra={
                "reason": reason.value,
                "captured_seconds": round(recording.audio.duration_seconds, 2),
                "speech_seconds": round(recording.speech_seconds, 2),
            },
        )
        return recording
