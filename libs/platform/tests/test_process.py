from __future__ import annotations

import sys

import pytest

from janus_platform.process import spawn

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="uses POSIX shell commands to exercise spawn"
)


def test_spawn_rejects_command_string():
    with pytest.raises(TypeError):
        spawn("echo hello")  # type: ignore[arg-type]


async def test_spawn_runs_and_waits(tmp_path):
    handle = spawn(["true"])
    exit_code = await handle.wait()
    assert exit_code == 0


async def test_spawn_reports_nonzero_exit():
    handle = spawn(["false"])
    exit_code = await handle.wait()
    assert exit_code != 0


async def test_terminate_stops_a_long_running_process():
    handle = spawn(["sleep", "30"])
    assert handle.poll() is None
    await handle.terminate(grace_s=2.0)
    exit_code = await handle.wait()
    assert exit_code != 0


def test_spawn_exposes_pid():
    handle = spawn(["true"])
    assert isinstance(handle.pid, int)
    assert handle.pid > 0
