from __future__ import annotations

from janus_platform.diagnostics import platform_info


def test_platform_info_returns_known_os():
    info = platform_info()
    assert info.os in ("linux", "windows")


def test_platform_info_has_python_version():
    info = platform_info()
    assert info.python_version.count(".") >= 1


def test_platform_info_session_type_is_known_value():
    info = platform_info()
    assert info.session_type in ("x11", "wayland", "win32", "headless")
