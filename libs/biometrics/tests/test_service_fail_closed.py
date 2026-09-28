from __future__ import annotations

import pytest
from conftest import make_enrollment

from janus_biometrics.base import BiometricResult, Decision, Liveness, PcmAudio, SpeakerVerifier
from janus_biometrics.errors import BiometricsError, ModelMismatch, ModelSourceError
from janus_biometrics.policy import Thresholds
from janus_biometrics.registry import ProviderRegistry
from janus_biometrics.service import BiometricService
from janus_biometrics.store import EncryptedTemplateStore

FAKE_KEY = b"0" * 32


class RaisingOnVerifySpeaker(SpeakerVerifier):
    """Simulates a provider whose lazy model load fails inside verify(),
    exactly where WeSpeakerProvider/SFaceFaceVerifier raise it."""

    id = "raising"

    def __init__(self, error: Exception, variant=None) -> None:
        self._error = error

    async def verify(self, audio: PcmAudio, enrollment) -> BiometricResult:
        raise self._error

    async def close(self) -> None:
        return None


def build_service(tmp_path, speaker_factory) -> tuple[BiometricService, EncryptedTemplateStore]:
    registry = ProviderRegistry()
    registry.register_speaker_factory("raising", speaker_factory)
    store = EncryptedTemplateStore(tmp_path, FAKE_KEY)
    service = BiometricService(
        registry=registry,
        store=store,
        face_thresholds=Thresholds(t_high=0.8, t_low=0.5),
        voice_thresholds=Thresholds(t_high=0.8, t_low=0.5),
        voice_provider_ref="raising",
    )
    return service, store


AUDIO = PcmAudio(samples=b"\x00" * 100)


class TestModelLoadFailuresFailClosed:
    @pytest.mark.asyncio
    async def test_model_source_error_during_verify_is_model_unavailable(self, tmp_path):
        error = ModelSourceError("could not download model")
        service, store = build_service(tmp_path, lambda variant=None: RaisingOnVerifySpeaker(error))
        store.save(make_enrollment(kind="voice"))

        result = await service.verify_voice(AUDIO)

        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "model_unavailable"
        assert result.liveness == Liveness.NOT_CHECKED

    @pytest.mark.asyncio
    async def test_missing_extra_reported_as_biometrics_error_is_model_unavailable(self, tmp_path):
        # SherpaWeSpeakerExtractor raises plain BiometricsError (not
        # ImportError) when sherpa-onnx is missing.
        error = BiometricsError("sherpa-onnx is not installed")
        service, store = build_service(tmp_path, lambda variant=None: RaisingOnVerifySpeaker(error))
        store.save(make_enrollment(kind="voice"))

        result = await service.verify_voice(AUDIO)

        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "model_unavailable"

    @pytest.mark.asyncio
    async def test_import_error_while_resolving_is_model_unavailable(self, tmp_path):
        def factory(variant=None):
            raise ImportError("No module named 'cv2'")

        service, store = build_service(tmp_path, factory)
        store.save(make_enrollment(kind="voice"))

        result = await service.verify_voice(AUDIO)

        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "model_unavailable"

    @pytest.mark.asyncio
    async def test_failure_does_not_count_as_a_failed_attempt(self, tmp_path):
        # A model that cannot load says nothing about the sender: it must
        # not push them toward lockout.
        error = ModelSourceError("offline")
        service, store = build_service(tmp_path, lambda variant=None: RaisingOnVerifySpeaker(error))
        store.save(make_enrollment(kind="voice"))

        for _ in range(10):
            result = await service.verify_voice(AUDIO, sender_id="owner")
            assert result.reason == "model_unavailable"


class TestModelMismatchStillPropagates:
    @pytest.mark.asyncio
    async def test_model_mismatch_is_not_hidden_as_model_unavailable(self, tmp_path):
        error = ModelMismatch("voice", "owner", "new-model", "old-model")
        service, store = build_service(tmp_path, lambda variant=None: RaisingOnVerifySpeaker(error))
        store.save(make_enrollment(kind="voice"))

        with pytest.raises(ModelMismatch):
            await service.verify_voice(AUDIO)
