"""Dictate from the terminal.

The whole pipeline without the desktop shell: speak, and the text is printed. Useful for
trying the engine before the Tauri application is built, and for checking a model change
against your own voice rather than against a benchmark.

    uv run laa-dictate
    uv run laa-dictate --model small.en --enhance --profile email

The transcript goes to stdout and nothing else does, so it can be piped:

    uv run laa-dictate | clip
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from app.adapters.speech.catalogue import WhisperModel, profile_for
from app.config.settings import Settings
from app.observability.logging import configure_logging
from app.pipeline.dictation import DictationResult
from app.runtime.services import build_services

EXIT_OK = 0
EXIT_NO_SPEECH = 1
EXIT_FAILED = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laa-dictate",
        description="Record from the microphone and print the transcribed text.",
    )
    parser.add_argument("--model", type=WhisperModel, help="Whisper model to use.")
    parser.add_argument("--device", type=int, help="Input device index.")
    parser.add_argument(
        "--enhance",
        action="store_true",
        help="Clean up the transcript with the local text model (requires Ollama).",
    )
    parser.add_argument("--profile", default="general", help="Cleanup profile.")
    parser.add_argument(
        "--silence",
        type=float,
        help="Seconds of silence that end the recording.",
    )
    parser.add_argument("--raw", action="store_true", help="Print the transcript before cleanup.")
    parser.add_argument("--quiet", action="store_true", help="Print only the text.")
    return parser


def _settings_from(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}

    speech: dict[str, Any] = {}
    if args.model is not None:
        speech["model"] = args.model
    if speech:
        overrides["speech"] = speech

    audio: dict[str, Any] = {}
    if args.device is not None:
        audio["input_device"] = args.device
    if args.silence is not None:
        audio["silence_seconds"] = args.silence
    if audio:
        overrides["audio"] = audio

    if args.enhance:
        overrides["enhancement"] = {"enabled": True, "profile": args.profile}

    return Settings(**overrides)


def _note(message: str, *, quiet: bool) -> None:
    """Progress goes to stderr so stdout carries only the transcript."""
    if not quiet:
        print(message, file=sys.stderr, flush=True)


async def _run(args: argparse.Namespace) -> int:
    settings = _settings_from(args)
    settings.paths.ensure_exist()
    configure_logging(settings.logging)

    services = build_services(settings)
    try:
        profile = profile_for(settings.speech.model)
        _note(
            f"Loading {settings.speech.model} ({profile.download_mb} MB on first run) ...",
            quiet=args.quiet,
        )
        await services.transcriber.warm_up()

        _note("Speak now. Recording stops after a pause.", quiet=args.quiet)
        result = await services.dictation.dictate_until_silence(args.profile)
    finally:
        await services.aclose()

    return _report(result, args)


def _report(result: DictationResult, args: argparse.Namespace) -> int:
    if result.is_empty:
        _note("No speech detected.", quiet=args.quiet)
        return EXIT_NO_SPEECH

    if args.raw and result.was_enhanced:
        _note(f"Raw: {result.raw_text}", quiet=args.quiet)

    print(result.text)

    if result.enhancement_error:
        _note(f"Cleanup skipped: {result.enhancement_error}", quiet=args.quiet)

    _note(
        f"\n{result.audio_seconds:.1f}s audio, "
        f"transcribed in {result.transcribe_seconds:.1f}s "
        f"({result.transcribe_seconds / max(result.audio_seconds, 0.01):.2f}x realtime)",
        quiet=args.quiet,
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``laa-dictate`` command."""
    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        _note("\nCancelled.", quiet=args.quiet)
        return EXIT_OK
    except Exception as error:
        print(f"Dictation failed: {error}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
