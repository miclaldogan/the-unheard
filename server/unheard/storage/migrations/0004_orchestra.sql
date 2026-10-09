-- 0004: the Impossible Orchestra (M4) — compositions, their sources, tracks and events.
-- recording ids are stored as plain text (no FK) on purpose: deleting a recording deletes the
-- compositions that contain it (service-level cascade), so no row can outlive its source.

CREATE TABLE IF NOT EXISTS composition (
    id TEXT PRIMARY KEY,
    parent_id TEXT,                          -- variation lineage
    name TEXT NOT NULL,
    saved INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('queued','processing','ready','failed')),
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    seed INTEGER NOT NULL,
    planner_version INTEGER NOT NULL,
    render_version INTEGER NOT NULL,
    analysis_version INTEGER NOT NULL,
    dsp_version INTEGER NOT NULL,
    request_hash TEXT NOT NULL,              -- idempotency key over sources+seed+controls+versions
    controls_json TEXT NOT NULL,
    overrides_json TEXT NOT NULL,
    target_duration_s REAL NOT NULL,
    duration_s REAL,
    tempo_bpm REAL,
    plan_json TEXT,
    plan_hash TEXT,
    metrics_json TEXT,
    master_path TEXT,
    master_sha256 TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rendered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_composition_request ON composition(request_hash);

CREATE TABLE IF NOT EXISTS composition_source (
    composition_id TEXT NOT NULL REFERENCES composition(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,               -- canonical order (content_hash ascending)
    recording_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    role TEXT,
    secondary_role TEXT,
    decision_json TEXT,                      -- scores + evidence + rationale
    analysis_json TEXT,
    PRIMARY KEY (composition_id, position)
);
CREATE INDEX IF NOT EXISTS idx_composition_source_rec ON composition_source(recording_id);

CREATE TABLE IF NOT EXISTS composition_track (
    id TEXT PRIMARY KEY,
    composition_id TEXT NOT NULL REFERENCES composition(id) ON DELETE CASCADE,
    track_key TEXT NOT NULL,                 -- plan track id ("t1", ...)
    recording_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    layer_order INTEGER NOT NULL,
    pan REAL NOT NULL,
    enters TEXT NOT NULL,
    stem_path TEXT,
    stem_sha256 TEXT,
    UNIQUE (composition_id, track_key)
);

CREATE TABLE IF NOT EXISTS composition_event (
    composition_id TEXT NOT NULL REFERENCES composition(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    track_key TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    role TEXT NOT NULL,
    section TEXT NOT NULL,
    comp_start_s REAL NOT NULL,
    comp_dur_s REAL NOT NULL,
    source_start_s REAL NOT NULL,
    source_end_s REAL NOT NULL,
    params_json TEXT NOT NULL,
    PRIMARY KEY (composition_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_composition_event_rec ON composition_event(recording_id);
