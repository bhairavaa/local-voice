"""Wrapper marking values that must not reach logs.

Transcribed speech is the most sensitive data this application handles. Wrapping it makes
leaking it require a deliberate ``reveal()`` call: the string forms render as a redaction
marker, so an accidental f-string or ``%s`` interpolation is safe by default.
"""

from __future__ import annotations

REDACTED = "<redacted>"


class Sensitive[T]:
    """A value that logging must redact unless policy explicitly permits disclosure."""

    __slots__ = ("_value",)

    def __init__(self, value: T) -> None:
        self._value = value

    def reveal(self) -> T:
        """Return the underlying value. Call only where disclosure is intended."""
        return self._value

    def __str__(self) -> str:
        return REDACTED

    def __repr__(self) -> str:
        return REDACTED

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sensitive):
            return bool(self._value == other._value)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)
