from __future__ import annotations

from janus_biometrics.base import (
    BiometricResult,
    Decision,
    Enrollment,
    FaceVerifier,
    Liveness,
    PcmAudio,
    SpeakerVerifier,
)

_PROVIDER_ID = "null"
_MODEL_ID = "null"


class NullFaceVerifier(FaceVerifier):
    """Disables the face signal without conditionals in the core (requisito 3)."""

    id = _PROVIDER_ID

    def __init__(self, variant: str | None = None) -> None:
        del variant

    async def verify(self, image: bytes, enrollment: Enrollment) -> BiometricResult:
        del image, enrollment
        return BiometricResult(
            decision=Decision.INCONCLUSIVE,
            liveness=Liveness.NOT_CHECKED,
            quality_ok=False,
            reason="signal_disabled",
            provider_id=_PROVIDER_ID,
            model_id=_MODEL_ID,
        )

    async def close(self) -> None:
        return None


class NullSpeakerVerifier(SpeakerVerifier):
    """Disables the voice signal without conditionals in the core (requisito 3)."""

    id = _PROVIDER_ID

    def __init__(self, variant: str | None = None) -> None:
        del variant

    async def verify(self, audio: PcmAudio, enrollment: Enrollment) -> BiometricResult:
        del audio, enrollment
        return BiometricResult(
            decision=Decision.INCONCLUSIVE,
            liveness=Liveness.NOT_CHECKED,
            quality_ok=False,
            reason="signal_disabled",
            provider_id=_PROVIDER_ID,
            model_id=_MODEL_ID,
        )

    async def close(self) -> None:
        return None
