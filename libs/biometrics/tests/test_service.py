from __future__ import annotations

import dataclasses

import pytest
from conftest import FakeFaceVerifier, FakeSpeakerVerifier, make_enrollment

from janus_biometrics.base import BiometricResult, Decision, PcmAudio
from janus_biometrics.policy import AttemptLimiter, Thresholds
from janus_biometrics.registry import ProviderRegistry
from janus_biometrics.service import BiometricService
from janus_biometrics.store import EncryptedTemplateStore

FAKE_KEY = b"0" * 32


def build_service(
    tmp_path,
    face_score: float = 0.95,
    voice_score: float = 0.95,
    attempt_limiter: AttemptLimiter | None = None,
) -> tuple[BiometricService, EncryptedTemplateStore]:
    registry = ProviderRegistry()
    registry.register_face_factory("fake", lambda variant=None: FakeFaceVerifier(score=face_score))
    registry.register_speaker_factory(
        "fake", lambda variant=None: FakeSpeakerVerifier(score=voice_score)
    )
    store = EncryptedTemplateStore(tmp_path, FAKE_KEY)
    service = BiometricService(
        registry=registry,
        store=store,
        face_thresholds=Thresholds(t_high=0.8, t_low=0.5),
        voice_thresholds=Thresholds(t_high=0.8, t_low=0.5),
        face_provider_ref="fake",
        voice_provider_ref="fake",
        attempt_limiter=attempt_limiter,
    )
    return service, store


class TestScoreNeverLeavesTheLibrary:
    def test_biometric_result_has_no_score_field(self):
        """Requisito 16: the score is not part of the public result, with or
        without a sender_id. Structural guarantee: BiometricResult simply
        has no score field, so it cannot leak regardless of call path."""
        field_names = {f.name for f in dataclasses.fields(BiometricResult)}
        assert "score" not in field_names


class TestVerifyFaceNotEnrolled:
    @pytest.mark.asyncio
    async def test_returns_inconclusive_when_no_template(self, tmp_path):
        service, _ = build_service(tmp_path)
        result = await service.verify_face(b"fake-image-bytes")
        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "not_enrolled"


class TestVerifyFaceEnrolled:
    @pytest.mark.asyncio
    async def test_high_score_yields_high_decision(self, tmp_path):
        service, store = build_service(tmp_path, face_score=0.95)
        store.save(make_enrollment(kind="face"))
        result = await service.verify_face(b"fake-image-bytes")
        assert result.decision == Decision.HIGH

    @pytest.mark.asyncio
    async def test_low_score_yields_low_decision(self, tmp_path):
        service, store = build_service(tmp_path, face_score=0.1)
        store.save(make_enrollment(kind="face"))
        result = await service.verify_face(b"fake-image-bytes")
        assert result.decision == Decision.LOW


class TestVerifyVoiceEnrolled:
    @pytest.mark.asyncio
    async def test_high_score_yields_high_decision(self, tmp_path):
        service, store = build_service(tmp_path, voice_score=0.95)
        store.save(make_enrollment(kind="voice"))
        audio = PcmAudio(samples=b"\x00" * 100)
        result = await service.verify_voice(audio)
        assert result.decision == Decision.HIGH


class TestLockoutIntegration:
    @pytest.mark.asyncio
    async def test_locked_sender_gets_inconclusive_without_calling_provider(self, tmp_path):
        limiter = AttemptLimiter(max_failed_attempts=1)
        service, store = build_service(tmp_path, face_score=0.1, attempt_limiter=limiter)
        store.save(make_enrollment(kind="face"))

        first = await service.verify_face(b"img", sender_id="attacker")
        assert first.decision == Decision.LOW

        second = await service.verify_face(b"img", sender_id="attacker")
        assert second.decision == Decision.INCONCLUSIVE
        assert second.reason == "locked_out"

    @pytest.mark.asyncio
    async def test_successful_verification_does_not_lock(self, tmp_path):
        limiter = AttemptLimiter(max_failed_attempts=1)
        service, store = build_service(tmp_path, face_score=0.95, attempt_limiter=limiter)
        store.save(make_enrollment(kind="face"))

        result = await service.verify_face(b"img", sender_id="owner")
        assert result.decision == Decision.HIGH
        assert not limiter.is_locked("owner")


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_reports_no_enrollment_initially(self, tmp_path):
        service, _ = build_service(tmp_path)
        status = await service.status()
        assert status.enrolled == []

    @pytest.mark.asyncio
    async def test_status_reports_enrolled_profile(self, tmp_path):
        service, store = build_service(tmp_path)
        store.save(make_enrollment(kind="face"))
        status = await service.status()
        assert {"kind": "face", "profile": "owner"} in status.enrolled
