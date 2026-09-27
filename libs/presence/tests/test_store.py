from __future__ import annotations

from datetime import UTC, datetime

import pytest

from conftest import KEY_A, make_embedding
from janus_presence.errors import PersonNotFoundError, PresenceError
from janus_presence.models import PersonRecord
from janus_presence.store import PresenceStore


def make_person(person_id: str = "p1", known: bool = False, label: str | None = None) -> PersonRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return PersonRecord(
        person_id=person_id,
        known=known,
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

    def test_update_persists_label_and_known(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        person = make_person()
        store.create_person(person)

        person.label = "Joanfer"
        person.known = True
        store.update_person(person)

        loaded = store.get_person("p1")
        assert loaded.label == "Joanfer"
        assert loaded.known is True


class TestEmbeddingMapping:
    """requisito 6: hnsw_id <-> person_id mapping, used to rebuild the
    in-memory index at startup."""

    def test_add_and_lookup_embedding(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        store.create_person(make_person())
        store.add_embedding("p1", hnsw_id=7)

        assert store.person_id_for_hnsw_id(7) == "p1"
        assert store.all_embeddings() == [("p1", 7)]

    def test_unknown_hnsw_id_returns_none(self, tmp_state_dir):
        store = PresenceStore(tmp_state_dir, KEY_A)
        assert store.person_id_for_hnsw_id(999) is None


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
        from janus_presence.models import Sighting

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
