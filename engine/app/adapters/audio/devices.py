"""Enumeration and selection of audio input devices."""

from __future__ import annotations

from typing import Any

from app.adapters.audio.backend import AudioBackend, SoundDeviceBackend
from app.domain.audio import AudioDevice
from app.observability.logging import get_logger

logger = get_logger(__name__)


class NoInputDeviceError(RuntimeError):
    """Raised when no usable microphone exists, or the configured one is unavailable."""


class DeviceRegistry:
    """Reports which microphones exist and resolves the one to record from."""

    def __init__(self, backend: AudioBackend | None = None) -> None:
        self._backend = backend if backend is not None else SoundDeviceBackend()

    def input_devices(self) -> list[AudioDevice]:
        """Every device capable of capturing audio, in host index order."""
        default_index = self._backend.default_input_index()

        devices = [
            _to_device(index, record, is_default=index == default_index)
            for index, record in enumerate(self._backend.query_devices())
        ]
        return [device for device in devices if device.is_usable]

    def resolve(self, index: int | None) -> AudioDevice:
        """Return the requested device, or the system default when ``index`` is None.

        A configured device that has since been unplugged is an error rather than a silent
        fallback: recording from an unexpected microphone is worse than refusing to start.
        """
        available = self.input_devices()
        if not available:
            raise NoInputDeviceError(
                "no audio input device is available; connect a microphone and try again"
            )

        if index is None:
            return next(
                (device for device in available if device.is_default),
                available[0],
            )

        for device in available:
            if device.index == index:
                return device

        known = ", ".join(f"{device.index}: {device.name}" for device in available)
        raise NoInputDeviceError(
            f"configured input device {index} is not available. Available devices: {known}"
        )


def _to_device(index: int, record: dict[str, Any], *, is_default: bool) -> AudioDevice:
    return AudioDevice(
        index=index,
        name=str(record.get("name", f"device {index}")),
        max_input_channels=int(record.get("max_input_channels", 0)),
        default_sample_rate=float(record.get("default_samplerate", 0.0)),
        is_default=is_default,
    )
