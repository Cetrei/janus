from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from janus_biometrics.base import (
    BiometricResult,
    Decision,
    FaceVerifier,
    Liveness,
    PcmAudio,
    SpeakerVerifier,
)
from janus_biometrics.errors import SensorUnavailable
from janus_biometrics.policy import AttemptLimiter, Thresholds
from janus_biometrics.registry import ProviderRegistry
from janus_biometrics.store import EncryptedTemplateStore

if TYPE_CHECKING:
    from janus_biometrics.sensors import SensorSource

_log = logging.getLogger(__name__)

_NOT_ENROLLED = "not_enrolled"
_LOCKED_OUT = "locked_out"
_MODEL_UNAVAILABLE = "model_unavailable"
_UNKNOWN_SENSOR = "unknown_sensor"
_SENSOR_UNAVAILABLE = "sensor_unavailable"
_UNKNOWN_KIND = "unknown_kind"


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
        sensors: dict[str, SensorSource] | None = None,
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
        # Sensors are looked up by SensorConfig.id (requisito 21), not by
        # hardware index, so capture_and_verify's caller (the core) never
        # needs to know which camera/microphone index a named sensor maps
        # to on this particular machine. Empty by default: a service used
        # only with message-attached samples (verify_face/verify_voice
        # called directly, no local sensor) has no sensors to register.
        self._sensors: dict[str, SensorSource] = dict(sensors or {})

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

    async def capture_and_verify(
        self,
        sensor_id: str,
        kind: str,
        profile: str = "owner",
        sender_id: str | None = None,
    ) -> BiometricResult:
        """Captures one bounded sample from a configured local sensor and
        verifies it (requisito 23). This is the only path that touches
        hardware directly: verify_face/verify_voice take a sample the
        caller already has (a message attachment), while this method is
        for a channel whose policy names a local sensor instead
        (requisito 21). Never raises on the normal path, same contract as
        verify_face/verify_voice: an unknown sensor id, a kind mismatch, or
        a hardware failure (SensorUnavailable) all resolve to INCONCLUSIVE
        with a reason rather than propagating (Edge Cases table, spec-18:
        "Camara u microfono ocupado o ausente -> SensorUnavailable;
        INCONCLUSIVE con motivo").
        """
        source = self._sensors.get(sensor_id)
        if source is None:
            return self._inconclusive(kind, _UNKNOWN_SENSOR)

        try:
            if kind == "face":
                image = await asyncio.to_thread(source.capture_frame)
                return await self.verify_face(image, profile=profile, sender_id=sender_id)
            if kind == "voice":
                audio = await asyncio.to_thread(source.capture_audio, 3.0)
                return await self.verify_voice(audio, profile=profile, sender_id=sender_id)
            _log.warning("capture_and_verify: unknown kind '%s' for sensor '%s'", kind, sensor_id)
            return self._inconclusive(kind, _UNKNOWN_KIND)
        except (SensorUnavailable, NotImplementedError) as exc:
            # NotImplementedError: a sensor registered under the wrong kind
            # (e.g. a CameraSource asked for capture_audio) -- same
            # INCONCLUSIVE contract as a hardware-level SensorUnavailable,
            # since from the caller's perspective both mean "this sensor
            # could not deliver what capture_and_verify needed".
            _log.warning(
                "sensor '%s' unavailable for kind=%s: %s", sensor_id, kind, exc
            )
            return self._inconclusive(kind, _SENSOR_UNAVAILABLE)

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
