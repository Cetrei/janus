from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass


def _is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def _session_type() -> str:
    if sys.platform == "win32":
        return "win32"
    if _is_wsl():
        return "headless"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "headless"


@dataclass(frozen=True)
class PlatformInfo:
    os: str  # "linux" or "windows"
    arch: str
    is_wsl: bool
    session_type: str  # "x11", "wayland", "win32", "headless"
    python_version: str


def platform_info() -> PlatformInfo:
    return PlatformInfo(
        os="windows" if sys.platform == "win32" else "linux",
        arch=platform.machine(),
        is_wsl=_is_wsl(),
        session_type=_session_type(),
        python_version=platform.python_version(),
    )
