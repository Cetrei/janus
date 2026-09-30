"""Behaviour introduced by the F1 fixes (findings A-H), one class per topic.

The reproductions in test_f1_regressions.py show that each defect is gone;
these tests pin the behaviour that replaced it, so a later change cannot
quietly bring one back. Written without being able to run them: a failure
here is a result to investigate, not a test to bend.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import KEY_A, FakeFrameSource, make_embedding

from janus_presence.errors import PresenceError
from janus_presence.models import EvidenceStatus, IdentityState, SourceKind
from janus_presence.service import PresenceService
from janus_presence.store import LATEST_SCHEMA_VERSION, PresenceStore

CAMERA = "front-door"


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


def _faces(*faces: FakeFace):
    return patch.object(PresenceService, "_embed", return_value=list(faces))


def _build(tmp_path: Path, index, **overrides) -> PresenceService:
    options = {
        "match_threshold": 0.01,
        "match_threshold_ambiguous": 2.0,
        "established_min_samples": 2,
        "max_samples_per_person": 20,
    }
    options.update(overrides)
    return PresenceService(
        store=PresenceStore(tmp_path / "state", KEY_A),
        index=index,
        model_cache=object(),
        frame_sources={CAMERA: FakeFrameSource({CAMERA: b"frame"})},
        clip_duration_s=15,
        clips_root=tmp_path / "clips",
        clips_max_total_mb=2048,
        unknown_snapshot_retention_s=86_400,
        snapshots_root=tmp_path / "snapshots",
        **options,
    )


def _observe(service: PresenceService, value: float):
    with _faces(FakeFace(make_embedding(value))):
        return service.observe(CAMERA, b"frame")


class TestConfirmReinforcesTemplates:
    """requisito 28: confirming evidence adds its embedding to the person."""

    def test_confirming_adds_the_captured_embedding_to_the_person(self, tmp_path, fake_index):
        service = _build(tmp_path, fake_index, match_threshold=1.0)
        person_id = _observe(service, 0.0).person_id
        service.name_person(person_id, "Joanfer")
        _observe(service, 0.0)
        newest = service._store.pending_evidence()[-1]
        assert newest.person_id == person_id
        before = len(service._store.embeddings_for_person(person_id))

        service.confirm_evidence(newest.evidence_id)

        assert len(service._store.embeddings_for_person(person_id)) == before + 1
        assert service._store.get_evidence(newest.evidence_id).promoted is True

    def test_retracting_takes_the_embedding_back_out(self, tmp_path, fake_index):
        service = _build(tmp_path, fake_index, match_threshold=1.0)
        person_id = _observe(service, 0.0).person_id
        service.name_person(person_id, "Joanfer")
        [evidence] = service._store.pending_evidence()
        before = len(service._store.embeddings_for_person(person_id))
        service.confirm_evidence(evidence.evidence_id)

        service.retract_evidence(evidence.evidence_id)

        assert len(service._store.embeddings_for_person(person_id)) == before
        stored = service._store.get_evidence(evidence.evidence_id)
        assert stored.promoted is False
        assert stored.status == EvidenceStatus.PENDING

    def test_a_person_never_holds_more_than_the_configured_samples(self, tmp_path, fake_index):
        service = _build(tmp_path, fake_index, match_threshold=1.0, max_samples_per_person=2)
        person_id = _observe(service, 0.0).person_id
        service.name_person(person_id, "Joanfer")
        for _ in range(3):
            _observe(service, 0.0)
        for evidence in service._store.pending_evidence():
            service.confirm_evidence(evidence.evidence_id)

        assert len(service._store.embeddings_for_person(person_id)) <= 2


class TestConfirmValidatesFirst:
    """Finding D: a refused confirmation changes nothing."""

    def test_confirming_an_already_rejected_evidence_raises_and_keeps_it_rejected(
        self, tmp_path, fake_index
    ):
        service = _build(tmp_path, fake_index)
        person_id = _observe(service, 0.0).person_id
        service.name_person(person_id, "Joanfer")
        [evidence] = service._store.pending_evidence()
        service.reject_evidence(evidence.evidence_id)

        with pytest.raises(PresenceError):
            service.confirm_evidence(evidence.evidence_id)

        stored = service._store.get_evidence(evidence.evidence_id)
        assert stored.status == EvidenceStatus.REJECTED


class TestExclusionsAreApplied:
    """requisito 27: a rejection sticks, the same confusion is not proposed
    again."""

    def test_rejected_confusion_is_not_offered_as_a_hypothesis_again(self, tmp_path, fake_index):
        service = _build(tmp_path, fake_index, match_threshold=0.01, match_threshold_ambiguous=5000)
        first = _observe(service, 0.0)
        second = _observe(service, 1.0)  # ambiguous zone: hypothesises `first`
        [evidence] = [
            e for e in service._store.pending_evidence() if e.person_id == second.person_id
        ]
        assert evidence.hypothesis_person_id == first.person_id
        service.reject_evidence(evidence.evidence_id)

        _observe(service, 1.0)

        newest = [e for e in service._store.pending_evidence() if e.person_id == second.person_id]
        assert all(e.hypothesis_person_id != first.person_id for e in newest)


class TestStatusCountsPeople:
    def test_status_counts_each_person_once(self, tmp_path, fake_index):
        service = _build(tmp_path, fake_index, match_threshold=1.0)
        person_id = _observe(service, 0.0).person_id
        service.name_person(person_id, "Joanfer")
        _observe(service, 5.0)
        [evidence] = [
            e for e in service._store.pending_evidence() if e.person_id == person_id
        ]
        service.confirm_evidence(evidence.evidence_id)  # gives Joanfer a second embedding

        status = service.status()

        assert status.known_persons == 1
        assert status.unknown_persons == 1
        assert status.index_size == 3


class TestMigrationThree:
    """The sightings foreign key, cameras -> sources, per-modality ids."""

    def test_fresh_database_has_no_cameras_table_and_a_sources_table(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        tables = {
            row[0]
            for row in store._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "sources" in tables
        assert "cameras" not in tables

    def test_sighting_can_be_recorded_for_an_unregistered_source(self, tmp_state_dir):
        from datetime import UTC, datetime

        from janus_presence.models import PersonRecord, Sighting

        store = PresenceStore(tmp_state_dir, KEY_A)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        store.create_person(
            PersonRecord(
                person_id="p1",
                state=IdentityState.UNKNOWN,
                embedding_ids=[],
                first_seen_at=now,
                last_seen_at=now,
            )
        )

        store.record_sighting(Sighting("s1", "p1", "never-registered", now, 0.9))

        assert store._conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1

    def test_upgrading_a_v2_database_folds_cameras_into_sources(self, tmp_state_dir):
        presence_dir = tmp_state_dir / "presence"
        presence_dir.mkdir(parents=True)
        legacy = sqlite3.connect(presence_dir / "presence.db")
        legacy.executescript(
            """
            CREATE TABLE persons (
                person_id TEXT PRIMARY KEY, label TEXT, known INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, snapshot_ref TEXT
            );
            CREATE TABLE person_embeddings (
                embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT NOT NULL REFERENCES persons(person_id),
                hnsw_id INTEGER NOT NULL UNIQUE
            );
            CREATE TABLE cameras (
                camera_id TEXT PRIMARY KEY, label TEXT NOT NULL, source_kind TEXT NOT NULL
            );
            CREATE TABLE sightings (
                sighting_id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES persons(person_id),
                camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
                seen_at TEXT NOT NULL, confidence REAL NOT NULL, clip_ref TEXT
            );
            INSERT INTO cameras VALUES ('front-door', 'Front door', 'local');
            """
        )
        legacy.commit()
        legacy.close()

        store = PresenceStore(tmp_state_dir, KEY_A)

        assert store._conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        [source] = store.all_sources()
        assert source.source_id == "front-door"
        assert source.kind == SourceKind.CAMERA

    def test_the_same_durable_id_can_exist_in_two_modalities(self, tmp_state_dir):
        from datetime import UTC, datetime

        from janus_presence.models import PersonRecord

        store = PresenceStore(tmp_state_dir, KEY_A)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        store.create_person(
            PersonRecord("p1", IdentityState.UNKNOWN, [], now, now)
        )

        store.add_embedding("p1", 1, modality="face")
        store.add_embedding("p1", 1, modality="voice")

        with pytest.raises(sqlite3.IntegrityError):
            store.add_embedding("p1", 1, modality="face")
