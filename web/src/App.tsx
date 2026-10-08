import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from './api/client';
import type { Health, MemoryOverview, ModelStatus, Neighbour, RecordingSummary } from './api/types';
import { AnalysisPanel } from './components/AnalysisPanel';
import { Archive } from './components/Archive';
import { HearingPanel } from './components/HearingPanel';
import { MemoryPanel } from './components/MemoryPanel';
import { RecordingPanel } from './components/RecordingPanel';

const DEFAULT_LIMITS = { min_duration_s: 3, max_duration_s: 30 };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [items, setItems] = useState<RecordingSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [memory, setMemory] = useState<MemoryOverview | null>(null);
  const [neighbours, setNeighbours] = useState<Neighbour[]>([]);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const [l, h, m, mem] = await Promise.all([api.list(), api.health(), api.model().catch(() => null), api.memory().catch(() => null)]);
      setItems(l.items);
      setHealth(h);
      setModel(m);
      setMemory(mem);
      setHealthError(null);
    } catch (e) {
      setHealthError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    }
  }, []);
  const onMemoryChanged = useCallback(() => { setVersion((v) => v + 1); void refresh(); }, [refresh]);
  const onNeighbours = useCallback((n: Neighbour[]) => { setNeighbours(n); setVersion((v) => v + 1); }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // keep the archive fresh while anything is still processing
  useEffect(() => {
    if (!items.some((r) => r.status === 'uploaded' || r.status === 'processing')) return;
    const t = window.setTimeout(() => void refresh(), 1000);
    return () => window.clearTimeout(t);
  }, [items, refresh]);

  const onDeletedOrChanged = useCallback(() => {
    void refresh().then(() => {
      setSelected((cur) => (cur && !items.some((r) => r.id === cur) ? cur : cur));
    });
  }, [refresh, items]);

  useEffect(() => {
    if (selected && items.length && !items.some((r) => r.id === selected)) setSelected(null);
  }, [items, selected]);

  const limits = health?.limits ?? DEFAULT_LIMITS;

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>THE <span>UNHEARD</span></h1>
          <div className="sub">acoustic field instrument · M2: ears (CLAP) + personal memory · no music yet</div>
        </div>
        <div className="health" aria-label="server status">
          {health ? (
            <>
              <span className="ok">server ok</span>
              <span>dsp v{health.dsp_version}</span>
              <span>{health.decoder.ffmpeg_available ? 'ffmpeg' : 'wav/flac only'}</span>
              <span>ears: {model ? `${model.status}${model.model_id ? ` · ${model.model_id.split('/')[1] ?? model.model_id}` : ''} · ${model.device}` : '…'}</span>
              <span>{health.recordings} stored</span>
            </>
          ) : (
            <span className="bad">{healthError ? `server unreachable (${healthError})` : 'connecting…'}</span>
          )}
        </div>
      </header>

      <main className="grid">
        <div style={{ display: 'grid', gap: 18, minWidth: 0, alignContent: 'start' }}>
          <RecordingPanel limits={limits} onProcessed={(id) => { setSelected(id); void refresh(); }} onArchiveChanged={() => void refresh()} />
          <MemoryPanel memory={memory} neighbours={neighbours} onSelect={setSelected} />
        </div>
        <div style={{ display: 'grid', gap: 18, minWidth: 0, alignContent: 'start' }}>
          <HearingPanel recordingId={selected} onMemoryChanged={onMemoryChanged} onNeighbours={onNeighbours} />
          <AnalysisPanel recordingId={selected} version={version} />
          <Archive items={items} selected={selected} onSelect={setSelected} onChanged={onDeletedOrChanged} />
        </div>
      </main>

      <footer className="footer">
        Recordings never leave this machine. ECHO-0's ears are a local open-weight model (LAION-CLAP); its memory is only your labelled recordings. Nothing is fine-tuned. · <a href="/api/docs">API</a>
      </footer>
    </div>
  );
}
