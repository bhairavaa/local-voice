"""HTTP server lifecycle: socket binding, serving, and cooperative shutdown.

The socket is bound before uvicorn starts so the ephemeral port is known in time to be
published in the handshake. The parent therefore never has to poll or guess.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import socket

import uvicorn

from app import __version__
from app.bootstrap import create_app
from app.config.settings import Environment, Settings
from app.observability.logging import get_logger
from app.runtime.context import EngineContext
from app.runtime.handshake import Handshake
from app.runtime.services import build_services
from app.runtime.shutdown import ShutdownSignal

logger = get_logger(__name__)

TOKEN_BYTES = 32
LISTEN_BACKLOG = 16


class EngineServer:
    """Owns the listening socket and the uvicorn instance serving on it."""

    def __init__(self, settings: Settings, *, auth_token: str | None = None) -> None:
        self._settings = settings
        self._shutdown = ShutdownSignal()
        self._context = EngineContext(
            settings=settings,
            auth_token=auth_token or secrets.token_urlsafe(TOKEN_BYTES),
            version=__version__,
            shutdown=self._shutdown,
            process_id=os.getpid(),
            services=build_services(settings),
        )
        self._app = create_app(self._context)
        self._socket: socket.socket | None = None

    @property
    def context(self) -> EngineContext:
        """The assembled dependencies backing this server."""
        return self._context

    def bind(self) -> Handshake:
        """Reserve the listening socket and return the details the shell needs."""
        if self._socket is not None:
            raise RuntimeError("bind() has already been called")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((self._settings.server.host, self._settings.server.port))
            sock.listen(LISTEN_BACKLOG)
        except OSError:
            sock.close()
            raise

        self._socket = sock
        bound_port = int(sock.getsockname()[1])
        logger.info(
            "engine bound",
            extra={"host": self._settings.server.host, "port": bound_port},
        )
        return Handshake(
            port=bound_port,
            token=self._context.auth_token,
            pid=self._context.process_id,
            version=__version__,
        )

    def close(self) -> None:
        """Release the listening socket without serving. Safe to call repeatedly."""
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def __enter__(self) -> EngineServer:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def run(self) -> None:
        """Serve until shutdown is requested. Blocks the calling thread."""
        sock = self._socket
        if sock is None:
            raise RuntimeError("bind() must be called before run()")

        config = uvicorn.Config(
            self._app,
            log_config=None,
            access_log=self._settings.environment is Environment.DEVELOPMENT,
            timeout_graceful_shutdown=int(self._settings.runtime.shutdown_grace_seconds),
        )
        server = uvicorn.Server(config)
        try:
            asyncio.run(self._serve(server, sock))
        finally:
            sock.close()
            self._socket = None

    async def _serve(self, server: uvicorn.Server, sock: socket.socket) -> None:
        supervisor = asyncio.create_task(self._await_shutdown(server), name="shutdown-supervisor")
        try:
            await server.serve(sockets=[sock])
        finally:
            supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await supervisor

    async def _await_shutdown(self, server: uvicorn.Server) -> None:
        reason = await self._shutdown.wait()
        logger.info("shutdown requested", extra={"reason": reason})
        server.should_exit = True
