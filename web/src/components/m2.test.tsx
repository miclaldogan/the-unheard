import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MemoryOverview, Prediction } from '../api/types';
import { HearingPanel } from './HearingPanel';
import { MemoryPanel } from './MemoryPanel';
import { PredictionPanel } from './PredictionPanel';
import { TeachPanel } from './TeachPanel';

function json(body: unknown, status = 200, ct = 'application/json'): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': ct } });
}

const cand = (id: string, name: string, rank: number, mem: number | null = null, n = 0) => ({
  label_id: id, slug: name.toLowerCase(), name, rank, fused_score: 1 / rank / 2, base_similarity: 0.4 / rank, base_score: 0.5 / rank,
  memory_similarity: mem, memory_score: mem ? 0.8 : null, n_exemplars: n, lambda: n ? 0.5 : 0, evidence: mem ? ('memory' as const) : ('ears' as const),
});

const novelty = { novel: false, nearest_exemplar_similarity: null, fused_margin: 0.3, base_entropy_normalised: 0.4, memory_size: 0, relevant_exemplars: 0, lambda: 0, nothing_similar_remembered: true, disagreement: false, ears_top: 'l1', memory_top: null, neighbours: [] };

const ready: Prediction = {
  recording_id: '0199a000-0000-7000-8000-000000000001', state: 'awaiting_feedback', model_status: 'ready',
  model: { id: 'laion/clap-htsat-unfused', revision: '8fa0f1c6abcd', preprocessing_version: 1, embedding_dim: 512 },
  job: { status: 'done', error: null, attempts: 1, updated_at: '' },
  base: { score_kind: 'cosine', candidates: [], windows: [], inference_ms: 210, created_at: '' },
  fused: { score_kind: 'fused', memory_version: 0, candidates: [cand('l1', 'Water', 1), cand('l2', 'Wind', 2)], novelty, created_at: '' },
  annotation: null,
};

afterEach(() => vi.restoreAllMocks());

describe('PredictionPanel', () => {
  it('shows ranked hypotheses with cosine values and no percentages', () => {
    render(<PredictionPanel prediction={ready} onInfer={vi.fn()} busy={false} />);
    expect(screen.getByText(/Hypothesizing/)).toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'hypotheses' });
    expect(table).toHaveTextContent('Water');
    expect(table).toHaveTextContent('0.400');
    expect(table.textContent).not.toMatch(/%/);
    expect(screen.getByText(/not a probability/)).toBeInTheDocument();
  });
  it('renders analyzing, failed (with retry), disabled and unknown states', () => {
    const { rerender } = render(<PredictionPanel prediction={{ ...ready, state: 'analyzing', fused: null, base: null }} onInfer={vi.fn()} busy={false} />);
    expect(screen.getByText('Analyzing')).toBeInTheDocument();
    const onInfer = vi.fn();
    rerender(<PredictionPanel prediction={{ ...ready, state: 'inference_failed', fused: null, base: null, job: { status: 'failed', error: 'RuntimeError: boom', attempts: 1, updated_at: '' } }} onInfer={onInfer} busy={false} />);
    expect(screen.getByRole('alert')).toHaveTextContent('boom');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onInfer).toHaveBeenCalled();
    rerender(<PredictionPanel prediction={{ ...ready, state: 'model_disabled', fused: null, base: null }} onInfer={vi.fn()} busy={false} />);
    expect(screen.getByText(/UNHEARD_MODEL=none/)).toBeInTheDocument();
    rerender(<PredictionPanel prediction={{ ...ready, fused: { ...ready.fused!, novelty: { ...novelty, novel: true } } }} onInfer={vi.fn()} busy={false} />);
    expect(screen.getByRole('status')).toHaveTextContent(/cannot name it yet/);
  });
});

describe('TeachPanel', () => {
  it('confirms the top hypothesis and submits label ids + descriptors', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      if (String(url).endsWith('/api/labels')) return json([]);
      if (init?.method === 'POST') return json({ annotation: { id: 'a1', action: 'confirm' }, memory_version: 1, exemplars_added: 1, exemplars_retracted: 0, created_label_ids: [], rescored_changes: [], fused_top: [] }, 201);
      return json({});
    });
    const onSaved = vi.fn();
    render(<TeachPanel prediction={ready} onSaved={onSaved} />);
    expect(screen.getByRole('button', { name: 'Teach ECHO-0' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Water' }));
    fireEvent.click(screen.getByRole('button', { name: 'tonal' }));
    fireEvent.click(screen.getByRole('button', { name: 'Teach ECHO-0' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const call = fetchSpy.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')!;
    const body = JSON.parse((call[1] as RequestInit).body as string);
    expect(body).toMatchObject({ label_ids: ['l1'], new_labels: [], is_unknown: false, descriptors: ['tonal'] });
  });
  it('rejecting a hypothesis and naming a new source sends new_labels + rejected ids; unknown clears both', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      if (String(url).endsWith('/api/labels')) return json([]);
      if (init?.method === 'POST') return json({ annotation: { id: 'a1', action: 'create' }, memory_version: 1, exemplars_added: 1, exemplars_retracted: 0, created_label_ids: ['n1'], rescored_changes: [], fused_top: [] }, 201);
      return json({});
    });
    render(<TeachPanel prediction={ready} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'reject Water' }));
    fireEvent.change(screen.getByLabelText('new label'), { target: { value: 'Roof gutter' } });
    fireEvent.click(screen.getByRole('button', { name: 'Teach ECHO-0' }));
    await waitFor(() => expect(fetchSpy.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === 'POST')).toBe(true));
    const body = JSON.parse((fetchSpy.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')![1] as RequestInit).body as string);
    expect(body).toMatchObject({ label_ids: [], new_labels: ['Roof gutter'], rejected_label_ids: ['l1'] });
    // unknown
    fireEvent.click(screen.getByLabelText(/unknown/));
    expect((screen.getByLabelText('new label') as HTMLInputElement).value).toBe('');
    expect(screen.getByRole('button', { name: 'Teach ECHO-0' })).toBeEnabled();
  });
  it('shows an API failure as a clearable error', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      if (String(url).endsWith('/api/labels')) return json([]);
      if (init?.method === 'POST') return json({ type: 'x', title: 'Validation Failed', status: 422, detail: 'at most 6 labels', code: 'VALIDATION_FAILED' }, 422, 'application/problem+json');
      return json({});
    });
    render(<TeachPanel prediction={ready} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Water' }));
    fireEvent.click(screen.getByRole('button', { name: 'Teach ECHO-0' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('VALIDATION_FAILED');
  });
  it('shows the existing annotation and lets the user correct it', () => {
    const annotated: Prediction = { ...ready, state: 'remembered', annotation: { id: 'a1', recording_id: ready.recording_id, action: 'confirm', status: 'active', labels: [{ label_id: 'l1', slug: 'water', name: 'Water' }], rejected_label_ids: [], is_unknown: false, descriptors: ['continuous'], environment: 'park', mood: null, note: null, prediction_id: null, superseded_by: null, created_at: '' } };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json([]));
    render(<TeachPanel prediction={annotated} onSaved={vi.fn()} />);
    expect(screen.getByText(/You told ECHO-0 this is/)).toHaveTextContent('Water');
    fireEvent.click(screen.getByRole('button', { name: 'Correct this' }));
    expect(screen.getByRole('button', { name: 'Save correction' })).toBeInTheDocument();
  });
});

describe('MemoryPanel', () => {
  it('renders counts, labels and neighbours without calling them accuracy', () => {
    const mem: MemoryOverview = { memory_version: 3, model_version_id: 'm', exemplars: 4, annotations: 4, unknown_annotations: 1, custom_labels: 1,
      labels: [{ label_id: 'l1', slug: 'water', name: 'Water', origin: 'vocabulary', n_exemplars: 3, hue_seed: 200, recording_ids: ['0199a000-0000-7000-8000-000000000001'], prototype: { n_eff: 3, sigma: 0.12 } }], label_names: {} };
    const onSelect = vi.fn();
    render(<MemoryPanel memory={mem} neighbours={[{ recording_id: '0199a000-0000-7000-8000-000000000002', similarity: 0.81, labels: ['Water'], is_unknown: false, captured_at: null, duration_s: 5 }]} onSelect={onSelect} />);
    expect(screen.getByText('Confirmed examples').nextSibling).toHaveTextContent('4');
    expect(screen.getByText(/Example counts are not accuracy/)).toBeInTheDocument();
    expect(screen.getByText('Water')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: '0199a000' })[1]);
    expect(onSelect).toHaveBeenCalledWith('0199a000-0000-7000-8000-000000000002');
  });
});

describe('HearingPanel', () => {
  it('reports API failures and polls while analyzing', async () => {
    let calls = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u.endsWith('/prediction')) {
        calls += 1;
        return json(calls < 3 ? { ...ready, state: 'analyzing', fused: null, base: null } : ready);
      }
      if (u.endsWith('/echo')) return json([{ template: 'hypothesis', text: 'I hear something.', tags: ['model'], event_ids: [] }]);
      if (u.endsWith('/api/labels')) return json([]);
      if (u.includes('/neighbours')) return json([]);
      return json({ type: 'x', title: 'Server', status: 500, detail: 'down', code: 'INTERNAL_ERROR' }, 500, 'application/problem+json');
    });
    render(<HearingPanel recordingId={ready.recording_id} onMemoryChanged={vi.fn()} onNeighbours={vi.fn()} />);
    expect(await screen.findByText('I hear something.', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(calls).toBeGreaterThanOrEqual(3);
  });
  it('does not claim a memory formed while the label is only stored (learning race)', async () => {
    const result = (pending: boolean) => ({ annotation: { id: 'a1', action: 'create' }, memory_version: 1, exemplars_added: pending ? 0 : 1, exemplars_retracted: 0, memory_pending: pending, created_label_ids: ['n1'], rescored_changes: [], fused_top: [] });
    for (const pending of [true, false]) {
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
        const u = String(url);
        if (init?.method === 'POST') return json(result(pending), 201);
        if (u.endsWith('/prediction')) return json(pending ? { ...ready, state: 'inference_failed', fused: null, base: null } : ready);
        if (u.endsWith('/echo')) return json([]);
        if (u.endsWith('/api/labels')) return json([]);
        if (u.includes('/neighbours')) return json([]);
        return json({});
      });
      const { unmount } = render(<HearingPanel recordingId={ready.recording_id} onMemoryChanged={vi.fn()} onNeighbours={vi.fn()} />);
      fireEvent.change(await screen.findByLabelText('new label'), { target: { value: 'Gate' } });
      fireEvent.click(screen.getByRole('button', { name: 'Teach ECHO-0' }));
      const banner = await screen.findByRole('status');
      if (pending) {
        expect(banner).toHaveTextContent(/memory has not changed/);
        expect(banner).not.toHaveTextContent(/taken shape/);
      } else {
        expect(banner).toHaveTextContent(/A memory has taken shape/);
      }
      unmount();
      vi.restoreAllMocks();
    }
  });
  it('surfaces a failed prediction request', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ type: 'x', title: 'Not Found', status: 404, detail: 'recording not found', code: 'NOT_FOUND' }, 404, 'application/problem+json'));
    render(<HearingPanel recordingId={ready.recording_id} onMemoryChanged={vi.fn()} onNeighbours={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('NOT_FOUND');
  });
});
