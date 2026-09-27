from __future__ import annotations

import sys

import pytest

from janus_platform.errors import LockHeld
from janus_platform.lock import InstanceLock

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="uses os.fork via subprocess for the held-lock test"
)


def test_instance_lock_acquires_and_releases(tmp_path):
    lock_path = tmp_path / "core.lock"
    with InstanceLock(lock_path) as lock:
        assert lock is not None
        assert lock_path.exists()
    # released cleanly, re-acquire should succeed
    with InstanceLock(lock_path):
        pass


def test_instance_lock_writes_own_pid(tmp_path):
    import os

    lock_path = tmp_path / "core.lock"
    with InstanceLock(lock_path):
        assert lock_path.read_text().strip() == str(os.getpid())


def test_instance_lock_raises_lock_held_when_taken(tmp_path):
    import multiprocessing

    lock_path = tmp_path / "core.lock"

    def _hold_lock(path, ready, release):
        with InstanceLock(path):
            ready.set()
            release.wait(timeout=5)

    ready = multiprocessing.Event()
    release = multiprocessing.Event()
    proc = multiprocessing.Process(target=_hold_lock, args=(lock_path, ready, release))
    proc.start()
    try:
        assert ready.wait(timeout=5)
        with pytest.raises(LockHeld) as exc_info:
            with InstanceLock(lock_path):
                pass
        assert exc_info.value.owner_pid == proc.pid
    finally:
        release.set()
        proc.join(timeout=5)
