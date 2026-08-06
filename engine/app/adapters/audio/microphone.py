"""Microphone capture as an async stream of chunks.

``sounddevice`` delivers audio on its own high-priority thread. That thread must never block,
so the callback does nothing but hand the samples to the event loop and return. Everything
else -- endpointing, buffering, transcription -- happens on the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.adapters.audio.backend import AudioBackend, SoundDeviceBackend
from app.adapters.audio.devices import DeviceRegistry
from app.config.settings import AudioSettings
from app.domain.audio import AudioChunk, AudioFormat
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Sentinel pushed onto the queue when the stream reports an unrecoverable error.
_STREAM_FAILED = object()


class MicrophoneSource:
    """Captures from a microphone, yielding fixed-size mono chunks."""

    def __init__(
        self,
        settings: AudioSettings,
        *,
        backend: AudioBackend | None = None,
        registry: DeviceRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._backend = backend if backend is not None else SoundDeviceBackend()
        self._registry = registry if registry is not None else DeviceRegistry(self._backend)
        self._audio_format = AudioFormat(sample_rate=settings.sample_rate, channels=1)

    @property
    def audio_format(self) -> AudioFormat:
        return self._audio_format

    async def stream(self) -> AsyncGenerator[AudioChunk, None]:
        """Yield captured chunks until the consumer stops iterating.

        Closing the iterator -- by breaking out of the loop or by cancellation -- releases the
        device, so the microphone is never left open.
        """
        device = self._registry.resolve(self._settings.input_device)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[NDArray[np.float32] | object] = asyncio.Queue(
            maxsize=self._settings.queue_capacity_blocks
        )
        dropped = 0

        def on_audio(
            indata: NDArray[np.float32],
            _frames: int,
            _time_info: Any,
            status: Any,
        ) -> None:
            """Runs on the audio thread. Must not block or allocate excessively."""
            nonlocal dropped
            if status:
                logger.warning("audio capture status", extra={"status": str(status)})

            # indata is reused by the backend between callbacks, so it must be copied.
            samples = _to_mono(indata)
            # RuntimeError means the loop closed while the stream was still running; there is
            # nothing useful left to do with the samples in that case.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, samples)

        logger.info(
            "opening microphone",
            extra={
                "device": device.name,
                "device_index": device.index,
                "sample_rate": self._settings.sample_rate,
            },
        )

        stream = self._backend.open_input_stream(
            device=device.index,
            channels=1,
            sample_rate=self._settings.sample_rate,
            block_frames=self._settings.block_frames,
            callback=on_audio,
        )

        with stream:
            stream.start()
            try:
                while True:
                    item = await queue.get()
                    if item is _STREAM_FAILED:
                        return
                    if isinstance(item, np.ndarray):
                        yield AudioChunk(item, self._audio_format)
            finally:
                stream.stop()
                if dropped:
                    logger.warning("dropped audio blocks", extra={"dropped_blocks": dropped})
                logger.info("microphone closed", extra={"device_index": device.index})


def _to_mono(indata: NDArray[np.float32]) -> NDArray[np.float32]:
    """Copy the callback's buffer and collapse any channels to mono."""
    if indata.ndim == 1:
        return np.array(indata, dtype=np.float32, copy=True)
    if indata.shape[1] == 1:
        return np.array(indata[:, 0], dtype=np.float32, copy=True)
    return np.asarray(np.mean(indata, axis=1), dtype=np.float32)
