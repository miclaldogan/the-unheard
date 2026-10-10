-- 0006: ECHO-0's narrative layer (M5). Truth is always re-derived from the existing tables; these rows only
-- store generated wording, activated missions and settings. Nothing here is authoritative game state.

-- One utterance per narrative moment (moment_key is derived from real records, e.g. 'annotation:<id>').
CREATE TABLE IF NOT EXISTS narrative_utterance (
    id TEXT PRIMARY KEY,
    moment_key TEXT NOT NULL UNIQUE,
    moment_kind TEXT NOT NULL,
    act TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    facts_hash TEXT NOT NULL,               -- regenerate when the cited facts change
    facts_json TEXT NOT NULL,
    lines_json TEXT NOT NULL,
    recording_ids_json TEXT NOT NULL DEFAULT '[]',   -- for dropping utterances whose recordings were deleted
    composition_id TEXT,
    source TEXT NOT NULL CHECK (source IN ('gemma','template')),
    model TEXT,
    status TEXT NOT NULL CHECK (status IN ('ready','pending','fallback')),
    fallback_reason TEXT,
    latency_ms REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS narrative_utterance_time ON narrative_utterance(occurred_at);

-- Missions the player activated. Candidates are computed live; only activation/completion is stored.
CREATE TABLE IF NOT EXISTS narrative_mission (
    id TEXT PRIMARY KEY,                    -- stable: msn_ + hash(type, evidence key)
    type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','completed','expired')),
    params_json TEXT NOT NULL,              -- type-specific targets (label id, recording ids, thresholds)
    baseline_json TEXT NOT NULL,            -- recordings that existed at activation
    snapshot_json TEXT NOT NULL,            -- title/objective/reason as shown at activation
    activated_at TEXT NOT NULL,
    completed_at TEXT,
    completion_evidence_json TEXT
);

-- Settings, selection cache and generation statistics (key/value).
CREATE TABLE IF NOT EXISTS narrative_meta (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
INSERT OR IGNORE INTO narrative_meta (key, value_json) VALUES ('gemma_enabled', 'true');
INSERT OR IGNORE INTO narrative_meta (key, value_json) VALUES ('revision', '0');
