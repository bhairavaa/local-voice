"""Ports: the interfaces the pipeline depends on.

Every port is an async iterator or an async method even where the first implementation is
synchronous and batch. Streaming transcription can then be added as a second adapter rather
than as a change to these signatures.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol, runtime_checkable

from app.domain.audio import AudioChunk, AudioDevice
from app.domain.transcript import Transcript


@runtime_checkable
class AudioSource(Protocol):
    """A source of captured audio, such as a microphone or a file.

    The return type is a generator rather than a plain iterator because the consumer must be
    able to close it: that is what releases the microphone. Being able to stop the source is
    part of the contract, not an implementation detail.
    """

    def stream(self) -> AsyncGenerator[AudioChunk, None]:
        """Yield chunks until the source is exhausted or the consumer stops iterating."""
        ...


@runtime_checkable
class DeviceCatalogue(Protocol):
    """Enumeration of the machine's audio input devices."""

    def input_devices(self) -> list[AudioDevice]: ...

    def resolve(self, index: int | None) -> AudioDevice:
        """Return the requested device, or the system default when ``index`` is None."""
        ...


@runtime_checkable
class Transcriber(Protocol):
    """Converts audio into text."""

    async def transcribe(self, audio: AudioChunk) -> Transcript: ...

    async def warm_up(self) -> None:
        """Prepare the model so the first transcription does not pay the loading cost."""
        ...

    @property
    def is_loaded(self) -> bool:
        """Whether the model is resident and ready. Reported to the interface."""
        ...


@runtime_checkable
class TextEnhancer(Protocol):
    """Improves punctuation, casing, and grammar without changing meaning."""

    async def enhance(self, text: str, profile: str) -> str: ...

    async def is_available(self) -> bool:
        """Whether the backing model can currently be reached."""
        ...
