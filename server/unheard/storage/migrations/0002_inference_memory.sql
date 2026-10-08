-- 0002: model inference, embeddings, labels, annotations and personal acoustic memory (M2).

CREATE TABLE IF NOT EXISTS model_version (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,                     -- e.g. 'laion/clap-htsat-unfused'
    revision TEXT NOT NULL,                 -- checkpoint commit hash or tag
    framework TEXT NOT NULL,                -- 'transformers+torch'
    preprocessing_version INTEGER NOT NULL, -- adapter windowing/resampling contract version
    embedding_dim INTEGER NOT NULL,
    input_sample_rate INTEGER NOT NULL,
    license_note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (name, revision, preprocessing_version)
);

-- One row per window plus one pooled row (window_idx = -1) per recording/model.
CREATE TABLE IF NOT EXISTS embedding (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    model_version_id TEXT NOT NULL REFERENCES model_version(id),
    window_idx INTEGER NOT NULL,
    window_start_s REAL NOT NULL,
    window_end_s REAL NOT NULL,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL,                      -- float32 little-endian, L2-normalised
    created_at TEXT NOT NULL,
    UNIQUE (recording_id, model_version_id, window_idx)
);
CREATE INDEX IF NOT EXISTS embedding_recording_idx ON embedding(recording_id);

-- Source labels (what made the sound). Vocabulary rows come from the adapter's controlled
-- list; user rows are created from the Teach panel. Descriptors/environment/mood are NOT
-- labels: they live on the annotation and never feed classification.
CREATE TABLE IF NOT EXISTS label (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,              -- normalised internal id, e.g. 'running_water'
    name TEXT NOT NULL,                     -- display name
    origin TEXT NOT NULL CHECK (origin IN ('vocabulary','user')),
    text_prompt TEXT,                       -- prompt embedded by the text tower for zero-shot
    text_vec BLOB,                          -- float32 LE text embedding (nullable)
    text_model_version_id TEXT REFERENCES model_version(id),
    merged_into TEXT REFERENCES label(id),
    hue_seed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Model output per recording. kind='base' = ears only; kind='fused' = ears + memory at
-- memory_version. Latest row per kind is the current prediction.
CREATE TABLE IF NOT EXISTS prediction (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    model_version_id TEXT NOT NULL REFERENCES model_version(id),
    kind TEXT NOT NULL CHECK (kind IN ('base','fused')),
    memory_version INTEGER NOT NULL DEFAULT 0,
    score_kind TEXT NOT NULL,               -- documents the semantics of results_json scores
    results_json TEXT NOT NULL,             -- ranked candidates
    windows_json TEXT,                      -- per-window top labels (base only)
    novelty_json TEXT,                      -- unknown-detection evidence
    inference_ms REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS prediction_recording_idx ON prediction(recording_id, kind, created_at);

-- Human annotations. One 'active' row per recording; a new submission supersedes the old.
CREATE TABLE IF NOT EXISTS annotation (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('confirm','correct','create','unknown')),
    status TEXT NOT NULL CHECK (status IN ('active','superseded')),
    label_ids_json TEXT NOT NULL,           -- source labels (may be empty when unknown)
    rejected_label_ids_json TEXT NOT NULL DEFAULT '[]',
    is_unknown INTEGER NOT NULL DEFAULT 0,
    descriptors_json TEXT NOT NULL DEFAULT '[]',   -- how it sounds (rhythmic, tonal, ...)
    environment TEXT,                       -- where (free text, short)
    mood TEXT,                              -- what it evokes (free text, short)
    note TEXT,
    prediction_id TEXT REFERENCES prediction(id) ON DELETE SET NULL,  -- what the user saw
    superseded_by TEXT REFERENCES annotation(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS annotation_recording_idx ON annotation(recording_id, status);

-- Memory membership: an (embedding, label) pair contributed by an annotation.
CREATE TABLE IF NOT EXISTS exemplar (
    id TEXT PRIMARY KEY,
    annotation_id TEXT NOT NULL REFERENCES annotation(id) ON DELETE CASCADE,
    embedding_id TEXT NOT NULL REFERENCES embedding(id) ON DELETE CASCADE,
    recording_id TEXT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    label_id TEXT NOT NULL REFERENCES label(id),
    weight REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL CHECK (status IN ('active','retracted')),
    created_at TEXT NOT NULL,
    UNIQUE (annotation_id, embedding_id, label_id)
);
CREATE INDEX IF NOT EXISTS exemplar_label_idx ON exemplar(label_id, status);

CREATE TABLE IF NOT EXISTS prototype (
    label_id TEXT NOT NULL REFERENCES label(id) ON DELETE CASCADE,
    model_version_id TEXT NOT NULL REFERENCES model_version(id),
    vec BLOB NOT NULL,
    n_eff REAL NOT NULL,
    sigma REAL NOT NULL,                    -- mean cosine distance of exemplars to prototype
    memory_version INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (label_id, model_version_id)
);

CREATE TABLE IF NOT EXISTS memory_meta (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
INSERT OR IGNORE INTO memory_meta (key, value_json) VALUES ('memory_version', '0');
