from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import numpy as np

from janus_presence.errors import PersonNotFoundError
from janus_presence.frame_source import FrameSource
from janus_presence.index import PresenceIndex
from janus_presence.models import ClipRecord, PersonRecord, PersonSeenEvent, Sighting
from janus_presence.store import PresenceStore


@dataclass
class FaceDetection:
    embedding: np.ndarray
    quality_ok: bool


class FaceEmbedder(Protocol):
    def detect_and_embed(self, frame: bytes) -> list[FaceDetection]: ...


class PresenceService:
    def __init__(
        self,
        store: PresenceStore,
        index: PresenceIndex,
        embedder: FaceEmbedder,
        frame_source: FrameSource,
        match_threshold: float,
        match_threshold_ambiguous: float,
        clip_duration_s: int,
        decision_model_enabled: bool = False,
        decision_model_confidence_threshold: float = 0.85,
        decision_gate=None,
    ) -> None:
        self._store = store
        self._index = index
        self._embedder = embedder
        self._frame_source = frame_source
        self._match_threshold = match_threshold
        self._match_threshold_ambiguous = match_threshold_ambiguous
        self._clip_duration_s = clip_duration_s
        self._decision_model_enabled = decision_model_enabled
        self._decision_model_confidence_threshold = decision_model_confidence_threshold
        self._decision_gate = decision_gate
        self._listeners: list = []
        self._next_hnsw_id = 0

    def on_person_seen(self, callback) -> None:
        self._listeners.append(callback)

    def enroll_known_person(self, label: str, samples: list[bytes]) -> PersonRecord:
        person_id = str(uuid4())
        now = self._now()
        person = PersonRecord(
            person_id=person_id,
            known=True,
            first_seen_at=now,
            last_seen_at=now,
            label=label,
        )
        self._store.insert_person(person)
        for sample in samples:
            for detection in self._embedder.detect_and_embed(sample):
                self._insert_embedding(person_id, detection.embedding)
        return self._store.get_person(person_id)

    def name_person(self, person_id: str, label: str) -> PersonRecord:
        return self._store.name_person(person_id, label)

    def process_frame(self, camera_id: str, frame: bytes) -> Sighting | None:
        detections = self._embedder.detect_and_embed(frame)
        if not detections:
            return None
        last_sighting = None
        for detection in detections:
            last_sighting = self._process_single_face(camera_id, detection)
        return last_sighting

    def _process_single_face(self, camera_id: str, detection: FaceDetection) -> Sighting:
        matches = self._index.search(detection.embedding, k=5)
        person_id, first_seen, confidence = self._resolve_match(matches)

        now = self._now()
        if first_seen:
            self._store.update_last_seen(person_id, now)
        else:
            self._store.update_last_seen(person_id, now)

        clip_ref = None
        if first_seen:
            clip = self.record_clip(camera_id, self._clip_duration_s)
            clip_ref = clip.clip_ref
        elif self._decision_model_enabled and self._decision_gate is not None:
            if self._decision_gate.should_record(person_id, camera_id, first_seen=False):
                clip = self.record_clip(camera_id, self._clip_duration_s)
                clip_ref = clip.clip_ref

        person = self._store.get_person(person_id)
        sighting = Sighting(
            sighting_id=str(uuid4()),
            person_id=person_id,
            camera_id=camera_id,
            seen_at=now,
            confidence=confidence,
            clip_ref=clip_ref,
        )
        self._store.insert_sighting(sighting)

        self._emit(
            PersonSeenEvent(
                person_id=person_id,
                known=person.known,
                first_seen=first_seen,
                confidence=confidence,
                camera_id=camera_id,
                timestamp=now,
                snapshot_ref=person.snapshot_ref,
                clip_ref=clip_ref,
            )
        )
        return sighting

    def _resolve_match(self, matches: list[tuple[int, float]]) -> tuple[str, bool, float]:
        if matches:
            best_hnsw_id, best_distance = matches[0]
            if best_distance <= self._match_threshold:
                person_id = self._store.get_person_id_for_hnsw_id(best_hnsw_id)
                return person_id, False, self._confidence_from_distance(best_distance)
        return self._create_unknown_person(), True, 1.0

    def _create_unknown_person(self) -> str:
        person_id = str(uuid4())
        now = self._now()
        person = PersonRecord(
            person_id=person_id,
            known=False,
            first_seen_at=now,
            last_seen_at=now,
        )
        self._store.insert_person(person)
        return person_id

    def _insert_embedding(self, person_id: str, embedding: np.ndarray) -> int:
        hnsw_id = self._next_hnsw_id
        self._next_hnsw_id += 1
        self._index.insert(hnsw_id, embedding)
        return self._store.add_embedding(person_id, hnsw_id)

    def record_clip(self, camera_id: str, duration_s: int) -> ClipRecord:
        return ClipRecord(
            clip_ref=str(uuid4()),
            camera_id=camera_id,
            started_at=self._now(),
            duration_s=duration_s,
        )

    def status(self):
        raise NotImplementedError

    def _confidence_from_distance(self, distance: float) -> float:
        if distance <= 0:
            return 1.0
        return max(0.0, 1.0 - (distance / self._match_threshold))

    def _emit(self, event: PersonSeenEvent) -> None:
        for listener in self._listeners:
            listener(event)

    def _now(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
