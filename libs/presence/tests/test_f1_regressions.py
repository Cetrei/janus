"""Reproductions for defects found by reading the F1 implementation.

Every test targets ONE finding and is expected to FAIL against the code as it
stood when this file was written. None of them was executed at that time (the
session had no shell): a red run confirms the finding, a green run means the
finding was wrong and the test should be discarded, not "fixed".

Finding letters match the diagnosis report:
    A  foreign_keys=ON but sightings.camera_id is never registered
    B  forget_person / merge_persons versus foreign keys and sample files
    C  PROVISIONAL people never produce PENDING evidence
    D  confirm_evidence mutates state before validating
    E  migrations: atomicity and backfill on a populated v1 database
    F  real hnsw index rebuild: id order and gaps

Service level tests build their own service instead of importing the helper
from test_service_ampliacion.py, on purpose: that helper is the natural place
to "fix" finding A by registering the camera, which would hide the production
bug these tests are meant to expose.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import KEY_A, FakeFrameSource, make_embedding

from janus_presence import store as store_module
from janus_presence.errors import PresenceError
from janus_presence.models import EvidenceStatus, IdentityState
from janus_presence.service import PresenceService
from janus_presence.store import LATEST_SCHEMA_VERSION, PresenceStore

CAMERA = "front-door"
FIRST_SEEN = "2026-09-01T00:00:00+00:00"
LAST_SEEN = "2026-09-02T00:00:00+00:00"


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


def _build(
    tmp_path: Path, index, register_camera: bool = False, match_threshold: float = 1.0
) -> PresenceService:
    store = PresenceStore(tmp_path / "state", KEY_A)
    if register_camera:
        store.upsert_camera(CAMERA, "Front door", "local")
    return PresenceService(
        store=store,
        index=index,
        model_cache=object(),
        frame_sources={CAMERA: FakeFrameSource({CAMERA: b"frame"})},
        match_threshold=match_threshold,
        match_threshold_ambiguous=match_threshold + 1.0,
        clip_duration_s=15,
        clips_root=tmp_path / "clips",
        clips_max_total_mb=2048,
        unknown_snapshot_retention_s=86_400,
        snapshots_root=tmp_path / "snapshots",
    )


def _observe(service: PresenceService, value: float):
    with _faces(FakeFace(make_embedding(value))):
        return service.observe(CAMERA, b"frame")


class TestFindingA:
    def test_observe_works_without_a_preregistered_camera(self, tmp_path, fake_index):
        """foreign_keys=ON makes sightings.camera_id require a row in
        cameras, and nothing in the service ever creates that row."""
        service = _build(tmp_path, fake_index)

        sighting = _observe(service, 0.0)

        assert sighting is not None


class TestFindingB:
    def test_forget_person_removes_the_person_and_every_dependent_row(self, tmp_path, fake_index):
        """delete_person hits FK constraints from person_embeddings,
        sightings, visits and evidence, and forget_person deletes none of
        those child rows first."""
        service = _build(tmp_path, fake_index, register_camera=True)
        person_id = _observe(service, 0.0).person_id

        service.forget_person(person_id)

        assert service._store.get_person(person_id) is None
        conn = service._store._conn
        for table in ("person_embeddings", "sightings", "visits", "evidence"):
            remaining = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE person_id = ?", (person_id,)
            ).fetchone()[0]
            assert remaining == 0, table

    def test_merge_moves_encrypted_samples_to_the_target(self, tmp_path, fake_index):
        """Samples live at samples/<person_id>/<hnsw_id>.enc. Merge only
        reassigns DB rows, so the source's files stay under the source id
        and a later forget of the target never deletes them."""
        service = _build(tmp_path, fake_index, register_camera=True, match_threshold=0.01)
        first = _observe(service, 0.0)
        second = _observe(service, 5.0)

        service.merge_persons(second.person_id, first.person_id)

        samples_root = tmp_path / "state" / "presence" / "samples"
        leftovers = [p for p in samples_root.rglob("*.enc") if p.parent.name != first.person_id]
        assert leftovers == []

    def test_merge_survives_an_exclusion_that_points_at_the_source(self, tmp_path, fake_index):
        """person_exclusions and evidence.hypothesis_person_id reference
        persons(person_id); merge never reassigns them, so deleting the
        source violates a foreign key."""
        service = _build(tmp_path, fake_index, register_camera=True, match_threshold=0.01)
        first = _observe(service, 0.0)
        second = _observe(service, 5.0)
        [evidence] = [
            e for e in service._store.pending_evidence() if e.person_id == first.person_id
        ]
        service.reject_evidence(evidence.evidence_id, actual_person_id=second.person_id)

        service.merge_persons(second.person_id, first.person_id)

        assert service._store.get_person(second.person_id) is None


class TestFindingC:
    def test_provisional_person_keeps_producing_pending_evidence(self, tmp_path, fake_index):
        """The docstring says UNKNOWN/PROVISIONAL both produce evidence, but
        the code tests `not person.known`, which is False for PROVISIONAL,
        so a named person can never accumulate the confirmations needed to
        become ESTABLISHED."""
        service = _build(tmp_path, fake_index, register_camera=True)
        first = _observe(service, 0.0)
        service.name_person(first.person_id, "Joanfer")
        before = len(service._store.pending_evidence())

        _observe(service, 0.0)

        assert len(service._store.pending_evidence()) == before + 1


class TestFindingD:
    def test_failed_confirm_leaves_the_evidence_pending(self, tmp_path, fake_index):
        """confirm_evidence persists CONFIRMED before checking that the
        person has a label, so the error path leaves corrupted state."""
        service = _build(tmp_path, fake_index, register_camera=True)
        _observe(service, 0.0)
        [evidence] = service._store.pending_evidence()

        with pytest.raises(PresenceError):
            service.confirm_evidence(evidence.evidence_id)

        stored = service._store.get_evidence(evidence.evidence_id)
        assert stored.status == EvidenceStatus.PENDING


V1_DDL = """
CREATE TABLE persons (
    person_id TEXT PRIMARY KEY,
    label TEXT,
    known INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    snapshot_ref TEXT
);
CREATE TABLE person_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL REFERENCES persons(person_id),
    hnsw_id INTEGER NOT NULL UNIQUE
);
CREATE TABLE cameras (
    camera_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    source_kind TEXT NOT NULL
);
CREATE TABLE sightings (
    sighting_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES persons(person_id),
    camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
    seen_at TEXT NOT NULL,
    confidence REAL NOT NULL,
    clip_ref TEXT
);
"""


class TestFindingE:
    def test_migrating_a_populated_v1_database_keeps_data_and_backfills_state(
        self, tmp_state_dir
    ):
        """A database created by the pre-ampliacion code has user_version 0,
        rows with `known`, and (because v1 ran with foreign keys off and
        never registered cameras) sightings that point at a camera that
        does not exist. None of the existing migration tests cover this."""
        presence_dir = tmp_state_dir / "presence"
        presence_dir.mkdir(parents=True)
        legacy = sqlite3.connect(presence_dir / "presence.db")
        legacy.executescript(V1_DDL)
        legacy.executemany(
            "INSERT INTO persons VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("p_known", "Joanfer", 1, FIRST_SEEN, LAST_SEEN, None),
                ("p_unknown", None, 0, FIRST_SEEN, LAST_SEEN, None),
            ],
        )
        legacy.executemany(
            "INSERT INTO person_embeddings (person_id, hnsw_id) VALUES (?, ?)",
            [("p_known", 0), ("p_unknown", 1)],
        )
        legacy.execute(
            "INSERT INTO sightings VALUES (?, ?, ?, ?, ?, ?)",
            ("s1", "p_unknown", CAMERA, LAST_SEEN, 0.9, None),
        )
        legacy.commit()
        legacy.close()

        store = PresenceStore(tmp_state_dir, KEY_A)

        assert store._conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        known = store.get_person("p_known")
        assert known.state == IdentityState.ESTABLISHED
        assert known.label == "Joanfer"
        assert store.get_person("p_unknown").state == IdentityState.UNKNOWN
        assert sorted(store.all_embeddings()) == [("p_known", 0), ("p_unknown", 1)]
        assert store._conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1

    def test_interrupted_migration_leaves_no_partial_schema(self, tmp_state_dir, monkeypatch):
        """PresenceStore promises each migration is atomic, but Python's
        executescript() issues an implicit COMMIT first, so DDL run before
        it inside the BEGIN is already durable when a later statement
        fails. Migration 0002 has exactly this shape (ALTERs, then an
        executescript), so this injects a failure with the same structure."""

        def half_applied(conn: sqlite3.Connection) -> None:
            conn.execute("ALTER TABLE persons ADD COLUMN role TEXT")
            conn.executescript("CREATE TABLE marker (a); THIS IS NOT VALID SQL;")

        monkeypatch.setattr(
            store_module,
            "_MIGRATIONS",
            [(1, store_module._migration_0001), (2, half_applied)],
        )

        with pytest.raises(sqlite3.OperationalError):
            PresenceStore(tmp_state_dir, KEY_A)

        raw = sqlite3.connect(tmp_state_dir / "presence" / "presence.db")
        columns = {row[1] for row in raw.execute("PRAGMA table_info(persons)")}
        raw.close()
        assert "role" not in columns


def _real_service(tmp_path: Path) -> PresenceService:
    from janus_presence.index import PresenceIndex

    return PresenceService(
        store=PresenceStore(tmp_path / "state", KEY_A),
        index=PresenceIndex(),
        model_cache=object(),
        frame_sources={},
        match_threshold=1.0,
        match_threshold_ambiguous=2.0,
        clip_duration_s=15,
        clips_root=tmp_path / "clips",
        clips_max_total_mb=2048,
        unknown_snapshot_retention_s=86_400,
        snapshots_root=tmp_path / "snapshots",
    )


class TestFindingF:
    """The real hnsw-c only accepts id == current node count (see
    test_index_real_hnsw.py::test_ids_must_be_sequential_from_zero). The
    conftest FakeHnswIndex accepts any id in any order, so no service level
    test can see how startup behaves against the real index."""

    def test_restart_rebuilds_a_real_index_from_several_samples(self, tmp_path):
        """load_all_samples() walks directories with iterdir()/glob(), whose
        order is filesystem dependent, and the service inserts in that
        order. Six samples make an accidentally ascending order very
        unlikely."""
        pytest.importorskip("janus_presence._hnsw_cffi")
        service = _real_service(tmp_path)
        faces = [[FakeFace(make_embedding(float(i)))] for i in range(6)]
        with patch.object(PresenceService, "_embed", side_effect=faces):
            service.enroll_known_person("Joanfer", samples=[b"s"] * 6)
        service.close()

        reopened = _real_service(tmp_path)
        try:
            assert reopened.status().index_size == 6
        finally:
            reopened.close()

    def test_restart_tolerates_a_gap_in_the_stored_ids(self, tmp_path):
        """Simulates on disk what forget_person does to the samples of a
        person whose ids sit at the start: the remaining ids (2 and 3) can
        never be inserted into an empty real index, which demands 0 first.
        Uses delete_all_samples_for_person directly so this stays
        independent of finding B."""
        pytest.importorskip("janus_presence._hnsw_cffi")
        service = _real_service(tmp_path)
        faces = [[FakeFace(make_embedding(float(i)))] for i in range(4)]
        with patch.object(PresenceService, "_embed", side_effect=faces):
            first = service.enroll_known_person("A", samples=[b"s", b"s"])
            service.enroll_known_person("B", samples=[b"s", b"s"])
        service._store.delete_all_samples_for_person(first.person_id)
        service.close()

        reopened = _real_service(tmp_path)
        reopened.close()
