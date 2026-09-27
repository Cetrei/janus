from __future__ import annotations

import dataclasses

import pytest
from conftest import FakeFaceVerifier, FakeSpeakerVerifier, make_enrollment

from janus_biometrics.base import BiometricResult, Decision, PcmAudio
from janus_biometrics.errors import SensorUnavailable
from janus_biometrics.policy import AttemptLimiter, Thresholds
from janus_biometrics.registry import ProviderRegistry
from janus_biometrics.service import BiometricService
from janus_biometrics.store import EncryptedTemplateStore

FAKE_KEY = b"0" * 32


class FakeCameraSensor:
    """Deterministic double for sensors.SensorSource: no real camera.py or
    face-gui extra needed to exercise capture_and_verify's plumbing."""

    id = "fake-camera"

    def __init__(self, frame: bytes = b"fake-frame", fail: bool = False) -> None:
        self._frame = frame
        self._fail = fail
        self.capture_calls = 0

    def capture_frame(self) -> bytes:
        self.capture_calls += 1
        if self._fail:
            raise SensorUnavailable(self.id, "camera busy")
        return self._frame

    def capture_audio(self, max_s: float):
        raise NotImplementedError("FakeCameraSensor does not support audio capture")


class FakeMicrophoneSensor:
    """Deterministic double for sensors.SensorSource's audio path."""

    id = "fake-mic"

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    def capture_frame(self) -> bytes:
        raise NotImplementedError("FakeMicrophoneSensor does not support frame capture")

    def capture_audio(self, max_s: float) -> PcmAudio:
        if self._fail:
            raise SensorUnavailable(self.id, "microphone busy")
        return PcmAudio(samples=b"\x00" * 100)


def build_service(
    tmp_path,
    face_score: float = 0.95,
    voice_score: float = 0.95,
    attempt_limiter: AttemptLimiter | None = None,
    sensors: dict[str, object] | None = None,
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
        sensors=sensors,
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


class TestCaptureAndVerify:
    @pytest.mark.asyncio
    async def test_unknown_sensor_id_is_inconclusive(self, tmp_path):
        service, store = build_service(tmp_path, sensors={})
        store.save(make_enrollment(kind="face"))
        result = await service.capture_and_verify("missing-sensor", kind="face")
        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "unknown_sensor"

    @pytest.mark.asyncio
    async def test_face_capture_feeds_verify_face(self, tmp_path):
        camera = FakeCameraSensor(frame=b"real-frame-bytes")
        service, store = build_service(tmp_path, face_score=0.95, sensors={"cam": camera})
        store.save(make_enrollment(kind="face"))

        result = await service.capture_and_verify("cam", kind="face")

        assert result.decision == Decision.HIGH
        assert camera.capture_calls == 1

    @pytest.mark.asyncio
    async def test_voice_capture_feeds_verify_voice(self, tmp_path):
        mic = FakeMicrophoneSensor()
        service, store = build_service(tmp_path, voice_score=0.95, sensors={"mic": mic})
        store.save(make_enrollment(kind="voice"))

        result = await service.capture_and_verify("mic", kind="voice")

        assert result.decision == Decision.HIGH

    @pytest.mark.asyncio
    async def test_sensor_unavailable_is_inconclusive_not_raised(self, tmp_path):
        camera = FakeCameraSensor(fail=True)
        service, store = build_service(tmp_path, sensors={"cam": camera})
        store.save(make_enrollment(kind="face"))

        result = await service.capture_and_verify("cam", kind="face")

        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "sensor_unavailable"

    @pytest.mark.asyncio
    async def test_kind_mismatch_on_sensor_is_inconclusive_not_raised(self, tmp_path):
        # A camera sensor asked to do voice capture: capture_audio() raises
        # NotImplementedError (sensors.SensorSource's own contract for a
        # method that doesn't match the sensor's kind), which
        # capture_and_verify must also absorb into INCONCLUSIVE rather than
        # letting it propagate as an unhandled TypeError-adjacent failure.
        camera = FakeCameraSensor()
        service, store = build_service(tmp_path, sensors={"cam": camera})
        store.save(make_enrollment(kind="voice"))

        result = await service.capture_and_verify("cam", kind="voice")

        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "sensor_unavailable"

    @pytest.mark.asyncio
    async def test_unknown_kind_is_inconclusive(self, tmp_path):
        camera = FakeCameraSensor()
        service, store = build_service(tmp_path, sensors={"cam": camera})
        store.save(make_enrollment(kind="face"))

        result = await service.capture_and_verify("cam", kind="retina")

        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "unknown_kind"

    @pytest.mark.asyncio
    async def test_capture_and_verify_respects_lockout(self, tmp_path):
        limiter = AttemptLimiter(max_failed_attempts=1)
        camera = FakeCameraSensor()
        service, store = build_service(
            tmp_path, face_score=0.1, attempt_limiter=limiter, sensors={"cam": camera}
        )
        store.save(make_enrollment(kind="face"))

        first = await service.capture_and_verify("cam", kind="face", sender_id="attacker")
        assert first.decision == Decision.LOW

        second = await service.capture_and_verify("cam", kind="face", sender_id="attacker")
        assert second.decision == Decision.INCONCLUSIVE
        assert second.reason == "locked_out"
        # The sensor is never touched once locked out: capture_and_verify
        # checks the lockout inside verify_face's own _verify() path, which
        # runs after capture_frame() -- confirming the lockout still fires
        # is the point of this test, not that capture is skipped (it isn't:
        # the image is captured, then _verify rejects it before calling the
        # provider). See docstring note in service.py if this changes.
        assert camera.capture_calls == 2
