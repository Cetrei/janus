from __future__ import annotations

import importlib.util
import textwrap

import pytest

from janus_biometrics.defaults import DEFAULT_VOICE_THRESHOLDS, build_default_registry
from janus_biometrics.models import ModelCache
from janus_biometrics.policy import Thresholds
from janus_biometrics.providers.null import NullFaceVerifier, NullSpeakerVerifier


@pytest.fixture
def model_cache(tmp_path) -> ModelCache:
    config = tmp_path / "models.yaml"
    config.write_text(
        textwrap.dedent(
            """\
            models:
              wespeaker:
                sha256: "0000"
                url: "https://example.invalid/wespeaker.onnx"
            """
        )
    )
    return ModelCache(config_path=config, cache_dir=tmp_path / "cache")


class TestNullProviders:
    def test_null_face_is_registered(self, model_cache):
        registry = build_default_registry(model_cache)
        assert isinstance(registry.resolve_face("null"), NullFaceVerifier)

    def test_null_speaker_is_registered(self, model_cache):
        registry = build_default_registry(model_cache)
        assert isinstance(registry.resolve_speaker("null"), NullSpeakerVerifier)


# providers/speaker_wespeaker.py imports _face_pipeline, which imports cv2 at
# module level, so resolving "local" needs the `face` extra even though the
# provider itself never touches opencv. Skip only the classes that need it
# (same convention as test_sface.py) instead of failing without the extra.
requires_cv2 = pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None, reason="needs the `face` extra (opencv)"
)


@requires_cv2
class TestLocalSpeaker:
    def test_local_speaker_is_registered_and_lazy(self, model_cache):
        # Constructing must not resolve the model or need sherpa-onnx: the
        # download URL above is unreachable and would fail if it did.
        registry = build_default_registry(model_cache)
        verifier = registry.resolve_speaker("local")
        assert verifier.id == "local"

    def test_local_speaker_rejects_a_variant(self, model_cache):
        registry = build_default_registry(model_cache)
        with pytest.raises(ValueError, match="no variants"):
            registry.resolve_speaker("local:something")

    def test_custom_voice_thresholds_reach_the_provider(self, model_cache):
        custom = Thresholds(t_high=0.9, t_low=0.6)
        registry = build_default_registry(model_cache, voice_thresholds=custom)
        verifier = registry.resolve_speaker("local")
        assert verifier._pending_thresholds == custom

    def test_default_voice_thresholds_are_used_when_none_given(self, model_cache):
        registry = build_default_registry(model_cache)
        verifier = registry.resolve_speaker("local")
        assert verifier._pending_thresholds == DEFAULT_VOICE_THRESHOLDS


class TestRemoteStaysDisabled:
    def test_dotted_path_is_rejected_by_default(self, model_cache):
        from janus_biometrics.errors import RemoteProviderNotAcknowledged

        registry = build_default_registry(model_cache)
        with pytest.raises(RemoteProviderNotAcknowledged):
            registry.resolve_face("some.remote.module:RemoteVerifier")
