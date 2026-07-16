PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS service_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO service_meta(key, value) VALUES
  ('service_version', '0.1.0'), ('schema_version', '2');
UPDATE service_meta SET value = '2' WHERE key = 'schema_version';

CREATE TABLE IF NOT EXISTS items (
  item_id INTEGER PRIMARY KEY,
  scope_id TEXT NOT NULL,
  root_kref TEXT NOT NULL,
  kind TEXT NOT NULL,
  hypothesis TEXT NOT NULL DEFAULT '',
  confidence_ppm INTEGER NOT NULL CHECK(confidence_ppm BETWEEN 0 AND 1000000),
  stakes TEXT NOT NULL DEFAULT 'medium',
  is_core_conviction INTEGER NOT NULL DEFAULT 0 CHECK(is_core_conviction IN (0,1)),
  last_evidence_days INTEGER CHECK(last_evidence_days IS NULL OR last_evidence_days >= 0),
  deprecated INTEGER NOT NULL DEFAULT 0 CHECK(deprecated IN (0,1)),
  deprecated_at TEXT,
  deprecation_reason TEXT,
  deprecated_by TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(scope_id, root_kref)
);

CREATE TABLE IF NOT EXISTS revisions (
  revision_id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(item_id),
  logical_kref TEXT NOT NULL,
  kind TEXT NOT NULL,
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  actor TEXT NOT NULL,
  revision_reason TEXT NOT NULL,
  last_evidence_days INTEGER,
  contradicts_prior INTEGER NOT NULL DEFAULT 0 CHECK(contradicts_prior IN (0,1)),
  contradiction_reason TEXT NOT NULL DEFAULT '',
  supersedes_revision_id INTEGER REFERENCES revisions(revision_id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_service_revisions_item
  ON revisions(item_id, revision_id);

CREATE TABLE IF NOT EXISTS tags (
  item_id INTEGER NOT NULL REFERENCES items(item_id),
  name TEXT NOT NULL,
  revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
  moved_at TEXT NOT NULL,
  PRIMARY KEY(item_id, name)
);

CREATE TABLE IF NOT EXISTS dependencies (
  dependent_item_id INTEGER NOT NULL REFERENCES items(item_id),
  support_item_id INTEGER NOT NULL REFERENCES items(item_id),
  strength_ppm INTEGER NOT NULL CHECK(strength_ppm BETWEEN 0 AND 1000000),
  created_at TEXT NOT NULL,
  PRIMARY KEY(dependent_item_id, support_item_id)
);
CREATE INDEX IF NOT EXISTS idx_service_dependencies_support
  ON dependencies(support_item_id, dependent_item_id);

CREATE TABLE IF NOT EXISTS operations (
  scope_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  operation TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  result_json TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY(scope_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS cascades (
  cascade_id INTEGER PRIMARY KEY,
  scope_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  origin_item_id INTEGER NOT NULL REFERENCES items(item_id),
  trigger_revision_id INTEGER REFERENCES revisions(revision_id),
  old_confidence_ppm INTEGER NOT NULL,
  new_confidence_ppm INTEGER NOT NULL,
  nodes_visited INTEGER NOT NULL,
  truncated INTEGER NOT NULL CHECK(truncated IN (0,1)),
  cycles_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(scope_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT PRIMARY KEY,
  cascade_id INTEGER NOT NULL REFERENCES cascades(cascade_id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL,
  target_item_id INTEGER NOT NULL REFERENCES items(item_id),
  upstream_item_id INTEGER NOT NULL REFERENCES items(item_id),
  depth INTEGER NOT NULL,
  old_confidence_ppm INTEGER NOT NULL,
  new_confidence_ppm INTEGER NOT NULL,
  beta_ppm INTEGER NOT NULL,
  gamma_ppm INTEGER NOT NULL,
  delta_ppm INTEGER NOT NULL,
  perturbation_ppm INTEGER NOT NULL,
  damped_ppm INTEGER NOT NULL,
  llm_delta_ppm INTEGER NOT NULL,
  llm_rationale TEXT NOT NULL,
  contradiction_detected INTEGER NOT NULL CHECK(contradiction_detected IN (0,1)),
  route TEXT NOT NULL,
  status TEXT NOT NULL,
  canonical_output TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(cascade_id, target_item_id)
);
CREATE INDEX IF NOT EXISTS idx_service_proposals_target
  ON proposals(target_item_id, created_at);

CREATE TABLE IF NOT EXISTS audit_events (
  event_id INTEGER PRIMARY KEY,
  scope_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  root_kref TEXT NOT NULL,
  actor TEXT NOT NULL,
  details_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_service_audit_scope_root
  ON audit_events(scope_id, root_kref, event_id);
