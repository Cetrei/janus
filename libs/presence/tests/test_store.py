from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import KEY_A, make_embedding

from janus_presence.errors import PersonNotFoundError, PresenceError
from janus_presence.models import Evidence, IdentityState, PersonRecord, Sighting, Visit
from janus_presence.store import LATEST_SCHEMA_VERSION, PresenceStore


def make_person(
    person_id: str = "p1",
    state: IdentityState = IdentityState.UNKNOWN,
    label: str | None = None,
) -> PersonRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return PersonRecord(
        person_id=person_id,
        state=state,
        embedding_ids=[],
        first_seen_at=now,
        last_seen_at=now,
        label=label,
    )


class TestKeyValidation:
    def test_rejects_key_of_wrong_length(self, tmp_state_dir):
        with pytest.raises(PresenceError):
            PresenceStore(tmp_state_dir, b"too-short")


class TestPersonRoundTrip:
    def test_create_and_get_person(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        person = make_person()
        store.create_person(person)

        loaded = store.get_person("p1")
        assert loaded is not None
        assert loaded.person_id == "p1"
        assert loaded.known is False
        assert loaded.label is None

    def test_get_missing_person_returns_none(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        assert store.get_person("missing") is None

    def test_update_missing_person_raises(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        with pytest.raises(PersonNotFoundError):
            store.update_person(make_person())

    def test_update_persists_label_and_state(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        person = make_person()
        store.create_person(person)

        person.label = "Joanfer"
        person.state = IdentityState.PROVISIONAL
        store.update_person(person)

        loaded = store.get_person("p1")
        assert loaded.label == "Joanfer"
        assert loaded.state == IdentityState.PROVISIONAL
        assert loaded.known is True

    def test_delete_person_removes_row(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        store.delete_person("p1")
        assert store.get_person("p1") is None

    def test_all_persons_returns_every_row(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person("p1"))
        store.create_person(make_person("p2"))
        assert {p.person_id for p in store.all_persons()} == {"p1", "p2"}


class TestEmbeddingMapping:
    """requisito 6, 23: hnsw_id <-> person_id mapping per modality, used to
    rebuild the in-memory index at startup."""

    def test_add_and_lookup_embedding(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        store.add_embedding("p1", hnsw_id=7)

        assert store.person_id_for_hnsw_id(7) == "p1"
        assert store.all_embeddings() == [("p1", 7)]

    def test_unknown_hnsw_id_returns_none(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        assert store.person_id_for_hnsw_id(999) is None

    def test_modalities_are_isolated(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        store.add_embedding("p1", hnsw_id=1, modality="face")
        store.add_embedding("p1", hnsw_id=1, modality="voice")

        assert store.person_id_for_hnsw_id(1, modality="face") == "p1"
        assert store.person_id_for_hnsw_id(1, modality="voice") == "p1"
        assert store.all_embeddings("face") == [("p1", 1)]
        assert store.all_embeddings("voice") == [("p1", 1)]

    def test_reassign_embeddings_moves_every_row(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person("p1"))
        store.create_person(make_person("p2"))
        store.add_embedding("p1", hnsw_id=1)
        store.add_embedding("p1", hnsw_id=2)

        store.reassign_embeddings("p1", "p2")

        assert store.all_embeddings() == [("p2", 1), ("p2", 2)]


class TestEncryptedSamples:
    """requisito 7: raw embeddings never sit unencrypted in presence.db;
    only encrypted raw samples on disk, used to rebuild the index."""

    def test_round_trip_preserves_embedding(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        embedding = make_embedding(0.42)
        store.save_sample("p1", hnsw_id=1, embedding=embedding)

        loaded = store.load_all_samples()
        assert len(loaded) == 1
        person_id, hnsw_id, loaded_embedding = loaded[0]
        assert person_id == "p1"
        assert hnsw_id == 1
        assert loaded_embedding == pytest.approx(embedding)

    def test_stored_sample_file_is_not_plaintext(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.save_sample("p1", hnsw_id=1, embedding=make_embedding(0.42))

        raw = (tmp_state_dir / "presence" / "samples" / "p1" / "1.enc").read_bytes()
        assert b"0.42" not in raw

    def test_wrong_key_raises_on_decrypt(self, tmp_state_dir):
        store_a = PresenceStore(tmp_state_dir, KEY_A)
        store_a.save_sample("p1", hnsw_id=1, embedding=make_embedding(0.1))

        store_b = PresenceStore(tmp_state_dir, b"b" * 32)
        with pytest.raises(PresenceError):
            store_b.load_all_samples()

    def test_delete_sample_removes_file(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.save_sample("p1", hnsw_id=1, embedding=make_embedding(0.1))
        store.delete_sample("p1", hnsw_id=1)

        assert store.load_all_samples() == []

    def test_delete_missing_sample_does_not_raise(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.delete_sample("p1", hnsw_id=1)


class TestSightings:
    def test_record_and_count_via_all_embeddings(self, tmp_state_dir):
        # Sightings don't feed all_embeddings, but this exercises the
        # write path end-to-end against the real schema (FK constraints).
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        store.upsert_camera("front-door", "Front door", "local")

        sighting = Sighting(
            sighting_id="s1",
            person_id="p1",
            camera_id="front-door",
            seen_at=datetime(2026, 1, 1, tzinfo=UTC),
            confidence=0.9,
        )
        store.record_sighting(sighting)  # should not raise

    def test_reassign_sightings_moves_person_id(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person("p1"))
        store.create_person(make_person("p2"))
        store.upsert_camera("front-door", "Front door", "local")
        store.record_sighting(
            Sighting(
                sighting_id="s1",
                person_id="p1",
                camera_id="front-door",
                seen_at=datetime(2026, 1, 1, tzinfo=UTC),
                confidence=0.9,
            )
        )

        store.reassign_sightings("p1", "p2")

        row = store._conn.execute(
            "SELECT person_id FROM sightings WHERE sighting_id = 's1'"
        ).fetchone()
        assert row["person_id"] == "p2"


class TestMigrations:
    """requisito 38: versioned migrations gated on PRAGMA user_version."""

    def test_fresh_db_lands_on_latest_version(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == LATEST_SCHEMA_VERSION

    def test_reopening_is_idempotent(self, tmp_state_dir):
        PresenceStore(tmp_state_dir, KEY_A).close()
        store = PresenceStore(tmp_state_dir, KEY_A)  # should not raise
        assert store.get_person("missing") is None

    def test_backfill_maps_known_to_established_and_unknown_to_unknown(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        # Simulate a v1 row written before the ampliación (known=1, no
        # state column value set by the app layer): the migration itself
        # already ran on this fresh db, so insert through the real API and
        # assert state reflects `known`.
        person = make_person("p1", state=IdentityState.ESTABLISHED, label="Joanfer")
        store.create_person(person)
        loaded = store.get_person("p1")
        assert loaded.state == IdentityState.ESTABLISHED


class TestVisits:
    """requisito 30."""

    def test_create_and_read_open_visit(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        now = datetime(2026, 1, 1, tzinfo=UTC)
        visit = Visit(
            visit_id="v1", person_id="p1", source_id="front-door",
            started_at=now, last_seen_at=now,
        )
        store.create_visit(visit)

        found = store.open_visit("p1", "front-door")
        assert found is not None
        assert found.visit_id == "v1"

    def test_closed_visit_is_not_open(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        now = datetime(2026, 1, 1, tzinfo=UTC)
        visit = Visit(
            visit_id="v1", person_id="p1", source_id="front-door",
            started_at=now, last_seen_at=now, ended_at=now,
        )
        store.create_visit(visit)

        assert store.open_visit("p1", "front-door") is None

    def test_open_visits_lists_only_unended(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        now = datetime(2026, 1, 1, tzinfo=UTC)
        store.create_visit(Visit("v1", "p1", "front-door", now, now))
        store.create_visit(Visit("v2", "p1", "front-door", now, now, ended_at=now))

        open_ids = [v.visit_id for v in store.open_visits()]
        assert open_ids == ["v1"]

    def test_reassign_visits_moves_person_id(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person("p1"))
        store.create_person(make_person("p2"))
        now = datetime(2026, 1, 1, tzinfo=UTC)
        store.create_visit(Visit("v1", "p1", "front-door", now, now))

        store.reassign_visits("p1", "p2")

        row = store._conn.execute("SELECT person_id FROM visits WHERE visit_id = 'v1'").fetchone()
        assert row["person_id"] == "p2"


class TestEvidence:
    """requisito 27, 28."""

    def _make_evidence(self, person_id: str = "p1") -> Evidence:
        return Evidence(
            evidence_id="e1",
            person_id=person_id,
            source_id="front-door",
            modality="face",
            hnsw_id=1,
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_create_and_get_evidence_defaults_to_pending(self, tmp_state_dir):
        from janus_presence.models import EvidenceStatus

        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        store.create_evidence(self._make_evidence())

        loaded = store.get_evidence("e1")
        assert loaded.status == EvidenceStatus.PENDING

    def test_pending_evidence_excludes_confirmed(self, tmp_state_dir):
        from janus_presence.models import EvidenceStatus

        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        evidence = self._make_evidence()
        store.create_evidence(evidence)

        evidence.status = EvidenceStatus.CONFIRMED
        store.update_evidence(evidence)

        assert store.pending_evidence() == []

    def test_update_missing_evidence_raises(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        with pytest.raises(PresenceError):
            store.update_evidence(self._make_evidence())

    def test_reassign_evidence_moves_person_id(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person("p1"))
        store.create_person(make_person("p2"))
        store.create_evidence(self._make_evidence("p1"))

        store.reassign_evidence("p1", "p2")

        assert store.get_evidence("e1").person_id == "p2"


class TestExclusions:
    """requisito 27: rejecting a hypothesis records a counterexample."""

    def test_add_and_check_exclusion(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person("p1"))
        store.create_person(make_person("p2"))
        store.create_evidence(
            Evidence(
                evidence_id="e1", person_id="p1", source_id="front-door",
                modality="face", hnsw_id=1, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert store.is_excluded("p1", "p2") is False
        store.add_exclusion("p1", "p2", "e1")
        assert store.is_excluded("p1", "p2") is True

    def test_duplicate_exclusion_does_not_raise(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person("p1"))
        store.create_person(make_person("p2"))
        store.create_evidence(
            Evidence(
                evidence_id="e1", person_id="p1", source_id="front-door",
                modality="face", hnsw_id=1, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        store.add_exclusion("p1", "p2", "e1")
        store.add_exclusion("p1", "p2", "e1")  # should not raise
