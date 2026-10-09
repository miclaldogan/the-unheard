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

// ---------------------------------------------------------------- M2: hearing + memory

export interface ModelStatus {
  status: 'disabled' | 'not_loaded' | 'loading' | 'ready' | 'failed';
  model_id: string | null;
  revision: string | null;
  device: string;
  embedding_dim: number | null;
  preprocessing_version: number;
  load_seconds: number | null;
  error: string | null;
  inference: 'local' | 'remote';
}

export type PredictionState = 'model_disabled' | 'not_run' | 'analyzing' | 'inference_failed' | 'awaiting_feedback' | 'remembered';

export interface BaseCandidate {
  label_id: string;
  slug: string;
  name: string;
  rank: number;
  similarity: number; // cosine(audio, text), max over windows
}

export interface FusedCandidate {
  label_id: string;
  slug: string;
  name: string;
  rank: number;
  fused_score: number; // relative ranking score over the label space (sums to 1), not calibrated
  base_similarity: number;
  base_score: number;
  memory_similarity: number | null; // max cosine to an exemplar of this label
  memory_score: number | null;
  n_exemplars: number;
  lambda: number;
  evidence: 'ears' | 'memory' | 'both';
}

export interface Novelty {
  novel: boolean;
  nearest_exemplar_similarity: number | null;
  fused_margin: number;
  base_entropy_normalised: number;
  memory_size: number;
  relevant_exemplars: number;
  lambda: number;
  nothing_similar_remembered: boolean;
  disagreement: boolean;
  ears_top: string;
  memory_top: string | null;
  neighbours: { exemplar_id: string; recording_id: string; label_id: string; similarity: number }[];
}

export interface AnnotationOut {
  id: string;
  recording_id: string;
  action: 'confirm' | 'correct' | 'create' | 'unknown';
  status: 'active' | 'superseded';
  labels: { label_id: string; slug: string; name: string }[];
  rejected_label_ids: string[];
  is_unknown: boolean;
  descriptors: string[];
  environment: string | null;
  mood: string | null;
  note: string | null;
  prediction_id: string | null;
  superseded_by: string | null;
  created_at: string;
}

export interface Prediction {
  recording_id: string;
  state: PredictionState;
  model_status: string;
  model: { id: string; revision: string; preprocessing_version: number; embedding_dim: number } | null;
  job: { status: string; error: string | null; attempts: number; updated_at: string } | null;
  base: { score_kind: string; candidates: BaseCandidate[]; windows: { idx: number; start_s: number; end_s: number; top: { label_id: string; name: string; similarity: number }[] }[]; inference_ms: number | null; created_at: string } | null;
  fused: { score_kind: string; memory_version: number; candidates: FusedCandidate[]; novelty: Novelty; created_at: string } | null;
  annotation: AnnotationOut | null;
}

export interface Label {
  id: string;
  slug: string;
  name: string;
  origin: 'vocabulary' | 'user';
  n_exemplars: number;
  hue_seed: number;
}

export interface AnnotationIn {
  label_ids?: string[];
  new_labels?: string[];
  rejected_label_ids?: string[];
  is_unknown?: boolean;
  descriptors?: string[];
  environment?: string | null;
  mood?: string | null;
  note?: string | null;
}

export interface AnnotationResult {
  annotation: AnnotationOut;
  memory_version: number;
  exemplars_added: number;
  exemplars_retracted: number;
  created_label_ids: string[];
  rescored_changes: { recording_id: string; from: string | null; to: string }[];
  fused_top: FusedCandidate[];
}

export interface MemoryOverview {
  memory_version: number;
  model_version_id: string | null;
  exemplars: number;
  annotations: number;
  unknown_annotations: number;
  custom_labels: number;
  labels: { label_id: string; slug: string; name: string; origin: 'vocabulary' | 'user'; n_exemplars: number; hue_seed: number; recording_ids: string[]; prototype: { n_eff: number; sigma: number } | null }[];
  label_names: Record<string, string>;
}

export interface Neighbour {
  recording_id: string;
  similarity: number;
  labels: string[];
  is_unknown: boolean;
  captured_at: string | null;
  duration_s: number | null;
}

export interface EchoLine {
  template: string;
  text: string;
  tags: ('model' | 'memory' | 'imagination')[];
  event_ids: string[];
}

// ---------------------------------------------------------------- M3: specimens + atlas

export interface VisualGeometry {
  ring: number[]; // 128 normalised RMS envelope points
  bands: number[]; // 32 normalised log-mel band means
  brightness_curve: number[]; // 32 normalised centroid points
  ticks: number[]; // onset positions 0..1
  sharpness: number;
  symmetry_order: number;
  jitter: number;
  fragmentation: number;
  scale: number;
  energy: number;
  duration_s: number;
  onset_density_per_s: number;
}

export interface VisualSemantic {
  label: string | null;
  hue: number | null;
  state: 'unknown' | 'uncertain' | 'hypothesis' | 'confirmed';
  resolution: number;
  confirmed_labels: string[];
  descriptors: string[];
  environment: string | null;
  mood: string | null;
  why: { novel: boolean; nearest_exemplar_similarity: number | null; fused_margin: number | null; base_entropy_normalised: number | null; disagreement: boolean } | null;
  model_version_id: string | null;
  memory_version: number | null;
}

export interface VisualParams {
  generator_version: number;
  seed: number;
  dsp_version: number;
  geometry: VisualGeometry;
  animation: { duration_s: number; envelope: number[]; flux: number[]; onsets_s: number[] };
  semantic: VisualSemantic;
  geometry_hash: string;
}

export interface Visual {
  artifact_id: string;
  recording_id: string;
  generator_version: number;
  seed: number;
  dsp_version: number;
  model_version_id: string | null;
  geometry_hash: string;
  status: 'ready' | 'stale';
  params: VisualParams;
  created_at: string;
  updated_at: string;
}

export interface AtlasNode {
  recording_id: string;
  artifact_id: string;
  x: number;
  y: number;
  embedded: boolean;
  state: VisualSemantic['state'];
  resolution: number;
  label: string | null;
  hue: number | null;
  label_ids: string[];
  confirmed_labels: string[];
  is_unknown: boolean;
  descriptors: string[];
  environment: string | null;
  mood: string | null;
  ears_top: string | null;
  fused_top: string | null;
  novel: boolean;
  captured_at: string;
  duration_s: number;
  glyph: Pick<VisualGeometry, 'sharpness' | 'symmetry_order' | 'jitter' | 'fragmentation' | 'scale' | 'energy'>;
  ring: number[];
  seed: number;
}

export interface AtlasEdge {
  a: string;
  b: string;
  type: 'acoustic' | 'shared_label';
  weight: number;
  label_id: string | null;
}

export interface AtlasAnchor {
  label_id: string;
  name: string;
  origin: 'vocabulary' | 'user';
  hue: number;
  x: number;
  y: number;
  n: number;
  spread: number;
}

export interface Atlas {
  atlas_version: number;
  layout_version: number;
  generator_version: number;
  model_version_id: string | null;
  model: { id: string; revision: string } | null;
  basis: { fitted_on: number; frozen: boolean; explained_variance_2d: number } | null;
  nodes: AtlasNode[];
  edges: AtlasEdge[];
  anchors: AtlasAnchor[];
  state: 'empty' | 'first_observation' | 'scattered' | 'emerging_relationships' | 'learned_categories' | 'new_concept';
  counts: Record<string, number>;
  narrative: (EchoLine & { edge?: [string, string] })[];
}

// ---------------------------------------------------------------- M4: the Orchestra

export type CompositionStatus = 'queued' | 'processing' | 'ready' | 'failed';
export type CompositionMode = 'organic' | 'composed' | 'legacy';
export type Hierarchy = 'lead' | 'foundation' | 'support' | 'gesture' | 'bed';
export type MusicRole = 'texture' | 'drone' | 'rhythmic_texture' | 'percussion' | 'tonal_motif' | 'accent' | 'granular';
export interface Controls { density: number; structure: number; intensity: number }

export interface RoleDecision {
  primary: MusicRole;
  secondary: MusicRole | null;
  scores: Record<string, number>;
  evidence: Record<string, number | null>;
  rationale: string;
  overridden: boolean;
}
export interface CompositionSource {
  position: number;
  recording_id: string;
  content_hash: string;
  exists: boolean;
  label: string | null;
  role: MusicRole | null;
  secondary_role: MusicRole | null;
  decision: RoleDecision | null;
  analysis: Record<string, unknown> | null;
}
export interface CompositionTrack {
  track_key: string;
  recording_id: string;
  role: MusicRole;
  layer_order: number;
  pan: number;
  enters: string;
  hierarchy: Hierarchy | null;
  stem_url: string | null;
  original_url: string;
}
export interface Section { name: string; start_bar: number; bars: number; start_s: number; end_s: number }
export interface CompositionEcho { text: string; tag: string; evidence: Record<string, unknown> }
export interface Composition {
  id: string;
  parent_id: string | null;
  name: string;
  saved: boolean;
  mode: CompositionMode;
  status: CompositionStatus;
  error: string | null;
  seed: number;
  controls: Controls;
  target_duration_s: number;
  duration_s: number | null;
  tempo_bpm: number | null;
  planner_version: number;
  render_version: number;
  plan_hash: string | null;
  master_sha256: string | null;
  master_url: string | null;
  export_url: string | null;
  metrics: Record<string, unknown> | null;
  sections: Section[];
  form: Record<string, string> | null;
  conversation: { lead: string; responder: string; evidence: Record<string, number> }[];
  groove: { quantisation: number; swing_steps: number; micro_ms: number; ghost_notes: boolean; fills: boolean; tonal_strategy: string } | null;
  hierarchy: Record<string, unknown> | null;
  key: { tonic_midi: number; scale: string; from: string } | null;
  tempo_source: string | null;
  sources: CompositionSource[];
  tracks: CompositionTrack[];
  echo: CompositionEcho[];
  created_at: string;
  updated_at: string;
  rendered_at: string | null;
  created: boolean | null;
}
export interface CompositionListItem {
  id: string;
  parent_id: string | null;
  name: string;
  saved: boolean;
  mode: CompositionMode;
  status: CompositionStatus;
  seed: number;
  duration_s: number | null;
  tempo_bpm: number | null;
  n_sources: number;
  recording_ids: string[];
  created_at: string;
}
export interface CompositionEvent {
  seq: number;
  track_key: string;
  recording_id: string;
  kind: 'slice' | 'loop' | 'grains';
  role: MusicRole;
  section: string;
  comp_start_s: number;
  comp_dur_s: number;
  source_start_s: number;
  source_end_s: number;
  params: { rate?: number; gain_db?: number; pitch_shift_st?: number; hierarchy?: Hierarchy; motif?: string | null; variation?: string | null; velocity?: number; ghost?: boolean; [k: string]: unknown };
}
export interface CompositionTrace {
  composition_id: string;
  event: CompositionEvent;
  track: Record<string, unknown>;
  source: { recording_id: string; exists: boolean; label?: string | null; captured_at?: string | null; duration_s?: number; audio_url?: string };
  specimen: { artifact_id: string; geometry_hash: string; generator_version: number } | null;
  also_in: string[];
}
