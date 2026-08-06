"""Cooperative shutdown signalling.

This is the seam that lets the parent-process watchdog stop the HTTP server without the
two holding references to each other.
"""

from __future__ import annotations

import asyncio


class ShutdownSignal:
    """A one-shot, awaitable request to stop the engine."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason = ""

    def request(self, reason: str) -> None:
        """Ask the engine to stop. Subsequent calls are ignored."""
        if self._event.is_set():
            return
        self._reason = reason
        self._event.set()

    async def wait(self) -> str:
        """Block until shutdown is requested, then return the recorded reason."""
        await self._event.wait()
        return self._reason

    @property
    def requested(self) -> bool:
        """Whether shutdown has already been requested."""
        return self._event.is_set()
