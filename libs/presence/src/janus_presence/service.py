from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from janus_biometrics import ModelCache, detect_and_embed_faces

from janus_presence.decision_gate import DecisionGate, NoulQuestion
from janus_presence.errors import PersonNotFoundError, PresenceError, PresenceUnavailableError
from janus_presence.frame_source import FrameSource
from janus_presence.index import PresenceIndex
from janus_presence.models import (
    NO_INDEXED_EMBEDDING,
    Candidate,
    ClipRecord,
    Evidence,
    EvidenceOrigin,
    EvidenceStatus,
    IdentifyResult,
    IdentityState,
    PersonRecord,
    PersonSeenEvent,
    Sighting,
    Visit,
)
from janus_presence.store import PresenceStore, new_person_id, secure_delete, utcnow

_log = logging.getLogger(__name__)

_FACE_MODALITY = "face"

# Neighbours returned by one search. The best one that maps to a live person
# decides the match; the rest feed the hypothesis attached to pending
# evidence (requisito 27).
_SEARCH_K = 5


@dataclass(frozen=True)
class PresenceStatus:
    known_persons: int
    unknown_persons: int
    index_size: int


def _squared_distance(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True))


def _most_redundant(samples: dict[int, list[float]], all_ids: list[int]) -> int:
    """The id whose removal loses the least information (requisito 28,
    "reemplazo de las más redundantes"): an id with no readable sample goes
    first, otherwise the one whose nearest sibling is closest. Ties go to
    the oldest id."""
    missing = [hnsw_id for hnsw_id in all_ids if hnsw_id not in samples]
    if missing:
        return min(missing)

    def nearest_sibling(hnsw_id: int) -> float:
        distances = (
            _squared_distance(samples[hnsw_id], samples[other])
            for other in samples
            if other != hnsw_id
        )
        return min(distances, default=float("inf"))

    return min(samples, key=lambda hnsw_id: (nearest_sibling(hnsw_id), hnsw_id))


class PresenceService:
    """Orchestrates detection, matching, persistence and clip recording
    (requisitos 8, 11-20, and the 2026-09-27 ampliación: 22, 26-30, 34, 37).

    Reuses janus_biometrics.detect_and_embed_faces for YuNet+SFace
    detection/embedding (requisito 8bis on the biometrics side); has its
    own storage (PresenceStore) and its own matching policy (PresenceIndex
    + match_threshold), never biometrics' EncryptedTemplateStore or 1:1
    thresholds (Technical Decisions: presence separated from biometrics).

    The in-memory index is derived state: everything it holds can be rebuilt
    from the encrypted samples in the store, which is the source of truth.
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
        established_min_samples: int = 5,
        provisional_confidence_cap: float = 0.7,
        visit_gap_s: int = 30,
        forget_after_days: int = 30,
        max_samples_per_person: int = 20,
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
        self._established_min_samples = established_min_samples
        self._provisional_confidence_cap = provisional_confidence_cap
        self._visit_gap_s = visit_gap_s
        self._forget_after_days = forget_after_days
        self._max_samples_per_person = max_samples_per_person
        self._callbacks: list[Callable[[PersonSeenEvent], None]] = []
        self._next_hnsw_id = (
            max((hid for _, hid in store.all_embeddings(_FACE_MODALITY)), default=-1) + 1
        )
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """requisito 7: hnsw-c cannot persist yet, so the face index is
        rebuilt at startup from the encrypted samples. Only samples that
        still have a database row are loaded: a file left behind by a crash
        must not become a phantom neighbour nobody can name."""
        known_ids = {hnsw_id for _, hnsw_id in self._store.all_embeddings(_FACE_MODALITY)}
        samples = sorted(self._store.load_all_samples(_FACE_MODALITY), key=lambda s: s[1])
        for person_id, hnsw_id, embedding in samples:
            if hnsw_id not in known_ids:
                _log.warning(
                    "skipping orphan sample hnsw_id=%s person_id=%s (no database row)",
                    hnsw_id,
                    person_id,
                )
                continue
            self._index.insert(hnsw_id, embedding)
            _log.info("rebuilt hnsw index entry hnsw_id=%s person_id=%s", hnsw_id, person_id)

    def _allocate_hnsw_id(self) -> int:
        hnsw_id = self._next_hnsw_id
        self._next_hnsw_id += 1
        return hnsw_id

    # -- identify vs observe (requisito 22) ------------------------------------

    def identify(self, sample: bytes) -> IdentifyResult:
        """requisito 22: read-only. Never creates a person, never writes a
        sighting or a visit, never touches any template, never emits
        person_seen. An empty candidate list means no match, not a
        fabricated unknown."""
        faces = detect_and_embed_faces(sample, self._model_cache)
        if not faces:
            return IdentifyResult(candidates=[], modalities=[])

        candidates = [
            candidate
            for face in faces
            if (candidate := self._candidate_for(face.embedding)) is not None
        ]
        return IdentifyResult(candidates=candidates, modalities=[_FACE_MODALITY])

    def _candidate_for(self, embedding: list[float]) -> Candidate | None:
        best = self._best_live_match(self._index.search(embedding, k=_SEARCH_K))
        if best is None:
            return None
        person, distance = best
        if distance > self._match_threshold_ambiguous:
            return None
        return Candidate(
            person_id=person.person_id,
            label=person.label,
            role=person.role,
            state=person.state,
            confidence=self._confidence_for(person, distance),
        )

    def observe(self, source_id: str, frame: bytes) -> Sighting | None:
        """The continuous route, with effects: visits, new unknowns,
        pending evidence, clips (requisito 22). This is the function
        `process_frame` aliases for a configured camera."""
        faces = detect_and_embed_faces(frame, self._model_cache)
        if not faces:
            return None

        last_sighting: Sighting | None = None
        for face in faces:
            last_sighting = self._process_one_face(source_id, face.embedding, face.quality_ok)
        return last_sighting

    def process_frame(self, camera_id: str, frame: bytes) -> Sighting | None:
        """Alias of `observe` over a configured camera (Correcciones al
        spec original, punto 2)."""
        return self.observe(camera_id, frame)

    def _process_one_face(
        self, source_id: str, embedding: list[float], quality_ok: bool
    ) -> Sighting:
        matches = self._index.search(embedding, k=_SEARCH_K)
        now = utcnow()

        # Every database write for this face commits together or not at all,
        # so a failure never leaves a person without its visit or sighting.
        with self._store.transaction():
            person, first_seen, confidence = self._resolve_person(embedding, matches, quality_ok)
            confidence = self._cap_confidence(person, confidence)
            person.last_seen_at = now
            self._store.update_person(person)
            if person.state != IdentityState.ESTABLISHED:
                self._record_pending_evidence(person, source_id, embedding, matches, now)
            visit = self._touch_visit(person.person_id, source_id, now)

        # Recording a clip is slow and touches the disk, so it stays out of
        # the transaction above instead of holding the write lock.
        clip_ref = self._maybe_record_clip(source_id, person, first_seen, confidence)

        sighting = Sighting(
            sighting_id=new_person_id(),
            person_id=person.person_id,
            camera_id=source_id,
            seen_at=now,
            confidence=confidence,
            clip_ref=clip_ref,
        )
        with self._store.transaction():
            if clip_ref is not None and visit.clip_ref is None:
                self._store.update_visit(replace(visit, clip_ref=clip_ref))
            self._store.record_sighting(sighting)

        self._emit(
            PersonSeenEvent(
                person_id=person.person_id,
                known=person.known,
                first_seen=first_seen,
                confidence=confidence,
                camera_id=source_id,
                timestamp=now,
                snapshot_ref=person.snapshot_ref,
                clip_ref=clip_ref,
            )
        )
        return sighting

    def _maybe_record_clip(
        self, source_id: str, person: PersonRecord, first_seen: bool, confidence: float
    ) -> str | None:
        if first_seen:
            return self._record_clip_safely(source_id)
        if self._decision_gate is None:
            return None
        question = NoulQuestion(
            prompt="Is this sighting worth recording a clip for?",
            person_id=person.person_id,
            known=person.known,
            first_seen=first_seen,
            camera_id=source_id,
            confidence=confidence,
        )
        if self._decision_gate.should_record_clip(question):
            return self._record_clip_safely(source_id)
        return None

    def _record_clip_safely(self, source_id: str) -> str | None:
        """A clip that cannot be recorded (no FrameSource for the source, a
        busy camera) is logged and skipped: seeing someone must never fail
        because recording did (SPEC.md Edge Cases and Reliability). Calling
        record_clip directly still raises, so a manual request is told."""
        try:
            return self.record_clip(source_id, self._clip_duration_s).clip_ref
        except PresenceUnavailableError as exc:
            _log.warning("clip skipped for source_id=%s: %s", source_id, exc)
            return None

    # -- visits (requisito 30) -------------------------------------------------

    def _touch_visit(self, person_id: str, source_id: str, now: datetime) -> Visit:
        """Opens a visit on the first sighting of a person on a source, or
        extends the open one if it's within visit_gap_s. Closing also happens
        out of band (close_stale_visits), since it depends on the passage
        of time rather than on a new sighting arriving."""
        open_visit = self._store.open_visit(person_id, source_id)
        if open_visit is not None:
            if (now - open_visit.last_seen_at).total_seconds() <= self._visit_gap_s:
                extended = replace(open_visit, last_seen_at=now)
                self._store.update_visit(extended)
                return extended
            self._close_visit(open_visit)

        visit = Visit(
            visit_id=new_person_id(),
            person_id=person_id,
            source_id=source_id,
            started_at=now,
            last_seen_at=now,
        )
        self._store.create_visit(visit)
        self._emit_visit_started(visit)
        return visit

    def close_stale_visits(self, now: datetime | None = None) -> list[Visit]:
        """Closes every open visit whose last_seen_at is older than
        visit_gap_s. Meant to be called periodically by a runner; a new
        sighting on the same source/person also closes and reopens a stale
        visit inline (see _touch_visit)."""
        now = now or utcnow()
        closed: list[Visit] = []
        for visit in self._store.open_visits():
            if (now - visit.last_seen_at).total_seconds() > self._visit_gap_s:
                closed.append(self._close_visit(visit))
        return closed

    def _close_visit(self, visit: Visit) -> Visit:
        # Visit is immutable (requisito 30): closing builds a new value.
        closed = replace(visit, ended_at=visit.last_seen_at)
        self._store.update_visit(closed)
        self._emit_visit_ended(closed)
        return closed

    def _emit_visit_started(self, visit: Visit) -> None:
        _log.info(
            "visit_started visit_id=%s person_id=%s source_id=%s",
            visit.visit_id,
            visit.person_id,
            visit.source_id,
        )

    def _emit_visit_ended(self, visit: Visit) -> None:
        _log.info(
            "visit_ended visit_id=%s person_id=%s source_id=%s",
            visit.visit_id,
            visit.person_id,
            visit.source_id,
        )

    # -- matching (requisito 5, 11) ---------------------------------------

    def _best_live_match(
        self, matches: list[tuple[int, float]]
    ) -> tuple[PersonRecord, float] | None:
        """The closest neighbour that still belongs to a person. The index
        is only a cache of the stored samples, so it can briefly hold a
        vector whose database row is gone (a rolled back write); skipping it
        keeps that from being read as "nobody I know"."""
        for hnsw_id, distance in matches:
            person = self._person_for_hnsw_id(hnsw_id)
            if person is not None:
                return person, distance
        return None

    def _resolve_person(
        self, embedding: list[float], matches: list[tuple[int, float]], quality_ok: bool
    ) -> tuple[PersonRecord, bool, float]:
        best = self._best_live_match(matches)
        if best is not None:
            person, distance = best
            if distance <= self._match_threshold:
                return person, False, self._confidence_from_distance(distance)
            # Ambiguous zone (requisito 5, 11): without a decision gate,
            # treated as a new unknown, documented as a known v1 limitation
            # until match_threshold is calibrated with real data.
            if distance <= self._match_threshold_ambiguous and self._decision_gate is not None:
                return person, False, self._confidence_from_distance(distance)

        return self._create_unknown_person(embedding, quality_ok), True, 1.0

    def _person_for_hnsw_id(self, hnsw_id: int) -> PersonRecord | None:
        person_id = self._store.person_id_for_hnsw_id(hnsw_id, _FACE_MODALITY)
        if person_id is None:
            return None
        return self._store.get_person(person_id)

    def _create_unknown_person(self, embedding: list[float], quality_ok: bool) -> PersonRecord:
        now = utcnow()
        person_id = new_person_id()
        hnsw_id = self._allocate_hnsw_id()

        self._index.insert(hnsw_id, embedding)
        self._store.save_sample(person_id, hnsw_id, embedding)

        person = PersonRecord(
            person_id=person_id,
            state=IdentityState.UNKNOWN,
            embedding_ids=[hnsw_id],
            first_seen_at=now,
            last_seen_at=now,
            label=None,
            snapshot_ref=None,
        )
        self._store.create_person(person)
        self._store.add_embedding(person_id, hnsw_id, _FACE_MODALITY)

        if quality_ok:
            person.snapshot_ref = self._save_snapshot(person_id)
            self._store.update_person(person)

        return person

    def _save_snapshot(self, person_id: str) -> str:
        # Path convention only: the actual JPEG bytes for the snapshot are
        # written by the caller from the originating frame, not derived
        # from the embedding here. Kept as a path reference (requisito 1:
        # `snapshot_ref: str`), consistent with retention (requisito 12).
        # Real, encrypted snapshots are phase F2 (requisito 38).
        self._snapshots_root.mkdir(parents=True, exist_ok=True)
        return str(self._snapshots_root / f"{person_id}.jpg")

    # -- evidence (requisito 27, 28, 29) ---------------------------------------

    def _record_pending_evidence(
        self,
        person: PersonRecord,
        source_id: str,
        embedding: list[float],
        matches: list[tuple[int, float]],
        now: datetime,
    ) -> Evidence:
        """requisito 27: every appearance of an UNKNOWN or PROVISIONAL person
        without the owner present is recorded as PENDING. It never modifies
        any template: the embedding it was captured with is kept aside,
        encrypted, and only enters the person's templates through
        confirm_evidence."""
        hypothesis_id, hypothesis_confidence = self._find_hypothesis(person, matches)
        evidence = Evidence(
            evidence_id=new_person_id(),
            person_id=person.person_id,
            source_id=source_id,
            modality=_FACE_MODALITY,
            hnsw_id=NO_INDEXED_EMBEDDING,
            captured_at=now,
            hypothesis_person_id=hypothesis_id,
            hypothesis_confidence=hypothesis_confidence,
        )
        self._store.save_pending_sample(evidence.evidence_id, embedding)
        try:
            self._store.create_evidence(evidence)
        except Exception:
            self._store.delete_pending_sample(evidence.evidence_id)
            raise
        return evidence

    def _find_hypothesis(
        self, person: PersonRecord, matches: list[tuple[int, float]]
    ) -> tuple[str | None, float | None]:
        """requisito 27: the closest *other* person inside the ambiguous
        zone, unless the owner already rejected that confusion for this
        person (person_exclusions). This is what makes a rejection stick."""
        for hnsw_id, distance in matches:
            if distance > self._match_threshold_ambiguous:
                continue
            other_id = self._store.person_id_for_hnsw_id(hnsw_id, _FACE_MODALITY)
            if other_id is None or other_id == person.person_id:
                continue
            if self._store.is_excluded(person.person_id, other_id):
                continue
            return other_id, self._confidence_from_distance(distance)
        return None, None

    def confirm_evidence(self, evidence_id: str) -> PersonRecord:
        """requisito 27, 28: 'ese era X'. Validates first and only then
        changes anything, so a refused confirmation leaves the evidence
        exactly as it was. Moves the evidence to CONFIRMED, adds its
        embedding to the person's templates, and lets UNKNOWN-then-named
        people reach ESTABLISHED (requisito 26)."""
        evidence = self._require_evidence(evidence_id)
        person = self._store.get_person(evidence.person_id)
        if person is None:
            raise PersonNotFoundError(evidence.person_id)
        if person.state == IdentityState.UNKNOWN:
            raise PresenceError(
                f"Person '{person.person_id}' has no label yet; call name_person before "
                "confirming evidence for them (requisito 26)."
            )
        if evidence.status == EvidenceStatus.CONFIRMED:
            return person
        if evidence.status != EvidenceStatus.PENDING:
            raise PresenceError(
                f"Evidence '{evidence_id}' is already {evidence.status.value}; "
                "only pending evidence can be confirmed."
            )

        with self._store.transaction():
            self._promote_evidence(evidence, person)
            evidence.status = EvidenceStatus.CONFIRMED
            evidence.origin = EvidenceOrigin.OWNER_CONFIRMED
            self._store.update_evidence(evidence)
            return self._establish_if_ready(person)

    def _establish_if_ready(self, person: PersonRecord) -> PersonRecord:
        """requisito 26: PROVISIONAL becomes ESTABLISHED once it has
        established_min_samples confirmed pieces of evidence."""
        if person.state != IdentityState.PROVISIONAL:
            return person
        confirmed = self._store.count_evidence(person.person_id, EvidenceStatus.CONFIRMED)
        if confirmed >= self._established_min_samples:
            person.state = IdentityState.ESTABLISHED
            self._store.update_person(person)
        return person

    def _promote_evidence(self, evidence: Evidence, person: PersonRecord) -> None:
        """requisito 28: copies the evidence's embedding into the person's
        templates. Evidence without a kept sample (or of another modality)
        is still confirmed, just without reinforcing anything."""
        evidence_id = evidence.evidence_id
        if evidence.modality != _FACE_MODALITY:
            _log.warning(
                "evidence %s: no index for modality %s yet", evidence_id, evidence.modality
            )
            return
        embedding = self._store.load_pending_sample(evidence_id)
        if embedding is None:
            _log.warning("evidence %s has no pending sample; nothing to reinforce", evidence_id)
            return

        self._make_room_for_sample(person.person_id)
        hnsw_id = self._allocate_hnsw_id()
        self._index.insert(hnsw_id, embedding)
        self._store.save_sample(person.person_id, hnsw_id, embedding, _FACE_MODALITY)
        self._store.add_embedding(person.person_id, hnsw_id, _FACE_MODALITY)
        evidence.hnsw_id = hnsw_id
        evidence.promoted = True

    def _make_room_for_sample(self, person_id: str) -> None:
        """requisito 28: a person holds at most max_samples_per_person
        templates; past that, the most redundant one is replaced."""
        hnsw_ids = self._store.embeddings_for_person(person_id, _FACE_MODALITY)
        if len(hnsw_ids) < self._max_samples_per_person:
            return
        samples = self._store.load_person_samples(person_id, _FACE_MODALITY)
        victim = _most_redundant(samples, hnsw_ids)
        _log.info("replacing redundant sample hnsw_id=%s of person_id=%s", victim, person_id)
        self._drop_embedding(person_id, victim)

    def _drop_embedding(self, person_id: str, hnsw_id: int) -> None:
        """Removes one embedding everywhere it lives: index, encrypted file,
        database row, and any evidence that recorded it as promoted."""
        try:
            self._index.remove(hnsw_id)
        except PresenceUnavailableError:
            _log.warning("hnsw_id=%s of person_id=%s was not in the index", hnsw_id, person_id)
        self._store.delete_sample(person_id, hnsw_id, _FACE_MODALITY)
        self._store.delete_embedding(hnsw_id, _FACE_MODALITY)
        self._store.unpromote_evidence_for_embedding(hnsw_id, _FACE_MODALITY)

    def _demote_evidence(self, evidence: Evidence) -> None:
        """Undoes what _promote_evidence did, if it did anything."""
        if evidence.promoted and evidence.hnsw_id != NO_INDEXED_EMBEDDING:
            self._drop_embedding(evidence.person_id, evidence.hnsw_id)
        evidence.promoted = False
        evidence.hnsw_id = NO_INDEXED_EMBEDDING

    def reject_evidence(self, evidence_id: str, actual_person_id: str | None = None) -> None:
        """requisito 27: the owner says 'no, that wasn't X'. Records a
        counterexample in person_exclusions so the system stops proposing
        the same confusion, and marks the evidence REJECTED. Anything the
        evidence had added to a template is taken back first."""
        evidence = self._require_evidence(evidence_id)
        if actual_person_id is not None and self._store.get_person(actual_person_id) is None:
            raise PersonNotFoundError(actual_person_id)

        with self._store.transaction():
            self._demote_evidence(evidence)
            evidence.status = EvidenceStatus.REJECTED
            self._store.update_evidence(evidence)
            for excluded in (evidence.hypothesis_person_id, actual_person_id):
                if excluded is not None and excluded != evidence.person_id:
                    self._store.add_exclusion(evidence.person_id, excluded, evidence_id)
        self._store.delete_pending_sample(evidence_id)

    def discard_evidence(self, evidence_id: str) -> None:
        """requisito 27: drops the evidence with no reinforcement and no
        exclusion, used when neither confirming nor rejecting is
        warranted."""
        evidence = self._require_evidence(evidence_id)
        with self._store.transaction():
            self._demote_evidence(evidence)
            evidence.status = EvidenceStatus.DISCARDED
            self._store.update_evidence(evidence)
        self._store.delete_pending_sample(evidence_id)

    def retract_evidence(self, evidence_id: str) -> None:
        """requisito 28: every reinforcement is reversible. Undoes a
        CONFIRMED evidence back to PENDING and takes its embedding out of
        the templates; does not by itself downgrade a person already
        promoted to ESTABLISHED by other confirmations. Only confirmed
        evidence can be retracted: rejected or discarded evidence has had
        its sample deleted and has nothing left to restore."""
        evidence = self._require_evidence(evidence_id)
        if evidence.status == EvidenceStatus.PENDING:
            return
        if evidence.status != EvidenceStatus.CONFIRMED:
            raise PresenceError(
                f"Evidence '{evidence_id}' is {evidence.status.value}; only confirmed "
                "evidence can be retracted."
            )
        with self._store.transaction():
            self._demote_evidence(evidence)
            evidence.status = EvidenceStatus.PENDING
            evidence.origin = None
            self._store.update_evidence(evidence)

    def pending_review(self) -> list[Evidence]:
        """requisito 29: lists PENDING evidence for the owner to review.
        Grouping by visit is a presentation concern left to the caller
        (runner/UI); this returns the flat list ordered by capture time.
        Presenting it stamps `presented_at` on the evidence once, and on the
        person every time, so the forget clock (requisito 34) never runs out
        on something the owner is still looking at."""
        pending = self._store.pending_evidence()
        now = utcnow()
        with self._store.transaction():
            for evidence in pending:
                if evidence.presented_at is None:
                    evidence.presented_at = now
                    self._store.update_evidence(evidence)
            for person_id in {evidence.person_id for evidence in pending}:
                person = self._store.get_person(person_id)
                if person is not None:
                    person.presented_at = now
                    self._store.update_person(person)
        return pending

    def _require_evidence(self, evidence_id: str) -> Evidence:
        evidence = self._store.get_evidence(evidence_id)
        if evidence is None:
            raise PresenceError(f"No evidence found with evidence_id '{evidence_id}'")
        return evidence

    # -- naming, roles, merge (requisito 20, 25, 26, 37) ------------------------

    def name_person(self, person_id: str, label: str) -> PersonRecord:
        """Requisito 3, 20, 26: the UNKNOWN -> PROVISIONAL transition.
        Deletes the retained snapshot (requisito 12); the embedding is kept
        indefinitely (Technical Decisions)."""
        person = self._store.get_person(person_id)
        if person is None:
            raise PersonNotFoundError(person_id)

        if person.snapshot_ref is not None:
            secure_delete(Path(person.snapshot_ref))
            person.snapshot_ref = None

        person.label = label
        if person.state == IdentityState.UNKNOWN:
            person.state = IdentityState.PROVISIONAL
        self._store.update_person(person)
        return person

    def set_role(self, person_id: str, role: str) -> PersonRecord:
        """requisito 25: role is a label from presence.roles, never a
        permission by itself. Authorization stays in Janus."""
        person = self._store.get_person(person_id)
        if person is None:
            raise PersonNotFoundError(person_id)
        person.role = role
        self._store.update_person(person)
        return person

    def merge_persons(self, source_id: str, target_id: str) -> PersonRecord:
        """requisito 37: mandatory in v1. Keeps target_id, reassigns
        embeddings, visits, evidence, exclusions and sightings from
        source_id, moves the encrypted sample files that back those
        embeddings, then deletes the source PersonRecord.

        The database side is one transaction. The files move afterwards: if
        that step fails the merge already happened and the files simply sit
        under the old directory, still found by the index rebuild (it goes
        by database rows, not by directory).
        """
        if source_id == target_id:
            raise PresenceError("Cannot merge a person into themselves")
        source = self._store.get_person(source_id)
        target = self._store.get_person(target_id)
        if source is None:
            raise PersonNotFoundError(source_id)
        if target is None:
            raise PersonNotFoundError(target_id)

        with self._store.transaction():
            self._store.reassign_embeddings(source_id, target_id)
            self._store.reassign_visits(source_id, target_id)
            self._store.reassign_evidence(source_id, target_id)
            self._store.reassign_sightings(source_id, target_id)
            self._store.reassign_exclusions(source_id, target_id)
            self._store.delete_person(source_id)

        self._store.move_samples(source_id, target_id)
        if source.snapshot_ref is not None:
            secure_delete(Path(source.snapshot_ref))

        merged = self._store.get_person(target_id)
        if merged is None:  # pragma: no cover - the transaction above just kept it
            raise PersonNotFoundError(target_id)
        return merged

    # -- forgetting (requisito 34) ----------------------------------------------

    def forget_person(self, person_id: str) -> None:
        """requisito 34: deletes embeddings, samples, pending samples,
        snapshot, and the person record itself with everything that points
        at it. Idempotent: forgetting an already-forgotten (or
        never-existing) person is a no-op, never an error.

        Biometric files go first and the database rows last, so a crash in
        between leaves a person with nothing sensitive on disk that a retry
        finishes removing, rather than orphaned files nothing points at.
        """
        person = self._store.get_person(person_id)
        if person is None:
            return

        if person.snapshot_ref is not None:
            secure_delete(Path(person.snapshot_ref))

        for hnsw_id in self._store.embeddings_for_person(person_id, _FACE_MODALITY):
            try:
                self._index.remove(hnsw_id)
            except PresenceUnavailableError:
                _log.warning(
                    "could not remove hnsw_id=%s for forgotten person_id=%s from index",
                    hnsw_id,
                    person_id,
                )

        for evidence_id in self._store.evidence_ids_for_person(person_id):
            self._store.delete_pending_sample(evidence_id)
        self._store.delete_all_samples_for_person(person_id)
        self._store.delete_person(person_id)

    def forget_stale_unknowns(self, now: datetime | None = None) -> list[str]:
        """requisito 34: forgets every UNKNOWN/PROVISIONAL person past
        forget_after_days, never confirmed to ESTABLISHED. The clock runs
        from the later of last_seen_at and presented_at, so pending
        evidence the owner has not yet seen never expires early. ESTABLISHED
        is never forgotten by this path."""
        now = now or utcnow()
        cutoff_s = self._forget_after_days * 86_400
        forgotten: list[str] = []
        for person in self._store.all_persons():
            if person.state == IdentityState.ESTABLISHED:
                continue
            reference = max(person.last_seen_at, person.presented_at or person.last_seen_at)
            age_s = (now - reference).total_seconds()
            if age_s > cutoff_s:
                self.forget_person(person.person_id)
                forgotten.append(person.person_id)
        return forgotten

    # -- clips (requisito 14, 15, 16, 33) ---------------------------------------

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
        # Writing real clips is phase F2 (requisito 31).
        _log.info(
            "recording clip camera_id=%s duration_s=%s -> %s", camera_id, duration_s, clip_ref
        )

        return ClipRecord(
            clip_ref=clip_ref, camera_id=camera_id, started_at=now, duration_s=duration_s
        )

    def enroll_known_person(self, label: str, samples: list[bytes]) -> PersonRecord:
        """Manual enrollment of an owner/family member (requisito 8):
        analogous to biometrics' enroll, but ESTABLISHED from the start and
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
            hnsw_id = self._allocate_hnsw_id()
            self._index.insert(hnsw_id, embedding)
            self._store.save_sample(person_id, hnsw_id, embedding)
            hnsw_ids.append(hnsw_id)

        if not hnsw_ids:
            raise ValueError("No face could be detected in any of the provided samples")

        person = PersonRecord(
            person_id=person_id,
            state=IdentityState.ESTABLISHED,
            embedding_ids=hnsw_ids,
            first_seen_at=now,
            last_seen_at=now,
            label=label,
            snapshot_ref=None,
        )
        with self._store.transaction():
            self._store.create_person(person)
            for hnsw_id in hnsw_ids:
                self._store.add_embedding(person_id, hnsw_id, _FACE_MODALITY)
        return person

    def on_person_seen(self, callback: Callable[[PersonSeenEvent], None]) -> None:
        self._callbacks.append(callback)

    def status(self) -> PresenceStatus:
        """People counted once each, whatever number of embeddings they hold;
        `index_size` is the number of embeddings, which is a different thing."""
        persons = self._store.all_persons()
        known = sum(1 for person in persons if person.known)
        return PresenceStatus(
            known_persons=known,
            unknown_persons=len(persons) - known,
            index_size=len(self._store.all_embeddings(_FACE_MODALITY)),
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

    def _confidence_for(self, person: PersonRecord, distance: float) -> float:
        return self._cap_confidence(person, self._confidence_from_distance(distance))

    def _cap_confidence(self, person: PersonRecord, confidence: float) -> float:
        """requisito 26: while a person is not ESTABLISHED, emitted
        confidence is capped at provisional_confidence_cap."""
        if person.state == IdentityState.ESTABLISHED:
            return confidence
        return min(confidence, self._provisional_confidence_cap)

    def _enforce_clip_retention(self) -> None:
        """requisito 17: hard cap on total clip disk space, deleting oldest
        first. Never blocks process_frame if there still isn't room after
        deleting everything eligible (Edge Cases table): logs and lets the
        caller's record_clip attempt proceed regardless."""
        if not self._clips_root.exists():
            return
        clip_paths = sorted(self._clips_root.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
        total_bytes = sum(p.stat().st_size for p in clip_paths)
        limit_bytes = self._clips_max_total_mb * 1024 * 1024
        idx = 0
        while total_bytes > limit_bytes and idx < len(clip_paths):
            path = clip_paths[idx]
            total_bytes -= path.stat().st_size
            path.unlink(missing_ok=True)
            idx += 1
