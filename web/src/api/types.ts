// Mirrors server/unheard/api/schemas.py (API v1, see docs/api.md).

export type RecordingStatus = 'uploaded' | 'processing' | 'ready' | 'failed';

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  instance?: string;
  [k: string]: unknown;
}

export interface Health {
  status: 'ok';
  version: string;
  api_version: string;
  dsp_version: number;
  schema_version: number;
  inference: 'local' | 'remote';
  model_loaded: boolean;
  decoder: { ffmpeg_available: boolean; ffmpeg_version: string | null; fallback: string };
  limits: {
    max_upload_bytes: number;
    min_duration_s: number;
    max_duration_s: number;
    canonical_sample_rate: number;
    silence_dbfs: number;
    supported_containers: string[];
  };
  recordings: number;
  free_disk_bytes: number | null;
  python: string;
}

export interface Quality {
  peak: number;
  peak_dbfs: number;
  rms_dbfs: number;
  dc_offset: number;
  clipped_samples: number;
  clipping_ratio: number;
  flags: string[];
  decoder?: string;
}

export interface ErrorInfo {
  stage: string | null;
  message: string;
  attempts: number | null;
}

export interface RecordingSummary {
  id: string;
  created_at: string;
  captured_at: string | null;
  original_filename: string | null;
  duration_s: number;
  status: RecordingStatus;
  quality: Quality;
  error: ErrorInfo | null;
  dsp_version: number | null;
}

export interface Stats {
  mean: number;
  median: number;
  std: number;
  min: number;
  max: number;
}

export interface FeatureSummary {
  dsp_version: number;
  sample_rate: number;
  n_samples: number;
  duration_s: number;
  peak: number;
  peak_dbfs: number;
  rms: number;
  rms_dbfs: number;
  clipping_ratio: number;
  zero_crossing_rate: number;
  zero_crossings_per_s: number;
  active_frame_ratio: number;
  spectral_centroid_hz: Stats;
  spectral_bandwidth_hz: Stats;
  spectral_rolloff_hz: Stats;
  spectral_flatness: Stats;
  spectral_flux: Stats;
  rms_envelope_dbfs: Stats;
  onset_count: number;
  onset_density_per_s: number;
  onset_times_s: number[];
  log_mel: { n_mels: number; n_frames: number; fmin_hz: number; fmax_hz: number; min_db: number; max_db: number; dominant_band_hz: number };
}

export interface InferenceInfo {
  status: 'not_run' | 'ok' | 'failed' | 'unavailable';
  model_id: string | null;
  model_version: string | null;
  predictions: { label: string; score: number }[];
  embedding: { dim: number } | null;
  error: { code: string; message: string } | null;
}

export interface RecordingDetail extends RecordingSummary {
  content_hash: string;
  source_hash: string;
  client_mime: string | null;
  device_info: Record<string, unknown> | null;
  assets: { kind: 'source' | 'canonical'; container: string | null; codec: string | null; sample_rate: number; channels: number; bytes: number }[];
  jobs: { id: string; stage: string; status: string; attempts: number; error: string | null; updated_at: string }[];
  features: FeatureSummary | null;
  inference: InferenceInfo;
  links: Record<string, string>;
}

export interface RecordingList {
  items: RecordingSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface UploadAccepted {
  recording_id: string;
  status: RecordingStatus;
  duration_s: number;
  quality: Quality;
  links: Record<string, string>;
}

export interface Features {
  recording_id: string;
  dsp_version: number;
  artifact_sha256: string;
  summary: FeatureSummary;
  waveform: { buckets: number; duration_s: number; min: number[]; max: number[]; rms: number[] };
  series: {
    times_s: number[];
    rms_envelope_db: number[];
    centroid_hz: number[];
    bandwidth_hz: number[];
    rolloff_hz: number[];
    flatness: number[];
    flux: number[];
  };
  onset_strength: number[];
  onset_times_s: number[];
}

export interface Spectrogram {
  recording_id: string;
  kind: 'mel' | 'stft';
  dsp_version: number;
  unit: 'dB';
  n_bins: number;
  n_frames: number;
  frames_pooled: number;
  duration_s: number;
  freqs_hz: number[];
  times_s: number[];
  min_db: number;
  max_db: number;
  values: number[][];
}
