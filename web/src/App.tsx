import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from './api/client';
import type { Health, RecordingSummary } from './api/types';
import { AnalysisPanel } from './components/AnalysisPanel';
import { Archive } from './components/Archive';
import { RecordingPanel } from './components/RecordingPanel';

const DEFAULT_LIMITS = { min_duration_s: 3, max_duration_s: 30 };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [items, setItems] = useState<RecordingSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [l, h] = await Promise.all([api.list(), api.health()]);
      setItems(l.items);
      setHealth(h);
      setHealthError(null);
    } catch (e) {
      setHealthError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    }
  }, []);

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
          <div className="sub">acoustic field instrument · M1 audio foundation · no recognition yet</div>
        </div>
        <div className="health" aria-label="server status">
          {health ? (
            <>
              <span className="ok">server ok</span>
              <span>dsp v{health.dsp_version}</span>
              <span>{health.decoder.ffmpeg_available ? 'ffmpeg' : 'wav/flac only'}</span>
              <span>inference: {health.inference}, model {health.model_loaded ? 'loaded' : 'none'}</span>
              <span>{health.recordings} stored</span>
            </>
          ) : (
            <span className="bad">{healthError ? `server unreachable (${healthError})` : 'connecting…'}</span>
          )}
        </div>
      </header>

      <main className="grid">
        <RecordingPanel limits={limits} onProcessed={(id) => { setSelected(id); void refresh(); }} onArchiveChanged={() => void refresh()} />
        <div style={{ display: 'grid', gap: 18, minWidth: 0 }}>
          <AnalysisPanel recordingId={selected} />
          <Archive items={items} selected={selected} onSelect={setSelected} onChanged={onDeletedOrChanged} />
        </div>
      </main>

      <footer className="footer">
        Recordings never leave this machine. ECHO-0 does not recognise or learn sounds yet; that arrives with the M2 audio model. · <a href="/api/docs">API</a>
      </footer>
    </div>
  );
}
