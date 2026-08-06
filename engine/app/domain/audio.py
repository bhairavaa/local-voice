"""Audio value objects.

Pure data with no I/O, so the recording logic can be exercised without a microphone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

# Whisper resamples anything else to this rate internally, so capturing here avoids a
# conversion and the quality loss that comes with it.
WHISPER_SAMPLE_RATE = 16_000

Samples = NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """Describes how a block of samples should be interpreted."""

    sample_rate: int
    channels: int = 1

    def duration_of(self, frame_count: int) -> float:
        """Seconds of audio represented by ``frame_count`` frames."""
        return frame_count / self.sample_rate

    def frames_in(self, seconds: float) -> int:
        """Number of frames covering ``seconds`` of audio."""
        return round(seconds * self.sample_rate)


@dataclass(frozen=True, slots=True, eq=False)
class AudioChunk:
    """A contiguous block of mono samples normalised to the range [-1.0, 1.0].

    Equality is disabled because comparing numpy arrays yields an array rather than a bool;
    tests compare the ``samples`` field directly.
    """

    samples: Samples
    audio_format: AudioFormat

    def __post_init__(self) -> None:
        if self.samples.ndim != 1:
            raise ValueError(f"expected mono samples with one dimension, got {self.samples.ndim}")

    @property
    def frame_count(self) -> int:
        return int(self.samples.shape[0])

    @property
    def duration_seconds(self) -> float:
        return self.audio_format.duration_of(self.frame_count)

    @property
    def is_empty(self) -> bool:
        return self.frame_count == 0

    def rms(self) -> float:
        """Root mean square amplitude, the loudness measure used for endpointing."""
        if self.is_empty:
            return 0.0
        return float(np.sqrt(np.mean(np.square(self.samples, dtype=np.float64))))

    def peak(self) -> float:
        """Largest absolute sample, used to detect clipping."""
        if self.is_empty:
            return 0.0
        return float(np.max(np.abs(self.samples)))

    def to_int16(self) -> NDArray[np.int16]:
        """Convert to signed 16-bit PCM, clipping rather than wrapping on overflow."""
        clipped = np.clip(self.samples, -1.0, 1.0)
        return (clipped * np.float32(32767.0)).astype(np.int16)


def concatenate(chunks: list[AudioChunk], audio_format: AudioFormat) -> AudioChunk:
    """Join chunks into one, returning an empty chunk when there is nothing to join."""
    if not chunks:
        return AudioChunk(np.empty(0, dtype=np.float32), audio_format)

    return AudioChunk(np.concatenate([chunk.samples for chunk in chunks]), audio_format)


def resample(chunk: AudioChunk, target_rate: int) -> AudioChunk:
    """Convert a chunk to ``target_rate``.

    An exact integer ratio is handled by averaging groups of samples, which low-pass filters
    as a side effect and so avoids the aliasing that plain decimation would introduce. Other
    ratios fall back to linear interpolation, which is adequate for speech but is why
    capturing at the model's native rate is preferred.
    """
    source_rate = chunk.audio_format.sample_rate
    if source_rate == target_rate or chunk.is_empty:
        return AudioChunk(chunk.samples, AudioFormat(target_rate, chunk.audio_format.channels))

    target_format = AudioFormat(target_rate, chunk.audio_format.channels)

    if source_rate % target_rate == 0:
        ratio = source_rate // target_rate
        usable = (chunk.frame_count // ratio) * ratio
        grouped = chunk.samples[:usable].reshape(-1, ratio)
        return AudioChunk(np.asarray(grouped.mean(axis=1), dtype=np.float32), target_format)

    target_frames = round(chunk.frame_count * target_rate / source_rate)
    source_positions = np.arange(chunk.frame_count, dtype=np.float64)
    target_positions = np.linspace(0, chunk.frame_count - 1, target_frames, dtype=np.float64)
    interpolated = np.interp(target_positions, source_positions, chunk.samples)
    return AudioChunk(np.asarray(interpolated, dtype=np.float32), target_format)


def silence(seconds: float, audio_format: AudioFormat) -> AudioChunk:
    """A silent chunk of the requested duration."""
    return AudioChunk(
        np.zeros(audio_format.frames_in(seconds), dtype=np.float32),
        audio_format,
    )


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """An input device reported by the host audio system."""

    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_default: bool = False

    @property
    def is_usable(self) -> bool:
        return self.max_input_channels > 0
