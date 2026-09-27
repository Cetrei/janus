from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

__all__ = [
    "CameraConfig",
    "CameraSourceKind",
    "ClipRecord",
    "PersonRecord",
    "PersonSeenEvent",
    "PresenceConfig",
    "Sighting",
]


class CameraSourceKind(StrEnum):
    LOCAL = "local"
    MCP = "mcp"


@dataclass
class PersonRecord:
    """Identity that presence itself manages (requisitos 1-3). `person_id`
    is presence's own UUID, unrelated to any id from janus_biometrics.

    `known` becomes True only when `label` is set (requisito 3): a
    recurring unknown is still `known=False` even though presence already
    recognizes them across sightings.
    """

    person_id: str
    known: bool
    embedding_ids: list[int]
    first_seen_at: datetime
    last_seen_at: datetime
    label: str | None = None
    snapshot_ref: str | None = None

    def __post_init__(self) -> None:
        if self.known and self.label is None:
            raise ValueError("A known PersonRecord must have a label (requisito 3)")


@dataclass(frozen=True)
class Sighting:
    """One detection event for a person on a camera (requisito 6, table
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
    """The single event janus_presence emits to whoever consumes it
    (requisito 18). Transport is not fixed by the spec: this is just the
    payload a registered Python callback receives."""

    person_id: str
    known: bool
    first_seen: bool
    confidence: float
    camera_id: str
    timestamp: datetime
    snapshot_ref: str | None = None
    clip_ref: str | None = None


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    label: str
    source: CameraSourceKind = CameraSourceKind.LOCAL


@dataclass
class PresenceConfig:
    """Config knobs from the spec's `Config presence` block. Deliberately
    no factory defaults for the two match thresholds (requisito 5, Open
    Questions): they must be calibrated with real data before use, same
    honesty criterion spec-18 applies to its own thresholds.
    """

    match_threshold: float
    match_threshold_ambiguous: float
    clip_duration_s: int = 15
    clips_max_total_mb: int = 2048
    unknown_snapshot_retention_s: int = 86_400
    decision_model_enabled: bool = False
    decision_model_confidence_threshold: float = 0.85
    cameras: list[CameraConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.match_threshold_ambiguous <= self.match_threshold:
            raise ValueError(
                "match_threshold_ambiguous must be greater than match_threshold "
                "(requisito 5: the ambiguous zone sits above the main threshold)"
            )
