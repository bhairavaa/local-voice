"""Command-line entrypoint for the engine sidecar.

Invoked by the desktop shell as a child process. Reads configuration, publishes the startup
handshake on stdout, then serves until the parent exits or shutdown is requested.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app import __version__
from app.bootstrap import create_app
from app.config.settings import CONFIG_FILE_ENV_VAR, Environment, LogLevel, Settings
from app.observability.logging import configure_logging, get_logger
from app.runtime.context import EngineContext
from app.runtime.handshake import emit
from app.runtime.server import TOKEN_BYTES, EngineServer
from app.runtime.services import build_services
from app.runtime.shutdown import ShutdownSignal

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_BIND_ERROR = 3


def _build_parser() -> argparse.ArgumentParser:
    """Define the command-line surface. Every option overrides file and environment values."""
    parser = argparse.ArgumentParser(
        prog="laa-engine",
        description="Local AI Assistant engine sidecar.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, help="Path to a TOML configuration file.")
    parser.add_argument("--host", help="Loopback address to bind.")
    parser.add_argument("--port", type=int, help="Port to bind; 0 selects an ephemeral port.")
    parser.add_argument(
        "--parent-pid",
        type=int,
        help="Process to supervise; the engine exits when it disappears.",
    )
    parser.add_argument("--log-level", choices=[level.value for level in LogLevel])
    parser.add_argument("--log-format", choices=["json", "console"])
    parser.add_argument("--log-file", type=Path, help="Additional rotating log file target.")
    parser.add_argument("--environment", choices=[env.value for env in Environment])
    parser.add_argument(
        "--export-openapi",
        type=Path,
        metavar="PATH",
        help="Write the OpenAPI document to PATH and exit without serving.",
    )
    return parser


def _collect_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Turn supplied arguments into nested settings overrides, omitting absent options."""
    server = _present(host=args.host, port=args.port)
    logging_ = _present(
        level=args.log_level,
        format=args.log_format,
        file=args.log_file,
    )
    runtime = _present(parent_pid=args.parent_pid)

    overrides = _present(
        environment=args.environment,
        server=server or None,
        logging=logging_ or None,
        runtime=runtime or None,
    )
    return overrides


def _present(**values: Any) -> dict[str, Any]:
    """Drop keys whose value was not supplied."""
    return {key: value for key, value in values.items() if value is not None}


def _export_openapi(settings: Settings, destination: Path) -> int:
    """Write the API contract to disk without binding a socket.

    The TypeScript client is generated from this document, so it is committed and checked in
    CI: a schema change that is not regenerated shows up as a diff rather than as a runtime
    mismatch between the two languages.
    """
    context = EngineContext(
        settings=settings,
        auth_token=secrets.token_urlsafe(TOKEN_BYTES),
        version=__version__,
        shutdown=ShutdownSignal(),
        process_id=os.getpid(),
        services=build_services(settings),
    )
    document = create_app(context).openapi()

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return EXIT_OK


def _fail(message: str, code: int) -> int:
    """Report a startup failure on stderr, keeping stdout reserved for the handshake."""
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()
    return code


def main(argv: list[str] | None = None) -> int:
    """Start the engine. Returns the process exit code."""
    args = _build_parser().parse_args(argv)

    if args.config is not None:
        os.environ[CONFIG_FILE_ENV_VAR] = str(args.config)

    try:
        settings = Settings(**_collect_overrides(args))
    except ValidationError as error:
        return _fail(f"Invalid configuration:\n{error}", EXIT_CONFIGURATION_ERROR)

    if args.export_openapi is not None:
        return _export_openapi(settings, args.export_openapi)

    settings.paths.ensure_exist()
    configure_logging(settings.logging)

    server = EngineServer(settings)
    try:
        handshake = server.bind()
    except OSError as error:
        logger.error("failed to bind listening socket", exc_info=error)
        return _fail(f"Could not bind {settings.server.host}: {error}", EXIT_BIND_ERROR)

    emit(handshake)
    server.run()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
