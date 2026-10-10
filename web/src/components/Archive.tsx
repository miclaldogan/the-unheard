import { useAudioSource } from '../platform/useAudioSource';
import { useState } from 'react';
import { ApiError, api } from '../api/client';
import type { RecordingSummary } from '../api/types';

interface Props {
  items: RecordingSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
  onChanged: () => void;
}

export function Archive({ items, selected, onSelect, onChanged }: Props) {
  const [playing, setPlaying] = useState<string | null>(null);
  const audioSource = useAudioSource(playing ? api.audioUrl(playing) : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const del = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      await api.delete(id);
      if (playing === id) setPlaying(null);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(null);
    }
  };
  const retry = async (id: string) => {
    setBusy(id);
    try {
      await api.retry(id);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="panel" aria-labelledby="ar-h">
      <h2 id="ar-h">Archive</h2>
      <p className="caption">{items.length} preserved signal{items.length === 1 ? '' : 's'} · preserved in the connected laboratory</p>
      {audioSource.error && <p role="alert" className="caption">{audioSource.error}</p>}
      {error && <div className="error" role="alert"><span>{error}</span><button className="btn small" onClick={() => setError(null)}>Clear</button></div>}
      {items.length === 0 ? (
        <p className="empty">The archive is quiet. Bring a sound from outside to begin.</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="archive">
            <thead>
              <tr><th>Captured</th><th>Duration</th><th>Quality</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className={r.id === selected ? 'selected' : ''}>
                  <td>{new Date(r.captured_at ?? r.created_at).toLocaleString()}</td>
                  <td>{r.duration_s.toFixed(1)} s</td>
                  <td>{r.quality.flags.length ? <span className="flags">{r.quality.flags.join(', ')}</span> : <span className="caption">clean</span>}</td>
                  <td><span className={`chip ${r.status}`}>{r.status}</span></td>
                  <td>
                    <div className="row">
                      <button className="btn small" onClick={() => onSelect(r.id)} aria-label={`analyse ${r.id}`}>Analyse</button>
                      <button className="btn small" onClick={() => setPlaying(playing === r.id ? null : r.id)} aria-label={`play ${r.id}`}>{playing === r.id ? 'Hide' : 'Play'}</button>
                      {r.status === 'failed' && <button className="btn small" onClick={() => void retry(r.id)} disabled={busy === r.id}>Retry</button>}
                      <button className="btn small danger" onClick={() => void del(r.id)} disabled={busy === r.id} aria-label={`delete ${r.id}`}>Delete</button>
                    </div>
                    {playing === r.id && <audio controls autoPlay src={audioSource.src} style={{ width: '100%', marginTop: 6 }} aria-label={`playback ${r.id}`} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
