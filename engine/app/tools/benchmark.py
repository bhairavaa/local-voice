"""Measure transcription speed on this machine.

Model choice is the single biggest performance decision in the product, and the right answer
depends on hardware that varies enormously. Rather than guessing from the catalogue's
estimates, this measures the actual cost here.

    uv run laa-benchmark --models tiny.en base.en small.en
    uv run laa-benchmark --audio sample.wav

Downloads weights it does not already have, so the ``load`` column on a model's first run is
mostly download time rather than loading time.

Two caveats on the numbers. Synthetic audio contains no words, so the decoder does almost no
work and the reported speed is optimistic against real speech by roughly a factor of three;
pass ``--audio`` with a recording of your own voice for a true figure. The memory column is a
resident-set delta, which allocator behaviour makes noisy at this scale -- treat it as an
order of magnitude, not a measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import psutil

from app.adapters.audio.wav import read_wav
from app.adapters.speech.catalogue import WhisperModel, profile_for, recommend
from app.adapters.speech.transcriber import (
    WhisperTranscriber,
    resolve_cpu_threads,
    resolve_device,
)
from app.config.settings import Settings, SpeechSettings
from app.domain.audio import WHISPER_SAMPLE_RATE, AudioChunk, AudioFormat
from app.observability.logging import configure_logging

DEFAULT_MODELS = (WhisperModel.TINY_EN, WhisperModel.BASE_EN, WhisperModel.SMALL_EN)
DEFAULT_AUDIO_SECONDS = 15.0
DEFAULT_REPEATS = 3


def _synthetic_speech(seconds: float) -> AudioChunk:
    """Amplitude-modulated harmonics: not words, but a realistic workload for the encoder."""
    audio_format = AudioFormat(WHISPER_SAMPLE_RATE)
    times = np.arange(audio_format.frames_in(seconds), dtype=np.float32) / WHISPER_SAMPLE_RATE

    harmonics = (120.0, 240.0, 480.0, 960.0)
    carrier = sum(
        np.sin(2 * np.pi * frequency * times) / (index + 1)
        for index, frequency in enumerate(harmonics)
    )
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 3.0 * times))
    samples = np.asarray(0.3 * carrier * envelope, dtype=np.float32)

    return AudioChunk(samples, audio_format)


async def _measure(
    model: WhisperModel,
    audio: AudioChunk,
    repeats: int,
    settings: Settings,
    cpu_threads: int = 0,
) -> dict[str, float]:
    # Voice activity filtering is switched off here on purpose. It would skip the quiet parts
    # of the sample and report a speed the model cannot sustain on continuous speech, which is
    # the case that actually matters.
    transcriber = WhisperTranscriber(
        SpeechSettings(model=model, vad_filter=False, cpu_threads=cpu_threads),
        settings.paths,
    )

    process = psutil.Process()
    before_mb = process.memory_info().rss / (1024 * 1024)

    load_started = time.perf_counter()
    await transcriber.warm_up()
    load_seconds = time.perf_counter() - load_started

    durations: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        await transcriber.transcribe(audio)
        durations.append(time.perf_counter() - started)

    after_mb = process.memory_info().rss / (1024 * 1024)

    median = statistics.median(durations)
    return {
        "load_seconds": load_seconds,
        "median_seconds": median,
        "best_seconds": min(durations),
        "realtime_factor": median / audio.duration_seconds,
        "resident_mb": after_mb - before_mb,
    }


def _report(rows: list[tuple[WhisperModel, dict[str, float]]], audio_seconds: float) -> None:
    print()
    print(f"{'model':<12}{'threads':>8}{'median':>9}{'xRT':>8}{'estimate':>10}")
    print("-" * 47)

    for model, result in rows:
        estimated = profile_for(model).realtime_factor
        print(
            f"{model:<12}"
            f"{result['threads']:>8.0f}"
            f"{result['median_seconds']:>8.2f}s"
            f"{result['realtime_factor']:>8.2f}"
            f"{estimated:>10.2f}"
        )

    print()
    print(f"Audio length {audio_seconds:.1f}s. xRT below 1.0 is faster than real time.")

    usable = [(model, result) for model, result in rows if result["realtime_factor"] <= 0.6]
    if usable:
        best = max(usable, key=lambda row: profile_for(row[0]).resident_mb)
        print(f"Most accurate model that stays responsive here: {best[0]}")
    else:
        print("No model measured fast enough for comfortable dictation on this machine.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laa-benchmark",
        description="Measure Whisper transcription speed on this machine.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        type=WhisperModel,
        default=list(DEFAULT_MODELS),
        help="Models to measure.",
    )
    parser.add_argument("--audio", type=Path, help="A 16-bit WAV file to transcribe.")
    parser.add_argument(
        "--seconds",
        type=float,
        default=DEFAULT_AUDIO_SECONDS,
        help="Length of synthetic audio when --audio is not given.",
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument(
        "--threads",
        type=int,
        nargs="+",
        default=[0],
        help="CPU thread counts to compare. 0 uses the automatic value.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    settings.paths.ensure_exist()
    configure_logging(settings.logging)

    audio = read_wav(args.audio) if args.audio else _synthetic_speech(args.seconds)

    memory = psutil.virtual_memory()
    print(f"CPU threads   {resolve_cpu_threads(0)} (of {psutil.cpu_count(logical=True)} logical)")
    print(f"Device        {resolve_device('auto')}")
    print(f"Memory        {memory.available / (1024**3):.1f} GB available")
    print(f"Catalogue says {recommend(memory.available / (1024**2))}")

    rows: list[tuple[WhisperModel, dict[str, float]]] = []
    for model in args.models:
        for threads in args.threads:
            resolved = resolve_cpu_threads(threads)
            label = WhisperModel(model) if len(args.threads) == 1 else model
            print(f"\nMeasuring {model} on {resolved} threads ...", flush=True)
            measured = await _measure(model, audio, args.repeats, settings, threads)
            measured["threads"] = resolved
            rows.append((label, measured))

    _report(rows, audio.duration_seconds)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``laa-benchmark`` command."""
    return asyncio.run(_run(_build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
