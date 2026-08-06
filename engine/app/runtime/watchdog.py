"""Parent-process watchdog.

If the desktop shell dies, crashes, or is killed from Task Manager, the engine must not
survive it. An orphaned sidecar would keep a microphone handle and a loaded model resident
with no way for the user to see or stop it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import psutil

from app.observability.logging import get_logger

logger = get_logger(__name__)


class ParentWatchdog:
    """Polls a parent process and reports its disappearance exactly once."""

    def __init__(
        self,
        parent_pid: int,
        *,
        poll_seconds: float,
        on_parent_exit: Callable[[str], None],
    ) -> None:
        self._parent_pid = parent_pid
        self._poll_seconds = poll_seconds
        self._on_parent_exit = on_parent_exit

    async def run(self) -> None:
        """Watch until the parent exits, then invoke the callback and return."""
        try:
            parent = psutil.Process(self._parent_pid)
        except psutil.NoSuchProcess:
            self._report("parent process was already gone at startup")
            return

        logger.info("watching parent process", extra={"parent_pid": self._parent_pid})
        while True:
            await asyncio.sleep(self._poll_seconds)
            if not self._is_alive(parent):
                self._report("parent process exited")
                return

    @staticmethod
    def _is_alive(parent: psutil.Process) -> bool:
        """Whether the parent is still running, accounting for PID reuse and zombies."""
        try:
            return parent.is_running() and parent.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def _report(self, reason: str) -> None:
        logger.warning(reason, extra={"parent_pid": self._parent_pid})
        self._on_parent_exit(reason)
