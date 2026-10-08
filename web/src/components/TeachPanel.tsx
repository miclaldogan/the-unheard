import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { AnnotationResult, Label, Prediction } from '../api/types';

const DESCRIPTORS = ['continuous', 'rhythmic', 'tonal', 'noisy', 'metallic', 'soft', 'sharp', 'distant', 'close', 'layered'];

interface Props {
  prediction: Prediction;
  onSaved: (result: AnnotationResult) => void;
}

export function TeachPanel({ prediction, onSaved }: Props) {
  const existing = prediction.annotation;
  const [labels, setLabels] = useState<Label[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set(existing?.labels.map((l) => l.label_id) ?? []));
  const [rejected, setRejected] = useState<Set<string>>(new Set(existing?.rejected_label_ids ?? []));
  const [query, setQuery] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [unknown, setUnknown] = useState(existing?.is_unknown ?? false);
  const [descriptors, setDescriptors] = useState<Set<string>>(new Set(existing?.descriptors ?? []));
  const [environment, setEnvironment] = useState(existing?.environment ?? '');
  const [mood, setMood] = useState(existing?.mood ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(!existing);

  useEffect(() => {
    api.labels().then(setLabels).catch(() => setLabels([]));
  }, []);

  const candidates = prediction.fused?.candidates.slice(0, 5) ?? [];
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return labels.filter((l) => l.name.toLowerCase().includes(q) || l.slug.includes(q)).slice(0, 8);
  }, [labels, query]);

  const toggle = (set: Set<string>, id: string, setter: (s: Set<string>) => void) => {
    const n = new Set(set);
    if (n.has(id)) n.delete(id); else n.add(id);
    setter(n);
  };
  const choose = (id: string) => {
    if (unknown) setUnknown(false);
    const n = new Set(selected);
    if (n.has(id)) n.delete(id); else n.add(id);
    const r = new Set(rejected); r.delete(id);
    setSelected(n); setRejected(r);
  };
  const reject = (id: string) => {
    const s = new Set(selected); s.delete(id);
    setSelected(s);
    toggle(rejected, id, setRejected);
  };

  const canSubmit = !busy && (unknown || selected.size > 0 || newLabel.trim().length > 0);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.annotate(prediction.recording_id, {
        label_ids: unknown ? [] : Array.from(selected),
        new_labels: unknown || !newLabel.trim() ? [] : [newLabel.trim()],
        rejected_label_ids: Array.from(rejected),
        is_unknown: unknown,
        descriptors: Array.from(descriptors),
        environment: environment.trim() || null,
        mood: mood.trim() || null,
      });
      setNewLabel('');
      setEditing(false);
      onSaved(res);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  };

  const nameOf = (id: string) => labels.find((l) => l.id === id)?.name ?? candidates.find((c) => c.label_id === id)?.name ?? existing?.labels.find((l) => l.label_id === id)?.name ?? id.slice(0, 8);

  if (!editing && existing) {
    return (
      <section className="panel" aria-labelledby="teach-h">
        <h2 id="teach-h">Teach</h2>
        <p>
          {existing.is_unknown ? <>You marked this sound as <strong>unknown</strong>.</> : <>You told ECHO-0 this is <strong>{existing.labels.map((l) => l.name).join(', ')}</strong>.</>}
          {existing.descriptors.length > 0 && <span className="caption"> · {existing.descriptors.join(', ')}</span>}
          {existing.environment && <span className="caption"> · at {existing.environment}</span>}
          {existing.mood && <span className="caption"> · feels {existing.mood}</span>}
        </p>
        <button className="btn small" onClick={() => setEditing(true)}>Correct this</button>
      </section>
    );
  }

  return (
    <section className="panel" aria-labelledby="teach-h">
      <h2 id="teach-h">Teach</h2>
      <p className="caption">What produced the sound? Confirm, reject or add sources. Descriptors, place and feeling are kept separately and never used for recognition.</p>
      <div className="teach-grid">
        <div>
          <div className="field-label">Hypotheses</div>
          {candidates.length === 0 && <p className="caption">No hypotheses yet — you can still name the sound.</p>}
          <ul className="choices">
            {candidates.map((c) => (
              <li key={c.label_id} className={selected.has(c.label_id) ? 'on' : rejected.has(c.label_id) ? 'off' : ''}>
                <button className="btn small" aria-pressed={selected.has(c.label_id)} onClick={() => choose(c.label_id)}>{selected.has(c.label_id) ? '✓ ' : ''}{c.name}</button>
                <button className="btn small ghost" aria-label={`reject ${c.name}`} aria-pressed={rejected.has(c.label_id)} onClick={() => reject(c.label_id)}>✕</button>
              </li>
            ))}
          </ul>
          {Array.from(selected).filter((id) => !candidates.some((c) => c.label_id === id)).map((id) => (
            <span key={id} className="chip on" style={{ marginRight: 6 }}>✓ {nameOf(id)} <button className="linkish" onClick={() => choose(id)} aria-label={`remove ${nameOf(id)}`}>×</button></span>
          ))}
          <div className="field-label" style={{ marginTop: 10 }}>Other source</div>
          <input className="input" placeholder="search known sources…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="search labels" />
          {filtered.length > 0 && (
            <ul className="choices">
              {filtered.map((l) => (
                <li key={l.id} className={selected.has(l.id) ? 'on' : ''}>
                  <button className="btn small" aria-pressed={selected.has(l.id)} onClick={() => choose(l.id)}>{selected.has(l.id) ? '✓ ' : ''}{l.name}{l.origin === 'user' ? ' ·' : ''}{l.n_exemplars ? ` (${l.n_exemplars})` : ''}</button>
                </li>
              ))}
            </ul>
          )}
          <input className="input" placeholder="or name a new source (e.g. roof gutter)" value={newLabel} maxLength={48} onChange={(e) => { setNewLabel(e.target.value); if (e.target.value) setUnknown(false); }} aria-label="new label" />
          <label className="check"><input type="checkbox" checked={unknown} onChange={(e) => { setUnknown(e.target.checked); if (e.target.checked) { setSelected(new Set()); setNewLabel(''); } }} /> I can't name it either (unknown)</label>
        </div>
        <div>
          <div className="field-label">How does it sound? <span className="caption">(optional)</span></div>
          <div className="row">
            {DESCRIPTORS.map((d) => (
              <button key={d} className={`btn small ${descriptors.has(d) ? 'teal' : 'ghost'}`} aria-pressed={descriptors.has(d)} onClick={() => toggle(descriptors, d, setDescriptors)}>{d}</button>
            ))}
          </div>
          <div className="field-label" style={{ marginTop: 10 }}>Where <span className="caption">(optional)</span></div>
          <input className="input" placeholder="park, street, courtyard…" value={environment} maxLength={80} onChange={(e) => setEnvironment(e.target.value)} aria-label="environment" />
          <div className="field-label" style={{ marginTop: 10 }}>What it evokes <span className="caption">(optional, never used for recognition)</span></div>
          <input className="input" placeholder="peaceful, unsettling…" value={mood} maxLength={80} onChange={(e) => setMood(e.target.value)} aria-label="mood" />
        </div>
      </div>
      {error && <div className="error" role="alert"><span>{error}</span><button className="btn small" onClick={() => setError(null)}>Clear</button></div>}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" onClick={() => void submit()} disabled={!canSubmit}>{busy ? 'Remembering…' : existing ? 'Save correction' : 'Teach ECHO-0'}</button>
        {existing && <button className="btn" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>}
      </div>
    </section>
  );
}
