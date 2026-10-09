import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api } from './api/client';
import type { Health, MemoryOverview, ModelStatus, Neighbour, RecordingSummary } from './api/types';
import { AnalysisPanel } from './components/AnalysisPanel';
import { Archive } from './components/Archive';
import { Atlas } from './components/Atlas';
import { Orchestra } from './components/Orchestra';
import { HearingPanel } from './components/HearingPanel';
import { Specimen } from './components/Specimen';
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
  const [view, setView] = useState<'hearing' | 'specimen' | 'atlas' | 'orchestra'>('hearing');
  const [orchestraIds, setOrchestraIds] = useState<string[]>([]);
  const activityRef = useRef<Record<string, number>>({});
  const toggleOrchestra = useCallback((id: string) => setOrchestraIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : cur.length >= 8 ? cur : [...cur, id])), []);

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
          <div className="sub">acoustic field instrument · M4: ears, memory, a visible world and an orchestra made of it</div>
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

      <nav className="views" aria-label="views">
        <button className={view === 'hearing' ? 'active' : ''} onClick={() => setView('hearing')}>Hearing</button>
        <button className={view === 'specimen' ? 'active' : ''} onClick={() => setView('specimen')} disabled={!selected}>Specimen</button>
        <button className={view === 'atlas' ? 'active' : ''} onClick={() => setView('atlas')}>Atlas</button>
        <button className={view === 'orchestra' ? 'active' : ''} onClick={() => setView('orchestra')}>Orchestra</button>
      </nav>

      {view === 'atlas' && <Atlas version={version + items.length} onOpenSpecimen={(id) => { setSelected(id); setView('specimen'); }} onBack={() => setView('hearing')} selection={orchestraIds} onToggleSelect={toggleOrchestra} onCompose={() => setView('orchestra')} activityRef={activityRef} />}
      {view === 'orchestra' && <Orchestra items={items} preselected={orchestraIds} activityRef={activityRef} onOpenSpecimen={(id) => { setSelected(id); setView('specimen'); }} onOpenAtlas={() => setView('atlas')} />}
      {view === 'specimen' && selected && <Specimen recordingId={selected} onTeach={() => setView('hearing')} onOpenAtlas={() => setView('atlas')} onSelect={setSelected} />}
      <main className="grid" hidden={view !== 'hearing'}>
        <div style={{ display: 'grid', gap: 18, minWidth: 0, alignContent: 'start' }}>
          <RecordingPanel limits={limits} onProcessed={(id) => { setSelected(id); void refresh(); }} onArchiveChanged={() => void refresh()} />
          <MemoryPanel memory={memory} neighbours={neighbours} onSelect={setSelected} />
        </div>
        <div style={{ display: 'grid', gap: 18, minWidth: 0, alignContent: 'start' }}>
          {selected && <div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn small teal" onClick={() => setView('specimen')}>Open visual memory</button></div>}
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
