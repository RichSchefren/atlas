-- Atlas Candidates Store — quarantine SQLite schema.
-- Ported from Bicameral truth/candidates.py with Atlas lane names.
-- Single source of truth for promotion-state lifecycle.

PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS candidates (
    -- Identity
    candidate_id TEXT PRIMARY KEY,        -- ULID, time-sortable + cryptographic random suffix
    fingerprint TEXT NOT NULL,            -- SHA-256(canonical claim) — UNIQUE, dedups identical
                                          --    claims arriving from different sources
    -- Lifecycle state
    status TEXT NOT NULL,                 -- pending | requires_approval | auto_promoted |
                                          --    approved | denied
    risk_level TEXT NOT NULL,             -- low | medium | high
    policy_version TEXT NOT NULL,         -- promotion policy version applied
    trust_score REAL NOT NULL,            -- 0.25 (single source) / 0.6 (corroborated) / 1.0 (ledger)

    -- Content
    lane TEXT NOT NULL,                   -- atlas_sessions | atlas_om | atlas_imported | etc.
    assertion_type TEXT NOT NULL,         -- decision | preference | factual_assertion |
                                          --    episode | procedure
    subject_kref TEXT NOT NULL,           -- kref of the entity being asserted about
    predicate TEXT NOT NULL,              -- e.g., 'pricing_belief', 'role'
    object_value TEXT NOT NULL,           -- the asserted value
    scope TEXT NOT NULL DEFAULT 'global', -- private/group_safe/global

    -- Evidence
    evidence_refs_json TEXT NOT NULL,     -- JSON list of {source, source_family, kref, timestamp}
    evidence_stats_json TEXT NOT NULL,    -- JSON: {n_sources, independent_source_families, ...}
    confidence REAL NOT NULL,             -- per-source confidence (NOT trust_score)

    -- Policy trace
    policy_trace_json TEXT NOT NULL,      -- JSON: {recommendation, reasons, evaluated_at}

    -- Lineage
    decision_id TEXT,                     -- 'auto_promoted' or NULL or human-resolution UUID
    ledger_event_id TEXT,                 -- foreign-key into change_events (when promoted)
    conflict_with_fact_id TEXT,           -- candidate_id of a conflicting fact (if any)

    -- Audit timestamps
    created_at TEXT NOT NULL,             -- ISO 8601 UTC
    updated_at TEXT NOT NULL,
    promoted_at TEXT,
    denied_at TEXT,

    UNIQUE (fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_candidates_status        ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_lane          ON candidates(lane);
CREATE INDEX IF NOT EXISTS idx_candidates_subject       ON candidates(subject_kref);
CREATE INDEX IF NOT EXISTS idx_candidates_subject_pred  ON candidates(subject_kref, predicate);
CREATE INDEX IF NOT EXISTS idx_candidates_pending_age   ON candidates(status, created_at);


-- Append-only verification records — keyed by (candidate_id, verifier_version).
CREATE TABLE IF NOT EXISTS candidate_verifications (
    candidate_id      TEXT NOT NULL,
    verifier_version  TEXT NOT NULL,
    verified_at       TEXT NOT NULL,
    verification_status TEXT NOT NULL,   -- pending | corroborated | contradicted |
                                         --    insufficient_evidence
    notes             TEXT,
    PRIMARY KEY (candidate_id, verifier_version, verified_at),
    FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_verifications_candidate ON candidate_verifications(candidate_id);


-- Dead letter queue — failed extractions after N retries.
CREATE TABLE IF NOT EXISTS om_dead_letter_queue (
    dead_letter_id    TEXT PRIMARY KEY,
    source_lane       TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    attempts          INTEGER NOT NULL,
    last_error        TEXT,
    first_seen_at     TEXT NOT NULL,
    last_attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dlq_lane ON om_dead_letter_queue(source_lane);
