from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from janus_biometrics import ModelCache, detect_and_embed_faces

from janus_presence.decision_gate import DecisionGate, NoulQuestion
from janus_presence.errors import PersonNotFoundError, PresenceUnavailableError
from janus_presence.frame_source import FrameSource
from janus_presence.index import PresenceIndex
from janus_presence.models import ClipRecord, PersonRecord, PersonSeenEvent, Sighting
from janus_presence.store import PresenceStore, new_person_id, utcnow

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PresenceStatus:
    known_persons: int
    unknown_persons: int
    index_size: int


class PresenceService:
    """Orchestrates detection, matching, persistence and clip recording
    (requisitos 8, 11-20). Never assigns a role to a person (dueño,
    familiar, visita): it only emits who was seen, with a confidence.

    Reuses janus_biometrics.detect_and_embed_faces for YuNet+SFace
    detection/embedding (requisito 8bis on the biometrics side); has its
    own storage (PresenceStore) and its own matching policy (PresenceIndex
    + match_threshold), never biometrics' EncryptedTemplateStore or 1:1
    thresholds (Technical Decisions: presence separated from biometrics).
    """

    def __init__(
        self,
        store: PresenceStore,
        index: PresenceIndex,
        model_cache: ModelCache,
        frame_sources: dict[str, FrameSource],
        match_threshold: float,
        match_threshold_ambiguous: float,
        clip_duration_s: int,
        clips_root: Path,
        clips_max_total_mb: int,
        unknown_snapshot_retention_s: int,
        snapshots_root: Path,
        decision_gate: DecisionGate | None = None,
    ) -> None:
        if match_threshold_ambiguous <= match_threshold:
            raise ValueError("match_threshold_ambiguous must be greater than match_threshold")
        self._store = store
        self._index = index
        self._model_cache = model_cache
        self._frame_sources = frame_sources
        self._match_threshold = match_threshold
        self._match_threshold_ambiguous = match_threshold_ambiguous
        self._clip_duration_s = clip_duration_s
        self._clips_root = clips_root
        self._clips_max_total_mb = clips_max_total_mb
        self._unknown_snapshot_retention_s = unknown_snapshot_retention_s
        self._snapshots_root = snapshots_root
        self._decision_gate = decision_gate
        self._callbacks: list[Callable[[PersonSeenEvent], None]] = []
        self._next_hnsw_id = max((hid for _, hid in store.all_embeddings()), default=-1) + 1

        for person_id, hnsw_id, embedding in store.load_all_samples():
            self._index.insert(hnsw_id, embedding)
            _log.info("rebuilt hnsw index entry hnsw_id=%s person_id=%s", hnsw_id, person_id)

    # -- public API (per SPEC.md API Contracts) ------------------------------

    def process_frame(self, camera_id: str, frame: bytes) -> Sighting | None:
        """Detects every face in `frame` (requisito 11: unlike biometrics,
        multi-face is processed, never rejected), matches each against the
        index, updates or creates PersonRecords, and emits person_seen for
        each. Returns the last Sighting recorded, or None if no face was
        detected."""
        faces = detect_and_embed_faces(frame, self._model_cache)
        if not faces:
            return None

        last_sighting: Sighting | None = None
        for face in faces:
            last_sighting = self._process_one_face(
                camera_id, face.embedding, face.quality_ok
            )
        return last_sighting

    def _process_one_face(
        self, camera_id: str, embedding: list[float], quality_ok: bool
    ) -> Sighting:
        matches = self._index.search(embedding, k=1)
        person, first_seen, confidence = self._resolve_person(embedding, matches, quality_ok)

        now = utcnow()
        person.last_seen_at = now
        self._store.update_person(person)

        clip_ref: str | None = None
        if first_seen:
            clip = self.record_clip(camera_id, self._clip_duration_s)
            clip_ref = clip.clip_ref
        elif self._decision_gate is not None:
            question = NoulQuestion(
                prompt="Is this sighting worth recording a clip for?",
                person_id=person.person_id,
                known=person.known,
                first_seen=first_seen,
                camera_id=camera_id,
                confidence=confidence,
            )
            if self._decision_gate.should_record_clip(question):
                clip = self.record_clip(camera_id, self._clip_duration_s)
                clip_ref = clip.clip_ref

        sighting = Sighting(
            sighting_id=new_person_id(),
            person_id=person.person_id,
            camera_id=camera_id,
            seen_at=now,
            confidence=confidence,
            clip_ref=clip_ref,
        )
        self._store.record_sighting(sighting)
        self._emit(
            PersonSeenEvent(
                person_id=person.person_id,
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

    def _resolve_person(
        self, embedding: list[float], matches: list[tuple[int, float]], quality_ok: bool
    ) -> tuple[PersonRecord, bool, float]:
        if matches:
            hnsw_id, distance = matches[0]
            if distance <= self._match_threshold:
                person_id = self._store.person_id_for_hnsw_id(hnsw_id)
                if person_id is not None:
                    person = self._store.get_person(person_id)
                    if person is not None:
                        return person, False, self._confidence_from_distance(distance)
            # Ambiguous zone (requisito 5, 11): without a decision gate,
            # treated as a new unknown, documented as a known v1 limitation
            # until match_threshold is calibrated with real data.
            if distance <= self._match_threshold_ambiguous and self._decision_gate is not None:
                person_id = self._store.person_id_for_hnsw_id(hnsw_id)
                if person_id is not None:
                    person = self._store.get_person(person_id)
                    if person is not None:
                        return person, False, self._confidence_from_distance(distance)

        return self._create_unknown_person(embedding, quality_ok), True, 1.0

    def _create_unknown_person(self, embedding: list[float], quality_ok: bool) -> PersonRecord:
        now = utcnow()
        person_id = new_person_id()
        hnsw_id = self._next_hnsw_id
        self._next_hnsw_id += 1

        self._index.insert(hnsw_id, embedding)
        self._store.save_sample(person_id, hnsw_id, embedding)

        person = PersonRecord(
            person_id=person_id,
            known=False,
            embedding_ids=[hnsw_id],
            first_seen_at=now,
            last_seen_at=now,
            label=None,
            snapshot_ref=None,
        )
        self._store.create_person(person)
        self._store.add_embedding(person_id, hnsw_id)

        if quality_ok:
            person.snapshot_ref = self._save_snapshot(person_id)
            self._store.update_person(person)

        return person

    def _save_snapshot(self, person_id: str) -> str:
        # Path convention only: the actual JPEG bytes for the snapshot are
        # written by the caller from the originating frame, not derived
        # from the embedding here. Kept as a path reference (requisito 1:
        # `snapshot_ref: str`), consistent with retention (requisito 12).
        self._snapshots_root.mkdir(parents=True, exist_ok=True)
        return str(self._snapshots_root / f"{person_id}.jpg")

    def record_clip(self, camera_id: str, duration_s: int) -> ClipRecord:
        """Public, and the single execution path for all three trigger
        routes (requisito 16): deterministic (requisito 14), decision-model
        (requisito 15), and manual invocation all call this."""
        self._enforce_clip_retention()
        camera_dir = self._clips_root / camera_id
        camera_dir.mkdir(parents=True, exist_ok=True)
        now = utcnow()
        clip_ref = str(camera_dir / f"{now.strftime('%Y%m%dT%H%M%S')}.mp4")

        source = self._frame_sources.get(camera_id)
        if source is None:
            raise PresenceUnavailableError(
                f"camera:{camera_id}", "no FrameSource configured for this camera"
            )

        # Actual continuous capture for duration_s is a host/FrameSource
        # concern (requisito 14 only specifies the trigger and the
        # resulting ClipRecord); this records the intent and reference,
        # leaving the encoding loop to the FrameSource implementation used.
        _log.info(
            "recording clip camera_id=%s duration_s=%s -> %s", camera_id, duration_s, clip_ref
        )

        return ClipRecord(
            clip_ref=clip_ref, camera_id=camera_id, started_at=now, duration_s=duration_s
        )

    def enroll_known_person(self, label: str, samples: list[bytes]) -> PersonRecord:
        """Manual enrollment of an owner/family member (requisito 8):
        analogous to biometrics' enroll, but known=True from the start and
        never triggers the automatic "unknown" clip path."""
        if not samples:
            raise ValueError("enroll_known_person requires at least one sample")

        now = utcnow()
        person_id = new_person_id()
        hnsw_ids: list[int] = []

        for sample in samples:
            faces = detect_and_embed_faces(sample, self._model_cache)
            if not faces:
                continue
            embedding = faces[0].embedding
            hnsw_id = self._next_hnsw_id
            self._next_hnsw_id += 1
            self._index.insert(hnsw_id, embedding)
            self._store.save_sample(person_id, hnsw_id, embedding)
            hnsw_ids.append(hnsw_id)

        if not hnsw_ids:
            raise ValueError("No face could be detected in any of the provided samples")

        person = PersonRecord(
            person_id=person_id,
            known=True,
            embedding_ids=hnsw_ids,
            first_seen_at=now,
            last_seen_at=now,
            label=label,
            snapshot_ref=None,
        )
        self._store.create_person(person)
        for hnsw_id in hnsw_ids:
            self._store.add_embedding(person_id, hnsw_id)
        return person

    def name_person(self, person_id: str, label: str) -> PersonRecord:
        """Requisito 3, 20: the only known=False -> known=True transition.
        Deletes the retained snapshot (requisito 12); the embedding is kept
        indefinitely (Technical Decisions)."""
        person = self._store.get_person(person_id)
        if person is None:
            raise PersonNotFoundError(person_id)

        if person.snapshot_ref is not None:
            snapshot_path = Path(person.snapshot_ref)
            if snapshot_path.exists():
                self._secure_delete(snapshot_path)
            person.snapshot_ref = None

        person.label = label
        person.known = True
        self._store.update_person(person)
        return person

    def on_person_seen(self, callback: Callable[[PersonSeenEvent], None]) -> None:
        self._callbacks.append(callback)

    def status(self) -> PresenceStatus:
        known = 0
        unknown = 0
        for person_id, _ in self._store.all_embeddings():
            person = self._store.get_person(person_id)
            if person is None:
                continue
            if person.known:
                known += 1
            else:
                unknown += 1
        return PresenceStatus(
            known_persons=known,
            unknown_persons=unknown,
            index_size=len(self._store.all_embeddings()),
        )

    def close(self) -> None:
        self._index.close()
        self._store.close()

    # -- internal helpers -----------------------------------------------------

    def _emit(self, event: PersonSeenEvent) -> None:
        for callback in self._callbacks:
            callback(event)

    def _confidence_from_distance(self, distance: float) -> float:
        # Squared-Euclidean distance from hnsw-c: lower is more confident.
        # No calibrated mapping to a [0,1] confidence yet (Open Questions on
        # match_threshold itself); this is a monotonic placeholder, not a
        # calibrated probability.
        return max(0.0, 1.0 - distance)

    def _enforce_clip_retention(self) -> None:
        """requisito 17: hard cap on total clip disk space, deleting oldest
        first. Never blocks process_frame if there still isn't room after
        deleting everything eligible (Edge Cases table): logs and lets the
        caller's record_clip attempt proceed regardless."""
        if not self._clips_root.exists():
            return
        clip_paths = sorted(
            self._clips_root.rglob("*.mp4"), key=lambda p: p.stat().st_mtime
        )
        total_bytes = sum(p.stat().st_size for p in clip_paths)
        limit_bytes = self._clips_max_total_mb * 1024 * 1024
        idx = 0
        while total_bytes > limit_bytes and idx < len(clip_paths):
            path = clip_paths[idx]
            total_bytes -= path.stat().st_size
            path.unlink(missing_ok=True)
            idx += 1

    @staticmethod
    def _secure_delete(path: Path) -> None:
        import os
        import secrets

        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.write(secrets.token_bytes(size))
            handle.flush()
            os.fsync(handle.fileno())
        path.unlink()
