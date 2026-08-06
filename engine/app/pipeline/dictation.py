"""The dictation flow: record, transcribe, clean up.

Recording runs as a background task so the HTTP request that starts it can return
immediately. The user is speaking during that time; a request left open would tie the
interface to the length of the utterance.

Enhancement is the only optional step, and it is the only one allowed to fail without failing
the whole dictation. Getting the raw transcript back is always better than getting nothing.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.config.settings import Settings
from app.domain.ports import AudioSource, TextEnhancer, Transcriber
from app.observability.logging import get_logger
from app.observability.redaction import Sensitive
from app.pipeline.recording import Recording, RecordingService, StopReason

logger = get_logger(__name__)

AudioSourceFactory = Callable[[], AudioSource]


class DictationState(Enum):
    """What the engine is doing."""

    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"


class DictationConflictError(RuntimeError):
    """Raised when an operation does not make sense for the current state."""


@dataclass(frozen=True, slots=True)
class DictationResult:
    """Everything one dictation produced."""

    text: str
    """The text to give the user: enhanced when that succeeded, raw otherwise."""

    raw_text: str
    """The transcript exactly as the speech model produced it."""

    was_enhanced: bool
    enhancement_error: str | None
    language: str
    model: str
    audio_seconds: float
    speech_seconds: float
    transcribe_seconds: float
    enhance_seconds: float
    stopped_because: StopReason

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class DictationService:
    """Owns the one recording that can be in progress at a time."""

    def __init__(
        self,
        source_factory: AudioSourceFactory,
        transcriber: Transcriber,
        enhancer: TextEnhancer,
        settings: Settings,
    ) -> None:
        self._source_factory = source_factory
        self._transcriber = transcriber
        self._enhancer = enhancer
        self._settings = settings

        self._state = DictationState.IDLE
        self._task: asyncio.Task[Recording] | None = None
        self._stop_requested = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> DictationState:
        return self._state

    async def start(self) -> None:
        """Begin capturing. Returns as soon as the microphone is open."""
        async with self._lock:
            if self._state is not DictationState.IDLE:
                raise DictationConflictError(f"cannot start while {self._state.value}")

            self._stop_requested = asyncio.Event()
            recorder = RecordingService(self._source_factory(), self._settings.audio)
            self._task = asyncio.create_task(
                recorder.record(self._stop_requested), name="dictation-recording"
            )
            self._state = DictationState.RECORDING
            logger.info("dictation started")

    async def stop(self, profile: str | None = None) -> DictationResult:
        """End capture and produce the text."""
        async with self._lock:
            if self._state is not DictationState.RECORDING or self._task is None:
                raise DictationConflictError(f"cannot stop while {self._state.value}")

            self._stop_requested.set()
            task = self._task
            self._state = DictationState.PROCESSING

        try:
            recording = await task
            return await self._process(recording, profile or self._settings.enhancement.profile)
        finally:
            async with self._lock:
                self._task = None
                self._state = DictationState.IDLE

    async def cancel(self) -> None:
        """Discard an in-progress recording without transcribing it."""
        async with self._lock:
            if self._state is not DictationState.RECORDING or self._task is None:
                raise DictationConflictError(f"cannot cancel while {self._state.value}")

            self._stop_requested.set()
            task = self._task
            self._task = None
            self._state = DictationState.IDLE

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("dictation cancelled")

    async def dictate_until_silence(self, profile: str | None = None) -> DictationResult:
        """Record until the speaker stops, then produce the text.

        The hands-free path, and the one the command line tool uses.
        """
        await self.start()
        return await self._await_natural_end(profile)

    async def _await_natural_end(self, profile: str | None) -> DictationResult:
        async with self._lock:
            task = self._task
            if task is None:
                raise DictationConflictError("recording did not start")
            self._state = DictationState.PROCESSING

        try:
            recording = await task
            return await self._process(recording, profile or self._settings.enhancement.profile)
        finally:
            async with self._lock:
                self._task = None
                self._state = DictationState.IDLE

    async def _process(self, recording: Recording, profile: str) -> DictationResult:
        started = time.perf_counter()
        transcript = await self._transcriber.transcribe(recording.audio)
        transcribe_seconds = time.perf_counter() - started

        raw_text = transcript.text.strip()
        text = raw_text
        was_enhanced = False
        enhancement_error: str | None = None
        enhance_seconds = 0.0

        if raw_text and self._settings.enhancement.enabled:
            enhance_started = time.perf_counter()
            try:
                text = await self._enhancer.enhance(raw_text, profile)
                was_enhanced = text != raw_text
            except Exception as error:
                # Never fail a dictation because the optional cleanup step was unavailable.
                enhancement_error = str(error)
                text = raw_text
                logger.warning(
                    "enhancement failed; keeping the raw transcript",
                    extra={"reason": enhancement_error},
                )
            enhance_seconds = time.perf_counter() - enhance_started

        result = DictationResult(
            text=text,
            raw_text=raw_text,
            was_enhanced=was_enhanced,
            enhancement_error=enhancement_error,
            language=transcript.language,
            model=transcript.model,
            audio_seconds=recording.audio.duration_seconds,
            speech_seconds=recording.speech_seconds,
            transcribe_seconds=transcribe_seconds,
            enhance_seconds=enhance_seconds,
            stopped_because=recording.stopped_because,
        )

        logger.info(
            "dictation finished",
            extra={
                "stopped_because": result.stopped_because.value,
                "audio_seconds": round(result.audio_seconds, 2),
                "transcribe_seconds": round(result.transcribe_seconds, 2),
                "enhance_seconds": round(result.enhance_seconds, 2),
                "was_enhanced": result.was_enhanced,
                "word_count": len(result.text.split()),
                "text": Sensitive(result.text),
            },
        )
        return result
