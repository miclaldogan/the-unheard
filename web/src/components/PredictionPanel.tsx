import type { FusedCandidate, Prediction } from '../api/types';

const STATE_LABEL: Record<Prediction['state'], string> = {
  model_disabled: 'Ears disabled on this server',
  not_run: 'Not yet heard',
  analyzing: 'Analyzing',
  inference_failed: 'Hearing failed',
  awaiting_feedback: 'Hypothesizing — awaiting your answer',
  remembered: 'Remembered',
};

function Bar({ value, max, cls }: { value: number; max: number; cls: string }) {
  const w = Math.max(0, Math.min(100, (value / max) * 100));
  return <span className={`bar ${cls}`} aria-hidden="true"><i style={{ width: `${w}%` }} /></span>;
}

export function PredictionPanel({ prediction, onInfer, busy }: { prediction: Prediction | null; onInfer: () => void; busy: boolean }) {
  if (!prediction) return null;
  const p = prediction;
  const fused = p.fused?.candidates ?? [];
  const nov = p.fused?.novelty;
  const top: FusedCandidate[] = fused.slice(0, 5);
  const maxBase = Math.max(0.01, ...top.map((c) => c.base_similarity));
  return (
    <section className="panel" aria-labelledby="pr-h">
      <h2 id="pr-h">Hearing</h2>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className={`chip state-${p.state}`}>{STATE_LABEL[p.state]}</span>
        {p.model && <span className="caption">{p.model.id} · {p.model.revision.slice(0, 8)} · {p.model.embedding_dim}-d · {p.base?.inference_ms ? `${p.base.inference_ms.toFixed(0)} ms` : ''}</span>}
      </div>
      {p.state === 'model_disabled' && <p className="caption" style={{ marginTop: 8 }}>The server runs with <code>UNHEARD_MODEL=none</code>. Features and annotations still work; no hypotheses are produced.</p>}
      {p.state === 'not_run' && (
        <div className="row" style={{ marginTop: 10 }}>
          <span className="caption">This recording predates the ears, or inference was never queued.</span>
          <button className="btn small teal" onClick={onInfer} disabled={busy}>Listen with ECHO-0's ears</button>
        </div>
      )}
      {p.state === 'analyzing' && <p className="caption" style={{ marginTop: 8 }}>CLAP is embedding the canonical audio in 10 s windows…</p>}
      {p.state === 'inference_failed' && (
        <div className="error" role="alert" style={{ marginTop: 8 }}>
          <span><code>INFERENCE_FAILED</code> {p.job?.error ?? 'unknown error'} — the recording and its features are intact.</span>
          <button className="btn small" onClick={onInfer} disabled={busy}>Retry</button>
        </div>
      )}
      {p.fused && (
        <>
          {nov?.novel && <p className="novel" role="status">Unknown: nothing in memory resembles this and the ears are undecided. ECHO-0 cannot name it yet.</p>}
          {nov?.disagreement && !nov.novel && <p className="novel" role="status">Ears and memory disagree — both hypotheses are shown.</p>}
          <table className="hyp" aria-label="hypotheses">
            <thead>
              <tr><th>#</th><th>source</th><th>ears<br /><span className="caption">cosine</span></th><th>memory<br /><span className="caption">nearest cosine · n</span></th><th>fused<br /><span className="caption">rank score</span></th></tr>
            </thead>
            <tbody>
              {top.map((c) => (
                <tr key={c.label_id} className={c.rank === 1 ? 'top' : ''}>
                  <td>{c.rank}</td>
                  <td>{c.name} <span className={`ev ev-${c.evidence}`}>{c.evidence}</span></td>
                  <td><Bar value={c.base_similarity} max={maxBase} cls="ears" />{c.base_similarity.toFixed(3)}</td>
                  <td>{c.memory_similarity === null ? <span className="caption">—</span> : <><Bar value={c.memory_similarity} max={1} cls="mem" />{c.memory_similarity.toFixed(3)} · {c.n_exemplars}</>}</td>
                  <td>{c.fused_score.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="caption">
            Ears: cosine similarity between the CLAP audio embedding and each label's text prompt (max over windows) — not a probability.
            Memory: cosine to your labelled recordings. Fused: relative rank score over {fused.length}+ labels at memory v{p.fused.memory_version}
            {nov && nov.memory_size > 0 ? ` · λ=${nov.lambda.toFixed(2)} from ${nov.relevant_exemplars} relevant exemplar(s)` : ' · memory empty'}.
          </p>
          {p.base && p.base.windows.length > 1 && (
            <details>
              <summary className="caption">{p.base.windows.length} windows (10 s, 5 s hop)</summary>
              <ul className="windows">
                {p.base.windows.map((w) => (
                  <li key={w.idx}><code>{w.start_s.toFixed(0)}–{w.end_s.toFixed(0)} s</code> {w.top.map((t) => `${t.name} ${t.similarity.toFixed(2)}`).join(' · ')}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
