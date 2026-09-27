from __future__ import annotations

from datetime import UTC, datetime

import pytest

from janus_biometrics.base import (
    BiometricResult,
    Decision,
    Enrollment,
    FaceVerifier,
    Liveness,
    PcmAudio,
    SpeakerVerifier,
)

FAKE_MODEL_ID = "fake-model-v1"


def make_enrollment(kind: str = "face", profile: str = "owner") -> Enrollment:
    return Enrollment(
        kind=kind,
        profile=profile,
        model_id=FAKE_MODEL_ID,
        dim=4,
        embeddings=[[0.1, 0.2, 0.3, 0.4]] * 5,
        centroid=[0.1, 0.2, 0.3, 0.4],
        samples=5,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class FakeFaceVerifier(FaceVerifier):
    """Deterministic fake: the score to return is set by the test."""

    id = "fake:face"

    def __init__(
        self,
        score: float = 0.95,
        liveness: Liveness = Liveness.PASS,
        quality_ok: bool = True,
        variant: str | None = None,
    ) -> None:
        del variant
        self.score = score
        self.liveness = liveness
        self.quality_ok = quality_ok
        self.closed = False

    async def verify(self, image: bytes, enrollment: Enrollment) -> BiometricResult:
        del image, enrollment
        decision = Decision.HIGH if self.score >= 0.8 else Decision.LOW
        return BiometricResult(
            decision=decision,
            liveness=self.liveness,
            quality_ok=self.quality_ok,
            reason="ok",
            provider_id=self.id,
            model_id=FAKE_MODEL_ID,
        )

    async def close(self) -> None:
        self.closed = True


class FakeSpeakerVerifier(SpeakerVerifier):
    id = "fake:speaker"

    def __init__(self, score: float = 0.95, variant: str | None = None) -> None:
        del variant
        self.score = score
        self.closed = False

    async def verify(self, audio: PcmAudio, enrollment: Enrollment) -> BiometricResult:
        del audio, enrollment
        decision = Decision.HIGH if self.score >= 0.8 else Decision.LOW
        return BiometricResult(
            decision=decision,
            liveness=Liveness.NOT_CHECKED,
            quality_ok=True,
            reason="ok",
            provider_id=self.id,
            model_id=FAKE_MODEL_ID,
        )

    async def close(self) -> None:
        self.closed = True


class FakeClock:
    """Deterministic clock for AttemptLimiter tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def enrollment() -> Enrollment:
    return make_enrollment()


@pytest.fixture
def tmp_state_dir(tmp_path):
    return tmp_path / "state"
