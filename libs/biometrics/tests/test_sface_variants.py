"""Unit tests for SFaceFaceVerifier's variant selection (local:sface vs
local:scrfd, see providers/sface.py's docstring). These only exercise
__init__'s branching (detector backend + model_id chosen from `variant`)
and never touch a real ONNX session, so unlike test_sface.py they do not
need real model weights or network access -- they only need cv2 and
onnxruntime importable (the `face` extra), same precondition as
test_sface.py's importorskip, but no models.yaml resolution at all.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cv2", reason="opencv-python-headless not installed (face extra)")
pytest.importorskip("onnxruntime", reason="onnxruntime not installed (face extra)")

from janus_biometrics.providers.sface import SFaceFaceVerifier  # noqa: E402


class _StubModelCache:
    """SFaceFaceVerifier.__init__ never calls model_cache (models are only
    resolved lazily in _ensure_loaded), so a stub that raises on any use
    is enough to prove __init__ itself does no model I/O."""

    def resolve(self, model_id: str):
        raise AssertionError(f"__init__ should not resolve models, got resolve({model_id!r})")


class TestVariantSelection:
    def test_default_variant_is_sface_backend(self) -> None:
        verifier = SFaceFaceVerifier(model_cache=_StubModelCache())
        assert verifier._detector_backend == "yunet"
        assert verifier._model_id == "sface-yunet-minifasnet-v1"

    def test_explicit_sface_variant_matches_default(self) -> None:
        verifier = SFaceFaceVerifier(variant="sface", model_cache=_StubModelCache())
        assert verifier._detector_backend == "yunet"
        assert verifier._model_id == "sface-yunet-minifasnet-v1"

    def test_scrfd_variant_selects_scrfd_backend_and_distinct_model_id(self) -> None:
        verifier = SFaceFaceVerifier(variant="scrfd", model_cache=_StubModelCache())
        assert verifier._detector_backend == "scrfd"
        assert verifier._model_id == "scrfd-sface-minifasnet-v1"
        # Different model_id from local:sface's, per requisito 18: an
        # enrollment made under one variant must not silently verify
        # under the other (ModelMismatch enforces this in verify()).
        assert verifier._model_id != "sface-yunet-minifasnet-v1"

    def test_unknown_variant_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown local face variant"):
            SFaceFaceVerifier(variant="not-a-real-variant", model_cache=_StubModelCache())

    def test_close_also_clears_scrfd_session_attribute(self) -> None:
        verifier = SFaceFaceVerifier(variant="scrfd", model_cache=_StubModelCache())
        verifier._scrfd_session = object()  # simulate a loaded session
        import asyncio

        asyncio.run(verifier.close())
        assert verifier._scrfd_session is None
