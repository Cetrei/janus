from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from janus_biometrics.base import (
    BiometricResult,
    Decision,
    FaceVerifier,
    Liveness,
    PcmAudio,
    SpeakerVerifier,
)
from janus_biometrics.policy import AttemptLimiter, Thresholds
from janus_biometrics.registry import ProviderRegistry
from janus_biometrics.store import EncryptedTemplateStore

_log = logging.getLogger(__name__)

_NOT_ENROLLED = "not_enrolled"
_LOCKED_OUT = "locked_out"
_MODEL_UNAVAILABLE = "model_unavailable"


@dataclass(frozen=True)
class ProviderHealth:
    kind: str
    provider_id: str
    loaded: bool
    state: str


@dataclass(frozen=True)
class BiometricStatus:
    providers: list[ProviderHealth]
    enrolled: list[dict[str, str]]
    lockouts: list[str]


class BiometricService:
    """Facade consumed only by the core (requisito 5, 23). Never raises on
    the normal verification path: missing template, missing model, or a
    locked-out signal all resolve to INCONCLUSIVE with a reason."""

    def __init__(
        self,
        registry: ProviderRegistry,
        store: EncryptedTemplateStore,
        face_thresholds: Thresholds,
        voice_thresholds: Thresholds,
        face_provider_ref: str = "null",
        voice_provider_ref: str = "null",
        face_liveness_mode: str = "required",
        attempt_limiter: AttemptLimiter | None = None,
        inference_concurrency: int = 1,
    ) -> None:
        self._registry = registry
        self._store = store
        self._face_thresholds = face_thresholds
        self._voice_thresholds = voice_thresholds
        self._face_provider_ref = face_provider_ref
        self._voice_provider_ref = voice_provider_ref
        self._face_liveness_mode = face_liveness_mode
        self._attempt_limiter = attempt_limiter or AttemptLimiter()
        self._semaphore = asyncio.Semaphore(inference_concurrency)
        self._face_verifier: FaceVerifier | None = None
        self._speaker_verifier: SpeakerVerifier | None = None

    async def verify_face(
        self, image: bytes, profile: str = "owner", sender_id: str | None = None
    ) -> BiometricResult:
        return await self._verify(
            kind="face",
            profile=profile,
            sender_id=sender_id,
            perform=lambda verifier, enrollment: verifier.verify(image, enrollment),
            resolve_verifier=lambda: self._get_face_verifier(),
        )

    async def verify_voice(
        self, audio: PcmAudio, profile: str = "owner", sender_id: str | None = None
    ) -> BiometricResult:
        return await self._verify(
            kind="voice",
            profile=profile,
            sender_id=sender_id,
            perform=lambda verifier, enrollment: verifier.verify(audio, enrollment),
            resolve_verifier=lambda: self._get_speaker_verifier(),
        )

    async def _verify(
        self,
        kind: str,
        profile: str,
        sender_id: str | None,
        perform,
        resolve_verifier,
    ) -> BiometricResult:
        if sender_id is not None and self._attempt_limiter.is_locked(sender_id):
            return self._inconclusive(kind, _LOCKED_OUT)

        enrollment = self._store.load(kind, profile)
        if enrollment is None:
            return self._inconclusive(kind, _NOT_ENROLLED)

        try:
            verifier = resolve_verifier()
        except (KeyError, ImportError) as exc:
            _log.warning("biometric provider unavailable for kind=%s: %s", kind, exc)
            return self._inconclusive(kind, _MODEL_UNAVAILABLE)

        async with self._semaphore:
            result = await perform(verifier, enrollment)

        if sender_id is not None:
            if result.decision == Decision.HIGH:
                self._attempt_limiter.record_success(sender_id)
            elif result.decision == Decision.LOW:
                self._attempt_limiter.record_failure(sender_id)

        return result

    def _get_face_verifier(self) -> FaceVerifier:
        if self._face_verifier is None:
            self._face_verifier = self._registry.resolve_face(self._face_provider_ref)
        return self._face_verifier

    def _get_speaker_verifier(self) -> SpeakerVerifier:
        if self._speaker_verifier is None:
            self._speaker_verifier = self._registry.resolve_speaker(self._voice_provider_ref)
        return self._speaker_verifier

    @staticmethod
    def _inconclusive(kind: str, reason: str) -> BiometricResult:
        return BiometricResult(
            decision=Decision.INCONCLUSIVE,
            liveness=Liveness.NOT_CHECKED,
            quality_ok=False,
            reason=reason,
            provider_id="none",
            model_id="none",
        )

    async def status(self) -> BiometricStatus:
        providers = []
        if self._face_verifier is not None:
            providers.append(ProviderHealth("face", self._face_verifier.id, True, "OK"))
        if self._speaker_verifier is not None:
            providers.append(ProviderHealth("voice", self._speaker_verifier.id, True, "OK"))
        enrolled = []
        for kind in ("face", "voice"):
            if self._store.exists(kind, "owner"):
                enrolled.append({"kind": kind, "profile": "owner"})
        return BiometricStatus(providers=providers, enrolled=enrolled, lockouts=[])

    async def close(self) -> None:
        if self._face_verifier is not None:
            await self._face_verifier.close()
        if self._speaker_verifier is not None:
            await self._speaker_verifier.close()
