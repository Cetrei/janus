from __future__ import annotations

import pytest
from pydantic import ValidationError

from janus_config import ConfigError, SecretRef


def test_secret_ref_from_env(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "hunter2")
    ref = SecretRef(env="MY_SECRET")
    assert ref.resolve().get_secret_value() == "hunter2"


def test_secret_ref_from_file(tmp_path):
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("supersecret\n")
    ref = SecretRef(file=str(secret_file))
    assert ref.resolve().get_secret_value() == "supersecret"


def test_secret_ref_rejects_both_env_and_file():
    with pytest.raises(ValidationError):
        SecretRef(env="X", file="/tmp/x")


def test_secret_ref_rejects_neither_env_nor_file():
    with pytest.raises(ValidationError):
        SecretRef()


def test_secret_ref_resolve_missing_env_raises_config_error(monkeypatch):
    monkeypatch.delenv("DOES_NOT_EXIST_XYZ", raising=False)
    ref = SecretRef(env="DOES_NOT_EXIST_XYZ")
    with pytest.raises(ConfigError):
        ref.resolve()


def test_secret_ref_resolve_missing_file_raises_config_error(tmp_path):
    ref = SecretRef(file=str(tmp_path / "nope.txt"))
    with pytest.raises(ConfigError):
        ref.resolve()


def test_secret_ref_repr_never_shows_resolved_value(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "hunter2")
    ref = SecretRef(env="MY_SECRET")
    assert "hunter2" not in repr(ref)
    assert "MY_SECRET" in repr(ref)
