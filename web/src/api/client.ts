import type {
  AnnotationIn,
  Atlas,
  AnnotationOut,
  Composition,
  CompositionEvent,
  CompositionListItem,
  CompositionTrace,
  Controls,
  AnnotationResult,
  EchoLine,
  Features,
  Health,
  Label,
  MemoryOverview,
  ModelStatus,
  Neighbour,
  Prediction,
  Problem,
  RecordingDetail,
  RecordingList,
  Spectrogram,
  UploadAccepted,
  Visual,
} from './types';

export class ApiError extends Error {
  readonly problem: Problem;
  constructor(problem: Problem) {
    super(problem.detail || problem.title);
    this.problem = problem;
  }
  get code(): string {
    return this.problem.code;
  }
  get status(): number {
    return this.problem.status;
  }
}

const TOKEN_KEY = 'unheard.token';

/** Optional bearer token (needed only when the server runs with UNHEARD_API_TOKEN). */
export function getToken(): string | null {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('token');
    if (fromUrl) {
      localStorage.setItem(TOKEN_KEY, fromUrl);
      return fromUrl;
    }
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch (e) {
    throw new ApiError({ type: 'network', title: 'Network error', status: 0, code: 'NETWORK', detail: String(e) });
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type') ?? '';
  const body = ct.includes('json') ? await res.json() : null;
  if (!res.ok) {
    const problem: Problem =
      body && typeof body === 'object' && 'code' in body
        ? (body as Problem)
        : { type: 'http', title: res.statusText, status: res.status, code: `HTTP_${res.status}`, detail: res.statusText };
    throw new ApiError(problem);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>('/api/health'),
  list: (limit = 100) => request<RecordingList>(`/api/recordings?limit=${limit}`),
  get: (id: string) => request<RecordingDetail>(`/api/recordings/${encodeURIComponent(id)}`),
  features: (id: string) => request<Features>(`/api/recordings/${encodeURIComponent(id)}/features`),
  spectrogram: (id: string, kind: 'mel' | 'stft' = 'mel', maxFrames = 600) =>
    request<Spectrogram>(`/api/recordings/${encodeURIComponent(id)}/spectrogram?kind=${kind}&max_frames=${maxFrames}`),
  audioUrl: (id: string) => `/api/recordings/${encodeURIComponent(id)}/audio`,
  retry: (id: string) => request<{ recording_id: string }>(`/api/recordings/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  delete: (id: string) => request<void>(`/api/recordings/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  // M2
  model: () => request<ModelStatus>('/api/model'),
  loadModel: () => request<ModelStatus>('/api/model/load', { method: 'POST' }),
  prediction: (id: string) => request<Prediction>(`/api/recordings/${encodeURIComponent(id)}/prediction`),
  infer: (id: string) => request<{ recording_id: string; state: string }>(`/api/recordings/${encodeURIComponent(id)}/infer`, { method: 'POST' }),
  neighbours: (id: string, limit = 5) => request<Neighbour[]>(`/api/recordings/${encodeURIComponent(id)}/neighbours?limit=${limit}`),
  labels: (q?: string) => request<Label[]>(`/api/labels${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  createLabel: (name: string) => request<Label>('/api/labels', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name }) }),
  annotate: (id: string, body: AnnotationIn) =>
    request<AnnotationResult>(`/api/recordings/${encodeURIComponent(id)}/annotations`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  annotations: (id: string) => request<AnnotationOut[]>(`/api/recordings/${encodeURIComponent(id)}/annotations`),
  memory: () => request<MemoryOverview>('/api/memory'),
  echo: (id: string) => request<EchoLine[]>(`/api/recordings/${encodeURIComponent(id)}/echo`),
  // M3
  visual: (id: string) => request<Visual>(`/api/recordings/${encodeURIComponent(id)}/visual`),
  atlas: () => request<Atlas>('/api/atlas'),
  rebuildAtlas: () => request<Atlas>('/api/atlas/rebuild', { method: 'POST' }),
  // M4
  compositions: (recordingId?: string) =>
    request<CompositionListItem[]>(`/api/compositions${recordingId ? `?recording_id=${encodeURIComponent(recordingId)}` : ''}`),
  composition: (id: string) => request<Composition>(`/api/compositions/${encodeURIComponent(id)}`),
  createComposition: (body: { recording_ids: string[]; seed?: number; controls?: Partial<Controls>; duration_s?: number; name?: string; role_overrides?: Record<string, string> }) =>
    request<Composition>('/api/compositions', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  variation: (id: string, body: { seed?: number; controls?: Partial<Controls> } = {}) =>
    request<Composition>(`/api/compositions/${encodeURIComponent(id)}/variation`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  rerender: (id: string) => request<Composition>(`/api/compositions/${encodeURIComponent(id)}/render`, { method: 'POST' }),
  patchComposition: (id: string, body: { name?: string; saved?: boolean }) =>
    request<Composition>(`/api/compositions/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  deleteComposition: (id: string) => request<void>(`/api/compositions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  compositionEvents: (id: string) => request<CompositionEvent[]>(`/api/compositions/${encodeURIComponent(id)}/events`),
  trace: (id: string, seq: number) => request<CompositionTrace>(`/api/compositions/${encodeURIComponent(id)}/trace/${seq}`),
  upload: (blob: Blob, filename: string, deviceInfo: Record<string, unknown>) => {
    const form = new FormData();
    form.append('file', blob, filename);
    form.append('captured_at', new Date().toISOString());
    form.append('device_info', JSON.stringify(deviceInfo));
    return request<UploadAccepted>('/api/recordings', { method: 'POST', body: form });
  },
};

/** Poll until the recording leaves the uploaded/processing states. */
export async function waitUntilProcessed(
  id: string,
  opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<RecordingDetail> {
  const interval = opts.intervalMs ?? 500;
  const deadline = Date.now() + (opts.timeoutMs ?? 60_000);
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException('aborted', 'AbortError');
    const d = await api.get(id);
    if (d.status === 'ready' || d.status === 'failed') return d;
    if (Date.now() > deadline) throw new ApiError({ type: 'timeout', title: 'Timeout', status: 0, code: 'TIMEOUT', detail: 'processing took too long' });
    await new Promise((r) => setTimeout(r, interval));
  }
}

/** Poll the prediction until inference has finished (ready or failed) or the model is disabled. */
export async function waitForPrediction(id: string, opts: { intervalMs?: number; timeoutMs?: number } = {}): Promise<Prediction> {
  const interval = opts.intervalMs ?? 700;
  const deadline = Date.now() + (opts.timeoutMs ?? 120_000);
  for (;;) {
    const p = await api.prediction(id);
    if (p.state !== 'analyzing' && p.state !== 'not_run') return p;
    if (p.state === 'not_run' && p.model_status === 'disabled') return p;
    if (Date.now() > deadline) return p;
    await new Promise((r) => setTimeout(r, interval));
  }
}

/** Poll a composition until it is ready or failed. */
export async function waitForComposition(id: string, opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {}): Promise<Composition> {
  const interval = opts.intervalMs ?? 700;
  const deadline = Date.now() + (opts.timeoutMs ?? 180_000);
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException('aborted', 'AbortError');
    const c = await api.composition(id);
    if (c.status === 'ready' || c.status === 'failed') return c;
    if (Date.now() > deadline) throw new ApiError({ type: 'timeout', title: 'Timeout', status: 0, code: 'TIMEOUT', detail: 'the render is taking too long' });
    await new Promise((r) => setTimeout(r, interval));
  }
}

/** Authenticated fetch of binary audio (the token header cannot ride on <audio src>). */
export async function fetchAudio(url: string): Promise<ArrayBuffer> {
  const token = getToken();
  const res = await fetch(url, token ? { headers: { Authorization: `Bearer ${token}` } } : undefined);
  if (!res.ok) throw new ApiError({ type: 'http', title: res.statusText, status: res.status, code: `HTTP_${res.status}`, detail: `could not load ${url}` });
  return res.arrayBuffer();
}
