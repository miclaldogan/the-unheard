import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api, waitForComposition } from '../api/client';
import type {
  Atlas as AtlasData,
  Composition,
  CompositionEvent,
  CompositionListItem,
  CompositionMode,
  Hierarchy,
  CompositionTrace,
  Controls,
  MusicRole,
  RecordingSummary,
  Visual,
} from '../api/types';
import { OrchestraPlayer, SourceClock, activityAt, effectiveGains } from '../audio/orchestra';
import { SignatureCanvas, prefersReducedMotion } from './SignatureCanvas';

export interface OrchestraProps {
  items: RecordingSummary[];
  preselected: string[];
  /** live per-recording activity (0…1) for the atlas; written every frame while playing */
  activityRef: { current: Record<string, number> };
  onOpenSpecimen: (id: string) => void;
  onOpenAtlas: () => void;
  /** injectable for tests (Web Audio is unavailable in jsdom) */
  createPlayer?: () => OrchestraPlayer;
}

const ROLE_COLOR: Record<MusicRole, string> = {
  texture: '#3fa7a0',
  drone: '#275f5b',
  rhythmic_texture: '#7fb3a0',
  percussion: '#d9a441',
  tonal_motif: '#e7e3da',
  accent: '#c0564a',
  granular: '#b87333',
};
const ROLE_NAME: Record<MusicRole, string> = {
  texture: 'atmosphere',
  drone: 'drone',
  rhythmic_texture: 'pulse',
  percussion: 'percussion',
  tonal_motif: 'melody',
  accent: 'accents',
  granular: 'grain cloud',
};
const SLIDERS: { key: keyof Controls; lo: string; hi: string; hint: string }[] = [
  { key: 'density', lo: 'Sparse', hi: 'Dense', hint: 'how many of each sound’s hits, notes and grains are kept' },
  { key: 'structure', lo: 'Organic', hi: 'Structured', hint: 'keep each sound’s natural timing ↔ snap to a 16th-note grid' },
  { key: 'intensity', lo: 'Calm', hi: 'Intense', hint: 'tempo ±8 %, brightness and the loudness of the climax' },
];
const HIER_NAME: Record<Hierarchy, string> = { lead: 'lead', foundation: 'groove', support: 'answer', gesture: 'gesture', bed: 'atmosphere' };
const MODES: { key: CompositionMode; name: string; hint: string }[] = [
  { key: 'composed', name: 'Composed', hint: 'clear phrases, call-and-response, a steadier groove with swing and ghost notes' },
  { key: 'organic', name: 'Organic', hint: 'sources keep their own timing; sparse, atmospheric, the environment stays forward' },
];
const DURATIONS = [30, 45, 60, 75];
const MAX_SOURCES = 8;

function fmt(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}
const errText = (e: unknown): string => (e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));

function Instrument({ recordingId, clock, setRef, label }: { recordingId: string; clock: SourceClock | null; setRef: (id: string, el: HTMLElement | null) => void; label: string }) {
  const [visual, setVisual] = useState<Visual | null>(null);
  useEffect(() => {
    let off = false;
    api.visual(recordingId).then((v) => { if (!off) setVisual(v); }).catch(() => undefined);
    return () => { off = true; };
  }, [recordingId]);
  return (
    <div className="instrument" ref={(el) => setRef(recordingId, el)} aria-label={`specimen of ${label}`}>
      {visual ? <SignatureCanvas params={visual.params} size={76} audio={clock} detail="glyph" ariaLabel={`specimen: ${label}`} /> : <div className="instrument-ph" />}
    </div>
  );
}

export function Orchestra({ items, preselected, activityRef, onOpenSpecimen, onOpenAtlas, createPlayer }: OrchestraProps) {
  const [atlas, setAtlas] = useState<AtlasData | null>(null);
  const [picked, setPicked] = useState<string[]>(preselected);
  const [controls, setControls] = useState<Controls>({ density: 0.5, structure: 0.5, intensity: 0.5 });
  const [duration, setDuration] = useState(45);
  const [mode, setMode] = useState<CompositionMode>('composed');
  const [comp, setComp] = useState<Composition | null>(null);
  const [events, setEvents] = useState<CompositionEvent[]>([]);
  const [saved, setSaved] = useState<CompositionListItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState<Set<string>>(new Set());
  const [solo, setSolo] = useState<Set<string>>(new Set());
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [trace, setTrace] = useState<CompositionTrace | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [name, setName] = useState('');
  const playerRef = useRef<OrchestraPlayer | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const instRefs = useRef(new Map<string, HTMLElement>());
  const origRef = useRef<HTMLAudioElement>(null);
  const reduced = prefersReducedMotion();

  const getPlayer = useCallback((): OrchestraPlayer => {
    if (!playerRef.current) playerRef.current = createPlayer ? createPlayer() : new OrchestraPlayer();
    return playerRef.current;
  }, [createPlayer]);

  useEffect(() => { void api.atlas().then(setAtlas).catch(() => undefined); }, [items.length]);
  const refreshSaved = useCallback(() => { void api.compositions().then(setSaved).catch(() => undefined); }, []);
  useEffect(refreshSaved, [refreshSaved]);
  useEffect(() => () => { void playerRef.current?.dispose(); activityRef.current = {}; }, [activityRef]);
  useEffect(() => { setPicked((cur) => (preselected.length ? preselected : cur)); }, [preselected]);

  const labelOf = useMemo(() => {
    const m = new Map<string, { label: string | null; state: string; hue: number | null }>();
    atlas?.nodes.forEach((n) => m.set(n.recording_id, { label: n.label, state: n.state, hue: n.hue }));
    return (id: string) => m.get(id);
  }, [atlas]);
  const ready = useMemo(() => items.filter((r) => r.status === 'ready'), [items]);

  const trackKeys = useMemo(() => comp?.tracks.map((t) => t.track_key) ?? [], [comp]);
  const gains = useMemo(() => effectiveGains(trackKeys, muted, solo), [trackKeys, muted, solo]);
  useEffect(() => { playerRef.current?.setGains(gains); }, [gains]);

  const clocks = useMemo(() => {
    const p = playerRef.current;
    const m = new Map<string, SourceClock>();
    if (p && comp) for (const t of comp.tracks) if (!m.has(t.recording_id)) m.set(t.recording_id, new SourceClock(p, events, t.recording_id));
    return m;
  }, [comp, events]);

  const draw = useCallback((t: number) => {
    const canvas = canvasRef.current;
    if (!canvas || !comp || !comp.duration_s) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 700;
    const lane = 26;
    const h = lane * comp.tracks.length + 20;
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.height = `${h}px`;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const D = comp.duration_s;
    const x = (s: number) => (s / D) * w;
    comp.sections.forEach((s) => {
      ctx.fillStyle = 'rgba(231,227,218,0.04)';
      ctx.fillRect(x(s.start_s), 0, x(s.end_s) - x(s.start_s) - 1, h - 14);
      ctx.fillStyle = 'rgba(154,150,141,0.9)';
      ctx.font = '10px IBM Plex Mono, monospace';
      ctx.fillText(s.name, x(s.start_s) + 4, h - 3);
    });
    const laneOf = new Map(comp.tracks.map((tr, i) => [tr.track_key, i] as const));
    for (const e of events) {
      const i = laneOf.get(e.track_key);
      if (i === undefined) continue;
      const on = gains[e.track_key] > 0;
      const sel = trace?.event.seq === e.seq;
      ctx.fillStyle = ROLE_COLOR[e.role];
      ctx.globalAlpha = on ? (e.kind === 'slice' ? 0.9 : 0.35) : 0.1;
      const x0 = x(e.comp_start_s);
      ctx.fillRect(x0, i * lane + 5, Math.max(2, x(e.comp_start_s + e.comp_dur_s) - x0), lane - 10);
      if (sel) { ctx.globalAlpha = 1; ctx.strokeStyle = '#e7e3da'; ctx.strokeRect(x0 - 1, i * lane + 3, Math.max(4, x(e.comp_start_s + e.comp_dur_s) - x0 + 2), lane - 6); }
    }
    ctx.globalAlpha = 1;
    ctx.strokeStyle = '#e7e3da';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x(t), 0);
    ctx.lineTo(x(t), h - 14);
    ctx.stroke();
  }, [comp, events, gains, trace]);

  // One clock drives everything: the player's Web Audio time.
  useEffect(() => {
    const p = playerRef.current;
    if (!p || !comp) return;
    let raf = 0;
    let last = 0;
    const frame = () => {
      const t = p.currentTime;
      const act = p.paused ? {} : activityAt(events, t, gains); // restrained when nothing sounds
      activityRef.current = act;
      instRefs.current.forEach((el, rid) => el.style.setProperty('--lv', String(reduced ? Math.round((act[rid] ?? 0) * 3) / 3 : (act[rid] ?? 0).toFixed(3))));
      draw(t);
      const now = performance.now();
      if (now - last > (reduced ? 250 : 66)) { setTime(t); last = now; }
      if (!p.paused) raf = requestAnimationFrame(frame);
    };
    const sync = () => { setPlaying(!p.paused); cancelAnimationFrame(raf); frame(); };
    ['play', 'pause', 'ended', 'seeked'].forEach((ev) => p.addEventListener(ev, sync));
    sync();
    return () => { cancelAnimationFrame(raf); ['play', 'pause', 'ended', 'seeked'].forEach((ev) => p.removeEventListener(ev, sync)); };
  }, [comp, events, gains, draw, activityRef, reduced]);

  const loadComposition = useCallback(async (c: Composition) => {
    const p = getPlayer();
    p.stop();
    setComp(c);
    setEvents([]);
    setTrace(null);
    setMuted(new Set());
    setSolo(new Set());
    setFocus(null);
    if (c.status !== 'ready' || !c.duration_s) return;
    const evs = await api.compositionEvents(c.id);
    await p.load(c.tracks.filter((t) => t.stem_url).map((t) => ({ key: t.track_key, url: t.stem_url as string })), c.duration_s);
    setEvents(evs);
    setName(c.name);
  }, [getPlayer]);

  const run = useCallback(async (label: string, start: () => Promise<Composition>) => {
    setBusy(label);
    setError(null);
    try {
      const first = await start();
      setComp(first);
      const done = first.status === 'ready' || first.status === 'failed' ? first : await waitForComposition(first.id);
      await loadComposition(done);
      if (done.status === 'failed') setError(`render failed: ${done.error ?? 'unknown error'}`);
      refreshSaved();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  }, [loadComposition, refreshSaved]);

  const generate = () => run('Composing…', () => api.createComposition({ recording_ids: picked, mode, controls, duration_s: duration }));
  const another = () => comp && run('Composing a variation…', () => api.variation(comp.id, { controls }));
  const retry = () => comp && run('Rendering again…', () => api.rerender(comp.id));
  const openSaved = (id: string) => run('Opening…', () => api.composition(id));

  const toggle = (id: string) => setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : cur.length >= MAX_SOURCES ? cur : [...cur, id]));
  const flip = (set: Set<string>, setter: (s: Set<string>) => void, k: string) => { const n = new Set(set); if (n.has(k)) n.delete(k); else n.add(k); setter(n); };

  const togglePlay = async () => {
    const p = getPlayer();
    origRef.current?.pause();
    if (p.paused) await p.play(); else p.pause();
  };
  const onCanvasClick = (ev: React.MouseEvent<HTMLCanvasElement>) => {
    if (!comp?.duration_s) return;
    const rect = ev.currentTarget.getBoundingClientRect();
    const t = ((ev.clientX - rect.left) / rect.width) * comp.duration_s;
    const lane = Math.floor((ev.clientY - rect.top) / 26);
    const tr = comp.tracks[lane];
    const hit = tr && events.filter((e) => e.track_key === tr.track_key && t >= e.comp_start_s - 0.05 && t <= e.comp_start_s + Math.max(0.15, e.comp_dur_s)).sort((a, b) => a.comp_dur_s - b.comp_dur_s)[0];
    if (hit) { setFocus(tr.track_key); void api.trace(comp.id, hit.seq).then(setTrace).catch((e) => setError(errText(e))); } else { getPlayer().seek(t); }
  };

  const compare = async (mode: 'original' | 'layer' | 'full', key: string) => {
    const p = getPlayer();
    setFocus(key);
    if (mode === 'original') {
      p.pause();
      const tr = comp?.tracks.find((t) => t.track_key === key);
      if (tr && origRef.current) { origRef.current.src = tr.original_url; await origRef.current.play().catch(() => undefined); }
      return;
    }
    origRef.current?.pause();
    if (mode === 'layer') { setSolo(new Set([key])); setMuted(new Set()); } else { setSolo(new Set()); setMuted(new Set()); }
    await p.play();
  };

  const save = async () => {
    if (!comp) return;
    try { setComp(await api.patchComposition(comp.id, { saved: true, name: name.trim() || comp.name })); refreshSaved(); } catch (e) { setError(errText(e)); }
  };
  const removeComp = async (id: string) => {
    try { await api.deleteComposition(id); if (comp?.id === id) { getPlayer().stop(); setComp(null); setEvents([]); } refreshSaved(); } catch (e) { setError(errText(e)); }
  };

  const focusTrack = comp?.tracks.find((t) => t.track_key === focus) ?? null;
  const focusSource = comp?.sources.find((s) => s.recording_id === focusTrack?.recording_id) ?? null;
  const nameOf = (rid: string) => comp?.sources.find((s) => s.recording_id === rid)?.label ?? labelOf(rid)?.label ?? rid.slice(0, 8);
  const lines = comp?.echo ?? [];

  return (
    <section className="orchestra" aria-labelledby="orch-h">
      <header className="specimen-head">
        <div>
          <div className="eyebrow">The Orchestra · the recordings are the instruments, the environment is the composer</div>
          <h2 id="orch-h">{comp?.status === 'ready' ? comp.name : 'An orchestra of your memories'}</h2>
        </div>
        <div className="row"><button className="btn small" onClick={onOpenAtlas}>Pick from the atlas</button></div>
      </header>
      {error && <div className="error" role="alert"><span>{error}</span><span className="row">{comp?.status === 'failed' && <button className="btn small" onClick={() => void retry()}>Retry render</button>}<button className="btn small" onClick={() => setError(null)}>Dismiss</button></span></div>}

      <div className="orch-grid">
        <div className="panel" aria-label="sources">
          <h2>Sources</h2>
          {ready.length === 0 && <p className="caption">No ready recordings yet. Record something first — everything here is built from your own sounds.</p>}
          <ul className="picklist">
            {ready.map((r) => {
              const info = labelOf(r.id);
              const on = picked.includes(r.id);
              return (
                <li key={r.id}>
                  <label className={`pick ${on ? 'on' : ''}`}>
                    <input type="checkbox" checked={on} onChange={() => toggle(r.id)} disabled={!on && picked.length >= MAX_SOURCES} aria-label={`use ${info?.label ?? r.id.slice(0, 8)}`} />
                    <span className="dot" style={{ background: info?.hue != null ? `hsl(${info.hue} 55% 55%)` : 'var(--line)' }} />
                    <span className="pick-name">{info?.label ?? 'unnamed'}</span>
                    <span className="caption">{r.duration_s.toFixed(1)} s · {info?.state ?? '…'}</span>
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="modes" role="group" aria-label="arrangement mode">
            {MODES.map((m) => (
              <button key={m.key} className={`btn small ${mode === m.key ? 'teal' : ''}`} aria-pressed={mode === m.key} title={m.hint} onClick={() => setMode(m.key)}>{m.name}</button>
            ))}
          </div>
          <div className="sliders">
            {SLIDERS.map((s) => (
              <label key={s.key} className="slider" title={s.hint}>
                <span>{s.lo}</span>
                <input type="range" min={0} max={1} step={0.05} value={controls[s.key]} onChange={(e) => setControls({ ...controls, [s.key]: Number(e.target.value) })} aria-label={`${s.lo} to ${s.hi}`} />
                <span>{s.hi}</span>
              </label>
            ))}
            <label className="slider"><span>Length</span>
              <select className="input" style={{ marginBottom: 0 }} value={duration} onChange={(e) => setDuration(Number(e.target.value))} aria-label="target length">
                {DURATIONS.map((d) => <option key={d} value={d}>{d} s</option>)}
              </select><span />
            </label>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn primary" onClick={() => void generate()} disabled={picked.length === 0 || !!busy}>{busy ?? `Compose from ${picked.length} sound${picked.length === 1 ? '' : 's'}`}</button>
            {comp?.status === 'ready' && <button className="btn" onClick={() => void another()} disabled={!!busy}>Another variation</button>}
          </div>
          {saved.length > 0 && (
            <details className="saved" open={saved.some((s) => s.saved)}>
              <summary>Saved &amp; recent ({saved.length})</summary>
              <ul className="picklist">
                {saved.slice(0, 12).map((s) => (
                  <li key={s.id} className="row" style={{ justifyContent: 'space-between' }}>
                    <button className="btn small" onClick={() => void openSaved(s.id)} disabled={!!busy}>{s.saved ? '★ ' : ''}{s.name} · {s.n_sources} sounds{s.duration_s ? ` · ${fmt(s.duration_s)}` : ''}</button>
                    <span className={`chip ${s.status}`}>{s.status}</span>
                    <button className="btn small danger" aria-label={`delete ${s.name}`} onClick={() => void removeComp(s.id)}>✕</button>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>

        <div className="panel" aria-label="composition">
          <h2>Listen</h2>
          {!comp && <p className="caption">Choose sounds on the left and press Compose. Each becomes a layer; you can hear every layer alone, or the whole world together.</p>}
          {comp && comp.status !== 'ready' && <p className="caption" role="status">{comp.status === 'failed' ? `Render failed — ${comp.error}` : `${comp.status}… the recordings are being analysed and arranged.`}</p>}
          {comp?.status === 'ready' && comp.duration_s && (
            <>
              <div className="transport row">
                <button className="btn primary" onClick={() => void togglePlay()}>{playing ? 'Pause' : 'Play'}</button>
                <button className="btn" onClick={() => getPlayer().stop()}>Stop</button>
                <input type="range" className="seek" min={0} max={comp.duration_s} step={0.05} value={Math.min(time, comp.duration_s)} onChange={(e) => getPlayer().seek(Number(e.target.value))} aria-label="seek" />
                <span className="caption">{fmt(time)} / {fmt(comp.duration_s)}</span>
              </div>
              <p className="caption">{comp.tempo_bpm} BPM{comp.tempo_source === 'default_free' ? ' (free time; nothing periodic to lock to)' : ` (from ${comp.tempo_source?.replace('_', ' ')})`}{comp.key ? ' · key from the measured pitch of your melodic sound' : ' · no key: nothing here was pitched enough'} · seed {comp.seed} · plan {comp.plan_hash?.slice(0, 8)}</p>
              {comp.form && (
                <p className="caption form" aria-label="musical form">
                  {Object.entries(comp.form).map(([sec, f]) => `${sec}: ${f}`).join('  ·  ')}
                  {comp.conversation.length > 0 ? ` · conversation: ${comp.conversation.length} call-and-response (fit ${(comp.conversation[0].evidence.score ?? 0).toFixed(2)})` : ''}
                  {comp.groove ? ` · groove ${Math.round(comp.groove.quantisation * 100)} % on the grid${comp.groove.swing_steps ? `, swing ${comp.groove.swing_steps}` : ''}` : ''}
                </p>
              )}
              <div className="instruments">
                {comp.tracks.map((t) => (
                  <div key={t.track_key} className={`track ${focus === t.track_key ? 'focus' : ''} ${gains[t.track_key] === 0 ? 'dim' : ''}`}>
                    <Instrument recordingId={t.recording_id} clock={clocks.get(t.recording_id) ?? null} setRef={(id, el) => { if (el) instRefs.current.set(id, el); else instRefs.current.delete(id); }} label={nameOf(t.recording_id)} />
                    <div className="track-meta">
                      <strong>{nameOf(t.recording_id)}</strong>
                      <span className="chip" style={{ color: ROLE_COLOR[t.role], borderColor: ROLE_COLOR[t.role] }}>{t.hierarchy ? HIER_NAME[t.hierarchy] : ROLE_NAME[t.role]}</span>
                      <span className="caption">enters in {t.enters}</span>
                    </div>
                    <div className="row">
                      <button className={`btn small ${muted.has(t.track_key) ? 'danger' : ''}`} aria-pressed={muted.has(t.track_key)} onClick={() => flip(muted, setMuted, t.track_key)} aria-label={`mute ${nameOf(t.recording_id)}`}>M</button>
                      <button className={`btn small ${solo.has(t.track_key) ? 'teal' : ''}`} aria-pressed={solo.has(t.track_key)} onClick={() => flip(solo, setSolo, t.track_key)} aria-label={`solo ${nameOf(t.recording_id)}`}>S</button>
                      <button className="btn small" onClick={() => setFocus(t.track_key)} aria-label={`inspect ${nameOf(t.recording_id)}`}>?</button>
                    </div>
                  </div>
                ))}
              </div>
              <canvas ref={canvasRef} className="timeline" onClick={onCanvasClick} role="img" aria-label={`timeline of ${events.length} events; click an event to see where it came from, or empty space to seek`} />
              <p className="caption">Each bar is a real event: a slice of one of your recordings placed on the timeline. Click one to trace it back to its source.</p>

              {trace && (
                <div className="trace" role="region" aria-label="event provenance">
                  <div className="eyebrow">Where did that sound come from?</div>
                  <p>
                    <strong>{trace.source.label ?? 'an unnamed recording'}</strong> {trace.source.exists ? '' : '(deleted)'} → {ROLE_NAME[trace.event.role]} <span className="caption">({trace.event.kind})</span><br />
                    source {trace.event.source_start_s.toFixed(2)}–{trace.event.source_end_s.toFixed(2)} s of {trace.source.duration_s?.toFixed(1)} s → placed at {trace.event.comp_start_s.toFixed(2)} s in the piece
                    {trace.event.params.pitch_shift_st ? `, pitch ${Number(trace.event.params.pitch_shift_st) > 0 ? '+' : ''}${Number(trace.event.params.pitch_shift_st).toFixed(1)} semitones` : ''}
                    {trace.event.params.rate && trace.event.params.rate !== 1 ? `, rate ×${Number(trace.event.params.rate).toFixed(2)}` : ''}, gain {Number(trace.event.params.gain_db ?? 0).toFixed(1)} dB
                    {trace.event.params.motif ? ` · motif ${String(trace.event.params.motif).split(':').pop()}${trace.event.params.variation ? ` (${trace.event.params.variation})` : ''}` : ''}
                    {trace.also_in.length ? ` · also used in ${trace.also_in.length} other composition${trace.also_in.length > 1 ? 's' : ''}` : ''}
                  </p>
                  <div className="row"><button className="btn small teal" onClick={() => onOpenSpecimen(trace.source.recording_id)} disabled={!trace.source.exists}>Open its specimen</button><button className="btn small" onClick={() => setTrace(null)}>Close</button></div>
                </div>
              )}

              {focusTrack && focusSource && (
                <div className="compare" role="region" aria-label="source comparison">
                  <div className="eyebrow">Compare · {nameOf(focusTrack.recording_id)}</div>
                  <div className="row">
                    <button className="btn small" onClick={() => void compare('original', focusTrack.track_key)}>1 · Original recording</button>
                    <button className="btn small" onClick={() => void compare('layer', focusTrack.track_key)}>2 · Transformed layer</button>
                    <button className="btn small" onClick={() => void compare('full', focusTrack.track_key)}>3 · Full composition</button>
                    <audio ref={origRef} controls preload="none" aria-label="original recording" style={{ height: 32 }} />
                  </div>
                  {focusSource.decision && (
                    <p className="caption">Why {ROLE_NAME[focusSource.decision.primary]}? {focusSource.decision.rationale}.{focusSource.decision.secondary ? ` Also suited to ${ROLE_NAME[focusSource.decision.secondary]}.` : ''}{focusSource.decision.overridden ? ' (manual choice)' : ''}</p>
                  )}
                </div>
              )}

              <div className="row" style={{ marginTop: 12 }}>
                <input className="input" style={{ marginBottom: 0, maxWidth: 220 }} value={name} onChange={(e) => setName(e.target.value)} aria-label="composition name" maxLength={80} />
                <button className="btn small" onClick={() => void save()}>{comp.saved ? '★ Saved' : 'Save'}</button>
                <a className="btn small" href={comp.export_url ?? '#'} download>Export WAV</a>
                <a className="btn small" href={`${comp.export_url}?bundle=true`} download>Export with stems &amp; plan</a>
              </div>
              {comp.metrics && (
                <p className="caption">peak {Number(comp.metrics.peak_dbfs).toFixed(1)} dBFS · ≈{Number(comp.metrics.lufs_approx).toFixed(1)} LUFS · clipping {(Number(comp.metrics.clipping_ratio) * 100).toFixed(2)} % · {events.length} events · renders offline, plays at 48 kHz</p>
              )}
              <details className="caption"><summary>How it was built</summary>
                <ul>{comp.sources.map((s) => <li key={s.recording_id}><strong>{s.label ?? s.recording_id.slice(0, 8)}</strong>: {s.decision?.rationale}{comp.tracks.some((t) => t.recording_id === s.recording_id) ? '' : ' — not used in this arrangement (the composer keeps the foreground selective)'}</li>)}</ul>
                <p>This piece contains transformed audio from your recordings, possibly including background speech. It stays on this machine unless you export it.</p>
              </details>
            </>
          )}
          {lines.length > 0 && (
            <div className="echo-log" aria-label="ECHO-0 conductor">
              {lines.map((l, i) => (
                <p className="echo" key={i} role={i === lines.length - 1 ? 'status' : undefined}><span className="tag">ECHO-0</span>{l.text.split('\n').map((x, j) => <span key={j} style={{ display: 'block' }}>{x}</span>)}<span className="prov">{l.tag}</span></p>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
