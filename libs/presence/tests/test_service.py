from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import KEY_A, FakeFrameSource, make_decision_gate, make_embedding
from janus_presence.errors import PersonNotFoundError, PresenceUnavailableError
from janus_presence.models import PersonSeenEvent
from janus_presence.service import PresenceService
from janus_presence.store import PresenceStore


class FakeFace:
    """Stand-in for janus_biometrics.base.FaceEmbedding, so tests never
    need real ONNX models (SPEC.md Testing Requirements)."""

    def __init__(self, embedding: list[float], quality_ok: bool = True) -> None:
        self.embedding = embedding
        self.quality_ok = quality_ok


def make_service(
    tmp_path: Path,
    fake_index,
    match_threshold: float = 1.0,
    match_threshold_ambiguous: float = 2.0,
    decision_gate=None,
    frame_sources: dict | None = None,
) -> PresenceService:
    store = PresenceStore(tmp_path / "state", KEY_A)
    return PresenceService(
        store=store,
        index=fake_index,
        model_cache=object(),  # never touched: detect_and_embed_faces is patched
        frame_sources=(
            {"front-door": FakeFrameSource({"front-door": b"frame"})}
            if frame_sources is None
            else frame_sources
        ),
        match_threshold=match_threshold,
        match_threshold_ambiguous=match_threshold_ambiguous,
        clip_duration_s=15,
        clips_root=tmp_path / "clips",
        clips_max_total_mb=2048,
        unknown_snapshot_retention_s=86_400,
        snapshots_root=tmp_path / "snapshots",
        decision_gate=decision_gate,
    )


def _patch_faces(*faces: FakeFace):
    return patch("janus_presence.service.detect_and_embed_faces", return_value=list(faces))


class TestMatchThreshold:
    """SPEC.md requisito 5, 11: synthetic distances for clear match, clear
    no-match, and the ambiguous zone."""

    def test_no_faces_returns_none(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces():
            assert service.process_frame("front-door", b"frame") is None

    def test_first_sighting_is_unknown_and_first_seen(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        events: list[PersonSeenEvent] = []
        service.on_person_seen(events.append)

        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.process_frame("front-door", b"frame")

        assert sighting is not None
        assert len(events) == 1
        assert events[0].first_seen is True
        assert events[0].known is False

    def test_clear_match_is_recognized_as_same_person(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.process_frame("front-door", b"frame")

        events: list[PersonSeenEvent] = []
        service.on_person_seen(events.append)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            second = service.process_frame("front-door", b"frame")

        assert second.person_id == first.person_id
        assert events[0].first_seen is False

    def test_clear_no_match_creates_new_person(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, match_threshold=0.01)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.process_frame("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(5.0))):
            second = service.process_frame("front-door", b"frame")

        assert second.person_id != first.person_id

    def test_ambiguous_zone_without_decision_gate_is_treated_as_new(self, tmp_path, fake_index):
        # requisito 11 Edge Cases: without a decision gate, the ambiguous
        # zone is treated as a new unknown every time (documented v1
        # limitation).
        service = make_service(
            tmp_path, fake_index, match_threshold=0.01, match_threshold_ambiguous=10.0
        )
        with _patch_faces(FakeFace(make_embedding(0.0))):
            first = service.process_frame("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(1.0))):  # distance=128, ambiguous zone
            second = service.process_frame("front-door", b"frame")

        assert second.person_id != first.person_id

    def test_multiple_faces_each_processed_separately(self, tmp_path, fake_index):
        # requisito 11: unlike biometrics, multi-face is never rejected.
        service = make_service(tmp_path, fake_index, match_threshold=0.01)
        with _patch_faces(FakeFace(make_embedding(0.0)), FakeFace(make_embedding(5.0))):
            service.process_frame("front-door", b"frame")

        assert service.status().index_size == 2


class TestNamePerson:
    """requisito 3, 12, 20: naming is the only known=False -> True
    transition; deletes the retained snapshot; embedding stays."""

    def test_naming_sets_known_and_label(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.process_frame("front-door", b"frame")

        person = service.name_person(sighting.person_id, "Joanfer")

        assert person.known is True
        assert person.label == "Joanfer"

    def test_naming_deletes_retained_snapshot(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0), quality_ok=True)):
            sighting = service.process_frame("front-door", b"frame")

        stored = service._store.get_person(sighting.person_id)
        assert stored.snapshot_ref is not None
        snapshot_path = Path(stored.snapshot_ref)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(b"jpeg-bytes")

        person = service.name_person(sighting.person_id, "Joanfer")

        assert person.snapshot_ref is None
        assert not snapshot_path.exists()

    def test_low_quality_face_gets_no_snapshot(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0), quality_ok=False)):
            sighting = service.process_frame("front-door", b"frame")

        stored = service._store.get_person(sighting.person_id)
        assert stored.snapshot_ref is None

    def test_naming_unknown_person_raises(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with pytest.raises(PersonNotFoundError):
            service.name_person("missing", "Joanfer")


class TestClipTriggerRoutes:
    """requisito 14, 15, 16: deterministic, decision-model, and manual all
    converge on the same record_clip."""

    def test_first_seen_always_triggers_clip_deterministically(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, decision_gate=make_decision_gate(value=False))
        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.process_frame("front-door", b"frame")

        assert sighting.clip_ref is not None

    def test_recognized_person_without_decision_gate_gets_no_clip(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.process_frame("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(0.0))):
            second = service.process_frame("front-door", b"frame")

        assert second.clip_ref is None

    def test_decision_gate_can_add_a_clip_for_recognized_person(self, tmp_path, fake_index):
        gate = make_decision_gate(value=True, confidence=0.99)
        service = make_service(tmp_path, fake_index, decision_gate=gate)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            service.process_frame("front-door", b"frame")
        with _patch_faces(FakeFace(make_embedding(0.0))):
            second = service.process_frame("front-door", b"frame")

        assert second.clip_ref is not None

    def test_decision_gate_never_suppresses_first_seen_clip(self, tmp_path, fake_index):
        # requisito 15: the gate is only ever consulted for sightings the
        # deterministic layer did NOT already clip; it can never suppress
        # first_seen's clip because that path never calls it.
        gate = make_decision_gate(value=False, confidence=1.0)
        service = make_service(tmp_path, fake_index, decision_gate=gate)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            sighting = service.process_frame("front-door", b"frame")

        assert sighting.clip_ref is not None

    def test_manual_record_clip_is_the_same_function(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        clip = service.record_clip("front-door", duration_s=5)

        assert clip.camera_id == "front-door"
        assert clip.duration_s == 5


class TestEnrollKnownPerson:
    """requisito 8: manual enrollment is known=True from the start and
    never goes through the unknown/first_seen clip path."""

    def test_enroll_creates_known_person(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces(FakeFace(make_embedding(0.0))):
            person = service.enroll_known_person("Joanfer", samples=[b"sample.jpg"])

        assert person.known is True
        assert person.label == "Joanfer"

    def test_enroll_with_no_detectable_face_raises(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with _patch_faces():  # no faces detected in any sample
            with pytest.raises(ValueError):
                service.enroll_known_person("Joanfer", samples=[b"sample.jpg"])

    def test_enroll_with_no_samples_raises(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index)
        with pytest.raises(ValueError):
            service.enroll_known_person("Joanfer", samples=[])


class TestFrameSourceUnavailable:
    """SPEC.md Edge Cases: camera unavailable propagates as
    PresenceUnavailableError, never a crash."""

    def test_missing_camera_raises_presence_unavailable(self, tmp_path, fake_index):
        service = make_service(tmp_path, fake_index, frame_sources={})
        with pytest.raises(PresenceUnavailableError):
            service.record_clip("front-door", duration_s=5)
