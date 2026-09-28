-- Ampliación 2026-09-27 (requisito 38): identity lifecycle, roles, per-
-- modality embeddings, visits, evidence, exclusions and sources.
--
-- Applied at runtime by PresenceStore._migrate() inside a transaction,
-- gated on PRAGMA user_version (only advances if the transaction commits,
-- per the ampliación's edge case "Migración interrumpida"). Kept here too
-- as a versioned reference, same convention as 0001_init.sql.

ALTER TABLE persons ADD COLUMN role TEXT;
ALTER TABLE persons ADD COLUMN state TEXT NOT NULL DEFAULT 'established';
ALTER TABLE persons ADD COLUMN presented_at TEXT;

-- Backfill: every person that existed before this migration was tracked
-- under the old known/unknown boolean. known=1 maps to ESTABLISHED (they
-- already had a label and were fully trusted under v1); known=0 maps to
-- UNKNOWN (no label yet, same meaning as before).
UPDATE persons SET state = 'established' WHERE known = 1;
UPDATE persons SET state = 'unknown' WHERE known = 0;

ALTER TABLE person_embeddings ADD COLUMN modality TEXT NOT NULL DEFAULT 'face';

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
