"""Endpointing: deciding when the speaker has finished.

This is a root-mean-square energy detector, not a trained voice activity model. That is a
deliberate choice for version 1: no extra dependency, no model download, no per-chunk
inference cost, and it is accurate enough for dictation where the user is close to the
microphone and deliberately stops speaking.

A naive energy gate fails in a real room, and did: a fixed threshold on a quiet laptop
microphone let intermittent background noise reset the silence timer, so a two second
utterance produced a twenty-eight second recording. Two mechanisms address that, and both
exist because of that measurement rather than in anticipation of it:

* **A calibrated noise floor.** The first fraction of a second measures the room and the
  threshold is set above it, so the gate adapts to the environment instead of assuming one.
* **Confirmation over consecutive blocks.** A single loud block is a door or a keystroke, not
  speech, and is treated as silence. Sustained energy is speech.

When this stops being good enough, replacing it means writing another class with the same
``observe`` method.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum

from app.domain.audio import AudioChunk


class SpeechState(Enum):
    """Where the utterance has got to."""

    WAITING = "waiting"
    """No speech heard yet. Includes the initial noise-floor measurement."""

    SPEAKING = "speaking"
    """Speech is in progress."""

    ENDED = "ended"
    """Speech was heard and has now been followed by enough silence."""


@dataclass(frozen=True, slots=True)
class VadThresholds:
    """Tuning for :class:`SilenceDetector`.

    The adaptive fields default to values that disable adaptation, so the detector can be
    reasoned about and tested as a plain fixed-threshold gate. Production configuration turns
    them on; see :func:`app.pipeline.recording.thresholds_from`.
    """

    activation_rms: float
    """Loudness above which a chunk counts as speech, and the floor for the calibrated value."""

    silence_seconds: float
    """Trailing silence that ends an utterance."""

    minimum_speech_seconds: float
    """Speech required before silence can end it, so a cough does not stop recording."""

    calibration_seconds: float = 0.0
    """Audio measured at the start to establish the room's noise floor. 0 disables it."""

    noise_multiplier: float = 3.0
    """How far above the measured noise floor the threshold sits."""

    max_activation_boost: float = 8.0
    """Ceiling on the calibrated threshold, as a multiple of ``activation_rms``.

    Protects against the user starting to speak during calibration, which would otherwise
    measure their voice as the noise floor and leave the gate deaf.
    """

    confirm_blocks: int = 1
    """Consecutive blocks above the threshold needed to *start* speech."""

    release_ratio: float = 0.5
    """Threshold for *continuing* speech, as a fraction of the activation threshold.

    Speech is not a steady tone. Across 30 millisecond blocks its energy swings widely between
    vowels, plosives and the gaps within a word. Holding it to the entry threshold made those
    dips count as silence and, because confirmation then had to be earned again from scratch,
    silence could accumulate past the limit and end a recording mid-sentence.

    So the gate is strict to open and forgiving to stay open, which is the standard shape for
    this and the reason a lone noise blip still cannot hold a recording alive.
    """


class SilenceDetector:
    """Tracks whether the speaker is still talking.

    Feed every captured chunk to :meth:`observe`. The returned state is monotonic: once
    ``ENDED`` is reached it stays there until :meth:`reset` is called.
    """

    def __init__(self, thresholds: VadThresholds) -> None:
        self._thresholds = thresholds
        self._state = SpeechState.WAITING
        self._speech_seconds = 0.0
        self._trailing_silence_seconds = 0.0
        self._consecutive_loud = 0
        self._pending_loud_seconds = 0.0
        self._calibration_seconds = 0.0
        self._calibration_samples: list[float] = []
        self._threshold = thresholds.activation_rms

    @property
    def state(self) -> SpeechState:
        return self._state

    @property
    def speech_seconds(self) -> float:
        """Total duration judged to be speech."""
        return self._speech_seconds

    @property
    def threshold(self) -> float:
        """The activation threshold currently in force, after any calibration."""
        return self._threshold

    @property
    def is_calibrating(self) -> bool:
        return self._calibration_seconds < self._thresholds.calibration_seconds

    def reset(self) -> None:
        """Return to the initial state, ready for another utterance."""
        self._state = SpeechState.WAITING
        self._speech_seconds = 0.0
        self._trailing_silence_seconds = 0.0
        self._consecutive_loud = 0
        self._pending_loud_seconds = 0.0
        self._calibration_seconds = 0.0
        self._calibration_samples.clear()
        self._threshold = self._thresholds.activation_rms

    def observe(self, chunk: AudioChunk) -> SpeechState:
        """Update the state with one chunk and return the state after it."""
        if self._state is SpeechState.ENDED:
            return self._state

        duration = chunk.duration_seconds
        loudness = chunk.rms()

        # The fields are compared directly rather than through ``is_calibrating``: appending
        # here is what ends calibration, and a type checker cannot see a property change value
        # partway through a block.
        target = self._thresholds.calibration_seconds
        if self._calibration_seconds < target:
            self._calibration_samples.append(loudness)
            self._calibration_seconds += duration
            if self._calibration_seconds >= target:
                self._threshold = self._calibrated_threshold()
            return self._state

        # Once speaking, the bar drops so the dips within a word still register as speech. The
        # sustained requirement stays: relaxing that as well would let a single loud blip hold
        # a finished recording open indefinitely.
        speaking = self._state is SpeechState.SPEAKING
        threshold = (
            self._threshold * self._thresholds.release_ratio if speaking else self._threshold
        )

        if loudness >= threshold:
            return self._observe_loud(duration)

        return self._observe_quiet(duration)

    def _observe_loud(self, duration: float) -> SpeechState:
        """Hold a loud block pending until it is known to be speech or noise.

        Pending blocks are deliberately not counted as silence yet. Counting them immediately
        would let the confirmation delay push a mid-sentence pause over the silence threshold,
        ending the utterance just as the speaker resumed.
        """
        self._consecutive_loud += 1
        self._pending_loud_seconds += duration

        if self._consecutive_loud >= self._thresholds.confirm_blocks:
            self._speech_seconds += self._pending_loud_seconds
            self._pending_loud_seconds = 0.0
            self._trailing_silence_seconds = 0.0
            self._state = SpeechState.SPEAKING

        return self._state

    def _observe_quiet(self, duration: float) -> SpeechState:
        """A quiet block settles any pending run as noise, then extends the silence."""
        self._trailing_silence_seconds += self._pending_loud_seconds + duration
        self._pending_loud_seconds = 0.0
        self._consecutive_loud = 0

        if (
            self._state is SpeechState.SPEAKING
            and self._trailing_silence_seconds >= self._thresholds.silence_seconds
            and self._speech_seconds >= self._thresholds.minimum_speech_seconds
        ):
            self._state = SpeechState.ENDED

        return self._state

    def _calibrated_threshold(self) -> float:
        """Set the gate above the measured noise floor, within configured bounds.

        The median is used rather than the mean so one loud block during calibration cannot
        drag the floor up.
        """
        if not self._calibration_samples:
            return self._thresholds.activation_rms

        noise_floor = statistics.median(self._calibration_samples)
        adapted = noise_floor * self._thresholds.noise_multiplier
        ceiling = self._thresholds.activation_rms * self._thresholds.max_activation_boost

        return min(max(adapted, self._thresholds.activation_rms), ceiling)
