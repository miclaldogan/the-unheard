-- 0003: visual artifacts (acoustic signatures) and the acoustic atlas (M3).

-- One artifact per (recording, generator version). Params are compact JSON derived from the
-- scientific tables; geometry is rendered in the browser from these params + the seed.
CREATE TABLE IF NOT EXISTS visual_artifact (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    generator_version INTEGER NOT NULL,
    seed INTEGER NOT NULL,                  -- first 8 hex of content_hash as int (stable)
    dsp_version INTEGER NOT NULL,
    model_version_id TEXT REFERENCES model_version(id),
    geometry_hash TEXT NOT NULL,            -- sha256 of label-independent geometry params
    params_json TEXT NOT NULL,              -- geometry + semantic layer + animation timelines
    status TEXT NOT NULL CHECK (status IN ('ready','stale')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (recording_id, generator_version)
);

-- Frozen PCA basis + saved node positions per (model version, layout version).
CREATE TABLE IF NOT EXISTS atlas_state (
    id TEXT PRIMARY KEY,
    model_version_id TEXT NOT NULL REFERENCES model_version(id),
    layout_version INTEGER NOT NULL,
    basis BLOB,                             -- float32 LE (2 x dim) + mean (dim), NULL until fitted
    basis_n INTEGER NOT NULL DEFAULT 0,     -- recordings the basis was fitted on
    explained_variance REAL,
    positions_json TEXT NOT NULL,           -- {recording_id: [x, y]}
    atlas_version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (model_version_id, layout_version)
);
