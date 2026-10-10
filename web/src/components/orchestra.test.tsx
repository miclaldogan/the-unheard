import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { Atlas as AtlasData, Composition, CompositionEvent, CompositionTrace, RecordingSummary, Visual, VisualParams } from '../api/types';
import { OrchestraPlayer, type PlayerContext } from '../audio/orchestra';
import { Orchestra } from './Orchestra';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': status >= 400 ? 'application/problem+json' : 'application/json' } });

const rec = (id: string, d = 6): RecordingSummary => ({ id, created_at: '2026-10-09T00:00:00Z', captured_at: null, original_filename: null, duration_s: d, status: 'ready', quality: {} as RecordingSummary['quality'], error: null, dsp_version: 1 });
const items = [rec('r1'), rec('r2'), rec('r3')];

const atlas = { nodes: items.map((r, i) => ({ recording_id: r.id, label: ['Rain', 'Footsteps', 'Bird'][i], state: 'confirmed', hue: 100 + i * 60 })), edges: [] } as unknown as AtlasData;

const comp = (status: Composition['status'] = 'ready'): Composition => ({
  id: 'c1', parent_id: null, name: 'Untitled orchestra', saved: false, mode: 'composed', status, error: status === 'failed' ? 'boom' : null, seed: 7,
  controls: { density: 0.5, structure: 0.5, intensity: 0.5 }, target_duration_s: 45, duration_s: status === 'ready' ? 40 : null, tempo_bpm: 96,
  planner_version: 1, render_version: 1, plan_hash: 'abcdef123456', master_sha256: 'x', master_url: '/api/compositions/c1/master', export_url: '/api/compositions/c1/export',
  metrics: { peak_dbfs: -1, lufs_approx: -18, clipping_ratio: 0 }, sections: [{ name: 'introduction', start_bar: 0, bars: 4, start_s: 0, end_s: 10 }], form: { introduction: 'A', discovery: "A' + R→A" }, conversation: [{ lead: 'x:A', responder: 'y:R', evidence: { score: 0.82 } }], groove: { quantisation: 0.6, swing_steps: 0.22, micro_ms: 5, ghost_notes: true, fills: true, tonal_strategy: 'contour' }, hierarchy: null, key: null, tempo_source: 'periodicity',
  sources: items.map((r, i) => ({ position: i, recording_id: r.id, content_hash: `h${i}`, exists: true, label: ['Rain', 'Footsteps', 'Bird'][i], role: (['texture', 'percussion', 'tonal_motif'] as const)[i], secondary_role: null, decision: { primary: (['texture', 'percussion', 'tonal_motif'] as const)[i], secondary: null, scores: {}, evidence: {}, rationale: `measured reason ${i}`, overridden: false }, analysis: {} })),
  tracks: items.map((r, i) => ({ track_key: `t${i + 1}`, recording_id: r.id, role: (['texture', 'percussion', 'tonal_motif'] as const)[i], layer_order: i, pan: 0, enters: 'introduction', hierarchy: (['bed', 'foundation', 'lead'] as const)[i], stem_url: `/api/compositions/c1/stems/t${i + 1}`, original_url: `/api/recordings/${r.id}/audio` })),
  echo: [{ text: 'This is what your world sounds like through my memory.', tag: 'imagination', evidence: {} }],
  created_at: 'x', updated_at: 'x', rendered_at: 'x', created: true,
});
const events: CompositionEvent[] = [
  { seq: 0, track_key: 't1', recording_id: 'r1', kind: 'loop', role: 'texture', section: 'introduction', comp_start_s: 0, comp_dur_s: 10, source_start_s: 0, source_end_s: 3, params: { rate: 1, gain_db: -8, fade_in_s: 1, fade_out_s: 1 } },
  { seq: 1, track_key: 't2', recording_id: 'r2', kind: 'slice', role: 'percussion', section: 'introduction', comp_start_s: 2, comp_dur_s: 0.3, source_start_s: 1, source_end_s: 1.3, params: { rate: 1, gain_db: -6 } },
];
const params: VisualParams = {
  generator_version: 1, seed: 123456, dsp_version: 1, geometry_hash: 'abc123def456',
  geometry: { ring: Array.from({ length: 128 }, (_, i) => 0.3 + 0.5 * Math.abs(Math.sin(i / 7))), bands: Array.from({ length: 32 }, (_, i) => i / 31), brightness_curve: Array(32).fill(0.5), ticks: [0.1, 0.5, 0.9], sharpness: 0.6, symmetry_order: 4, jitter: 0.3, fragmentation: 0.4, scale: 0.8, energy: 0.7, duration_s: 5, onset_density_per_s: 0.6 },
  animation: { duration_s: 5, envelope: Array.from({ length: 256 }, (_, i) => i / 255), flux: Array(128).fill(0.2), onsets_s: [0.5, 2.5, 4.5] },
  semantic: { label: 'Water', hue: 200, state: 'hypothesis', resolution: 0.5, confirmed_labels: [], descriptors: [], environment: null, mood: null, why: null, model_version_id: 'm', memory_version: 0 },
};
const trace: CompositionTrace = { composition_id: 'c1', event: events[1], track: {}, source: { recording_id: 'r2', exists: true, label: 'Footsteps', duration_s: 6 }, specimen: { artifact_id: 'a', geometry_hash: 'g', generator_version: 1 }, also_in: [] };

beforeAll(() => {
  const handler: ProxyHandler<object> = { get: (_t, p) => (p === 'canvas' ? {} : () => ({ addColorStop() { /* noop */ } })), set: () => true };
  HTMLCanvasElement.prototype.getContext = (() => new Proxy({}, handler)) as unknown as typeof HTMLCanvasElement.prototype.getContext;
  HTMLMediaElement.prototype.pause = () => undefined;
  HTMLMediaElement.prototype.play = () => Promise.resolve();
});
afterEach(() => vi.restoreAllMocks());

function fakePlayer() {
  const gains: Record<string, number>[] = [];
  const ctx = { currentTime: 0, state: 'running', destination: {}, resume: async () => undefined, close: async () => undefined, decodeAudioData: async () => ({ duration: 10 }) as unknown as AudioBuffer, createGain: () => ({ gain: { value: 1 }, connect() { /* */ }, disconnect() { /* */ } }) as unknown as GainNode, createBufferSource: () => ({ connect() { /* */ }, disconnect() { /* */ }, stop() { /* */ }, start() { /* */ } }) as unknown as AudioBufferSourceNode } as unknown as PlayerContext;
  const p = new OrchestraPlayer(() => ctx, async () => new ArrayBuffer(4));
  const orig = p.setGains.bind(p);
  p.setGains = (g) => { gains.push(g); orig(g); };
  return { p, gains };
}

function mockApi(overrides: Record<string, () => Response> = {}) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const key = `${method} ${url.split('?')[0]}`;
    if (overrides[key]) return overrides[key]();
    if (key === 'GET /api/atlas') return json(atlas);
    if (key === 'GET /api/compositions') return json([]);
    if (key === 'POST /api/compositions') return json(comp('queued'), 202);
    if (key === 'GET /api/compositions/c1') return json(comp('ready'));
    if (key === 'GET /api/compositions/c1/events') return json(events);
    if (key === 'GET /api/compositions/c1/trace/1') return json(trace);
    if (key.startsWith('GET /api/recordings/') && key.endsWith('/visual')) return json({ artifact_id: 'a', recording_id: 'r', params } as unknown as Visual);
    if (key === 'PATCH /api/compositions/c1') return json({ ...comp('ready'), saved: true, name: 'Dawn' });
    return json({ code: 'NOT_FOUND', title: 'x', type: 'x', status: 404, detail: `unmocked ${key}` }, 404);
  }));
  return calls;
}

const setup = (over: Record<string, () => Response> = {}) => {
  const calls = mockApi(over);
  const { p, gains } = fakePlayer();
  const activityRef = { current: {} as Record<string, number> };
  const utils = render(<Orchestra items={items} preselected={['r1', 'r2', 'r3']} activityRef={activityRef} onOpenSpecimen={vi.fn()} onOpenAtlas={vi.fn()} createPlayer={() => p} />);
  return { calls, p, gains, activityRef, ...utils };
};

describe('Orchestra view', () => {
  it('keeps playback unavailable until authenticated stems finish loading', async () => {
    const { p } = setup({ 'POST /api/compositions': () => json(comp('ready')) });
    let finish!: () => void;
    const gate = new Promise<void>(resolve => { finish = resolve; });
    const load = p.load.bind(p);
    vi.spyOn(p, 'load').mockImplementation(async (...args) => { await gate; await load(...args); });
    await screen.findByText('Rain');
    fireEvent.click(screen.getByRole('button', { name: 'Compose from 3 sounds' }));
    expect(await screen.findByRole('button', { name: 'Play' })).toBeDisabled();
    finish();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Play' })).toBeEnabled());
  });

  it('lists the ready recordings with names from the atlas and composes the chosen sources', async () => {
    const { calls } = setup();
    expect(await screen.findByText('Rain')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('use Footsteps'));
    fireEvent.click(screen.getByRole('button', { name: /Compose from 2 sounds/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument());
    const post = calls.find((c) => c.method === 'POST' && c.url === '/api/compositions')!;
    expect(post.body).toMatchObject({ recording_ids: ['r1', 'r3'], controls: { density: 0.5, structure: 0.5, intensity: 0.5 }, duration_s: 45 });
    // one instrument per layer, each with a role chip and the conductor line
    expect(screen.getAllByRole('button', { name: /^mute / })).toHaveLength(3);
    expect(screen.getByText('groove')).toBeInTheDocument();
    expect(screen.getByText('lead')).toBeInTheDocument();
    expect(screen.getByText('atmosphere')).toBeInTheDocument();
    expect(screen.getByLabelText('musical form')).toHaveTextContent(/introduction: A.*conversation: 1 call-and-response \(fit 0\.82\).*swing 0\.22/s);
    expect(screen.getByText(/through my memory/)).toBeInTheDocument();
  });

  it('mute and solo change the live gains of the player', async () => {
    const { gains } = setup();
    fireEvent.click(await screen.findByRole('button', { name: /Compose from 3 sounds/ }));
    await screen.findByRole('button', { name: 'Play' });
    fireEvent.click(screen.getByRole('button', { name: 'mute Rain' }));
    await waitFor(() => expect(gains.at(-1)).toEqual({ t1: 0, t2: 1, t3: 1 }));
    fireEvent.click(screen.getByRole('button', { name: 'solo Bird' }));
    await waitFor(() => expect(gains.at(-1)).toEqual({ t1: 0, t2: 0, t3: 1 }));
    fireEvent.click(screen.getByRole('button', { name: 'solo Bird' }));
    fireEvent.click(screen.getByRole('button', { name: 'mute Rain' }));
    await waitFor(() => expect(gains.at(-1)).toEqual({ t1: 1, t2: 1, t3: 1 }));
  });

  it('plays, pauses and seeks through the player', async () => {
    const { p } = setup();
    fireEvent.click(await screen.findByRole('button', { name: /Compose from 3 sounds/ }));
    const play = await screen.findByRole('button', { name: 'Play' });
    fireEvent.click(play);
    await waitFor(() => expect(p.paused).toBe(false));
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('seek'), { target: { value: '12' } });
    expect(p.currentTime).toBeGreaterThanOrEqual(12);
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(p.paused).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(p.currentTime).toBe(0);
  });

  it('traces a clicked event back to its source recording', async () => {
    setup();
    fireEvent.click(await screen.findByRole('button', { name: /Compose from 3 sounds/ }));
    const tl = await screen.findByRole('img', { name: /timeline of 2 events/ });
    Object.defineProperty(tl, 'getBoundingClientRect', { value: () => ({ left: 0, top: 0, width: 400, height: 98, right: 400, bottom: 98 }) });
    fireEvent.click(tl, { clientX: 2.1 / 40 * 400, clientY: 26 + 10 }); // lane 2 (percussion) at t≈2.1 s
    const region = await screen.findByRole('region', { name: 'event provenance' });
    expect(within(region).getByText('Footsteps')).toBeInTheDocument();
    expect(region).toHaveTextContent(/source 1\.00–1\.30 s of 6\.0 s/);
    expect(within(region).getByRole('button', { name: 'Open its specimen' })).toBeEnabled();
  });

  it('offers original / transformed layer / full composition comparison', async () => {
    const { p } = setup();
    fireEvent.click(await screen.findByRole('button', { name: /Compose from 3 sounds/ }));
    await screen.findByRole('button', { name: 'Play' });
    fireEvent.click(screen.getByRole('button', { name: 'inspect Bird' }));
    const cmp = await screen.findByRole('region', { name: 'source comparison' });
    expect(cmp).toHaveTextContent('measured reason 2');
    fireEvent.click(within(cmp).getByRole('button', { name: /Transformed layer/ }));
    await waitFor(() => expect(p.paused).toBe(false));
    expect(screen.getByRole('button', { name: 'solo Bird' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(within(cmp).getByRole('button', { name: /Full composition/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'solo Bird' })).toHaveAttribute('aria-pressed', 'false'));
  });

  it('shows a failed render with a retry that works', async () => {
    let n = 0;
    const calls = setup({
      'POST /api/compositions': () => json(comp('failed'), 202),
      'POST /api/compositions/c1/render': () => { n++; return json(comp('queued'), 202); },
    }).calls;
    fireEvent.click(await screen.findByRole('button', { name: /Compose from 3 sounds/ }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('render failed: boom');
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry render' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument());
    expect(n).toBe(1);
    expect(calls.some((c) => c.url.endsWith('/render'))).toBe(true);
  });

  it('saves with a name and links the WAV export', async () => {
    const { calls } = setup();
    fireEvent.click(await screen.findByRole('button', { name: /Compose from 3 sounds/ }));
    await screen.findByRole('button', { name: 'Play' });
    fireEvent.change(screen.getByLabelText('composition name'), { target: { value: 'Dawn' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ saved: true, name: 'Dawn' }));
    expect(screen.getByRole('link', { name: 'Export WAV' })).toHaveAttribute('href', '/api/compositions/c1/export');
    expect(screen.getByRole('link', { name: /with stems/ })).toHaveAttribute('href', '/api/compositions/c1/export?bundle=true');
  });

  it('writes live activity for the atlas only while something is playing and an event covers the playhead', async () => {
    const { p, activityRef } = setup();
    fireEvent.click(await screen.findByRole('button', { name: /Compose from 3 sounds/ }));
    await screen.findByRole('button', { name: 'Play' });
    expect(activityRef.current).toEqual({}); // nothing plays yet → everything restrained
    p.seek(2.05);
    await p.play();
    await waitFor(() => expect(activityRef.current.r2).toBeGreaterThan(0.5));
    expect(activityRef.current.r1).toBeGreaterThan(0);
    p.seek(30);
    await waitFor(() => expect(activityRef.current).toEqual({}));
    p.pause();
  });

  it('asks for a recording first when nothing is ready', async () => {
    mockApi();
    render(<Orchestra items={[]} preselected={[]} activityRef={{ current: {} }} onOpenSpecimen={vi.fn()} onOpenAtlas={vi.fn()} />);
    expect(await screen.findByText(/No ready recordings yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Compose from 0 sounds/ })).toBeDisabled();
  });
});

describe('arrangement modes', () => {
  it('composes in Composed mode by default and lets the player switch to Organic', async () => {
    const { calls } = setup();
    expect(await screen.findByRole('button', { name: 'Composed' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Organic' }));
    expect(screen.getByRole('button', { name: 'Organic' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Composed' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: /Compose from 3 sounds/ }));
    await screen.findByRole('button', { name: 'Play' });
    expect(calls.find((c) => c.method === 'POST' && c.url === '/api/compositions')!.body).toMatchObject({ mode: 'organic' });
  });
  it('sends composed by default', async () => {
    const { calls } = setup();
    fireEvent.click(await screen.findByRole('button', { name: /Compose from 3 sounds/ }));
    await screen.findByRole('button', { name: 'Play' });
    expect(calls.find((c) => c.method === 'POST' && c.url === '/api/compositions')!.body).toMatchObject({ mode: 'composed' });
  });
});

describe('Atlas ↔ Orchestra hooks', () => {
  const empty = { atlas_version: 1, layout_version: 1, generator_version: 1, model_version_id: null, model: null, basis: null, state: 'scattered', nodes: [], edges: [], anchors: [], counts: { nodes: 0, edges: 0, unknown: 0, uncertain: 0, custom_labels: 0 }, narrative: [] };
  it('offers "choose sounds" and a compose button for the current selection', async () => {
    const { Atlas } = await import('./Atlas');
    vi.stubGlobal('fetch', vi.fn(async () => json(empty)));
    const onCompose = vi.fn();
    render(<Atlas version={0} onOpenSpecimen={vi.fn()} onBack={vi.fn()} selection={['r1', 'r2']} onToggleSelect={vi.fn()} onCompose={onCompose} activityRef={{ current: {} }} />);
    const pick = await screen.findByRole('button', { name: /Choose sounds for an orchestra/ });
    fireEvent.click(pick);
    expect(screen.getByRole('button', { name: /Choosing sounds/ })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Compose from 2' }));
    expect(onCompose).toHaveBeenCalledTimes(1);
  });
});
