"""Speech recognition backed by faster-whisper.

Two things dominate the design:

* **Inference is blocking and CPU-bound.** It runs on a worker thread so the event loop stays
  responsive; a health check must not queue behind a transcription.
* **Loading a model is slow.** It happens once, guarded by a lock so concurrent requests
  cannot start two loads, and the model then stays resident.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import psutil

from app.adapters.speech.backend import (
    FasterWhisperBackend,
    LoadedModel,
    RecognisedSegment,
    SpeechBackend,
)
from app.adapters.speech.catalogue import WhisperModel, profile_for
from app.config.settings import PathSettings, SpeechSettings
from app.domain.audio import WHISPER_SAMPLE_RATE, AudioChunk, resample
from app.domain.transcript import Transcript, TranscriptSegment
from app.observability.logging import get_logger
from app.observability.redaction import Sensitive
from app.runtime.threads import run_detached

logger = get_logger(__name__)

# Oversubscription guard for machines with very high core counts, not a tuning knob. It is
# deliberately far above any measured useful value.
MAX_AUTO_CPU_THREADS = 16


class ModelUnavailableError(RuntimeError):
    """Raised when the model cannot be loaded, typically a missing first-run download."""


def resolve_cpu_threads(configured: int) -> int:
    """Choose a thread count, defaulting to every logical processor.

    This originally capped the automatic value at the physical core count, on the theory that
    extra threads on a hybrid Intel CPU would land on efficiency cores and slow things down.
    Measurement on an i5-1335U showed the reverse, and by a wide margin::

        2 threads  0.54x realtime      6 threads  0.45x
        4 threads  0.51x realtime      8 threads  0.11x

    Nothing above eight gained much, but everything below it cost dearly. Reproduce with
    ``laa-benchmark --threads 2 4 6 8 12``.
    """
    if configured > 0:
        return configured

    logical = psutil.cpu_count(logical=True) or psutil.cpu_count(logical=False)
    if not logical:
        return 1
    return max(1, min(int(logical), MAX_AUTO_CPU_THREADS))


def resolve_device(configured: str) -> str:
    """Resolve ``auto`` to a concrete device.

    CTranslate2 supports CUDA only. There is no Intel or AMD GPU path, so on most laptops this
    correctly resolves to the CPU rather than silently failing later.
    """
    if configured != "auto":
        return configured

    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except (ImportError, AttributeError, RuntimeError):
        logger.debug("could not query CUDA devices; using the CPU")

    return "cpu"


class WhisperTranscriber:
    """Transcribes audio using a locally held Whisper model."""

    def __init__(
        self,
        settings: SpeechSettings,
        paths: PathSettings,
        *,
        backend: SpeechBackend | None = None,
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._backend = backend if backend is not None else FasterWhisperBackend()
        self._model: LoadedModel | None = None
        self._load_lock = asyncio.Lock()

    @property
    def model_name(self) -> WhisperModel:
        return self._settings.model

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def download_root(self) -> Path:
        return self._paths.models_dir / "whisper"

    async def warm_up(self) -> None:
        """Load the model ahead of the first transcription so it does not pay the cost."""
        await self._ensure_loaded()

    async def transcribe(self, audio: AudioChunk) -> Transcript:
        """Transcribe one recording."""
        if audio.is_empty:
            return Transcript.empty(model=str(self._settings.model))

        model = await self._ensure_loaded()
        prepared = resample(audio, WHISPER_SAMPLE_RATE)

        started = time.perf_counter()
        segments, info = await run_detached("whisper-transcribe", self._run, model, prepared)
        elapsed = time.perf_counter() - started

        transcript = _assemble(segments, info, str(self._settings.model))

        logger.info(
            "transcription finished",
            extra={
                "model": str(self._settings.model),
                "audio_seconds": round(prepared.duration_seconds, 2),
                "elapsed_seconds": round(elapsed, 2),
                "realtime_factor": round(elapsed / max(prepared.duration_seconds, 0.001), 2),
                "language": transcript.language,
                "word_count": transcript.word_count,
                "transcript": Sensitive(transcript.text),
            },
        )
        return transcript

    def _run(self, model: LoadedModel, audio: AudioChunk) -> tuple[list[RecognisedSegment], object]:
        """Blocking inference. Runs on a worker thread."""
        segments, info = model.transcribe(
            audio.samples,
            beam_size=self._settings.beam_size,
            language=self._settings.language,
            vad_filter=self._settings.vad_filter,
        )
        # faster-whisper returns a lazy generator; draining it here keeps all the blocking
        # work on this thread rather than leaking it back onto the event loop.
        return list(segments), info

    async def _load(self, *, offline: bool) -> LoadedModel | None:
        """Attempt one load, returning None rather than raising so the caller can fall back.

        Cached weights are always tried offline first. Left to itself the loader contacts
        HuggingFace on every start to check the revision, which cost sixteen seconds of startup
        on a measured run and, more importantly, is an outbound request this product promises
        not to make once it is set up.
        """
        try:
            return await run_detached(
                "whisper-load",
                self._backend.load,
                str(self._settings.model),
                device=resolve_device(self._settings.device),
                compute_type=self._settings.compute_type,
                cpu_threads=resolve_cpu_threads(self._settings.cpu_threads),
                download_root=self.download_root,
                local_files_only=offline,
            )
        except Exception as error:
            if offline:
                logger.debug("speech model is not available offline", extra={"reason": str(error)})
                return None
            logger.error("speech model download failed", extra={"reason": str(error)})
            return None

    async def _ensure_loaded(self) -> LoadedModel:
        # Read into a local each time: another coroutine can load the model while this one
        # waits for the lock, which is exactly what the second check exists to catch.
        loaded = self._model
        if loaded is not None:
            return loaded

        async with self._load_lock:
            loaded = self._model
            if loaded is not None:
                return loaded

            profile = profile_for(self._settings.model)
            logger.info(
                "preparing speech model",
                extra={
                    "model": str(self._settings.model),
                    "download_mb": profile.download_mb,
                    "resident_mb": profile.resident_mb,
                },
            )

            loaded = await self._load(offline=True)
            if loaded is None and self._settings.allow_downloads:
                logger.info(
                    "speech model not found locally; downloading",
                    extra={"model": str(self._settings.model), "download_mb": profile.download_mb},
                )
                loaded = await self._load(offline=False)

            if loaded is None:
                raise ModelUnavailableError(
                    f"could not load speech model {self._settings.model!r}. "
                    f"{'Downloads are disabled; ' if not self._settings.allow_downloads else ''}"
                    f"expected weights under {self.download_root}"
                )

            self._model = loaded
            return loaded


def _assemble(segments: list[RecognisedSegment], info: object, model: str) -> Transcript:
    """Turn the library's output into a domain transcript."""
    collected = tuple(
        TranscriptSegment(
            text=segment.text.strip(),
            start_seconds=float(segment.start),
            end_seconds=float(segment.end),
            no_speech_probability=float(segment.no_speech_prob),
        )
        for segment in segments
    )

    text = " ".join(segment.text for segment in collected if segment.text).strip()

    return Transcript(
        text=text,
        language=str(getattr(info, "language", "") or "en"),
        segments=collected,
        duration_seconds=float(getattr(info, "duration", 0.0) or 0.0),
        model=model,
    )
