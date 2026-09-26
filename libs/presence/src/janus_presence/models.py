from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PersonRecord:
    person_id: str
    known: bool
    first_seen_at: str
    last_seen_at: str
    label: str | None = None
    embedding_ids: list[int] = field(default_factory=list)
    snapshot_ref: str | None = None


@dataclass
class Sighting:
    sighting_id: str
    person_id: str
    camera_id: str
    seen_at: str
    confidence: float
    clip_ref: str | None = None


@dataclass
class ClipRecord:
    clip_ref: str
    camera_id: str
    started_at: str
    duration_s: int


@dataclass
class PersonSeenEvent:
    person_id: str
    known: bool
    first_seen: bool
    confidence: float
    camera_id: str
    timestamp: str
    snapshot_ref: str | None = None
    clip_ref: str | None = None
