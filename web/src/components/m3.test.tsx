import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { Atlas as AtlasData, VisualParams } from '../api/types';
import { buildGeometry, drawSignature, playbackState, signatureSVG, stateStyle } from '../visual/signature';
import { Atlas } from './Atlas';
import { Specimen } from './Specimen';

function json(body: unknown, status = 200, ct = 'application/json'): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': ct } });
}

const params: VisualParams = {
  generator_version: 1, seed: 123456, dsp_version: 1, geometry_hash: 'abc123def456',
  geometry: { ring: Array.from({ length: 128 }, (_, i) => 0.3 + 0.5 * Math.abs(Math.sin(i / 7))), bands: Array.from({ length: 32 }, (_, i) => i / 31), brightness_curve: Array(32).fill(0.5), ticks: [0.1, 0.5, 0.9], sharpness: 0.6, symmetry_order: 4, jitter: 0.3, fragmentation: 0.4, scale: 0.8, energy: 0.7, duration_s: 5, onset_density_per_s: 0.6 },
  animation: { duration_s: 5, envelope: Array.from({ length: 256 }, (_, i) => i / 255), flux: Array(128).fill(0.2), onsets_s: [0.5, 2.5, 4.5] },
  semantic: { label: 'Water', hue: 200, state: 'hypothesis', resolution: 0.5, confirmed_labels: [], descriptors: [], environment: null, mood: null, why: null, model_version_id: 'm', memory_version: 0 },
};

// jsdom has no canvas: stub a recording 2D context
const calls: string[] = [];
beforeAll(() => {
  const handler: ProxyHandler<object> = {
    get: (_t, prop) => {
      if (prop === 'canvas') return {};
      return (...args: unknown[]) => { calls.push(String(prop)); void args; };
    },
    set: () => true,
  };
  HTMLCanvasElement.prototype.getContext = (() => new Proxy({}, handler)) as unknown as typeof HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.toDataURL = () => 'data:image/png;base64,';
});
afterEach(() => { vi.restoreAllMocks(); calls.length = 0; });

describe('signature renderer', () => {
  it('is deterministic for the same params and seed, and differs with the seed', () => {
    const a = buildGeometry(params);
    const b = buildGeometry(params);
    expect(JSON.stringify(a.outline)).toBe(JSON.stringify(b.outline));
    const c = buildGeometry({ ...params, seed: 999 });
    expect(JSON.stringify(c.outline)).not.toBe(JSON.stringify(a.outline));
    expect(signatureSVG(params, a)).toBe(signatureSVG(params, b));
    expect(signatureSVG(params, a)).toContain('<polygon');
    expect(signatureSVG(params, a)).toContain('seed 123456');
  });
  it('keeps geometry bounded and finite for silent and extreme input', () => {
    const silent = { ...params, geometry: { ...params.geometry, ring: Array(128).fill(0), bands: Array(32).fill(0), ticks: [], energy: 0, jitter: 0 } };
    const g = buildGeometry(silent);
    expect(g.outline.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y) && Math.hypot(p.x, p.y) <= 1.6)).toBe(true);
    const loud = { ...params, geometry: { ...params.geometry, ring: Array(128).fill(1), energy: 1, jitter: 1, sharpness: 1, scale: 1 } };
    const l = buildGeometry(loud);
    expect(l.outline.every((p) => Number.isFinite(p.x) && Math.hypot(p.x, p.y) <= 1.6)).toBe(true);
  });
  it('maps playback time to envelope, flux and onset glow', () => {
    expect(playbackState(params, null)).toEqual({ envelope: 0.6, flux: 0, onsetGlow: 0 });
    const mid = playbackState(params, 2.5);
    expect(mid.envelope).toBeCloseTo(0.5, 1);
    expect(mid.onsetGlow).toBe(1);
    expect(playbackState(params, 3.5).onsetGlow).toBe(0);
    expect(playbackState(params, 99).envelope).toBeCloseTo(1, 5);
  });
  it('unknown state renders a dashed hollow outline; label only changes hue', () => {
    expect(stateStyle(params).dash).toEqual([]);
    expect(stateStyle({ ...params, semantic: { ...params.semantic, state: 'unknown' } }).dash).toEqual([3, 6]);
    const a = buildGeometry(params);
    const b = buildGeometry({ ...params, semantic: { ...params.semantic, label: 'Wind', hue: 30, state: 'confirmed' } });
    expect(JSON.stringify(a.outline)).toBe(JSON.stringify(b.outline));
    const ctx = new Proxy({}, { get: (_t, p) => (p === 'canvas' ? {} : () => calls.push(String(p))), set: () => true }) as unknown as CanvasRenderingContext2D;
    drawSignature(ctx, params, a, { size: 200, time: 1.2 });
    expect(calls).toContain('fill');
    expect(calls).toContain('stroke');
  });
});

const node = (id: string, state: AtlasData['nodes'][0]['state'], x = 0, y = 0) => ({
  recording_id: id, artifact_id: `a-${id}`, x, y, embedded: true, state, resolution: 0.5, label: state === 'unknown' ? null : 'Water', hue: 200, label_ids: [], confirmed_labels: [], is_unknown: state === 'unknown', descriptors: [], environment: null, mood: 'calm', ears_top: 'Water', fused_top: 'Water', novel: state === 'unknown', captured_at: '2026-10-09T00:00:00Z', duration_s: 5,
  glyph: { sharpness: 0.5, symmetry_order: 4, jitter: 0.3, fragmentation: 0.2, scale: 0.8, energy: 0.6 }, ring: Array(32).fill(0.6), seed: 7,
});
const atlas = (nodes: AtlasData['nodes'], edges: AtlasData['edges'] = [], state: AtlasData['state'] = 'scattered'): AtlasData => ({
  atlas_version: 1, layout_version: 1, generator_version: 1, model_version_id: 'm', model: { id: 'laion/clap-htsat-unfused', revision: 'r' }, basis: null, nodes, edges, anchors: [], state,
  counts: { nodes: nodes.length, embedded: nodes.length, edges: edges.length, unknown: nodes.filter((n) => n.state === 'unknown').length, uncertain: 0, confirmed: 0, custom_labels: 0 },
  narrative: [{ template: 'x', text: nodes.length ? 'This is my first memory. It has a shape now.' : 'My world is silent. Bring me a sound.', tags: ['memory'], event_ids: [] }],
});

describe('Atlas', () => {
  it('renders empty, single, related and unknown states and selects a node', async () => {
    const data = atlas([node('0199a000-0000-7000-8000-000000000001', 'confirmed', -0.3, 0), node('0199a000-0000-7000-8000-000000000002', 'unknown', 0.3, 0)], [{ a: '0199a000-0000-7000-8000-000000000001', b: '0199a000-0000-7000-8000-000000000002', type: 'acoustic', weight: 0.8, label_id: null }], 'emerging_relationships');
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(data));
    const open = vi.fn();
    render(<Atlas version={0} onOpenSpecimen={open} onBack={vi.fn()} />);
    expect(await screen.findByText('Emerging relationships')).toBeInTheDocument();
    expect(screen.getByText(/2 memories · 1 relationships/)).toBeInTheDocument();
    expect(screen.getByText(/1 unknown/)).toBeInTheDocument();
    expect(calls).toContain('stroke');
    // empty state
    fetchSpy.mockResolvedValue(json(atlas([], [], 'empty')));
    fireEvent.click(screen.getByRole('button', { name: 'Reset view' }));
    render(<Atlas version={1} onOpenSpecimen={open} onBack={vi.fn()} />);
    expect(await screen.findByText('Empty memory')).toBeInTheDocument();
    expect(screen.getByText('silence')).toBeInTheDocument();
  });
  it('shows a failure state with retry', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json({ type: 'x', title: 'Server', status: 500, detail: 'down', code: 'INTERNAL_ERROR' }, 500, 'application/problem+json'));
    render(<Atlas version={0} onOpenSpecimen={vi.fn()} onBack={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('INTERNAL_ERROR');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});

describe('Specimen', () => {
  it('loads the visual and recording and shows provenance; handles not-ready', async () => {
    const id = '0199a000-0000-7000-8000-000000000001';
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u.endsWith('/visual')) return json({ artifact_id: 'a1', recording_id: id, generator_version: 1, seed: 123456, dsp_version: 1, model_version_id: 'm', geometry_hash: 'abc123def456', status: 'ready', params, created_at: '', updated_at: '' });
      if (u.endsWith(`/recordings/${id}`)) return json({ id, created_at: '2026-10-09T00:00:00Z', captured_at: null, original_filename: null, duration_s: 5, status: 'ready', quality: { flags: [], peak_dbfs: -3, clipping_ratio: 0 }, error: null, dsp_version: 1, content_hash: 'h', source_hash: 's', client_mime: null, device_info: null, assets: [], jobs: [], features: null, inference: { status: 'ok', model_id: 'm', model_version: 'r', predictions: [], embedding: { dim: 512 }, error: null }, links: {} });
      if (u.endsWith('/prediction')) return json({ recording_id: id, state: 'awaiting_feedback', model_status: 'ready', model: { id: 'laion/clap-htsat-unfused', revision: 'abcdef123', preprocessing_version: 1, embedding_dim: 512 }, job: null, base: null, fused: { score_kind: 'f', memory_version: 2, candidates: [{ label_id: 'l', slug: 'water', name: 'Water', rank: 1, fused_score: 0.5, base_similarity: 0.4, base_score: 0.5, memory_similarity: null, memory_score: null, n_exemplars: 0, lambda: 0, evidence: 'ears' }], novelty: {}, created_at: '' }, annotation: null });
      if (u.includes('/neighbours')) return json([]);
      return json({});
    });
    render(<Specimen recordingId={id} onTeach={vi.fn()} onOpenAtlas={vi.fn()} onSelect={vi.fn()} />);
    expect(await screen.findByRole('heading', { name: /Water/ })).toBeInTheDocument();
    expect(screen.getByText(/seed 123456/)).toBeInTheDocument();
    expect(screen.getByText(/geometry abc123def456/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /acoustic signature/ })).toBeInTheDocument();
    expect(screen.getByLabelText('original recording')).toBeInTheDocument();
    expect(screen.getByText(/memory v2/)).toBeInTheDocument();
  });
  it('reports a not-ready specimen', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json({ type: 'x', title: 'Not Ready', status: 409, detail: 'features are not ready yet', code: 'NOT_READY' }, 409, 'application/problem+json'));
    render(<Specimen recordingId="0199a000-0000-7000-8000-000000000001" onTeach={vi.fn()} onOpenAtlas={vi.fn()} onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('NOT_READY'));
  });
});
