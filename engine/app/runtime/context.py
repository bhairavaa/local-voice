"""Composition root state shared with request handlers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from fastapi import FastAPI

from app.config.settings import Settings
from app.runtime.services import Services
from app.runtime.shutdown import ShutdownSignal


@dataclass(frozen=True, slots=True)
class EngineContext:
    """Dependencies assembled at startup and injected into the HTTP layer."""

    settings: Settings
    auth_token: str
    version: str
    shutdown: ShutdownSignal
    process_id: int
    services: Services
    started_at: float = field(default_factory=time.monotonic)

    def uptime_seconds(self) -> float:
        """Seconds elapsed since the engine finished assembling its dependencies."""
        return time.monotonic() - self.started_at


def attach_context(app: FastAPI, context: EngineContext) -> None:
    """Store the context on the application so handlers can retrieve it."""
    app.state.context = context


def context_of(app: FastAPI) -> EngineContext:
    """Retrieve the context, failing loudly if the application was not assembled."""
    context = getattr(app.state, "context", None)
    if not isinstance(context, EngineContext):
        raise RuntimeError("engine context is missing from application state")
    return context
