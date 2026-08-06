"""Running blocking work without tying the process to it.

``asyncio.to_thread`` uses the default executor, whose threads are not daemons: the
interpreter joins them on the way out. Loading a speech model can take tens of seconds, and
downloading one on first run takes minutes, so a shell that closed during a load would leave
the engine alive until the download finished.

Cancelling the awaiting task here abandons the thread rather than waiting for it. That is the
right trade for this process: the work is idempotent, it holds no resource that outlives the
process, and the alternative is an engine that ignores its parent going away.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable


def _dispatch[T](loop: asyncio.AbstractEventLoop, callback: Callable[[T], None], value: T) -> None:
    """Hand a value back to the event loop, tolerating a loop that has already closed."""
    # RuntimeError here means the loop shut down while the thread was still working. The
    # result has nowhere to go and is safely discarded.
    with contextlib.suppress(RuntimeError):
        loop.call_soon_threadsafe(callback, value)


async def run_detached[**P, R](
    name: str,
    func: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """Run ``func`` on a daemon thread and await its result."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[R] = loop.create_future()

    def deliver_result(value: R) -> None:
        if not future.done():
            future.set_result(value)

    def deliver_error(error: BaseException) -> None:
        if not future.done():
            future.set_exception(error)

    def runner() -> None:
        try:
            result = func(*args, **kwargs)
        except BaseException as error:
            _dispatch(loop, deliver_error, error)
        else:
            _dispatch(loop, deliver_result, result)

    threading.Thread(target=runner, name=name, daemon=True).start()
    return await future
