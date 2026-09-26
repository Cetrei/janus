from __future__ import annotations

import sys

import pytest

from janus_platform.paths import (
    PrivacyStatus,
    default_state_dir,
    make_private,
    path_is_within,
    privacy_status,
    write_private,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific behavior")


def test_default_state_dir_respects_override(monkeypatch, tmp_path):
    monkeypatch.setenv("JANUS_STATE_DIR", str(tmp_path / "custom"))
    assert default_state_dir() == tmp_path / "custom"


def test_default_state_dir_uses_xdg_state_home(monkeypatch, tmp_path):
    monkeypatch.delenv("JANUS_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert default_state_dir() == tmp_path / "janus"


def test_make_private_file_sets_0600(tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("x")
    make_private(target)
    assert privacy_status(target) == PrivacyStatus.PRIVATE


def test_make_private_directory_sets_0700(tmp_path):
    target = tmp_path / "secretdir"
    target.mkdir()
    make_private(target, directory=True)
    mode = target.stat().st_mode
    assert oct(mode)[-3:] == "700"


def test_write_private_creates_file_with_restricted_perms(tmp_path):
    target = tmp_path / "nested" / "key.bin"
    write_private(target, b"topsecret")
    assert target.read_bytes() == b"topsecret"
    assert privacy_status(target) == PrivacyStatus.PRIVATE


def test_write_private_is_atomic_no_leftover_tmp(tmp_path):
    target = tmp_path / "key.bin"
    write_private(target, b"v1")
    write_private(target, b"v2")
    assert target.read_bytes() == b"v2"
    assert not (tmp_path / "key.bin.tmp").exists()


def test_privacy_status_open_when_group_readable(tmp_path):
    target = tmp_path / "open.txt"
    target.write_text("x")
    target.chmod(0o644)
    assert privacy_status(target) == PrivacyStatus.OPEN


def test_privacy_status_unknown_for_missing_file(tmp_path):
    assert privacy_status(tmp_path / "nope.txt") == PrivacyStatus.UNKNOWN


def test_path_is_within_true_for_nested_path(tmp_path):
    root = tmp_path / "root"
    child = root / "sub" / "file.txt"
    root.mkdir()
    (root / "sub").mkdir()
    child.write_text("x")
    assert path_is_within(child, root) is True


def test_path_is_within_false_for_sibling_path(tmp_path):
    root = tmp_path / "root"
    sibling = tmp_path / "sibling"
    root.mkdir()
    sibling.mkdir()
    assert path_is_within(sibling, root) is False


def test_path_is_within_resolves_symlink_escape(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "escape"
    link.symlink_to(outside)
    assert path_is_within(link, root) is False
