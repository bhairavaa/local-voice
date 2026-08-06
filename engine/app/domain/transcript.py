"""Transcription results.

Transcribed speech is the most sensitive thing this application handles, so it is wrapped in
:class:`~app.observability.redaction.Sensitive` at the boundary where it is logged rather than
being trusted to every future call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """One timed span of recognised speech."""

    text: str
    start_seconds: float
    end_seconds: float
    no_speech_probability: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class Transcript:
    """The full result of transcribing one recording."""

    text: str
    language: str
    segments: tuple[TranscriptSegment, ...] = field(default=())
    duration_seconds: float = 0.0
    model: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @classmethod
    def empty(cls, language: str = "en", model: str = "") -> Transcript:
        """A result carrying no speech, used when a recording contains only silence."""
        return cls(text="", language=language, model=model)
