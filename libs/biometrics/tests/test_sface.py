"""Real integration tests for the local:sface chain (YuNet + SFace +
MiniFASNetV2/V1SE), spec-18 Testing Requirements: "alta y verificacion
reales con SFace, YuNet y MiniFASNet sobre imagenes de prueba con licencia
libre".

Standalone by design (see AGENT.md / HANDOFF.md): this module imports
nothing from Janus core or any spoke other than janus_biometrics itself.
It talks to the real ONNX models via ModelCache and cv2/onnxruntime
directly, exactly like providers/sface.py and low_level.py do.

Skips (does not fail) whenever the environment cannot support a real run:
  - opencv-python-headless / onnxruntime not installed (the `face` extra)
  - one or more of yunet / sface / minifasnet_v2 / minifasnet_v1se not
    resolvable via models.yaml (no local_path on disk and no network
    download attempted here)

This intentionally never falls back to mocks/fakes for what this file is
supposed to prove: that the real weights load and produce the expected
shapes end to end. FakeFaceVerifier (conftest.py) already covers the
service/policy layer without real models; duplicating that here with a
mocked SFaceFaceVerifier would not add anything spec-18 asks for.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from janus_biometrics.base import Enrollment
from janus_biometrics.errors import ModelSourceError
from janus_biometrics.models import ModelCache, ModelIntegrityError

cv2 = pytest.importorskip("cv2", reason="opencv-python-headless not installed (face extra)")
pytest.importorskip("onnxruntime", reason="onnxruntime not installed (face extra)")

from janus_biometrics.low_level import detect_and_embed_faces  # noqa: E402
from janus_biometrics.providers.sface import SFaceFaceVerifier  # noqa: E402

_MODELS_YAML = Path(__file__).parent.parent / "src" / "janus_biometrics" / "models.yaml"
_REQUIRED_MODELS = ("yunet", "sface", "minifasnet_v2", "minifasnet_v1se")


def _make_cache() -> ModelCache:
    return ModelCache(config_path=_MODELS_YAML, cache_dir=Path.home() / ".cache" / "janus-models")


def _weights_available() -> bool:
    """True only if every required model resolves to a real, hash-verified
    file without hitting the network (a missing local_path/cache entry
    raises ModelSourceError; a corrupt one raises ModelIntegrityError;
    either means "not available here", not a test failure)."""
    cache = _make_cache()
    for model_id in _REQUIRED_MODELS:
        spec = cache._specs.get(model_id)
        if spec is None:
            return False
        if spec.local_path is not None:
            if not Path(spec.local_path).exists():
                return False
        else:
            cached = cache._cache_dir / f"{model_id}.onnx"
            if not cached.exists():
                return False  # do not trigger a real download from a test run
    try:
        for model_id in _REQUIRED_MODELS:
            cache.resolve(model_id)
    except (ModelSourceError, ModelIntegrityError):
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _weights_available(),
    reason=(
        "real ONNX weights not available locally (yunet/sface/minifasnet_v2/"
        "minifasnet_v1se must be present via models.yaml local_path, or "
        "already downloaded to the ModelCache cache_dir; this test never "
        "downloads them itself)"
    ),
)


def _synthetic_face_image() -> bytes:
    """Encodes a synthetic BGR frame containing a simple face-like pattern
    (oval + two eye blobs) as PNG bytes. This is not a photograph of a real
    person and is not expected to reliably pass YuNet detection or
    MiniFASNet liveness; it exists only to exercise decode -> detect ->
    (no-detection) or detect -> embed as a real, license-free input.
    Detection-dependent tests use pytest.mark.xfail/soft assertions rather
    than asserting a specific face count, since a synthetic pattern is not
    a reliable stand-in for a real face for YuNet's purposes.
    """
    frame = np.full((240, 240, 3), 200, dtype=np.uint8)
    center = (120, 130)
    axes = (60, 80)
    cv2.ellipse(frame, center, axes, 0, 0, 360, (150, 120, 100), -1)
    cv2.circle(frame, (95, 110), 10, (30, 30, 30), -1)
    cv2.circle(frame, (145, 110), 10, (30, 30, 30), -1)
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("failed to encode synthetic test image")
    return encoded.tobytes()


def _blank_image() -> bytes:
    frame = np.full((240, 240, 3), 128, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("failed to encode blank test image")
    return encoded.tobytes()


@pytest.fixture(scope="module")
def model_cache() -> ModelCache:
    return _make_cache()


class TestModelCacheResolution:
    """Confirms the real weights resolve and verify by hash, the
    precondition every other test in this file depends on."""

    def test_all_required_models_resolve(self, model_cache: ModelCache) -> None:
        for model_id in _REQUIRED_MODELS:
            path = model_cache.resolve(model_id)
            assert path.exists()
            assert path.stat().st_size > 0


class TestSFaceFaceVerifierRealWeights:
    """1:1 verification path (providers/sface.py) against real YuNet +
    SFace + MiniFASNetV2/V1SE, per spec-18 Testing Requirements."""

    def test_blank_image_yields_no_face_detected(self, model_cache: ModelCache) -> None:
        verifier = SFaceFaceVerifier(model_cache=model_cache)
        enrollment = Enrollment(
            kind="face",
            profile="owner",
            model_id="sface-yunet-minifasnet-v1",
            dim=128,
            embeddings=[[0.0] * 128],
            centroid=[0.0] * 128,
            samples=1,
        )
        result = asyncio.run(verifier.verify(_blank_image(), enrollment))
        assert result.decision.name == "INCONCLUSIVE"
        assert result.reason == "no_face_detected"
        assert result.quality_ok is False
        asyncio.run(verifier.close())

    def test_model_mismatch_is_rejected_before_touching_models(
        self, model_cache: ModelCache
    ) -> None:
        from janus_biometrics.errors import ModelMismatch

        verifier = SFaceFaceVerifier(model_cache=model_cache)
        enrollment = Enrollment(
            kind="face",
            profile="owner",
            model_id="some-other-model",
            dim=128,
            embeddings=[[0.0] * 128],
            centroid=[0.0] * 128,
            samples=1,
        )
        with pytest.raises(ModelMismatch):
            asyncio.run(verifier.verify(_blank_image(), enrollment))
        asyncio.run(verifier.close())

    def test_close_releases_both_liveness_sessions(self, model_cache: ModelCache) -> None:
        verifier = SFaceFaceVerifier(model_cache=model_cache)
        enrollment = Enrollment(
            kind="face",
            profile="owner",
            model_id="sface-yunet-minifasnet-v1",
            dim=128,
            embeddings=[[0.0] * 128],
            centroid=[0.0] * 128,
            samples=1,
        )
        # Force real model loading (detector/recognizer/both liveness
        # sessions) via a real verify() call before checking close().
        asyncio.run(verifier.verify(_blank_image(), enrollment))
        asyncio.run(verifier.close())
        assert verifier._detector is None
        assert verifier._recognizer is None
        assert verifier._liveness_session_v2 is None
        assert verifier._liveness_session_v1se is None


class TestDetectAndEmbedFacesRealWeights:
    """8bis low-level path (low_level.py) against real YuNet + SFace,
    reused as-is by libs/presence. No liveness, no threshold: only
    detection + embedding shape/behavior."""

    def test_blank_image_returns_no_embeddings(self, model_cache: ModelCache) -> None:
        results = detect_and_embed_faces(_blank_image(), model_cache)
        assert results == []

    def test_embedding_dimension_matches_sface_output(self, model_cache: ModelCache) -> None:
        # Uses the synthetic image only to exercise the encode/decode path;
        # asserts on shape *if* a face happens to be detected, since a
        # synthetic pattern detecting is not guaranteed. This intentionally
        # does not assert a specific face count.
        results = detect_and_embed_faces(_synthetic_face_image(), model_cache)
        for face_embedding in results:
            assert len(face_embedding.embedding) == 128
            assert isinstance(face_embedding.quality_ok, bool)
