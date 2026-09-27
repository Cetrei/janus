-- Initial schema for state_dir/presence/presence.db (SPEC.md requisito 6).
--
-- Kept as a versioned reference of the schema, not read at runtime:
-- PresenceStore.__init__ applies this same schema itself via
-- `executescript`, with `CREATE TABLE IF NOT EXISTS`, so a fresh
-- presence.db is self-initializing without needing this file. If the
-- schema ever needs a real migration (altering an existing presence.db),
-- add 0002_*.sql here and a matching migration step in PresenceStore
-- rather than editing this file after the fact.

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
