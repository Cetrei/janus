from __future__ import annotations

import os
import stat
import subprocess
import sys
from enum import Enum
from pathlib import Path


class PrivacyStatus(str, Enum):
    PRIVATE = "private"
    OPEN = "open"
    UNKNOWN = "unknown"


def _is_windows() -> bool:
    return sys.platform == "win32"


def default_state_dir() -> Path:
    """~/.local/state/janus on Linux, %LOCALAPPDATA%\\Janus\\state on Windows.
    Respects JANUS_STATE_DIR."""
    override = os.environ.get("JANUS_STATE_DIR")
    if override:
        return Path(override).expanduser()

    if _is_windows():
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "Janus" / "state"

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state_home) if xdg_state_home else Path.home() / ".local" / "state"
    return base / "janus"


def make_private(path: Path, directory: bool = False) -> None:
    """POSIX: chmod 0600 (files) or 0700 (directories).
    Windows: strip ACL inheritance, grant full control to the current user only,
    via icacls with an argument list (never shell=True)."""
    path = Path(path)
    if _is_windows():
        _make_private_windows(path)
        return

    mode = 0o700 if directory else 0o600
    os.chmod(path, mode)


def _make_private_windows(path: Path) -> None:
    username = os.environ.get("USERNAME", "")
    args = [
        "icacls",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"{username}:F",
    ]
    subprocess.run(args, shell=False, check=True, capture_output=True)


def write_private(path: Path, data: bytes) -> None:
    """Atomic write (temp file in the same directory, then replace) that is
    born private: on POSIX the file is created with os.open(..., 0o600); on
    Windows make_private is applied before the content is written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    if _is_windows():
        tmp_path.write_bytes(data)
        _make_private_windows(tmp_path)
    else:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)

    tmp_path.replace(path)


def privacy_status(path: Path) -> PrivacyStatus:
    """POSIX: inspects the mode bits. Windows: inspects the ACL and returns
    UNKNOWN if it cannot be determined. Consumers should treat OPEN as an
    error and UNKNOWN as a warning."""
    path = Path(path)
    if not path.exists():
        return PrivacyStatus.UNKNOWN

    if _is_windows():
        return _privacy_status_windows(path)

    mode = stat.S_IMODE(path.stat().st_mode)
    # Private means no group/other permission bits at all.
    if mode & 0o077:
        return PrivacyStatus.OPEN
    return PrivacyStatus.PRIVATE


def _privacy_status_windows(path: Path) -> PrivacyStatus:
    try:
        result = subprocess.run(
            ["icacls", str(path)],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return PrivacyStatus.UNKNOWN

    output = result.stdout
    username = os.environ.get("USERNAME", "")
    # Heuristic: private if the only principals granted are the current user
    # and well-known system/admin accounts. Anything broader (Users,
    # Everyone, Authenticated Users) is OPEN. This is intentionally
    # conservative; ambiguous output falls back to UNKNOWN.
    broad_principals = ("Everyone", "BUILTIN\\Users", "Authenticated Users", "NT AUTHORITY\\Authenticated Users")
    if any(principal in output for principal in broad_principals):
        return PrivacyStatus.OPEN
    if username and username in output:
        return PrivacyStatus.PRIVATE
    return PrivacyStatus.UNKNOWN


def path_is_within(child: Path, root: Path) -> bool:
    """Resolves symlinks and, on Windows, compares case-insensitively and
    normalizes junctions."""
    child_resolved = Path(child).resolve()
    root_resolved = Path(root).resolve()

    if _is_windows():
        child_str = str(child_resolved).lower()
        root_str = str(root_resolved).lower()
        try:
            Path(child_str).relative_to(root_str)
            return True
        except ValueError:
            return False

    try:
        child_resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False
