from __future__ import annotations

import hashlib

import pytest

from janus_biometrics.models import (
    ModelCache,
    ModelConfigError,
    ModelIntegrityError,
    ModelSourceError,
    load_model_specs,
)


def _write_yaml(tmp_path, content: str):
    config_path = tmp_path / "models.yaml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_load_model_specs_parses_url_and_local_path(tmp_path):
    config_path = _write_yaml(
        tmp_path,
        """
        models:
          yunet:
            sha256: "abc123"
            url: "https://example.com/yunet.onnx"
            license: "MIT"
          minifasnet:
            sha256: "def456"
            local_path: "/opt/models/minifasnet.onnx"
        """,
    )
    specs = load_model_specs(config_path)
    assert specs["yunet"].url == "https://example.com/yunet.onnx"
    assert specs["yunet"].license == "MIT"
    assert specs["minifasnet"].local_path == "/opt/models/minifasnet.onnx"


def test_model_spec_rejects_both_url_and_local_path(tmp_path):
    config_path = _write_yaml(
        tmp_path,
        """
        models:
          bad:
            sha256: "abc123"
            url: "https://example.com/x.onnx"
            local_path: "/opt/x.onnx"
        """,
    )
    with pytest.raises(ModelConfigError):
        load_model_specs(config_path)


def test_model_spec_rejects_neither_url_nor_local_path(tmp_path):
    config_path = _write_yaml(
        tmp_path,
        """
        models:
          bad:
            sha256: "abc123"
        """,
    )
    with pytest.raises(ModelConfigError):
        load_model_specs(config_path)


def test_model_spec_requires_sha256(tmp_path):
    config_path = _write_yaml(
        tmp_path,
        """
        models:
          bad:
            url: "https://example.com/x.onnx"
        """,
    )
    with pytest.raises(ModelConfigError):
        load_model_specs(config_path)


def test_load_model_specs_missing_file(tmp_path):
    with pytest.raises(ModelConfigError):
        load_model_specs(tmp_path / "does_not_exist.yaml")


def test_load_model_specs_empty_models_section(tmp_path):
    config_path = _write_yaml(tmp_path, "models: {}\n")
    with pytest.raises(ModelConfigError):
        load_model_specs(config_path)


def test_model_cache_resolves_local_path_with_matching_hash(tmp_path):
    model_file = tmp_path / "minifasnet.onnx"
    model_file.write_bytes(b"fake-onnx-weights")
    real_hash = hashlib.sha256(b"fake-onnx-weights").hexdigest()

    config_path = _write_yaml(
        tmp_path,
        f"""
        models:
          minifasnet:
            sha256: "{real_hash}"
            local_path: "{model_file}"
        """,
    )
    cache = ModelCache(config_path=config_path, cache_dir=tmp_path / "cache")
    resolved = cache.resolve("minifasnet")
    assert resolved == model_file


def test_model_cache_rejects_local_path_hash_mismatch(tmp_path):
    model_file = tmp_path / "minifasnet.onnx"
    model_file.write_bytes(b"fake-onnx-weights")

    config_path = _write_yaml(
        tmp_path,
        f"""
        models:
          minifasnet:
            sha256: "0000000000000000000000000000000000000000000000000000000000000000"
            local_path: "{model_file}"
        """,
    )
    cache = ModelCache(config_path=config_path, cache_dir=tmp_path / "cache")
    with pytest.raises(ModelIntegrityError):
        cache.resolve("minifasnet")


def test_model_cache_rejects_missing_local_path_file(tmp_path):
    config_path = _write_yaml(
        tmp_path,
        f"""
        models:
          minifasnet:
            sha256: "abc123"
            local_path: "{tmp_path / "does_not_exist.onnx"}"
        """,
    )
    cache = ModelCache(config_path=config_path, cache_dir=tmp_path / "cache")
    with pytest.raises(ModelSourceError):
        cache.resolve("minifasnet")


def test_model_cache_reuses_cached_download(tmp_path, monkeypatch):
    cached_file = tmp_path / "cache" / "sface.onnx"
    cached_file.parent.mkdir(parents=True)
    cached_file.write_bytes(b"already-downloaded")
    real_hash = hashlib.sha256(b"already-downloaded").hexdigest()

    config_path = _write_yaml(
        tmp_path,
        f"""
        models:
          sface:
            sha256: "{real_hash}"
            url: "https://example.com/sface.onnx"
        """,
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not attempt a download when cache already has the file")

    monkeypatch.setattr("janus_biometrics.models._download", _fail_if_called)

    cache = ModelCache(config_path=config_path, cache_dir=tmp_path / "cache")
    resolved = cache.resolve("sface")
    assert resolved == cached_file


def test_model_cache_downloads_when_not_cached(tmp_path, monkeypatch):
    real_content = b"downloaded-bytes"
    real_hash = hashlib.sha256(real_content).hexdigest()

    config_path = _write_yaml(
        tmp_path,
        f"""
        models:
          sface:
            sha256: "{real_hash}"
            url: "https://example.com/sface.onnx"
        """,
    )

    def _fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(real_content)

    monkeypatch.setattr("janus_biometrics.models._download", _fake_download)

    cache = ModelCache(config_path=config_path, cache_dir=tmp_path / "cache")
    resolved = cache.resolve("sface")
    assert resolved.read_bytes() == real_content


def test_model_cache_evicts_idle_downloaded_models_but_keeps_local_path(tmp_path, monkeypatch):
    downloaded_content = b"downloaded"
    local_content = b"local"
    downloaded_hash = hashlib.sha256(downloaded_content).hexdigest()
    local_file = tmp_path / "local.onnx"
    local_file.write_bytes(local_content)
    local_hash = hashlib.sha256(local_content).hexdigest()

    config_path = _write_yaml(
        tmp_path,
        f"""
        models:
          downloaded_model:
            sha256: "{downloaded_hash}"
            url: "https://example.com/downloaded.onnx"
          local_model:
            sha256: "{local_hash}"
            local_path: "{local_file}"
        """,
    )

    def _fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(downloaded_content)

    monkeypatch.setattr("janus_biometrics.models._download", _fake_download)

    clock = {"t": 0.0}
    cache = ModelCache(
        config_path=config_path,
        cache_dir=tmp_path / "cache",
        model_idle_unload_s=10,
        clock=lambda: clock["t"],
    )
    cache.resolve("downloaded_model")
    cache.resolve("local_model")
    assert cache.is_loaded("downloaded_model")
    assert cache.is_loaded("local_model")

    clock["t"] = 100.0
    cache.resolve("local_model")  # triggers eviction check
    assert not cache.is_loaded("downloaded_model")
    assert cache.is_loaded("local_model")


def test_license_for_returns_configured_license(tmp_path):
    config_path = _write_yaml(
        tmp_path,
        """
        models:
          yunet:
            sha256: "abc123"
            url: "https://example.com/yunet.onnx"
            license: "MIT"
        """,
    )
    cache = ModelCache(config_path=config_path, cache_dir=tmp_path / "cache")
    assert cache.license_for("yunet") == "MIT"
    assert cache.license_for("unknown") is None
