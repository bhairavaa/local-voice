"""WAV import and export.

Uses the standard library's ``wave`` module: 16-bit PCM is universally readable, and adding a
codec dependency to write a debugging artefact would not be a good trade.

Recordings are only ever written when a developer explicitly asks for them. Nothing in the
normal dictation path writes audio to disk.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from app.domain.audio import AudioChunk, AudioFormat

_BYTES_PER_SAMPLE = 2
_INT16_FULL_SCALE = 32768.0


def write_wav(path: Path, chunk: AudioChunk) -> None:
    """Write a chunk as 16-bit PCM, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(chunk.audio_format.channels)
        handle.setsampwidth(_BYTES_PER_SAMPLE)
        handle.setframerate(chunk.audio_format.sample_rate)
        handle.writeframes(chunk.to_int16().tobytes())


def read_wav(path: Path) -> AudioChunk:
    """Read a 16-bit PCM WAV file, collapsing multiple channels to mono."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != _BYTES_PER_SAMPLE:
            raise ValueError(
                f"expected 16-bit PCM, got {handle.getsampwidth() * 8}-bit audio in {path}"
            )

        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())

    interleaved = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / _INT16_FULL_SCALE
    samples = interleaved if channels == 1 else interleaved.reshape(-1, channels).mean(axis=1)

    return AudioChunk(
        np.asarray(samples, dtype=np.float32),
        AudioFormat(sample_rate=sample_rate, channels=1),
    )
