from __future__ import annotations

import subprocess
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


async def test_stdin_is_none_by_default():
    handle = spawn(["true"])
    assert handle.stdin is None
    await handle.wait()


async def test_stdin_pipe_streams_bytes_to_the_child(tmp_path):
    output = tmp_path / "received.bin"
    handle = spawn(
        ["sh", "-c", 'cat > "$1"', "sh", str(output)],
        stdin=subprocess.PIPE,
    )
    assert handle.stdin is not None

    handle.stdin.write(b"raw-frame-bytes")
    handle.stdin.close()
    exit_code = await handle.wait()

    assert exit_code == 0
    assert output.read_bytes() == b"raw-frame-bytes"


async def test_kill_stops_a_process_synchronously():
    handle = spawn(["sleep", "30"])
    assert handle.poll() is None

    handle.kill()
    exit_code = await handle.wait()

    assert exit_code != 0


async def test_kill_is_a_noop_on_an_exited_process():
    handle = spawn(["true"])
    await handle.wait()
    handle.kill()
