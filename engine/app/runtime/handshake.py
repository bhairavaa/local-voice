"""Startup handshake published to the desktop shell.

The engine binds an ephemeral port and mints a per-session token, then writes a single JSON
line to stdout. The parent process reads that line to learn where to connect and how to
authenticate. Nothing else may ever be written to stdout.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from typing import TextIO

HANDSHAKE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Handshake:
    """Connection details for the engine's HTTP listener."""

    port: int
    token: str
    pid: int
    version: str
    schema_version: int = HANDSHAKE_SCHEMA_VERSION

    def to_json(self) -> str:
        """Serialise to the single-line form the desktop shell parses."""
        return json.dumps(asdict(self), separators=(",", ":"))


def emit(handshake: Handshake, stream: TextIO | None = None) -> None:
    """Write the handshake line and flush, so the parent unblocks immediately."""
    target = stream if stream is not None else sys.stdout
    target.write(handshake.to_json() + "\n")
    target.flush()
