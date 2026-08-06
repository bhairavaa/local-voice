"""Application factory.

Assembly happens here and nowhere else: routes receive their dependencies through the
:class:`~app.runtime.context.EngineContext` rather than reaching for module-level state.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import require_token
from app.api.routes import dictation, system
from app.config.settings import Environment
from app.observability.logging import get_logger
from app.runtime.context import EngineContext, attach_context, context_of
from app.runtime.services import Services
from app.runtime.watchdog import ParentWatchdog

logger = get_logger(__name__)

API_TITLE = "Local Voice Engine"

BACKGROUND_STOP_TIMEOUT_SECONDS = 2.0

# How long a browser may cache a preflight result. The origins never change during a run, so
# this only avoids repeating the round trip before every request.
PREFLIGHT_CACHE_SECONDS = 600


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run background supervision for as long as the server is serving."""
    context = context_of(app)
    background: list[asyncio.Task[None]] = []

    parent_pid = context.settings.runtime.parent_pid
    if parent_pid is not None:
        watchdog = ParentWatchdog(
            parent_pid,
            poll_seconds=context.settings.runtime.parent_poll_seconds,
            on_parent_exit=context.shutdown.request,
        )
        background.append(asyncio.create_task(watchdog.run(), name="parent-watchdog"))

    if context.settings.speech.warm_up_on_start:
        # Loading takes seconds. Doing it now means the first dictation does not pay for it,
        # and a missing model surfaces at startup rather than mid-sentence.
        background.append(asyncio.create_task(_warm_up(context.services), name="speech-warm-up"))

    logger.info(
        "engine ready",
        extra={"version": context.version, "environment": context.settings.environment.value},
    )
    try:
        yield
    finally:
        for task in background:
            task.cancel()
        if background:
            # Bounded, so a task blocked in native code cannot hold the process open. The
            # threads behind them are daemons and die with the process.
            await asyncio.wait(background, timeout=BACKGROUND_STOP_TIMEOUT_SECONDS)
        await context.services.aclose()
        logger.info("engine stopped")


async def _warm_up(services: Services) -> None:
    """Load the speech model, reporting rather than raising if it is unavailable."""
    try:
        await services.transcriber.warm_up()
    except Exception as error:
        # A failed warm-up must not stop the engine serving; the first dictation will retry
        # and report the failure to the user directly.
        logger.warning("speech model warm-up failed", extra={"reason": str(error)})


def create_app(context: EngineContext) -> FastAPI:
    """Build the ASGI application for a fully assembled engine context."""
    is_development = context.settings.environment is Environment.DEVELOPMENT

    app = FastAPI(
        title=API_TITLE,
        version=context.version,
        lifespan=_lifespan,
        docs_url="/docs" if is_development else None,
        redoc_url=None,
    )
    attach_context(app, context)

    # The interface and the engine are separate origins, so the browser preflights any request
    # carrying an Authorization header. Only the webview's own origins are named; the token
    # remains the thing that actually authorises a request, since CORS binds browsers only.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(context.settings.server.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=PREFLIGHT_CACHE_SECONDS,
    )

    # Applied at the router level so a new endpoint cannot be added without authentication.
    authenticated = [Depends(require_token)]
    app.include_router(system.router, dependencies=authenticated)
    app.include_router(dictation.router, dependencies=authenticated)
    return app
