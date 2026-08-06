"""The seam between capture logic and the host audio system.

``sounddevice`` is the only module here that touches hardware. Isolating it behind these two
protocols means the recording logic, the endpointing, and the pipeline can all be tested with
synthetic audio on a machine with no microphone -- including in CI.
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

CaptureCallback = Callable[[NDArray[np.float32], int, Any, Any], None]


@runtime_checkable
class InputStreamHandle(Protocol):
    """An open capture stream."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def __enter__(self) -> InputStreamHandle: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


@runtime_checkable
class AudioBackend(Protocol):
    """The host audio system."""

    def query_devices(self) -> list[dict[str, Any]]:
        """Return one record per device, in host index order."""
        ...

    def default_input_index(self) -> int | None:
        """Index of the system default input device, if there is one."""
        ...

    def open_input_stream(
        self,
        *,
        device: int | None,
        channels: int,
        sample_rate: int,
        block_frames: int,
        callback: CaptureCallback,
    ) -> InputStreamHandle: ...


class SoundDeviceBackend:
    """The real backend, delegating to ``sounddevice``."""

    def query_devices(self) -> list[dict[str, Any]]:
        import sounddevice

        return [dict(device) for device in sounddevice.query_devices()]

    def default_input_index(self) -> int | None:
        import sounddevice

        default = sounddevice.default.device
        index = default[0] if isinstance(default, (list, tuple)) else default
        return int(index) if isinstance(index, (int, np.integer)) and int(index) >= 0 else None

    def open_input_stream(
        self,
        *,
        device: int | None,
        channels: int,
        sample_rate: int,
        block_frames: int,
        callback: CaptureCallback,
    ) -> InputStreamHandle:
        import sounddevice

        stream: InputStreamHandle = sounddevice.InputStream(
            device=device,
            channels=channels,
            samplerate=sample_rate,
            blocksize=block_frames,
            dtype="float32",
            callback=callback,
        )
        return stream
