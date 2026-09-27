from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from janus_platform.paths import make_private

from janus_presence.errors import PersonNotFoundError, PresenceError
from janus_presence.models import PersonRecord, Sighting

_NONCE_SIZE = 12

_SCHEMA = """
CREATE TABLE IF NOT EXISTS persons (
    person_id TEXT PRIMARY KEY,
    label TEXT,
    known INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    snapshot_ref TEXT
);

CREATE TABLE IF NOT EXISTS person_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL REFERENCES persons(person_id),
    hnsw_id INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS cameras (
    camera_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    source_kind TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sightings (
    sighting_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES persons(person_id),
    camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
    seen_at TEXT NOT NULL,
    confidence REAL NOT NULL,
    clip_ref TEXT
);
"""


class PresenceStore:
    """Own SQLite database at state_dir/presence/presence.db (requisito 6).
    Never janus.db, never a table shared with libs/persistence: presence is
    a spoke and keeps its own storage, same criterion as libs/biometrics.

    Raw embeddings never sit in this .db (requisito 7): person_embeddings
    only keeps `hnsw_id`, the integer the in-memory HNSW index uses. The
    actual floats are only ever persisted, encrypted, as raw samples on
    disk via save_sample/load_all_samples, used to rebuild the index at
    startup until hnsw-c gains its own save/load extension.
    """

    def __init__(self, state_dir: Path, key: bytes) -> None:
        if len(key) != 32:
            raise PresenceError("Presence sample encryption key must be 32 bytes (AES-256)")
        self._root = Path(state_dir) / "presence"
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "presence.db"
        self._samples_root = self._root / "samples"
        self._aesgcm = AESGCM(key)

        is_new = not self._db_path.exists()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        if is_new:
            make_private(self._db_path)

    def close(self) -> None:
        self._conn.close()

    # -- persons ----------------------------------------------------------

    def create_person(self, person: PersonRecord) -> None:
        self._conn.execute(
            """INSERT INTO persons
               (person_id, label, known, first_seen_at, last_seen_at, snapshot_ref)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                person.person_id,
                person.label,
                int(person.known),
                person.first_seen_at.isoformat(),
                person.last_seen_at.isoformat(),
                person.snapshot_ref,
            ),
        )
        self._conn.commit()

    def get_person(self, person_id: str) -> PersonRecord | None:
        row = self._conn.execute(
            "SELECT * FROM persons WHERE person_id = ?", (person_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_person(row)

    def update_person(self, person: PersonRecord) -> None:
        cursor = self._conn.execute(
            """UPDATE persons
               SET label = ?, known = ?, last_seen_at = ?, snapshot_ref = ?
               WHERE person_id = ?""",
            (
                person.label,
                int(person.known),
                person.last_seen_at.isoformat(),
                person.snapshot_ref,
                person.person_id,
            ),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise PersonNotFoundError(person.person_id)

    def _row_to_person(self, row: sqlite3.Row) -> PersonRecord:
        embedding_ids = [
            r["hnsw_id"]
            for r in self._conn.execute(
                "SELECT hnsw_id FROM person_embeddings WHERE person_id = ?", (row["person_id"],)
            ).fetchall()
        ]
        return PersonRecord(
            person_id=row["person_id"],
            label=row["label"],
            known=bool(row["known"]),
            embedding_ids=embedding_ids,
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            snapshot_ref=row["snapshot_ref"],
        )

    # -- person_embeddings --------------------------------------------------

    def add_embedding(self, person_id: str, hnsw_id: int) -> None:
        self._conn.execute(
            "INSERT INTO person_embeddings (person_id, hnsw_id) VALUES (?, ?)",
            (person_id, hnsw_id),
        )
        self._conn.commit()

    def person_id_for_hnsw_id(self, hnsw_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT person_id FROM person_embeddings WHERE hnsw_id = ?", (hnsw_id,)
        ).fetchone()
        return row["person_id"] if row is not None else None

    def all_embeddings(self) -> list[tuple[str, int]]:
        """Every (person_id, hnsw_id) pair, used to rebuild the in-memory
        HNSW index at startup from the raw samples on disk."""
        rows = self._conn.execute("SELECT person_id, hnsw_id FROM person_embeddings").fetchall()
        return [(r["person_id"], r["hnsw_id"]) for r in rows]

    # -- cameras ------------------------------------------------------------

    def upsert_camera(self, camera_id: str, label: str, source_kind: str) -> None:
        self._conn.execute(
            """INSERT INTO cameras (camera_id, label, source_kind) VALUES (?, ?, ?)
               ON CONFLICT(camera_id) DO UPDATE SET label = excluded.label,
                   source_kind = excluded.source_kind""",
            (camera_id, label, source_kind),
        )
        self._conn.commit()

    # -- sightings ------------------------------------------------------------

    def record_sighting(self, sighting: Sighting) -> None:
        self._conn.execute(
            """INSERT INTO sightings
               (sighting_id, person_id, camera_id, seen_at, confidence, clip_ref)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                sighting.sighting_id,
                sighting.person_id,
                sighting.camera_id,
                sighting.seen_at.isoformat(),
                sighting.confidence,
                sighting.clip_ref,
            ),
        )
        self._conn.commit()

    # -- encrypted raw samples (requisito 7) ---------------------------------

    def save_sample(self, person_id: str, hnsw_id: int, embedding: list[float]) -> None:
        """Persists one raw embedding, encrypted, so the HNSW index (in
        memory only, requisito 7) can be rebuilt on the next startup. This
        is the only place presence keeps the actual floats on disk."""
        person_dir = self._samples_root / person_id
        person_dir.mkdir(parents=True, exist_ok=True)
        path = person_dir / f"{hnsw_id}.enc"
        payload = " ".join(repr(value) for value in embedding).encode("utf-8")
        nonce = secrets.token_bytes(_NONCE_SIZE)
        ciphertext = self._aesgcm.encrypt(nonce, payload, associated_data=None)
        path.write_bytes(nonce + ciphertext)
        make_private(path)

    def load_all_samples(self) -> list[tuple[str, int, list[float]]]:
        """Decrypts every retained raw sample: (person_id, hnsw_id,
        embedding). Used to rebuild PresenceIndex at startup."""
        results: list[tuple[str, int, list[float]]] = []
        if not self._samples_root.exists():
            return results
        for person_dir in self._samples_root.iterdir():
            if not person_dir.is_dir():
                continue
            for sample_path in person_dir.glob("*.enc"):
                hnsw_id = int(sample_path.stem)
                embedding = self._decrypt_sample(sample_path)
                results.append((person_dir.name, hnsw_id, embedding))
        return results

    def _decrypt_sample(self, path: Path) -> list[float]:
        raw = path.read_bytes()
        nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        try:
            payload = self._aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        except InvalidTag as exc:
            raise PresenceError(
                f"Sample at {path} could not be decrypted: wrong key or tampered file."
            ) from exc
        return [float(value) for value in payload.decode("utf-8").split(" ")]

    def delete_sample(self, person_id: str, hnsw_id: int) -> None:
        path = self._samples_root / person_id / f"{hnsw_id}.enc"
        if not path.exists():
            return
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.write(secrets.token_bytes(size))
            handle.flush()
            os.fsync(handle.fileno())
        path.unlink()

    def delete_all_samples_for_person(self, person_id: str) -> None:
        """Securely deletes every raw sample kept for a person. Not called
        by name_person: the spec's Technical Decisions keep the embedding
        indefinitely once a person is named, only the snapshot is deleted
        on naming (requisito 12). This exists for an explicit future
        "forget this person entirely" operation, not part of v1's API
        Contracts."""
        person_dir = self._samples_root / person_id
        if not person_dir.exists():
            return
        for sample_path in person_dir.glob("*.enc"):
            size = sample_path.stat().st_size
            with sample_path.open("r+b") as handle:
                handle.write(secrets.token_bytes(size))
                handle.flush()
                os.fsync(handle.fileno())
            sample_path.unlink()


def new_person_id() -> str:
    import uuid

    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)
