from __future__ import annotations

import sqlite3
from pathlib import Path

from janus_presence.errors import PersonNotFoundError
from janus_presence.models import PersonRecord, Sighting

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class PresenceStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        for migration_path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            self._connection.executescript(migration_path.read_text())
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def insert_person(self, person: PersonRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO persons
                (person_id, label, known, first_seen_at, last_seen_at, snapshot_ref)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                person.person_id,
                person.label,
                int(person.known),
                person.first_seen_at,
                person.last_seen_at,
                person.snapshot_ref,
            ),
        )
        self._connection.commit()

    def get_person(self, person_id: str) -> PersonRecord:
        row = self._connection.execute(
            "SELECT person_id, label, known, first_seen_at, last_seen_at, snapshot_ref "
            "FROM persons WHERE person_id = ?",
            (person_id,),
        ).fetchone()
        if row is None:
            raise PersonNotFoundError(person_id)
        return self._person_from_row(row)

    def update_last_seen(self, person_id: str, seen_at: str) -> None:
        self._require_person_exists(person_id)
        self._connection.execute(
            "UPDATE persons SET last_seen_at = ? WHERE person_id = ?",
            (seen_at, person_id),
        )
        self._connection.commit()

    def name_person(self, person_id: str, label: str) -> PersonRecord:
        self._require_person_exists(person_id)
        self._connection.execute(
            "UPDATE persons SET label = ?, known = 1, snapshot_ref = NULL "
            "WHERE person_id = ?",
            (label, person_id),
        )
        self._connection.commit()
        return self.get_person(person_id)

    def clear_snapshot(self, person_id: str) -> None:
        self._require_person_exists(person_id)
        self._connection.execute(
            "UPDATE persons SET snapshot_ref = NULL WHERE person_id = ?",
            (person_id,),
        )
        self._connection.commit()

    def add_embedding(self, person_id: str, hnsw_id: int) -> int:
        self._require_person_exists(person_id)
        cursor = self._connection.execute(
            "INSERT INTO person_embeddings (person_id, hnsw_id) VALUES (?, ?)",
            (person_id, hnsw_id),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def get_person_id_for_hnsw_id(self, hnsw_id: int) -> str:
        row = self._connection.execute(
            "SELECT person_id FROM person_embeddings WHERE hnsw_id = ?",
            (hnsw_id,),
        ).fetchone()
        if row is None:
            raise PersonNotFoundError(f"no person for hnsw_id={hnsw_id}")
        return row[0]

    def get_embedding_ids(self, person_id: str) -> list[int]:
        self._require_person_exists(person_id)
        rows = self._connection.execute(
            "SELECT hnsw_id FROM person_embeddings WHERE person_id = ?",
            (person_id,),
        ).fetchall()
        return [row[0] for row in rows]

    def ensure_camera(self, camera_id: str, source_kind: str, label: str | None = None) -> None:
        self._connection.execute(
            """
            INSERT INTO cameras (camera_id, label, source_kind)
            VALUES (?, ?, ?)
            ON CONFLICT(camera_id) DO NOTHING
            """,
            (camera_id, label, source_kind),
        )
        self._connection.commit()

    def insert_sighting(self, sighting: Sighting) -> None:
        self._connection.execute(
            """
            INSERT INTO sightings
                (sighting_id, person_id, camera_id, seen_at, confidence, clip_ref)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sighting.sighting_id,
                sighting.person_id,
                sighting.camera_id,
                sighting.seen_at,
                sighting.confidence,
                sighting.clip_ref,
            ),
        )
        self._connection.commit()

    def _require_person_exists(self, person_id: str) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM persons WHERE person_id = ?", (person_id,)
        ).fetchone()
        if row is None:
            raise PersonNotFoundError(person_id)

    def _person_from_row(self, row: tuple) -> PersonRecord:
        person_id, label, known, first_seen_at, last_seen_at, snapshot_ref = row
        return PersonRecord(
            person_id=person_id,
            label=label,
            known=bool(known),
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
            snapshot_ref=snapshot_ref,
            embedding_ids=self.get_embedding_ids(person_id),
        )
