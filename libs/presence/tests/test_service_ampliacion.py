from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import KEY_A, FakeFrameSource, make_embedding

from janus_presence.errors import PersonNotFoundError
from janus_presence.models import EvidenceStatus, IdentityState
from janus_presence.service import PresenceService
from janus_presence.store import PresenceStore


class FakeFace:
    def __init__(
        self,
        embedding: list[float],
        quality_ok: bool = True,
        bbox: tuple[int, int, int, int] | None = None,
    ) -> None:
        self.embedding = embedding
        self.quality_ok = quality_ok
        self.bbox = bbox


def make_service(
    tmp_path: Path,
    fake_index,
    match_threshold: float = 1.0,
    match_threshold_ambiguous: float = 2.0,
    established_min_samples: int = 2,
    provisional_confidence_cap: float = 0.7,
    visit_gap_s: int = 30,
    forget_after_days: int = 30,
) -> PresenceService:
    store = PresenceStore(tmp_path / "state", KEY_A)
    return PresenceService(
        store=store,
        index=fake_index,
        model_cache=object(),
        frame_sources={"front-door": FakeFrameSource({"front-door": b"frame"})},
        match_threshold=match_threshold,
        match_threshold_ambiguous=match_threshold_ambiguous,
        clip_duration_s=15,
        clips_root=tmp_path / "clips",
        clips_max_total_mb=2048,
        unknown_snapshot_retention_s=86_400,
        snapshots_root=tmp_path / "snapshots",
        established_min_samples=established_min_samples,
        provisional_confidence_cap=provisional_confidence_cap,
        visit_gap_s=visit_gap_s,
        forget_after_days=forget_after_days,
    )


def _patch_faces(*faces: FakeFace):
    return patch.object(PresenceService, "_embed", return_value=list(faces))


class TestIdentifyIsReadOnly:
    """requisito 22: identify never creates a person, never writes a
    sighting, never touches the index or store beyond reads."""

    def test_no_match_returns_empty_candidates(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            result = service.identify(b"sample")

        assert result.candidates == []
        assert service.status().index_size == 0  # nothing was created

    def test_match_returns_candidate_without_side_effects(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, match_threshold=0.01)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")  # creates the real person

        size_before = service.status().index_size
        with _patch_faces(FakeFace(make_embedding(0.0))):
            result = service.identify(b"sample")

        assert len(result.candidates) == 1
        assert service.status().index_size == size_before  # unchanged

    def test_no_faces_returns_empty_result(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces():
            result = service.identify(b"sample")
        assert result.candidates == []
        assert result.modalities == []


class TestObserveAliasing:
    def test_process_frame_is_observe(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            via_process_frame = service.process_frame("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(5.0))):
            via_observe = service.observe("front-door", b"frame")

        assert via_process_frame is not None
        assert via_observe is not None


class TestVisits:
    """requisito 30."""

    def test_first_sighting_opens_a_visit(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")

        open_visits = service._store.open_visits()
        assert len(open_visits) == 1
        assert open_visits[0].source_id == "front-door"

    def test_second_sighting_within_gap_extends_visit(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")

        assert len(service._store.open_visits()) == 1

    def test_close_stale_visits_closes_after_gap(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, visit_gap_s=30)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")

        future = datetime.now(UTC) + timedelta(seconds=60)
        closed = service.close_stale_visits(now=future)

        assert len(closed) == 1
        assert service._store.open_visits() == []


class TestEvidenceLifecycle:
    """requisito 26, 27, 28."""

    def test_unknown_sighting_creates_pending_evidence(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")

        assert len(service.pending_review()) == 1

    def test_confirming_evidence_before_naming_raises(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")
        [evidence] = service._store.pending_evidence()

        from janus_presence.errors import PresenceError

        with pytest.raises(PresenceError):
            service.confirm_evidence(evidence.evidence_id)

    def test_naming_moves_unknown_to_provisional(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.observe("front-door", b"frame")

        person = service.name_person(sighting.person_id, "Joanfer")
        assert person.state == IdentityState.PROVISIONAL
        assert person.known is True

    def test_provisional_confidence_is_capped(self, tmp_path, fake_index):
        service = make_service(
            tmp_path, fake_index, match_threshold=0.5, provisional_confidence_cap=0.3
        )
        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.observe("front-door", b"frame")
        service.name_person(first.person_id, "Joanfer")

        with _patch_faces(FakeFace(make_embedding(0.0))):
            second = service.observe("front-door", b"frame")

        assert second.confidence <= 0.3

    def test_enough_confirmations_promote_to_established(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, established_min_samples=2)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.observe("front-door", b"frame")
        person_id = first.person_id
        service.name_person(person_id, "Joanfer")

        # Two more sightings -> two more PENDING evidence entries to confirm.
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")

        pending = [e for e in service._store.pending_evidence() if e.person_id == person_id]
        for evidence in pending:
            service.confirm_evidence(evidence.evidence_id)

        person = service._store.get_person(person_id)
        assert person.state == IdentityState.ESTABLISHED

    def test_reject_evidence_records_exclusion(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, match_threshold=0.01)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(5.0))):
            other = service.observe("front-door", b"frame")
        [evidence] = [
            e for e in service._store.pending_evidence() if e.person_id != other.person_id
        ]

        service.reject_evidence(evidence.evidence_id, actual_person_id=other.person_id)

        assert service._store.is_excluded(evidence.person_id, other.person_id) is True

    def test_reject_evidence_for_a_missing_person_raises(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")
        [evidence] = service._store.pending_evidence()

        with pytest.raises(PersonNotFoundError):
            service.reject_evidence(evidence.evidence_id, actual_person_id="someone-else")

        assert service._store.get_evidence(evidence.evidence_id).status == EvidenceStatus.PENDING

    def test_discard_evidence_has_no_reinforcement_effect(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")
        [evidence] = service._store.pending_evidence()

        service.discard_evidence(evidence.evidence_id)

        assert service._store.pending_evidence() == []

    def test_retract_evidence_returns_it_to_pending(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.observe("front-door", b"frame")
        service.name_person(first.person_id, "Joanfer")
        [evidence] = service._store.pending_evidence()
        service.confirm_evidence(evidence.evidence_id)

        service.retract_evidence(evidence.evidence_id)

        assert len(service._store.pending_evidence()) == 1

    def test_pending_review_sets_presented_at_once(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")

        first_call = service.pending_review()
        assert first_call[0].presented_at is not None
        presented_at = first_call[0].presented_at

        second_call = service.pending_review()
        assert second_call[0].presented_at == presented_at  # unchanged, not re-stamped


class TestRoles:
    """requisito 25: role is a label, never consumed as a permission here."""

    def test_set_role_persists(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.observe("front-door", b"frame")

        person = service.set_role(sighting.person_id, "guest")
        assert person.role == "guest"
        assert service._store.get_person(sighting.person_id).role == "guest"

    def test_set_role_on_missing_person_raises(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with pytest.raises(PersonNotFoundError):
            service.set_role("missing", "guest")


class TestMergePersons:
    """requisito 37: mandatory in v1."""

    def test_merge_reassigns_embeddings_and_deletes_source(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, match_threshold=0.01)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.observe("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(5.0))):
            second = service.observe("front-door", b"frame")

        target = service.merge_persons(second.person_id, first.person_id)

        assert service._store.get_person(second.person_id) is None
        assert target.person_id == first.person_id
        assert len(target.embedding_ids) == 2

    def test_merge_missing_source_raises(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            target = service.observe("front-door", b"frame")

        with pytest.raises(PersonNotFoundError):
            service.merge_persons("missing", target.person_id)


class TestForgetting:
    """requisito 34: idempotent, respects presented_at, never touches
    ESTABLISHED."""

    def test_forget_person_is_idempotent(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.observe("front-door", b"frame")

        service.forget_person(sighting.person_id)
        service.forget_person(sighting.person_id)  # should not raise

        assert service._store.get_person(sighting.person_id) is None

    def test_forget_stale_unknowns_skips_established(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, forget_after_days=1)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.observe("front-door", b"frame")

        with _patch_faces(FakeFace(make_embedding(0.0))):
            person = service.enroll_known_person("Joanfer", samples=[b"sample"])

        future = datetime.now(UTC) + timedelta(days=2)
        forgotten = service.forget_stale_unknowns(now=future)

        assert person.person_id not in forgotten
        assert service._store.get_person(person.person_id) is not None

    def test_forget_stale_unknowns_respects_presented_at(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, forget_after_days=1)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.observe("front-door", b"frame")

        # Simulate a much later "presented_at": the clock must run from the
        # max(last_seen_at, presented_at), so it must not have expired yet.
        person = service._store.get_person(sighting.person_id)
        person.presented_at = datetime.now(UTC) + timedelta(hours=12)
        service._store.update_person(person)

        future = datetime.now(UTC) + timedelta(days=1, hours=6)
        forgotten = service.forget_stale_unknowns(now=future)

        assert sighting.person_id not in forgotten

    def test_forget_nonexistent_person_is_noop(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        service.forget_person("missing")  # should not raise
