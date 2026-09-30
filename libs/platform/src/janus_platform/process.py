from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import IO


def _is_windows() -> bool:
    return sys.platform == "win32"


class ProcessHandle:
    """Wraps a subprocess.Popen. wait() runs the blocking wait in a thread
    (asyncio.to_thread) so callers never depend on which event loop kind is
    active — this is the reason spawn/ProcessHandle exist at all: on Windows
    asyncio.create_subprocess_exec requires the Proactor loop, and grpc.aio
    is not verified against it, so everything goes through Popen instead."""

    def __init__(self, popen: subprocess.Popen) -> None:
        self._popen = popen

    @property
    def pid(self) -> int:
        return self._popen.pid

    @property
    def stdin(self) -> IO[bytes] | None:
        """The child's stdin pipe, or None unless spawn() was given
        stdin=subprocess.PIPE. Exposed so callers that stream data into a
        child (raw video frames into ffmpeg) never reach into _popen."""
        return self._popen.stdin

    def poll(self) -> int | None:
        return self._popen.poll()

    def kill(self) -> None:
        """Synchronous hard kill of the process itself, for sync callers that
        cannot await terminate(). A no-op if it already exited."""
        if self._popen.poll() is None:
            self._popen.kill()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._popen.wait)

    async def terminate(self, grace_s: float = 5.0) -> None:
        """Attempts a soft terminate, waits grace_s, then force-kills the
        whole process tree (via psutil if installed; without it, os.killpg
        on POSIX and taskkill /T /F on Windows)."""
        if self._popen.poll() is not None:
            return

        if _is_windows():
            self._popen.terminate()
        else:
            os.killpg(os.getpgid(self._popen.pid), signal.SIGTERM)

        try:
            await asyncio.wait_for(self.wait(), timeout=grace_s)
            return
        except TimeoutError:
            pass

        await self._force_kill()

    async def _force_kill(self) -> None:
        try:
            import psutil

            try:
                proc = psutil.Process(self._popen.pid)
                children = proc.children(recursive=True)
                for child in children:
                    child.kill()
                proc.kill()
            except psutil.NoSuchProcess:
                pass
            return
        except ImportError:
            pass

        if _is_windows():
            subprocess.run(
                ["taskkill", "/PID", str(self._popen.pid), "/T", "/F"],
                shell=False,
                capture_output=True,
            )
        else:
            try:
                os.killpg(os.getpgid(self._popen.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


def spawn(
    argv: list[str],
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    new_session: bool = True,
    stdin: int | None = None,
) -> ProcessHandle:
    """Launches via subprocess.Popen(shell=False). Never accepts a command
    string, only an argument list. POSIX: start_new_session. Windows:
    CREATE_NEW_PROCESS_GROUP. Pass stdin=subprocess.PIPE to get a writable
    ProcessHandle.stdin; the default leaves stdin inherited, as before."""
    if isinstance(argv, str):
        raise TypeError("spawn() requires a list of arguments, never a command string")

    kwargs: dict = {
        "shell": False,
        "env": env,
        "cwd": str(cwd) if cwd else None,
        "stdin": stdin,
    }

    if new_session:
        if _is_windows():
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

    popen = subprocess.Popen(argv, **kwargs)  # noqa: S603
    return ProcessHandle(popen)
