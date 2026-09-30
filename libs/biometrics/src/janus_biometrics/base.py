from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from janus_config import SecretRef

# SecretRef is re-exported so callers can keep importing it from
# janus_biometrics.base for backwards compatibility with code written
# against the provisional local declaration this replaces.

__all__ = [
    "BiometricResult",
    "Decision",
    "Enrollment",
    "FaceEmbedding",
    "FaceVerifier",
    "Liveness",
    "PcmAudio",
    "SecretRef",
    "SpeakerVerifier",
    "VoiceEmbedding",
]


class Decision(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INCONCLUSIVE = "INCONCLUSIVE"


class Liveness(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True)
class PcmAudio:
    """16-bit mono PCM audio at 16 kHz."""

    samples: bytes
    sample_rate: int = 16_000

    def __post_init__(self) -> None:
        if self.sample_rate != 16_000:
            raise ValueError("PcmAudio requires 16 kHz mono audio")


@dataclass(frozen=True)
class BiometricResult:
    """Outcome of a 1:1 verification. `score` is intentionally not a field:
    it never leaves janus_biometrics (requisito 16)."""

    decision: Decision
    liveness: Liveness
    quality_ok: bool
    reason: str
    provider_id: str
    model_id: str


@dataclass(frozen=True)
class FaceEmbedding:
    """Raw detection output for the bounded exception (requisito 8bis).
    Consumed only by libs/presence for 1:N identification. Callers receive
    raw biometric data and are responsible for their own safe handling."""

    embedding: list[float]
    quality_ok: bool
    # (x, y, w, h) in pixels of the original frame, clamped to it. Optional so
    # every existing caller keeps working; libs/presence uses it to know
    # where to zoom in a clip (requisito 32). A location is not a secret
    # biometric, unlike the embedding.
    bbox: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if len(self.embedding) != 128:
            raise ValueError("FaceEmbedding requires a 128-dim SFace embedding")


@dataclass(frozen=True)
class VoiceEmbedding:
    """Raw voice output for the bounded exception (requisito 8ter b), the
    voice counterpart of FaceEmbedding. Consumed only by libs/presence for
    1:N identification. `speech_s` is the speech left after trimming silence;
    `quality_ok` is False when that is under the minimum speech duration, so
    the caller decides whether so short a sample is worth matching on."""

    embedding: list[float]
    speech_s: float
    quality_ok: bool

    def __post_init__(self) -> None:
        if len(self.embedding) != 256:
            raise ValueError("VoiceEmbedding requires a 256-dim WeSpeaker embedding")


@dataclass(frozen=True)
class Enrollment:
    """Enrolled template for one kind/profile pair."""

    kind: str  # "face" | "voice"
    profile: str
    model_id: str
    dim: int
    embeddings: list[list[float]]
    centroid: list[float]
    samples: int
    created_at: datetime = field(default_factory=datetime.utcnow)


class FaceVerifier(ABC):
    id: str

    @abstractmethod
    async def verify(self, image: bytes, enrollment: Enrollment) -> BiometricResult: ...

    @abstractmethod
    async def close(self) -> None: ...


class SpeakerVerifier(ABC):
    id: str

    @abstractmethod
    async def verify(self, audio: PcmAudio, enrollment: Enrollment) -> BiometricResult: ...

    @abstractmethod
    async def close(self) -> None: ...
