"""What each Whisper model costs, and which one a machine can afford.

**This product transcribes English only.** Only the ``.en`` model variants are offered: at any
given size they are both smaller and more accurate than the multilingual model, because none
of their capacity is spent on other languages. Multilingual models and ``large-v3`` (which has
no English-only variant) are deliberately absent rather than being options that would only
ever be the wrong choice.

The figures are for ``int8`` quantisation, the only sensible compute type on a CPU without
AVX-512. They exist to stop the application choosing a model that will not fit, not to be
exact. Use ``laa-benchmark`` to measure a specific machine.

The realtime factors are indicative, not precise. They are anchored to one measurement of real
dictation on an i5-1335U -- ``small.en`` at 0.52x on four threads -- adjusted for the roughly
fivefold speed-up that came from raising the thread count, and scaled across the range by model
size.

Treat them as ordering rather than prediction. Synthetic benchmark runs of the same
configuration have varied by a factor of four between sessions depending on machine load and
free memory, so no fixed table can be trusted on a given machine. ``laa-benchmark`` is the
answer to "how fast is this here", and ``--audio`` with a real recording is the honest form of
that question.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WhisperModel(StrEnum):
    """English-only Whisper models, smallest first."""

    TINY_EN = "tiny.en"
    BASE_EN = "base.en"
    SMALL_EN = "small.en"
    MEDIUM_EN = "medium.en"


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """The cost of running one model."""

    model: WhisperModel
    download_mb: int
    """Approximate size of the weights fetched on first use."""

    resident_mb: int
    """Approximate resident memory once loaded, at int8."""

    realtime_factor: float
    """Seconds of processing per second of audio on a modern laptop CPU. Lower is faster."""


_PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(WhisperModel.TINY_EN, download_mb=75, resident_mb=130, realtime_factor=0.03),
    ModelProfile(WhisperModel.BASE_EN, download_mb=145, resident_mb=220, realtime_factor=0.05),
    ModelProfile(WhisperModel.SMALL_EN, download_mb=480, resident_mb=600, realtime_factor=0.14),
    ModelProfile(WhisperModel.MEDIUM_EN, download_mb=1530, resident_mb=1800, realtime_factor=0.45),
)

CATALOGUE: dict[WhisperModel, ModelProfile] = {profile.model: profile for profile in _PROFILES}

# Transcription slower than this feels broken for dictation: a 30 second thought would take
# longer than 18 seconds to come back.
USABLE_REALTIME_FACTOR = 0.6

# Headroom left for the operating system, the desktop shell, and any text model.
MEMORY_RESERVE_MB = 1500


def profile_for(model: WhisperModel) -> ModelProfile:
    """Cost profile for a model."""
    return CATALOGUE[model]


def affordable_models(available_memory_mb: float) -> list[ModelProfile]:
    """Models that fit in memory and are fast enough to be usable, most accurate first."""
    budget = available_memory_mb - MEMORY_RESERVE_MB

    candidates = [
        profile
        for profile in _PROFILES
        if profile.resident_mb <= budget and profile.realtime_factor <= USABLE_REALTIME_FACTOR
    ]
    return sorted(candidates, key=lambda profile: profile.resident_mb, reverse=True)


def recommend(available_memory_mb: float) -> WhisperModel:
    """The most accurate model this machine can run acceptably.

    Falls back to the smallest model rather than failing: a fast, less accurate transcript is
    more useful than none.
    """
    affordable = affordable_models(available_memory_mb)
    return affordable[0].model if affordable else WhisperModel.TINY_EN
