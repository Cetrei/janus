from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

__all__ = [
    "NO_INDEXED_EMBEDDING",
    "CameraConfig",
    "CameraSourceKind",
    "Candidate",
    "ClipRecord",
    "Evidence",
    "EvidenceStatus",
    "EvidenceOrigin",
    "IdentifyResult",
    "IdentityState",
    "PersonRecord",
    "PersonSeenEvent",
    "PresenceConfig",
    "Sighting",
    "SourceConfig",
    "SourceKind",
    "SourceLocation",
    "Visit",
]


# Evidence.hnsw_id sentinel: the evidence has no embedding of its own in the
# index. Its embedding (if any) sits as an encrypted pending sample until the
# owner confirms it (requisitos 27, 28).
NO_INDEXED_EMBEDDING = -1


class CameraSourceKind(StrEnum):
    LOCAL = "local"
    MCP = "mcp"


class SourceKind(StrEnum):
    """requisito 21: a source is a camera or a microphone."""

    CAMERA = "camera"
    MICROPHONE = "microphone"


class SourceLocation(StrEnum):
    """requisito 21: where a source's frames/audio actually come from."""

    LOCAL = "local"
    RTSP = "rtsp"
    MCP = "mcp"


class IdentityState(StrEnum):
    """requisito 26: ciclo de vida de identidad. `known` (requisito 1) is
    derived as `state != UNKNOWN`, never stored separately."""

    UNKNOWN = "unknown"
    PROVISIONAL = "provisional"
    ESTABLISHED = "established"


class EvidenceStatus(StrEnum):
    """requisito 27: an appearance/utterance seen without the owner present
    starts PENDING and never touches any template until it is CONFIRMED."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    DISCARDED = "discarded"


class EvidenceOrigin(StrEnum):
    """requisito 28: every reinforcement records where it came from, so it
    can be retracted (retract_evidence)."""

    OWNER_CONFIRMED = "owner_confirmed"
    DUAL_MODALITY = "dual_modality"
    ENROLL = "enroll"
    PRETRAIN = "pretrain"


@dataclass
class PersonRecord:
    """Identity that presence itself manages (requisitos 1-3, 25, 26).
    `person_id` is presence's own UUID, unrelated to any id from
    janus_biometrics.

    `known` is derived from `state` (requisito 26): True once state is no
    longer UNKNOWN. A recurring unknown stays state=UNKNOWN (known=False)
    even though presence already recognizes them across sightings; naming
    them moves state to PROVISIONAL.
    """

    person_id: str
    state: IdentityState
    embedding_ids: list[int]
    first_seen_at: datetime
    last_seen_at: datetime
    label: str | None = None
    role: str | None = None
    snapshot_ref: str | None = None
    presented_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.state != IdentityState.UNKNOWN and self.label is None:
            raise ValueError(
                "A PersonRecord past UNKNOWN must have a label (requisitos 3, 26)"
            )

    @property
    def known(self) -> bool:
        """requisito 26: known = state != UNKNOWN."""
        return self.state != IdentityState.UNKNOWN


@dataclass(frozen=True)
class Sighting:
    """One detection event for a person on a source (requisito 6, table
    `sightings`)."""

    sighting_id: str
    person_id: str
    camera_id: str
    seen_at: datetime
    confidence: float
    clip_ref: str | None = None


@dataclass(frozen=True)
class ClipRecord:
    """A recorded clip on disk (requisito 17)."""

    clip_ref: str
    camera_id: str
    started_at: datetime
    duration_s: int


@dataclass(frozen=True)
class PersonSeenEvent:
    """The single per-frame event janus_presence emits to whoever consumes
    it (requisito 18). Kept for compatibility alongside visit_started /
    visit_ended (requisito 30). Transport is not fixed by the spec: this is
    just the payload a registered Python callback receives."""

    person_id: str
    known: bool
    first_seen: bool
    confidence: float
    camera_id: str
    timestamp: datetime
    snapshot_ref: str | None = None
    clip_ref: str | None = None


@dataclass(frozen=True)
class Visit:
    """requisito 30: opened on the first sighting of a person on a source,
    closed after visit_gap_s without seeing them. person_seen keeps firing
    per frame; visit_started/visit_ended are the coarser events."""

    visit_id: str
    person_id: str
    source_id: str
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None = None
    clip_ref: str | None = None


@dataclass(frozen=True)
class Candidate:
    """One candidate identity returned by `identify` (requisito 22)."""

    person_id: str
    label: str | None
    role: str | None
    state: IdentityState
    confidence: float


@dataclass(frozen=True)
class IdentifyResult:
    """requisito 22: read-only result of `identify`. Never created, never
    written; an empty `candidates` list means no match, not a fabricated
    unknown."""

    candidates: list[Candidate]
    modalities: list[str]
    conflict: bool = False


@dataclass
class Evidence:
    """requisito 27: appearance/utterance recorded without the owner
    present. PENDING never modifies any template or the identity index.
    Only CONFIRMED reinforces (requisito 28); REJECTED records a
    counterexample in person_exclusions; DISCARDED drops it with no
    effect."""

    evidence_id: str
    person_id: str
    source_id: str
    modality: str
    hnsw_id: int
    captured_at: datetime
    status: EvidenceStatus = EvidenceStatus.PENDING
    hypothesis_person_id: str | None = None
    hypothesis_confidence: float | None = None
    presented_at: datetime | None = None
    origin: EvidenceOrigin | None = None
    # True once confirming this evidence added its embedding to the identity
    # (requisito 28). Retracting it must then remove that embedding again.
    promoted: bool = False


@dataclass(frozen=True)
class SourceConfig:
    """requisito 21: one configured camera or microphone."""

    source_id: str
    kind: SourceKind
    source: SourceLocation
    device: str
    label: str
    enabled: bool = True
    sample_fps: float | None = None


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    label: str
    source: CameraSourceKind = CameraSourceKind.LOCAL


@dataclass
class PresenceConfig:
    """Config knobs from the spec's `Config presence` block plus the
    2026-09-27 ampliación. Deliberately no factory defaults for the two
    face match thresholds (requisito 5, Open Questions): they must be
    calibrated with real data before use, same honesty criterion spec-18
    applies to its own thresholds.
    """

    match_threshold: float
    match_threshold_ambiguous: float
    clip_duration_s: int = 15
    clips_max_total_mb: int = 2048
    unknown_snapshot_retention_s: int = 86_400
    decision_model_enabled: bool = False
    decision_model_confidence_threshold: float = 0.85
    cameras: list[CameraConfig] = field(default_factory=list)
    sources: list[SourceConfig] = field(default_factory=list)
    roles: list[str] = field(default_factory=lambda: ["owner", "family", "guest", "staff"])
    established_min_samples: int = 5
    provisional_confidence_cap: float = 0.7
    auto_reinforce_dual_modality: bool = False
    max_samples_per_person: int = 20
    visit_gap_s: int = 30
    forget_after_days: int = 30
    clip_preroll_s: int = 5
    clip_audio: bool = False
    # requisito 23: the voice modality has its own thresholds, also without a
    # factory default. Both None means voice is off; setting one without the
    # other is a config error.
    voice_match_threshold: float | None = None
    voice_match_threshold_ambiguous: float | None = None

    def __post_init__(self) -> None:
        if self.match_threshold_ambiguous <= self.match_threshold:
            raise ValueError(
                "match_threshold_ambiguous must be greater than match_threshold "
                "(requisito 5: the ambiguous zone sits above the main threshold)"
            )
        voice_low = self.voice_match_threshold
        voice_high = self.voice_match_threshold_ambiguous
        if (voice_low is None) != (voice_high is None):
            raise ValueError(
                "voice_match_threshold and voice_match_threshold_ambiguous must be set together"
            )
        if voice_low is not None and voice_high is not None and voice_high <= voice_low:
            raise ValueError(
                "voice_match_threshold_ambiguous must be greater than voice_match_threshold"
            )
