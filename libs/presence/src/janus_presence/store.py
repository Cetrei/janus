from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from janus_platform.paths import make_private

from janus_presence.errors import PersonNotFoundError, PresenceError
from janus_presence.models import (
    NO_INDEXED_EMBEDDING,
    Evidence,
    EvidenceOrigin,
    EvidenceStatus,
    IdentityState,
    PersonRecord,
    Sighting,
    SourceConfig,
    SourceKind,
    SourceLocation,
    Visit,
)

_log = logging.getLogger(__name__)

_NONCE_SIZE = 12
_FACE_MODALITY = "face"


def secure_delete(path: Path) -> None:
    """Overwrites a file with random bytes, flushes it to disk and removes
    it (same pattern biometrics uses for `delete`). A missing file is a
    no-op, so callers can delete idempotently."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    with path.open("r+b") as handle:
        handle.write(secrets.token_bytes(size))
        handle.flush()
        os.fsync(handle.fileno())
    path.unlink()


# -- migrations (requisito 38) ---------------------------------------------------
#
# Each migration is a callable that receives a _MigrationContext. PresenceStore
# runs every migration whose number is greater than PRAGMA user_version, each
# inside one transaction, and user_version only advances if that transaction
# commits (edge case "Migración interrumpida"). The .sql files under
# migrations/ mirror these functions as human readable reference; the code
# below is what actually runs.


def _split_statements(script: str) -> Iterator[str]:
    """Splits a SQL script into single statements.

    Cuts at every `;` for which sqlite3.complete_statement() says the text so
    far is a whole statement, so semicolons inside string literals, comments
    and trigger bodies never split one. Splitting by line would break the
    moment two statements share a line.
    """
    start = 0
    for position, char in enumerate(script):
        if char != ";":
            continue
        fragment = script[start : position + 1]
        if sqlite3.complete_statement(fragment):
            if _has_sql(fragment):
                yield fragment.strip()
            start = position + 1
    tail = script[start:]
    if _has_sql(tail):
        yield tail.strip()


def _has_sql(fragment: str) -> bool:
    return any(
        line.strip() and not line.strip().startswith("--") for line in fragment.splitlines()
    )


class _MigrationContext:
    """What a migration receives instead of the raw connection.

    sqlite3.Connection.executescript() issues an implicit COMMIT before it
    runs, which silently ends the transaction the runner opened: any DDL a
    migration ran earlier would already be durable when a later statement
    fails, and the promised atomicity would be false. This wrapper's
    executescript() runs statement by statement inside the runner's
    transaction instead, so a migration is all or nothing.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def executescript(self, script: str) -> None:
        for statement in _split_statements(script):
            self._conn.execute(statement)


def _migration_0001(ctx: _MigrationContext) -> None:
    ctx.executescript(
        """
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
    )


def _migration_0002(ctx: _MigrationContext) -> None:
    # The column guards are not needed for atomicity anymore. They stay so a
    # database that an earlier build half-migrated (its executescript()
    # committed the ALTERs before failing) can still be finished.
    columns = {row[1] for row in ctx.execute("PRAGMA table_info(persons)")}
    if "role" not in columns:
        ctx.execute("ALTER TABLE persons ADD COLUMN role TEXT")
    if "state" not in columns:
        ctx.execute("ALTER TABLE persons ADD COLUMN state TEXT NOT NULL DEFAULT 'established'")
    if "presented_at" not in columns:
        ctx.execute("ALTER TABLE persons ADD COLUMN presented_at TEXT")

    ctx.execute("UPDATE persons SET state = 'established' WHERE known = 1")
    ctx.execute("UPDATE persons SET state = 'unknown' WHERE known = 0")

    embedding_columns = {row[1] for row in ctx.execute("PRAGMA table_info(person_embeddings)")}
    if "modality" not in embedding_columns:
        ctx.execute(
            "ALTER TABLE person_embeddings ADD COLUMN modality TEXT NOT NULL DEFAULT 'face'"
        )

    ctx.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            source TEXT NOT NULL,
            device TEXT NOT NULL,
            label TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            sample_fps REAL
        );

        CREATE TABLE IF NOT EXISTS visits (
            visit_id TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES persons(person_id),
            source_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            ended_at TEXT,
            clip_ref TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_visits_person ON visits(person_id);
        CREATE INDEX IF NOT EXISTS idx_visits_open ON visits(source_id, ended_at);

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES persons(person_id),
            source_id TEXT NOT NULL,
            modality TEXT NOT NULL,
            hnsw_id INTEGER NOT NULL,
            captured_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            hypothesis_person_id TEXT REFERENCES persons(person_id),
            hypothesis_confidence REAL,
            presented_at TEXT,
            origin TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_evidence_status ON evidence(status);
        CREATE INDEX IF NOT EXISTS idx_evidence_person ON evidence(person_id);

        CREATE TABLE IF NOT EXISTS person_exclusions (
            person_id TEXT NOT NULL REFERENCES persons(person_id),
            excluded_hypothesis_person_id TEXT NOT NULL REFERENCES persons(person_id),
            evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
            created_at TEXT NOT NULL,
            PRIMARY KEY (person_id, excluded_hypothesis_person_id, evidence_id)
        );
        """
    )


def _migration_0003(ctx: _MigrationContext) -> None:
    """Structural fixes, most of which SQLite can only make by rebuilding tables.

    * sightings.camera_id stops being a foreign key to cameras. A sighting is
      history and a source is configuration: requiring the camera row made
      every observe() fail until something registered it, and would block
      removing a decommissioned source. It is now a soft reference to a source
      id, the same way visits.source_id and evidence.source_id already are.
    * cameras is folded into sources (requisito 21, 38) and dropped.
    * person_embeddings.hnsw_id was UNIQUE on its own, but each modality has
      its own index with its own id space (requisito 23): uniqueness is now per
      (modality, hnsw_id), otherwise a voice embedding could never reuse the
      id of a face embedding.
    * evidence.promoted records that confirming the evidence copied its
      embedding into the person's templates, so retracting it can undo that.
    """
    ctx.executescript(
        """
        CREATE TABLE sightings_new (
            sighting_id TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES persons(person_id),
            camera_id TEXT NOT NULL,
            seen_at TEXT NOT NULL,
            confidence REAL NOT NULL,
            clip_ref TEXT
        );
        INSERT INTO sightings_new
            SELECT sighting_id, person_id, camera_id, seen_at, confidence, clip_ref
            FROM sightings;
        DROP TABLE sightings;
        ALTER TABLE sightings_new RENAME TO sightings;
        CREATE INDEX IF NOT EXISTS idx_sightings_person ON sightings(person_id);

        INSERT OR IGNORE INTO sources (source_id, kind, source, device, label, enabled)
            SELECT camera_id, 'camera',
                   CASE WHEN source_kind IN ('local', 'rtsp', 'mcp')
                        THEN source_kind ELSE 'local' END,
                   camera_id, label, 1
            FROM cameras;
        DROP TABLE cameras;

        CREATE TABLE person_embeddings_new (
            embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT NOT NULL REFERENCES persons(person_id),
            hnsw_id INTEGER NOT NULL,
            modality TEXT NOT NULL DEFAULT 'face',
            UNIQUE (modality, hnsw_id)
        );
        INSERT INTO person_embeddings_new (embedding_id, person_id, hnsw_id, modality)
            SELECT embedding_id, person_id, hnsw_id, modality FROM person_embeddings;
        DROP TABLE person_embeddings;
        ALTER TABLE person_embeddings_new RENAME TO person_embeddings;
        CREATE INDEX IF NOT EXISTS idx_embeddings_person ON person_embeddings(person_id);

        ALTER TABLE evidence ADD COLUMN promoted INTEGER NOT NULL DEFAULT 0;
        """
    )


_MIGRATIONS: list[tuple[int, Callable[[_MigrationContext], None]]] = [
    (1, _migration_0001),
    (2, _migration_0002),
    (3, _migration_0003),
]

LATEST_SCHEMA_VERSION = _MIGRATIONS[-1][0]


def _component(value: str) -> str:
    """Rejects an id that could escape its directory when used as a path
    component. Ids are internal UUIDs, so this is defense in depth for the
    files that hold third party biometrics."""
    if not value or value in {".", ".."} or Path(value).name != value:
        raise PresenceError(f"Unsafe identifier for a storage path: {value!r}")
    return value


def _sample_filename(modality: str, hnsw_id: int) -> str:
    # Face samples keep the bare `<hnsw_id>.enc` name they always had; other
    # modalities are prefixed, because each modality numbers its ids from
    # zero independently (requisito 23).
    if modality == _FACE_MODALITY:
        return f"{hnsw_id}.enc"
    return f"{modality}_{hnsw_id}.enc"


def _parse_sample_filename(stem: str) -> tuple[str, int]:
    modality, separator, raw_id = stem.rpartition("_")
    if not separator:
        return _FACE_MODALITY, int(raw_id)
    return modality, int(raw_id)


class PresenceStore:
    """Own SQLite database at state_dir/presence/presence.db (requisito 6).
    Never janus.db, never a table shared with libs/persistence: presence is
    a spoke and keeps its own storage, same criterion as libs/biometrics.

    Schema is applied via versioned migrations gated on PRAGMA user_version
    (requisito 38), WAL journal mode, and foreign keys enforced. A single
    writer (this class) mutates; read-only queries never block it because
    SQLite's WAL mode allows concurrent readers.

    Every mutator commits on its own unless it runs inside `transaction()`,
    which groups several of them so they succeed or fail together.

    Raw embeddings never sit in this .db (requisito 7): person_embeddings
    only keeps `hnsw_id` (plus `modality`, requisito 23), the durable integer
    id of an embedding. The actual floats are only ever persisted, encrypted,
    as raw samples on disk (save_sample / load_all_samples), which is how the
    in-memory HNSW index is rebuilt at startup until hnsw-c gains its own
    save/load extension. Embeddings of evidence that has not been confirmed
    yet live in the same encrypted form under `pending/`, outside `samples/`,
    so they can never be mistaken for, or rebuilt into, a person's templates
    (requisito 27).
    """

    def __init__(self, state_dir: Path, key: bytes) -> None:
        if len(key) != 32:
            raise PresenceError("Presence sample encryption key must be 32 bytes (AES-256)")
        self._root = Path(state_dir) / "presence"
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "presence.db"
        self._samples_root = self._root / "samples"
        self._pending_root = self._root / "pending"
        self._snapshots_root = self._root / "snapshots"
        self._thumbs_root = self._root / "evidence_thumbs"
        self._settings_path = self._root / "settings.json"
        self._aesgcm = AESGCM(key)
        self._in_transaction = False

        is_new = not self._db_path.exists()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        # NORMAL is the recommended pairing with WAL: a power cut can lose the
        # last commit but never corrupts the file.
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        if is_new:
            make_private(self._db_path)

    def _migrate(self) -> None:
        """requisito 38: applies every pending migration in order, each in
        its own transaction. user_version only advances when that migration
        commits, so a failure midway leaves the database at the last good
        version, safe to retry."""
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for version, migration in _MIGRATIONS:
            if version <= current:
                continue
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                migration(_MigrationContext(self._conn))
                self._conn.execute(f"PRAGMA user_version = {version}")
            except BaseException:
                self._conn.rollback()
                raise
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Groups every mutation done inside the block into one atomic
        commit; an exception rolls all of them back. Re-entrant: a nested
        block simply joins the outer one."""
        if self._in_transaction:
            yield
            return
        self._conn.execute("BEGIN IMMEDIATE")
        self._in_transaction = True
        try:
            yield
        except BaseException:
            self._in_transaction = False
            self._conn.rollback()
            raise
        self._in_transaction = False
        self._conn.commit()

    def _commit(self) -> None:
        if not self._in_transaction:
            self._conn.commit()

    # -- persons ----------------------------------------------------------

    def create_person(self, person: PersonRecord) -> None:
        self._conn.execute(
            """INSERT INTO persons
               (person_id, label, known, role, state, presented_at,
                first_seen_at, last_seen_at, snapshot_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                person.person_id,
                person.label,
                int(person.known),
                person.role,
                person.state.value,
                person.presented_at.isoformat() if person.presented_at else None,
                person.first_seen_at.isoformat(),
                person.last_seen_at.isoformat(),
                person.snapshot_ref,
            ),
        )
        self._commit()

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
               SET label = ?, known = ?, role = ?, state = ?, presented_at = ?,
                   last_seen_at = ?, snapshot_ref = ?
               WHERE person_id = ?""",
            (
                person.label,
                int(person.known),
                person.role,
                person.state.value,
                person.presented_at.isoformat() if person.presented_at else None,
                person.last_seen_at.isoformat(),
                person.snapshot_ref,
                person.person_id,
            ),
        )
        self._commit()
        if cursor.rowcount == 0:
            raise PersonNotFoundError(person.person_id)

    def delete_person(self, person_id: str) -> None:
        """Erases the person and every row that references them, in one
        transaction (requisitos 34 and 37). With foreign keys enforced, the
        parent row cannot go while children point at it, so this removes the
        children first: exclusions, then evidence (after detaching the
        hypotheses other people's evidence holds about this person), visits,
        sightings and embeddings.

        Files on disk (samples, pending samples, snapshot) are the caller's
        job: the store cannot know which ones a service-level operation
        already moved or wants to keep.
        """
        with self.transaction():
            self._conn.execute(
                """DELETE FROM person_exclusions
                   WHERE person_id = ? OR excluded_hypothesis_person_id = ?
                      OR evidence_id IN (SELECT evidence_id FROM evidence WHERE person_id = ?)""",
                (person_id, person_id, person_id),
            )
            self._conn.execute(
                """UPDATE evidence SET hypothesis_person_id = NULL, hypothesis_confidence = NULL
                   WHERE hypothesis_person_id = ?""",
                (person_id,),
            )
            for table in ("evidence", "visits", "sightings", "person_embeddings"):
                self._conn.execute(f"DELETE FROM {table} WHERE person_id = ?", (person_id,))
            self._conn.execute("DELETE FROM persons WHERE person_id = ?", (person_id,))

    def all_persons(self) -> list[PersonRecord]:
        rows = self._conn.execute("SELECT * FROM persons").fetchall()
        return [self._row_to_person(row) for row in rows]

    def _row_to_person(self, row: sqlite3.Row) -> PersonRecord:
        # embedding_ids lists the person's embeddings of every modality;
        # callers that need one modality use embeddings_for_person().
        embedding_ids = [
            r["hnsw_id"]
            for r in self._conn.execute(
                "SELECT hnsw_id FROM person_embeddings WHERE person_id = ? ORDER BY embedding_id",
                (row["person_id"],),
            ).fetchall()
        ]
        return PersonRecord(
            person_id=row["person_id"],
            label=row["label"],
            state=IdentityState(row["state"]),
            role=row["role"],
            embedding_ids=embedding_ids,
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            snapshot_ref=row["snapshot_ref"],
            presented_at=(
                datetime.fromisoformat(row["presented_at"]) if row["presented_at"] else None
            ),
        )

    # -- person_embeddings --------------------------------------------------

    def add_embedding(self, person_id: str, hnsw_id: int, modality: str = _FACE_MODALITY) -> None:
        self._conn.execute(
            "INSERT INTO person_embeddings (person_id, hnsw_id, modality) VALUES (?, ?, ?)",
            (person_id, hnsw_id, modality),
        )
        self._commit()

    def person_id_for_hnsw_id(self, hnsw_id: int, modality: str = _FACE_MODALITY) -> str | None:
        row = self._conn.execute(
            "SELECT person_id FROM person_embeddings WHERE hnsw_id = ? AND modality = ?",
            (hnsw_id, modality),
        ).fetchone()
        return row["person_id"] if row is not None else None

    def all_embeddings(self, modality: str = _FACE_MODALITY) -> list[tuple[str, int]]:
        """Every (person_id, hnsw_id) pair for one modality, used to
        rebuild the in-memory HNSW index of that modality at startup."""
        rows = self._conn.execute(
            "SELECT person_id, hnsw_id FROM person_embeddings WHERE modality = ?", (modality,)
        ).fetchall()
        return [(r["person_id"], r["hnsw_id"]) for r in rows]

    def embeddings_for_person(self, person_id: str, modality: str = _FACE_MODALITY) -> list[int]:
        """The durable ids of one person's embeddings in one modality,
        oldest first."""
        rows = self._conn.execute(
            """SELECT hnsw_id FROM person_embeddings
               WHERE person_id = ? AND modality = ? ORDER BY embedding_id""",
            (person_id, modality),
        ).fetchall()
        return [r["hnsw_id"] for r in rows]

    def delete_embedding(self, hnsw_id: int, modality: str = _FACE_MODALITY) -> bool:
        """Drops one embedding row. Returns whether a row existed."""
        cursor = self._conn.execute(
            "DELETE FROM person_embeddings WHERE hnsw_id = ? AND modality = ?",
            (hnsw_id, modality),
        )
        self._commit()
        return cursor.rowcount > 0

    def reassign_embeddings(self, from_person_id: str, to_person_id: str) -> None:
        """requisito 37: used by merge_persons to move every embedding row
        from the source person to the target person."""
        self._conn.execute(
            "UPDATE person_embeddings SET person_id = ? WHERE person_id = ?",
            (to_person_id, from_person_id),
        )
        self._commit()

    # -- cameras / sources ----------------------------------------------------

    def upsert_camera(self, camera_id: str, label: str, source_kind: str) -> None:
        """Registers a camera. Cameras are now just sources of kind
        `camera` (migration 0003 folded the old cameras table into
        sources); kept so callers written against the v1 API still work."""
        self.upsert_source(
            SourceConfig(
                source_id=camera_id,
                kind=SourceKind.CAMERA,
                source=SourceLocation(source_kind),
                device=camera_id,
                label=label,
            )
        )

    def upsert_source(self, source: SourceConfig) -> None:
        """requisito 21: registers one configured camera or microphone."""
        self._conn.execute(
            """INSERT INTO sources (source_id, kind, source, device, label, enabled, sample_fps)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id) DO UPDATE SET
                   kind = excluded.kind, source = excluded.source, device = excluded.device,
                   label = excluded.label, enabled = excluded.enabled,
                   sample_fps = excluded.sample_fps""",
            (
                source.source_id,
                source.kind.value,
                source.source.value,
                source.device,
                source.label,
                int(source.enabled),
                source.sample_fps,
            ),
        )
        self._commit()

    def all_sources(self) -> list[SourceConfig]:
        rows = self._conn.execute("SELECT * FROM sources").fetchall()
        return [
            SourceConfig(
                source_id=row["source_id"],
                kind=SourceKind(row["kind"]),
                source=SourceLocation(row["source"]),
                device=row["device"],
                label=row["label"],
                enabled=bool(row["enabled"]),
                sample_fps=row["sample_fps"],
            )
            for row in rows
        ]

    # -- sightings ------------------------------------------------------------

    def record_sighting(self, sighting: Sighting) -> None:
        """`sighting.camera_id` is a soft reference to a source id: it does
        not have to be registered (see migration 0003)."""
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
        self._commit()

    def reassign_sightings(self, from_person_id: str, to_person_id: str) -> None:
        """requisito 37: used by merge_persons."""
        self._conn.execute(
            "UPDATE sightings SET person_id = ? WHERE person_id = ?",
            (to_person_id, from_person_id),
        )
        self._commit()

    # -- visits (requisito 30) ------------------------------------------------

    def create_visit(self, visit: Visit) -> None:
        self._conn.execute(
            """INSERT INTO visits
               (visit_id, person_id, source_id, started_at, last_seen_at, ended_at, clip_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                visit.visit_id,
                visit.person_id,
                visit.source_id,
                visit.started_at.isoformat(),
                visit.last_seen_at.isoformat(),
                visit.ended_at.isoformat() if visit.ended_at else None,
                visit.clip_ref,
            ),
        )
        self._commit()

    def open_visit(self, person_id: str, source_id: str) -> Visit | None:
        """The visit for this person/source that has not ended yet, if
        any (requisito 30: a new sighting within visit_gap_s extends it
        instead of opening a new one)."""
        row = self._conn.execute(
            """SELECT * FROM visits
               WHERE person_id = ? AND source_id = ? AND ended_at IS NULL
               ORDER BY started_at DESC LIMIT 1""",
            (person_id, source_id),
        ).fetchone()
        return self._row_to_visit(row) if row is not None else None

    def update_visit(self, visit: Visit) -> None:
        self._conn.execute(
            """UPDATE visits SET last_seen_at = ?, ended_at = ?, clip_ref = ?
               WHERE visit_id = ?""",
            (
                visit.last_seen_at.isoformat(),
                visit.ended_at.isoformat() if visit.ended_at else None,
                visit.clip_ref,
                visit.visit_id,
            ),
        )
        self._commit()

    def open_visits(self) -> list[Visit]:
        """Every visit not yet closed, used by the runner to decide which
        ones have gone past visit_gap_s and must be ended."""
        rows = self._conn.execute("SELECT * FROM visits WHERE ended_at IS NULL").fetchall()
        return [self._row_to_visit(row) for row in rows]

    def reassign_visits(self, from_person_id: str, to_person_id: str) -> None:
        """requisito 37: used by merge_persons."""
        self._conn.execute(
            "UPDATE visits SET person_id = ? WHERE person_id = ?",
            (to_person_id, from_person_id),
        )
        self._commit()

    @staticmethod
    def _row_to_visit(row: sqlite3.Row) -> Visit:
        return Visit(
            visit_id=row["visit_id"],
            person_id=row["person_id"],
            source_id=row["source_id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
            clip_ref=row["clip_ref"],
        )

    # -- evidence (requisito 27, 28) ------------------------------------------

    def create_evidence(self, evidence: Evidence) -> None:
        self._conn.execute(
            """INSERT INTO evidence
               (evidence_id, person_id, source_id, modality, hnsw_id, captured_at,
                status, hypothesis_person_id, hypothesis_confidence, presented_at, origin,
                promoted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evidence.evidence_id,
                evidence.person_id,
                evidence.source_id,
                evidence.modality,
                evidence.hnsw_id,
                evidence.captured_at.isoformat(),
                evidence.status.value,
                evidence.hypothesis_person_id,
                evidence.hypothesis_confidence,
                evidence.presented_at.isoformat() if evidence.presented_at else None,
                evidence.origin.value if evidence.origin else None,
                int(evidence.promoted),
            ),
        )
        self._commit()

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        row = self._conn.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        return self._row_to_evidence(row) if row is not None else None

    def update_evidence(self, evidence: Evidence) -> None:
        cursor = self._conn.execute(
            """UPDATE evidence SET hnsw_id = ?, status = ?, hypothesis_person_id = ?,
                   hypothesis_confidence = ?, presented_at = ?, origin = ?, promoted = ?
               WHERE evidence_id = ?""",
            (
                evidence.hnsw_id,
                evidence.status.value,
                evidence.hypothesis_person_id,
                evidence.hypothesis_confidence,
                evidence.presented_at.isoformat() if evidence.presented_at else None,
                evidence.origin.value if evidence.origin else None,
                int(evidence.promoted),
                evidence.evidence_id,
            ),
        )
        self._commit()
        if cursor.rowcount == 0:
            raise PresenceError(f"No evidence found with evidence_id '{evidence.evidence_id}'")

    def pending_evidence(self) -> list[Evidence]:
        """requisito 29: pending_review() groups this by visit at the
        service layer; the store just returns every PENDING row."""
        rows = self._conn.execute(
            "SELECT * FROM evidence WHERE status = ? ORDER BY captured_at",
            (EvidenceStatus.PENDING.value,),
        ).fetchall()
        return [self._row_to_evidence(row) for row in rows]

    def evidence_ids_for_person(self, person_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT evidence_id FROM evidence WHERE person_id = ?", (person_id,)
        ).fetchall()
        return [r["evidence_id"] for r in rows]

    def count_evidence(self, person_id: str, status: EvidenceStatus) -> int:
        """requisito 26: used to decide PROVISIONAL -> ESTABLISHED once
        enough CONFIRMED evidence accumulates for a person."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE person_id = ? AND status = ?",
            (person_id, status.value),
        ).fetchone()
        return row[0]

    def unpromote_evidence_for_embedding(
        self, hnsw_id: int, modality: str = _FACE_MODALITY
    ) -> None:
        """Marks as not promoted any evidence whose embedding was just
        removed from the templates (displaced as redundant, or retracted).
        Ids are only unique among live embeddings, so a stale pointer could
        later aim at an unrelated embedding that reuses the number."""
        self._conn.execute(
            """UPDATE evidence SET promoted = 0, hnsw_id = ?
               WHERE promoted = 1 AND hnsw_id = ? AND modality = ?""",
            (NO_INDEXED_EMBEDDING, hnsw_id, modality),
        )
        self._commit()

    def reassign_evidence(self, from_person_id: str, to_person_id: str) -> None:
        """requisito 37: used by merge_persons. Moves the evidence itself,
        repoints the hypotheses other evidence held about the source, and
        clears a hypothesis that would now name the evidence's own person."""
        self._conn.execute(
            "UPDATE evidence SET hypothesis_person_id = ? WHERE hypothesis_person_id = ?",
            (to_person_id, from_person_id),
        )
        self._conn.execute(
            "UPDATE evidence SET person_id = ? WHERE person_id = ?",
            (to_person_id, from_person_id),
        )
        self._conn.execute(
            """UPDATE evidence SET hypothesis_person_id = NULL, hypothesis_confidence = NULL
               WHERE hypothesis_person_id = person_id"""
        )
        self._commit()

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> Evidence:
        return Evidence(
            evidence_id=row["evidence_id"],
            person_id=row["person_id"],
            source_id=row["source_id"],
            modality=row["modality"],
            hnsw_id=row["hnsw_id"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            status=EvidenceStatus(row["status"]),
            hypothesis_person_id=row["hypothesis_person_id"],
            hypothesis_confidence=row["hypothesis_confidence"],
            presented_at=(
                datetime.fromisoformat(row["presented_at"]) if row["presented_at"] else None
            ),
            origin=EvidenceOrigin(row["origin"]) if row["origin"] else None,
            promoted=bool(row["promoted"]),
        )

    # -- person_exclusions (requisito 27) --------------------------------------

    def add_exclusion(
        self, person_id: str, excluded_hypothesis_person_id: str, evidence_id: str
    ) -> None:
        """Records a counterexample: the system must not propose
        `excluded_hypothesis_person_id` again for evidence that looks like
        `person_id`. Both people and the evidence must exist (foreign keys
        are enforced; OR IGNORE only covers the duplicate primary key)."""
        self._conn.execute(
            """INSERT OR IGNORE INTO person_exclusions
               (person_id, excluded_hypothesis_person_id, evidence_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (person_id, excluded_hypothesis_person_id, evidence_id, utcnow().isoformat()),
        )
        self._commit()

    def is_excluded(self, person_id: str, hypothesis_person_id: str) -> bool:
        row = self._conn.execute(
            """SELECT 1 FROM person_exclusions
               WHERE person_id = ? AND excluded_hypothesis_person_id = ? LIMIT 1""",
            (person_id, hypothesis_person_id),
        ).fetchone()
        return row is not None

    def reassign_exclusions(self, from_person_id: str, to_person_id: str) -> None:
        """requisito 37: used by merge_persons. Rows that would collide with
        an existing primary key are left for delete_person to clear, and an
        exclusion that ends up saying "X is not X" carries no information,
        so it is dropped."""
        self._conn.execute(
            "UPDATE OR IGNORE person_exclusions SET person_id = ? WHERE person_id = ?",
            (to_person_id, from_person_id),
        )
        self._conn.execute(
            """UPDATE OR IGNORE person_exclusions SET excluded_hypothesis_person_id = ?
               WHERE excluded_hypothesis_person_id = ?""",
            (to_person_id, from_person_id),
        )
        self._conn.execute(
            "DELETE FROM person_exclusions WHERE person_id = excluded_hypothesis_person_id"
        )
        self._commit()

    # -- encrypted raw samples (requisito 7) ---------------------------------

    def save_sample(
        self,
        person_id: str,
        hnsw_id: int,
        embedding: list[float],
        modality: str = _FACE_MODALITY,
    ) -> None:
        """Persists one raw embedding, encrypted, so the HNSW index (in
        memory only, requisito 7) can be rebuilt on the next startup. This
        is the only place presence keeps the actual floats of a template
        on disk."""
        person_dir = self._samples_root / _component(person_id)
        person_dir.mkdir(parents=True, exist_ok=True)
        path = person_dir / _sample_filename(modality, hnsw_id)
        path.write_bytes(self._encrypt_embedding(embedding))
        make_private(path)

    def load_all_samples(
        self, modality: str = _FACE_MODALITY
    ) -> list[tuple[str, int, list[float]]]:
        """Decrypts every retained raw sample of one modality:
        (person_id, hnsw_id, embedding). Used to rebuild that modality's
        PresenceIndex at startup, so the order is deterministic (person
        directory, then id) but callers must not rely on it."""
        results: list[tuple[str, int, list[float]]] = []
        if not self._samples_root.exists():
            return results
        for person_dir in sorted(self._samples_root.iterdir()):
            if not person_dir.is_dir():
                continue
            for hnsw_id, embedding in self._samples_in(person_dir, modality).items():
                results.append((person_dir.name, hnsw_id, embedding))
        return results

    def load_person_samples(
        self, person_id: str, modality: str = _FACE_MODALITY
    ) -> dict[int, list[float]]:
        """One person's decrypted samples of one modality, by durable id."""
        person_dir = self._samples_root / _component(person_id)
        if not person_dir.is_dir():
            return {}
        return self._samples_in(person_dir, modality)

    def _samples_in(self, person_dir: Path, modality: str) -> dict[int, list[float]]:
        samples: dict[int, list[float]] = {}
        for sample_path in sorted(person_dir.glob("*.enc")):
            try:
                sample_modality, hnsw_id = _parse_sample_filename(sample_path.stem)
            except ValueError:
                _log.warning("ignoring file with an unrecognised sample name: %s", sample_path)
                continue
            if sample_modality == modality:
                samples[hnsw_id] = self._decrypt_sample(sample_path)
        return samples

    def delete_sample(
        self, person_id: str, hnsw_id: int, modality: str = _FACE_MODALITY
    ) -> None:
        person_dir = self._samples_root / _component(person_id)
        secure_delete(person_dir / _sample_filename(modality, hnsw_id))

    def delete_all_samples_for_person(self, person_id: str) -> None:
        """Securely deletes every raw sample kept for a person, of every
        modality. Used by forget_person (requisito 34)."""
        person_dir = self._samples_root / _component(person_id)
        if not person_dir.exists():
            return
        for sample_path in person_dir.glob("*.enc"):
            secure_delete(sample_path)
        try:
            person_dir.rmdir()
        except OSError:
            _log.warning("could not remove sample directory %s", person_dir)

    def move_samples(self, from_person_id: str, to_person_id: str) -> None:
        """requisito 37: merge_persons reassigns embeddings in the database,
        and the encrypted files that back them live under the owner's
        directory. Left behind, they would survive forgetting the target
        (requisito 34). File names are unique per (modality, hnsw_id), so
        two people never hold the same name."""
        source_dir = self._samples_root / _component(from_person_id)
        if not source_dir.is_dir():
            return
        target_dir = self._samples_root / _component(to_person_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        for sample_path in sorted(source_dir.glob("*.enc")):
            destination = target_dir / sample_path.name
            if destination.exists():
                raise PresenceError(f"Refusing to overwrite an existing sample: {destination}")
            sample_path.replace(destination)
        try:
            source_dir.rmdir()
        except OSError:
            _log.warning("could not remove sample directory %s", source_dir)

    # -- pending samples: embeddings of unconfirmed evidence (requisito 27) ---

    def save_pending_sample(self, evidence_id: str, embedding: list[float]) -> None:
        """Keeps the embedding an evidence was captured with, encrypted, so
        confirming it later can reinforce the person's templates (requisito
        28). Never read by load_all_samples: pending evidence must not touch
        the index (requisito 27)."""
        self._pending_root.mkdir(parents=True, exist_ok=True)
        path = self._pending_path(evidence_id)
        path.write_bytes(self._encrypt_embedding(embedding))
        make_private(path)

    def load_pending_sample(self, evidence_id: str) -> list[float] | None:
        path = self._pending_path(evidence_id)
        if not path.exists():
            return None
        return self._decrypt_sample(path)

    def delete_pending_sample(self, evidence_id: str) -> None:
        secure_delete(self._pending_path(evidence_id))

    def _pending_path(self, evidence_id: str) -> Path:
        return self._pending_root / f"{_component(evidence_id)}.enc"

    # -- encrypted evidence thumbnails (review page) ---------------------------
    #
    # One small JPEG of the face for each pending evidence, so the owner can see
    # who they are confirming or rejecting. Same AES-256-GCM envelope as
    # snapshots. It lives only while the evidence is pending: resolving or
    # forgetting the evidence deletes it.

    def save_evidence_thumb(self, evidence_id: str, jpeg_bytes: bytes) -> None:
        self._thumbs_root.mkdir(parents=True, exist_ok=True)
        path = self._thumb_path(evidence_id)
        path.write_bytes(self._encrypt_bytes(jpeg_bytes))
        make_private(path)

    def load_evidence_thumb(self, evidence_id: str) -> bytes | None:
        path = self._thumb_path(evidence_id)
        if not path.exists():
            return None
        return self._decrypt_bytes(path)

    def has_evidence_thumb(self, evidence_id: str) -> bool:
        return self._thumb_path(evidence_id).exists()

    def delete_evidence_thumb(self, evidence_id: str) -> None:
        secure_delete(self._thumb_path(evidence_id))

    def _thumb_path(self, evidence_id: str) -> Path:
        return self._thumbs_root / f"{_component(evidence_id)}.jpg.enc"

    # -- settings the owner changes from the review page --------------------------

    def get_setting(self, key: str) -> Any | None:
        return self._read_settings().get(key)

    def set_setting(self, key: str, value: Any) -> None:
        """Writes to a temporary file and renames it over the real one, so a crash
        never leaves a half written settings file."""
        settings = self._read_settings()
        settings[key] = value
        temporary = self._settings_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings), encoding="utf-8")
        make_private(temporary)
        temporary.replace(self._settings_path)

    def _read_settings(self) -> dict[str, Any]:
        if not self._settings_path.exists():
            return {}
        try:
            loaded = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log.warning("ignoring unreadable settings file %s: %s", self._settings_path, exc)
            return {}
        return loaded if isinstance(loaded, dict) else {}

    # -- encrypted snapshots (requisito 12, 38, ampliación F2) -----------------
    #
    # A snapshot is one JPEG frame taken at the moment an UNKNOWN person is
    # first detected (requisito 11, 13), kept only while that person has no
    # label (requisito 12). Like samples and pending samples, the plaintext
    # JPEG never touches disk: this stores the same AES-256-GCM envelope
    # (nonce + ciphertext) the embedding methods use, just with raw JPEG
    # bytes as the payload instead of a serialized float vector.

    def save_snapshot(self, person_id: str, jpeg_bytes: bytes) -> str:
        """Encrypts and writes one snapshot for person_id, returning the
        `snapshot_ref` path to store on the PersonRecord. Overwrites any
        snapshot already on file for this person (there is only ever one:
        requisito 12 retains a single frame, not a gallery)."""
        self._snapshots_root.mkdir(parents=True, exist_ok=True)
        path = self._snapshot_path(person_id)
        path.write_bytes(self._encrypt_bytes(jpeg_bytes))
        make_private(path)
        return str(path)

    def load_snapshot(self, person_id: str) -> bytes | None:
        """Decrypts and returns the retained JPEG bytes for person_id, or
        None if no snapshot is on file (already named, expired, or never
        captured because quality_ok was False)."""
        path = self._snapshot_path(person_id)
        if not path.exists():
            return None
        return self._decrypt_bytes(path)

    def delete_snapshot(self, person_id: str) -> None:
        """Securely deletes the retained snapshot, if any. Idempotent, same
        as every other delete in this class."""
        secure_delete(self._snapshot_path(person_id))

    def _snapshot_path(self, person_id: str) -> Path:
        return self._snapshots_root / f"{_component(person_id)}.jpg.enc"

    # -- encryption -------------------------------------------------------------

    def _encrypt_embedding(self, embedding: list[float]) -> bytes:
        payload = " ".join(repr(value) for value in embedding).encode("utf-8")
        return self._encrypt_bytes(payload)

    def _encrypt_bytes(self, payload: bytes) -> bytes:
        nonce = secrets.token_bytes(_NONCE_SIZE)
        return nonce + self._aesgcm.encrypt(nonce, payload, associated_data=None)

    def _decrypt_sample(self, path: Path) -> list[float]:
        payload = self._decrypt_bytes(path)
        return [float(value) for value in payload.decode("utf-8").split(" ")]

    def _decrypt_bytes(self, path: Path) -> bytes:
        raw = path.read_bytes()
        nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        try:
            return self._aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        except InvalidTag as exc:
            raise PresenceError(
                f"File at {path} could not be decrypted: wrong key or tampered file."
            ) from exc


def new_person_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)
