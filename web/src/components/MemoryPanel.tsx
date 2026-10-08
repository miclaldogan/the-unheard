import type { MemoryOverview, Neighbour } from '../api/types';

interface Props {
  memory: MemoryOverview | null;
  neighbours: Neighbour[];
  onSelect: (id: string) => void;
}

export function MemoryPanel({ memory, neighbours, onSelect }: Props) {
  return (
    <section className="panel" aria-labelledby="mem-h">
      <h2 id="mem-h">Acoustic memory</h2>
      {!memory ? (
        <p className="caption">loading…</p>
      ) : (
        <>
          <div className="stats">
            <div className="stat"><div className="label">Confirmed examples</div><div className="value">{memory.exemplars}</div></div>
            <div className="stat"><div className="label">Annotations</div><div className="value">{memory.annotations}<span className="unit">{memory.unknown_annotations ? ` (${memory.unknown_annotations} unknown)` : ''}</span></div></div>
            <div className="stat"><div className="label">Learned names</div><div className="value">{memory.custom_labels}</div></div>
            <div className="stat"><div className="label">Memory version</div><div className="value">v{memory.memory_version}</div></div>
          </div>
          <p className="caption">Example counts are not accuracy. Memory only influences a hypothesis when a remembered recording is acoustically close.</p>
          {memory.labels.length === 0 ? (
            <p className="empty">Nothing taught yet.</p>
          ) : (
            <ul className="memlist">
              {memory.labels.map((l) => (
                <li key={l.label_id}>
                  <span className="swatch" style={{ background: `hsl(${l.hue_seed} 45% 45%)` }} aria-hidden="true" />
                  <strong>{l.name}</strong>{l.origin === 'user' && <span className="chip" style={{ marginLeft: 6 }}>yours</span>}
                  <span className="caption"> · {l.n_exemplars} example{l.n_exemplars === 1 ? '' : 's'}{l.prototype ? ` · spread ${l.prototype.sigma.toFixed(2)}` : ''}</span>
                  <span className="recs">{l.recording_ids.slice(0, 6).map((rid) => <button key={rid} className="linkish" onClick={() => onSelect(rid)}>{rid.slice(0, 8)}</button>)}</span>
                </li>
              ))}
            </ul>
          )}
          {neighbours.length > 0 && (
            <>
              <div className="field-label" style={{ marginTop: 10 }}>Similar recordings to the selected one</div>
              <ul className="memlist">
                {neighbours.map((n) => (
                  <li key={n.recording_id}>
                    <button className="linkish" onClick={() => onSelect(n.recording_id)}>{n.recording_id.slice(0, 8)}</button>
                    <span className="caption"> · cos {n.similarity.toFixed(3)} · {n.is_unknown ? 'unknown' : n.labels.length ? n.labels.join(', ') : 'unlabelled'}{n.duration_s ? ` · ${n.duration_s.toFixed(0)} s` : ''}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
