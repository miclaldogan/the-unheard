-- 0001_init: M1 subset of the doc 08 schema. Primary keys are UUIDv7 text.
-- Later migrations add label/annotation/exemplar/prototype/embedding/prediction tables (M2).

CREATE TABLE IF NOT EXISTS install (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS recording (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    content_hash TEXT NOT NULL UNIQUE,      -- sha256 of canonical PCM (48 kHz mono float32)
    source_hash TEXT NOT NULL,              -- sha256 of the uploaded bytes
    created_at TEXT NOT NULL,
    captured_at TEXT,
    original_filename TEXT,
    client_mime TEXT,
    device_info_json TEXT,
    duration_s REAL NOT NULL,
    quality_json TEXT NOT NULL,             -- signal-level flags measured on decoded audio
    status TEXT NOT NULL CHECK (status IN ('uploaded','processing','ready','failed')),
    error_json TEXT,
    deleted_at TEXT
);

-- One row per stored file (source upload + canonical PCM). doc 08 "audio_asset".
CREATE TABLE IF NOT EXISTS audio_asset (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('source','canonical')),
    path TEXT NOT NULL,                     -- relative to data_dir
    container TEXT,                         -- sniffed container (wav, webm, mp4, ogg, flac, mp3)
    codec TEXT,                             -- as reported by ffprobe
    sample_rate INTEGER NOT NULL,
    channels INTEGER NOT NULL,
    sample_format TEXT,
    bytes INTEGER NOT NULL,
    UNIQUE (recording_id, kind)
);

CREATE TABLE IF NOT EXISTS feature_set (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    dsp_version INTEGER NOT NULL,
    summary_json TEXT NOT NULL,             -- scalar features + parameters
    artifact_path TEXT NOT NULL,            -- .npz with spectrogram / log-mel / envelopes
    artifact_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (recording_id, dsp_version)
);

CREATE TABLE IF NOT EXISTS job (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recording(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,                    -- 'dsp' (M1); 'embed', 'predict' later
    status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS job_status_idx ON job(status, created_at);

CREATE TABLE IF NOT EXISTS event (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    recording_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS event_recording_idx ON event(recording_id, created_at);
