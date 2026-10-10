import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { Atlas as AtlasData, AtlasNode } from '../api/types';
import { EchoLog } from './EchoLog';
import { prefersReducedMotion } from './SignatureCanvas';
import { mulberry32 } from '../visual/prng';

interface Props {
  version: number; // bump to refetch
  onOpenSpecimen: (id: string) => void;
  onBack: () => void;
  /** M4: memories chosen for an orchestra, and the live per-recording activity while it plays */
  selection?: string[];
  onToggleSelect?: (id: string) => void;
  onCompose?: () => void;
  activityRef?: { current: Record<string, number> };
}

const STATE_TITLE: Record<AtlasData['state'], string> = {
  empty: 'Empty memory',
  first_observation: 'First observation',
  scattered: 'Scattered memories',
  emerging_relationships: 'Emerging relationships',
  learned_categories: 'Learned categories',
  new_concept: 'A new concept',
};

function hsl(h: number, s: number, l: number, a = 1): string {
  return `hsla(${h.toFixed(0)}, ${(s * 100).toFixed(0)}%, ${(l * 100).toFixed(0)}%, ${a})`;
}

/** Node glyph: a small folded outline from the node's 32-point ring + glyph params. */
function glyphPath(ctx: CanvasRenderingContext2D, n: AtlasNode, cx: number, cy: number, r: number): void {
  const rng = mulberry32(n.seed);
  const pts = 48;
  const k = Math.max(2, Math.min(8, n.glyph.symmetry_order));
  ctx.beginPath();
  for (let i = 0; i < pts; i++) {
    const th = (i / pts) * Math.PI * 2;
    const u = ((th * k) / (Math.PI * 2)) % 1;
    const idx = u * (n.ring.length - 1);
    const i0 = Math.floor(idx);
    const env = n.ring.length ? n.ring[i0] + (n.ring[Math.min(n.ring.length - 1, i0 + 1)] - n.ring[i0]) * (idx - i0) : 0.5;
    const jit = n.glyph.jitter * 0.25 * Math.sin(rng() * Math.PI * 2 + th * 7);
    const rr = r * (0.55 + 0.45 * env) * n.glyph.scale * (1 + jit);
    const x = cx + Math.cos(th) * rr;
    const y = cy + Math.sin(th) * rr;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.closePath();
}

const NO_SELECTION: string[] = [];

export function Atlas({ version, onOpenSpecimen, onBack, selection = NO_SELECTION, onToggleSelect, onCompose, activityRef }: Props) {
  const [data, setData] = useState<AtlasData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filterLabel, setFilterLabel] = useState<string>('');
  const [onlyUncertain, setOnlyUncertain] = useState(false);
  const [showMood, setShowMood] = useState(false);
  const [frameMs, setFrameMs] = useState<number | null>(null);
  const [pickMode, setPickMode] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const view = useRef({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.atlas();
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load, version]);

  const visible = useMemo(() => {
    if (!data) return new Set<string>();
    const s = new Set<string>();
    for (const n of data.nodes) {
      if (filterLabel && !n.label_ids.includes(filterLabel) && n.label !== filterLabel) continue;
      if (onlyUncertain && n.state !== 'unknown' && n.state !== 'uncertain') continue;
      s.add(n.recording_id);
    }
    return s;
  }, [data, filterLabel, onlyUncertain]);

  const toScreen = useCallback((x: number, y: number, w: number, h: number) => {
    const v = view.current;
    const base = Math.min(w, h) * 0.38 * v.k;
    return [w / 2 + v.x + x * base, h / 2 + v.y + y * base] as const;
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const t0 = performance.now();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 800;
    const h = canvas.clientHeight || 520;
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#0d0e10';
    ctx.fillRect(0, 0, w, h);
    const v = view.current;
    const base = Math.min(w, h) * 0.38 * v.k;
    // faint reference ring: "distance = how alike they sound"
    ctx.strokeStyle = 'rgba(231,227,218,0.06)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(w / 2 + v.x, h / 2 + v.y, base, 0, Math.PI * 2);
    ctx.stroke();
    const pos = new Map(data.nodes.map((n) => [n.recording_id, toScreen(n.x, n.y, w, h)] as const));
    // edges
    for (const e of data.edges) {
      if (!visible.has(e.a) || !visible.has(e.b)) continue;
      const a = pos.get(e.a);
      const b = pos.get(e.b);
      if (!a || !b) continue;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      if (e.type === 'acoustic') {
        ctx.strokeStyle = `rgba(63,167,160,${(0.15 + 0.6 * Math.max(0, (e.weight - 0.4) / 0.6)).toFixed(3)})`;
        ctx.lineWidth = 0.8 + 1.5 * Math.max(0, e.weight - 0.5);
        ctx.setLineDash([]);
      } else {
        ctx.strokeStyle = 'rgba(184,115,51,0.45)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 5]);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // anchors
    ctx.font = '11px IBM Plex Mono, monospace';
    for (const a of data.anchors) {
      const [x, y] = toScreen(a.x, a.y, w, h);
      ctx.strokeStyle = hsl(a.hue, 0.4, 0.55, 0.35);
      ctx.setLineDash([2, 4]);
      ctx.beginPath();
      ctx.arc(x, y, 10 + a.spread * base, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = hsl(a.hue, 0.5, 0.7, 0.9);
      ctx.fillText(`${a.origin === 'user' ? '✦ ' : ''}${a.name} ·${a.n}`, x + 12 + a.spread * base, y - 6);
    }
    // nodes
    for (const n of data.nodes) {
      const p = pos.get(n.recording_id);
      if (!p) continue;
      const dim = !visible.has(n.recording_id);
      const r = (10 + 10 * n.glyph.energy) * Math.sqrt(v.k);
      const hue = n.hue ?? 200;
      const sel = selected === n.recording_id;
      glyphPath(ctx, n, p[0], p[1], r);
      const alpha = dim ? 0.12 : n.state === 'unknown' ? 0.6 : n.state === 'uncertain' ? 0.75 : 1;
      ctx.fillStyle = hsl(hue, 0.45, 0.5, (n.state === 'confirmed' ? 0.28 : n.state === 'hypothesis' ? 0.16 : 0.05) * alpha);
      ctx.fill();
      ctx.setLineDash(n.state === 'unknown' ? [2, 4] : n.state === 'uncertain' ? [5, 3] : []);
      ctx.lineWidth = sel ? 2.2 : 1.1;
      ctx.strokeStyle = sel ? '#e7e3da' : hsl(hue, 0.55, 0.6, alpha);
      ctx.stroke();
      ctx.setLineDash([]);
      const act = activityRef?.current[n.recording_id] ?? 0;
      if (act > 0.02) {
        const glow = ctx.createRadialGradient(p[0], p[1], r * 0.4, p[0], p[1], r * (1.6 + 1.8 * act));
        glow.addColorStop(0, hsl(hue, 0.7, 0.6, 0.55 * Math.min(1, act * 1.4)));
        glow.addColorStop(1, hsl(hue, 0.7, 0.6, 0));
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(p[0], p[1], r * (1.6 + 1.8 * act), 0, Math.PI * 2);
        ctx.fill();
      }
      if (selection.includes(n.recording_id)) {
        ctx.strokeStyle = 'rgba(217,164,65,0.95)';
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.arc(p[0], p[1], r * 1.5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (!n.embedded) {
        ctx.strokeStyle = 'rgba(231,227,218,0.25)';
        ctx.setLineDash([1, 3]);
        ctx.beginPath();
        ctx.arc(p[0], p[1], r * 1.3, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (showMood && n.mood) {
        ctx.fillStyle = 'rgba(217,164,65,0.8)';
        ctx.font = 'italic 10px Source Serif 4, serif';
        ctx.fillText(`“${n.mood}”`, p[0] + r + 4, p[1] + r);
        ctx.font = '11px IBM Plex Mono, monospace';
      }
    }
    const dt = performance.now() - t0;
    setFrameMs((prev) => (prev === null ? dt : prev * 0.8 + dt * 0.2));
  }, [data, visible, selected, showMood, toScreen, selection, activityRef]);

  useEffect(() => {
    draw();
    const canvas = canvasRef.current;
    const ro = typeof ResizeObserver !== 'undefined' && canvas ? new ResizeObserver(() => draw()) : null;
    if (ro && canvas) ro.observe(canvas);
    return () => ro?.disconnect();
  }, [draw]);

  // follow the orchestra: redraw only when the activity actually changed
  useEffect(() => {
    if (!activityRef) return;
    let last = '';
    const id = window.setInterval(() => {
      const sig = Object.entries(activityRef.current).map(([k, v]) => `${k}${Math.round(v * 20)}`).join();
      if (sig !== last) { last = sig; draw(); }
    }, prefersReducedMotion() ? 250 : 60);
    return () => window.clearInterval(id);
  }, [activityRef, draw]);

  const hit = (clientX: number, clientY: number): AtlasNode | null => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return null;
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    let best: AtlasNode | null = null;
    let bd = 18 * Math.sqrt(view.current.k);
    for (const n of data.nodes) {
      const [px, py] = toScreen(n.x, n.y, rect.width, rect.height);
      const d = Math.hypot(px - x, py - y);
      if (d < bd) { bd = d; best = n; }
    }
    return best;
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    drag.current = { x: e.clientX, y: e.clientY, moved: false };
    (e.target as HTMLCanvasElement).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x;
    const dy = e.clientY - drag.current.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
    view.current = { ...view.current, x: view.current.x + dx, y: view.current.y + dy };
    drag.current.x = e.clientX;
    drag.current.y = e.clientY;
    draw();
  };
  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved) {
      const n = hit(e.clientX, e.clientY);
      if (pickMode && n && onToggleSelect) onToggleSelect(n.recording_id);
      else setSelected(n ? n.recording_id : null);
    }
  };
  const onWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    const k = Math.max(0.4, Math.min(4, view.current.k * (e.deltaY < 0 ? 1.1 : 0.9)));
    view.current = { ...view.current, k };
    draw();
  };

  const sel = data?.nodes.find((n) => n.recording_id === selected) ?? null;
  const labels = useMemo(() => {
    const m = new Map<string, string>();
    data?.nodes.forEach((n) => { if (n.label) m.set(n.label, n.label); });
    return Array.from(m.keys()).sort();
  }, [data]);

  return (
    <section className="atlas" aria-labelledby="atlas-h">
      <header className="specimen-head">
        <div>
          <div className="eyebrow">Acoustic atlas · distance = how alike they sound (2-D projection of a 512-d space{data?.basis ? `, keeps ${(data.basis.explained_variance_2d * 100).toFixed(0)}% of the spread` : ''})</div>
          <h2 id="atlas-h">{data ? STATE_TITLE[data.state] : 'Reconstructing…'}</h2>
        </div>
        <div className="row">
          <select className="input" style={{ width: 'auto', marginBottom: 0 }} value={filterLabel} onChange={(e) => setFilterLabel(e.target.value)} aria-label="filter by label">
            <option value="">all names</option>
            {labels.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
          <label className="check"><input type="checkbox" checked={onlyUncertain} onChange={(e) => setOnlyUncertain(e.target.checked)} /> uncertain only</label>
          <label className="check"><input type="checkbox" checked={showMood} onChange={(e) => setShowMood(e.target.checked)} /> feelings (yours)</label>
          {onToggleSelect && <button className={`btn small ${pickMode ? 'teal' : ''}`} aria-pressed={pickMode} onClick={() => setPickMode(!pickMode)}>{pickMode ? 'Choosing sounds…' : 'Choose sounds for an orchestra'}</button>}
          {onCompose && selection.length > 0 && <button className="btn small primary" onClick={onCompose}>Compose from {selection.length}</button>}
          <button className="btn small" onClick={() => { view.current = { x: 0, y: 0, k: 1 }; draw(); }}>Reset view</button>
          <button className="btn small" onClick={onBack}>Record</button>
        </div>
      </header>
      {error && <div className="error" role="alert"><span>{error}</span><button className="btn small" onClick={() => void load()}>Retry</button></div>}
      {data && <EchoLog lines={data.narrative} />}
      <div className="atlas-navigation row" aria-label="Atlas navigation">
        <label className="check">Select a memory <select className="input" style={{ width: 'auto', marginBottom: 0 }} value={selected ?? ''} onChange={e => setSelected(e.target.value || null)} aria-label="select atlas memory"><option value="">None selected</option>{data?.nodes.filter(n => visible.has(n.recording_id)).map(n => <option key={n.recording_id} value={n.recording_id}>{n.label ?? 'Unnamed'} · {n.recording_id.slice(0,8)}</option>)}</select></label>
        <button className="btn small" aria-label="zoom in atlas" onClick={() => { view.current.k = Math.min(4, view.current.k * 1.2); draw(); }}>+</button>
        <button className="btn small" aria-label="zoom out atlas" onClick={() => { view.current.k = Math.max(.4, view.current.k / 1.2); draw(); }}>−</button>
        <span className="caption">Drag to explore · scroll or use + / − to zoom · arrow keys to pan</span>
      </div>
      <div className="atlas-stage">
        <canvas ref={canvasRef} className="atlas-canvas" tabIndex={0} onKeyDown={e => { const move = { ArrowLeft: [40,0], ArrowRight: [-40,0], ArrowUp: [0,40], ArrowDown: [0,-40] }[e.key]; if (move) { e.preventDefault(); view.current.x += move[0]; view.current.y += move[1]; draw(); } }} role="img" aria-label={data ? `atlas with ${data.counts.nodes} memories and ${data.counts.edges} relationships` : 'atlas loading'} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onWheel={onWheel} />
        {data && data.nodes.length === 0 && <div className="atlas-empty">silence</div>}
        {sel && (
          <aside className="atlas-side" aria-label="selected memory">
            <div className="eyebrow">{sel.recording_id.slice(0, 8)} · {new Date(sel.captured_at).toLocaleString()}</div>
            <strong>{sel.label ?? 'Unnamed'}</strong> <span className={`chip state-${sel.state}`}>{sel.state}</span>
            <p className="caption">ears: {sel.ears_top ?? '—'} · memory-fused: {sel.fused_top ?? '—'}{sel.novel ? ' · novel' : ''}{sel.embedded ? '' : ' · no embedding (not heard)'}</p>
            {sel.descriptors.length > 0 && <p className="caption">{sel.descriptors.join(', ')}{sel.environment ? ` · ${sel.environment}` : ''}</p>}
            <p className="caption">{data!.edges.filter((e) => e.a === sel.recording_id || e.b === sel.recording_id).map((e) => `${e.type === 'acoustic' ? 'sounds like' : 'shares name with'} ${(e.a === sel.recording_id ? e.b : e.a).slice(0, 8)} (${e.weight.toFixed(2)})`).join(' · ') || 'no relationships yet'}</p>
            <button className="btn small primary" onClick={() => onOpenSpecimen(sel.recording_id)}>Open specimen</button>
          </aside>
        )}
      </div>
      {data && (
        <p className="caption" style={{ marginTop: 6 }}>
          {data.counts.nodes} memories · {data.counts.edges} relationships ({data.edges.filter((e) => e.type === 'acoustic').length} acoustic, {data.edges.filter((e) => e.type === 'shared_label').length} shared names) · {data.counts.unknown} unknown · {data.counts.uncertain} uncertain · {data.counts.custom_labels} names you invented · layout v{data.atlas_version}
          {data.basis ? ` · basis ${data.basis.frozen ? 'frozen' : 'refit'} on ${data.basis.fitted_on}` : ''}{frameMs !== null ? ` · draw ${frameMs.toFixed(1)} ms` : ''}{prefersReducedMotion() ? ' · reduced motion' : ''}
          {data.model ? ` · ears ${data.model.id.split('/')[1]}` : ''}
        </p>
      )}
    </section>
  );
}
