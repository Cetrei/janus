from __future__ import annotations

import pytest
from conftest import make_enrollment

from janus_biometrics.base import Decision, PcmAudio
from janus_biometrics.errors import ModelMismatch
from janus_biometrics.policy import Thresholds
from janus_biometrics.providers.speaker_wespeaker import _MODEL_ID, WeSpeakerVerifier


class _FakeExtractor:
    """Double for WeSpeakerFeatureExtractor: returns a fixed embedding,
    letting tests control the resulting cosine score via the enrollment
    centroid instead of a real fbank/ONNX pipeline (blocked, see module
    docstring)."""

    def __init__(self, embedding: list[float]) -> None:
        self._embedding = embedding
        self.calls = 0

    def embed(self, audio: PcmAudio) -> list[float]:
        self.calls += 1
        return self._embedding


def _pcm(seconds: float, sample_rate: int = 16_000) -> PcmAudio:
    frame_count = int(seconds * sample_rate)
    # Non-zero samples so _trim_silence's energy threshold doesn't treat
    # the whole clip as silence.
    return PcmAudio(samples=b"\x00\x40" * frame_count, sample_rate=sample_rate)


def _voice_enrollment(centroid: list[float]) -> object:
    enrollment = make_enrollment(kind="voice")
    return enrollment.__class__(
        kind="voice",
        profile="owner",
        model_id=_MODEL_ID,
        dim=len(centroid),
        embeddings=[centroid],
        centroid=centroid,
        samples=1,
        created_at=enrollment.created_at,
    )


class TestWeSpeakerVerifier:
    @pytest.mark.asyncio
    async def test_model_mismatch_raises(self):
        verifier = WeSpeakerVerifier(_FakeExtractor([1.0]), Thresholds(t_high=0.8, t_low=0.5))
        enrollment = make_enrollment(kind="voice")  # model_id "fake-model-v1", not wespeaker's
        with pytest.raises(ModelMismatch):
            await verifier.verify(_pcm(3.0), enrollment)

    @pytest.mark.asyncio
    async def test_too_short_audio_is_inconclusive(self):
        verifier = WeSpeakerVerifier(
            _FakeExtractor([1.0, 0.0]), Thresholds(t_high=0.8, t_low=0.5), min_speech_s=2.5
        )
        enrollment = _voice_enrollment([1.0, 0.0])

        result = await verifier.verify(_pcm(1.0), enrollment)

        assert result.decision == Decision.INCONCLUSIVE
        assert result.reason == "too_short"

    @pytest.mark.asyncio
    async def test_high_similarity_yields_high_decision(self):
        verifier = WeSpeakerVerifier(
            _FakeExtractor([1.0, 0.0]), Thresholds(t_high=0.8, t_low=0.5), min_speech_s=2.5
        )
        enrollment = _voice_enrollment([1.0, 0.0])

        result = await verifier.verify(_pcm(3.0), enrollment)

        assert result.decision == Decision.HIGH
        assert result.reason == "ok"

    @pytest.mark.asyncio
    async def test_low_similarity_yields_low_decision(self):
        verifier = WeSpeakerVerifier(
            _FakeExtractor([0.0, 1.0]), Thresholds(t_high=0.8, t_low=0.5), min_speech_s=2.5
        )
        enrollment = _voice_enrollment([1.0, 0.0])

        result = await verifier.verify(_pcm(3.0), enrollment)

        assert result.decision == Decision.LOW

    @pytest.mark.asyncio
    async def test_default_liveness_mode_is_off_per_requisito_10(self):
        # requisito 10: v1 has no voice anti-spoofing; liveness stays
        # NOT_CHECKED regardless of score.
        verifier = WeSpeakerVerifier(_FakeExtractor([1.0, 0.0]), Thresholds(t_high=0.8, t_low=0.5))
        enrollment = _voice_enrollment([1.0, 0.0])

        result = await verifier.verify(_pcm(3.0), enrollment)

        from janus_biometrics.base import Liveness

        assert result.liveness == Liveness.NOT_CHECKED

    @pytest.mark.asyncio
    async def test_close_is_a_noop(self):
        verifier = WeSpeakerVerifier(_FakeExtractor([1.0]), Thresholds(t_high=0.8, t_low=0.5))
        assert await verifier.close() is None
