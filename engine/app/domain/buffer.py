"""Accumulation of captured audio with a hard ceiling.

The ceiling matters: a hotkey left on by accident would otherwise grow the buffer until the
process runs out of memory. At 16 kHz mono float32, audio costs 64 KB per second, so a ten
minute cap is about 38 MB.
"""

from __future__ import annotations

from app.domain.audio import AudioChunk, AudioFormat, concatenate


class AudioBuffer:
    """Collects chunks into a single recording, refusing to exceed a maximum duration."""

    def __init__(self, audio_format: AudioFormat, max_duration_seconds: float) -> None:
        if max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be positive")

        self._audio_format = audio_format
        self._max_duration_seconds = max_duration_seconds
        self._chunks: list[AudioChunk] = []
        self._frame_count = 0

    @property
    def duration_seconds(self) -> float:
        return self._audio_format.duration_of(self._frame_count)

    @property
    def is_full(self) -> bool:
        return self.duration_seconds >= self._max_duration_seconds

    @property
    def is_empty(self) -> bool:
        return self._frame_count == 0

    def append(self, chunk: AudioChunk) -> bool:
        """Add a chunk. Returns False and discards it once the ceiling is reached."""
        if self.is_full:
            return False

        self._chunks.append(chunk)
        self._frame_count += chunk.frame_count
        return True

    def collect(self) -> AudioChunk:
        """Return everything accumulated so far as one contiguous chunk."""
        return concatenate(self._chunks, self._audio_format)

    def clear(self) -> None:
        self._chunks.clear()
        self._frame_count = 0
