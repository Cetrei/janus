from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Callable


def _is_windows() -> bool:
    return sys.platform == "win32"


def install_shutdown_handlers(
    loop: asyncio.AbstractEventLoop, on_signal: Callable[[], None]
) -> None:
    """POSIX: registers SIGTERM and SIGINT via loop.add_signal_handler.
    Windows: registers SIGINT and SIGBREAK via signal.signal and forwards to
    the loop with call_soon_threadsafe (add_signal_handler is POSIX-only)."""
    if _is_windows():
        def _handler(signum, frame):  # noqa: ANN001, ARG001
            loop.call_soon_threadsafe(on_signal)

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGBREAK, _handler)
        return

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, on_signal)


def configure_event_loop() -> None:
    """POSIX: installs uvloop if available. Windows: does not change the
    default policy (grpc.aio compatibility with Windows' Proactor loop is
    an open question tracked in spec-16, validated in CI)."""
    if _is_windows():
        return

    try:
        import uvloop

        uvloop.install()
    except ImportError:
        pass
