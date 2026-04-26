-- Atlas Hash-Chained Ledger — Atlas-original.
-- Bicameral's change_ledger.py uses random event_ids (no chain).
-- Atlas adds previous_hash + monotonic chain_sequence + verify_chain().

PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS change_events (
    -- HASH CHAIN (Atlas-original; Bicameral lacks these fields)
    event_id        TEXT PRIMARY KEY,        -- SHA-256(previous_hash + canonical_payload)
    previous_hash   TEXT,                    -- NULL for genesis; SHA-256 of prior row's event_id
    chain_sequence  INTEGER NOT NULL UNIQUE, -- Monotonic; gap detection signal

    -- Event content (port from Bicameral)
    event_type      TEXT NOT NULL,           -- assert | supersede | invalidate |
                                             -- refine | derive | promote |
                                             -- procedure_success | procedure_failure
    recorded_at     TEXT NOT NULL,           -- ISO 8601 with TZ
    actor_id        TEXT NOT NULL,           -- 'rich' | 'atlas' | extractor name
    reason          TEXT,                    -- Free-text justification

    -- Identity / lineage
    object_id       TEXT NOT NULL,           -- kref:// of the affected revision
    target_object_id TEXT,                   -- For supersede/derive: prior kref
    object_type     TEXT NOT NULL,           -- 'Person' | 'Program' | 'Commitment' | etc.
    root_id         TEXT NOT NULL,           -- Lineage anchor — root item kref
    parent_id       TEXT,                    -- Direct ancestor revision

    -- Cross-references
    candidate_id    TEXT,                    -- ULID from candidates.db (when promoted)
    policy_version  TEXT,                    -- Promotion policy version applied

    -- Payload + audit
    payload_json    TEXT NOT NULL,           -- Full event content
    metadata_json   TEXT                     -- Free-form audit metadata
);

-- Lineage queries
CREATE INDEX IF NOT EXISTS idx_change_events_root      ON change_events(root_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_change_events_object    ON change_events(object_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_change_events_chain     ON change_events(chain_sequence);
CREATE INDEX IF NOT EXISTS idx_change_events_candidate ON change_events(candidate_id);

-- Materialized view: current state per root lineage (port from Bicameral)
CREATE TABLE IF NOT EXISTS typed_roots (
    root_id            TEXT PRIMARY KEY,
    object_type        TEXT NOT NULL,
    latest_object_id   TEXT NOT NULL,
    latest_event_id    TEXT NOT NULL,
    latest_recorded_at TEXT NOT NULL,
    is_invalidated     INTEGER NOT NULL DEFAULT 0  -- Boolean; 1 if contracted
);

CREATE INDEX IF NOT EXISTS idx_typed_roots_type_recency
  ON typed_roots(object_type, latest_recorded_at);

-- Chain integrity verification audit trail
CREATE TABLE IF NOT EXISTS chain_verifications (
    verified_at             TEXT PRIMARY KEY,
    last_verified_sequence  INTEGER NOT NULL,
    last_verified_event_id  TEXT NOT NULL,
    chain_intact            INTEGER NOT NULL,  -- Boolean
    verifier_version        TEXT NOT NULL,
    notes                   TEXT
);
