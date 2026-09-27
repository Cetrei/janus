from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType

from janus_platform.errors import LockHeld


def _is_windows() -> bool:
    return sys.platform == "win32"


class InstanceLock:
    """Non-blocking exclusive lock on a file, used as a context manager.
    POSIX: fcntl.flock. Windows: msvcrt.locking.
    Raises LockHeld (with the owner's pid if readable) if already taken."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._fh = None

    def __enter__(self) -> "InstanceLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a+")  # noqa: SIM115 - kept open for the lock's lifetime

        try:
            if _is_windows():
                self._lock_windows()
            else:
                self._lock_posix()
        except (OSError, BlockingIOError) as exc:
            owner_pid = self._read_owner_pid()
            self._fh.close()
            self._fh = None
            raise LockHeld(self._path, owner_pid) from exc

        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(str(os.getpid()))
        self._fh.flush()
        return self

    def _lock_posix(self) -> None:
        import fcntl

        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _lock_windows(self) -> None:
        import msvcrt

        self._fh.seek(0)
        msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _read_owner_pid(self) -> int | None:
        try:
            content = self._path.read_text().strip()
            return int(content) if content else None
        except (OSError, ValueError):
            return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fh is None:
            return
        try:
            if _is_windows():
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None
