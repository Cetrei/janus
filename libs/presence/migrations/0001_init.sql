-- janus_presence: initial schema.
-- See SPEC.md, functional requirement 6. Lives in state_dir/presence/presence.db,
-- never janus.db or any libs/persistence table (this is a spoke, not the core).

CREATE TABLE IF NOT EXISTS persons (
    person_id TEXT PRIMARY KEY,
    label TEXT,
    known INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    snapshot_ref TEXT
);

CREATE TABLE IF NOT EXISTS person_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL REFERENCES persons(person_id),
    hnsw_id INTEGER NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_person_embeddings_person_id
    ON person_embeddings(person_id);

CREATE TABLE IF NOT EXISTS cameras (
    camera_id TEXT PRIMARY KEY,
    label TEXT,
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

CREATE INDEX IF NOT EXISTS idx_sightings_person_id ON sightings(person_id);
CREATE INDEX IF NOT EXISTS idx_sightings_camera_id ON sightings(camera_id);
