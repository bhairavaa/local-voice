"""The seam between transcription logic and faster-whisper.

Isolating the library behind these protocols means the transcriber -- language selection,
segment assembly, threading, error handling -- is testable without downloading a model or
running inference.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from app.observability.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class RecognisedSegment(Protocol):
    """One timed span returned by the model."""

    @property
    def text(self) -> str: ...

    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...

    @property
    def no_speech_prob(self) -> float: ...


@runtime_checkable
class RecognitionInfo(Protocol):
    """Metadata about the recognition as a whole."""

    @property
    def language(self) -> str: ...

    @property
    def duration(self) -> float: ...


@runtime_checkable
class LoadedModel(Protocol):
    """A model held in memory and ready to transcribe."""

    def transcribe(
        self, audio: NDArray[np.float32], **options: Any
    ) -> tuple[Iterable[RecognisedSegment], RecognitionInfo]: ...


@runtime_checkable
class SpeechBackend(Protocol):
    """Loads models. Kept separate from the model itself so loading can be faked."""

    def load(
        self,
        model: str,
        *,
        device: str,
        compute_type: str,
        cpu_threads: int,
        download_root: Path,
        local_files_only: bool,
    ) -> LoadedModel: ...


class FasterWhisperBackend:
    """The real backend, delegating to faster-whisper."""

    def load(
        self,
        model: str,
        *,
        device: str,
        compute_type: str,
        cpu_threads: int,
        download_root: Path,
        local_files_only: bool,
    ) -> LoadedModel:
        # Imported lazily: faster-whisper pulls in CTranslate2 and tokenizers, which together
        # add noticeable import time that the engine should not pay unless it transcribes.
        from faster_whisper import WhisperModel as FasterWhisperModel

        download_root.mkdir(parents=True, exist_ok=True)

        logger.info(
            "loading speech model",
            extra={
                "model": model,
                "device": device,
                "compute_type": compute_type,
                "cpu_threads": cpu_threads,
                "local_files_only": local_files_only,
            },
        )

        loaded: LoadedModel = FasterWhisperModel(
            model,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            download_root=str(download_root),
            local_files_only=local_files_only,
        )
        return loaded
