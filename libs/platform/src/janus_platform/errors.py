from __future__ import annotations


class PlatformError(Exception):
    """Base class for all janus_platform errors."""


class LockHeld(PlatformError):
    """Raised by InstanceLock when the lock is already held by another process."""

    def __init__(self, path, owner_pid: int | None = None) -> None:
        message = f"Lock already held: {path}"
        if owner_pid is not None:
            message += f" (owner pid={owner_pid})"
        super().__init__(message)
        self.path = path
        self.owner_pid = owner_pid


class PlatformUnsupported(PlatformError):
    """Raised when an operation is requested on a platform/session it does not support
    (e.g. GUI automation under WSL, which has no usable display)."""
