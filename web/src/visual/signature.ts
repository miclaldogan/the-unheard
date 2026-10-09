/**
 * Acoustic signature renderer v1 — turns server-side VisualParams into geometry and draws it.
 *
 * Everything here is a pure function of (params, seed, time). The seeded PRNG only decides
 * *where* the measured irregularity (jitter) lands, never how much of it there is.
 *
 * Grammar (see docs/visual-grammar.md):
 *  - outline radius r(θ) = base · (0.55 + 0.45·ring(θ)) folded with `symmetry_order`,
 *    jittered by `jitter`, spikes sharpened by `sharpness`
 *  - `fragmentation` opens gaps in the outline (dash pattern)
 *  - inner rings from `bands` (log-mel texture), one radial tick per onset
 *  - hue from the semantic layer only; `state` controls solidity (unknown = dashed hollow)
 *  - playback: envelope(t) scales the outline, flux(t) brightens, onsets ring briefly
 */

import type { VisualParams } from '../api/types';
import { mulberry32 } from './prng';

export interface Palette {
  graphite: string;
  copper: string;
  amber: string;
  teal: string;
  ivory: string;
}

export const PALETTE: Palette = { graphite: '#0d0e10', copper: '#b87333', amber: '#d9a441', teal: '#3fa7a0', ivory: '#e7e3da' };

export interface Point { x: number; y: number }

export interface Geometry {
  outline: Point[]; // closed polyline, unit radius ~1
  rings: { r: number; alpha: number }[];
  ticks: { angle: number; len: number }[];
  jitterPhase: number[]; // per outline point, deterministic
  spikes: number[]; // 0..1 per point
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function sample(arr: number[], u: number): number {
  if (!arr.length) return 0;
  const x = Math.min(1, Math.max(0, u)) * (arr.length - 1);
  const i = Math.floor(x);
  const f = x - i;
  return lerp(arr[i], arr[Math.min(arr.length - 1, i + 1)], f);
}

/** Deterministic base geometry (no time dependence). */
export function buildGeometry(params: VisualParams, points = 256): Geometry {
  const g = params.geometry;
  const rng = mulberry32(params.seed);
  const jitterPhase: number[] = [];
  const spikes: number[] = [];
  for (let i = 0; i < points; i++) {
    jitterPhase.push(rng() * Math.PI * 2);
    spikes.push(rng());
  }
  const n = Math.max(2, Math.min(8, g.symmetry_order));
  const outline: Point[] = [];
  for (let i = 0; i < points; i++) {
    const theta = (i / points) * Math.PI * 2;
    // fold the envelope `n` times around the circle so tonal sounds read as symmetric
    const folded = ((theta * n) / (Math.PI * 2)) % 1;
    const env = sample(g.ring, folded % 1);
    const jitter = g.jitter * 0.22 * Math.sin(jitterPhase[i] + theta * 7);
    const spike = g.sharpness * 0.25 * Math.pow(spikes[i], 6) * (spikes[i] > 0.9 ? 1 : 0);
    const r = (0.55 + 0.45 * env) * g.scale * (1 + jitter) + spike;
    outline.push({ x: Math.cos(theta) * r, y: Math.sin(theta) * r });
  }
  const rings = g.bands.map((b, i) => ({ r: 0.12 + (i / g.bands.length) * 0.4, alpha: 0.08 + 0.5 * b }));
  const ticks = g.ticks.map((t) => ({ angle: t * Math.PI * 2, len: 0.08 + 0.1 * g.energy }));
  return { outline, rings, ticks, jitterPhase, spikes };
}

export interface DrawOptions {
  size: number; // css pixels (square)
  dpr?: number;
  time?: number | null; // playback position in seconds, null = static
  reducedMotion?: boolean;
  detail?: 'full' | 'glyph';
  background?: boolean;
}

export function stateStyle(params: VisualParams): { hue: number; dash: number[]; alpha: number; fill: number } {
  const s = params.semantic;
  const hue = s.hue ?? 0;
  switch (s.state) {
    case 'unknown':
      return { hue: s.hue ?? 200, dash: [3, 6], alpha: 0.75, fill: 0.02 };
    case 'uncertain':
      return { hue, dash: [8, 4], alpha: 0.8, fill: 0.05 };
    case 'hypothesis':
      return { hue, dash: [], alpha: 0.9, fill: 0.08 };
    default:
      return { hue, dash: [], alpha: 1, fill: 0.14 };
  }
}

function hsl(h: number, s: number, l: number, a = 1): string {
  return `hsla(${h.toFixed(0)}, ${(s * 100).toFixed(0)}%, ${(l * 100).toFixed(0)}%, ${a})`;
}

/** Playback modulation derived from precomputed timelines. */
export function playbackState(params: VisualParams, time: number | null): { envelope: number; flux: number; onsetGlow: number } {
  if (time === null || time === undefined || !Number.isFinite(time)) return { envelope: 0.6, flux: 0, onsetGlow: 0 };
  const a = params.animation;
  const u = a.duration_s > 0 ? Math.max(0, Math.min(1, time / a.duration_s)) : 0;
  let onsetGlow = 0;
  for (const o of a.onsets_s) {
    const d = time - o;
    if (d >= 0 && d < 0.35) onsetGlow = Math.max(onsetGlow, 1 - d / 0.35);
  }
  return { envelope: sample(a.envelope, u), flux: sample(a.flux, u), onsetGlow };
}

export function drawSignature(ctx: CanvasRenderingContext2D, params: VisualParams, geom: Geometry, opts: DrawOptions): void {
  const { size } = opts;
  const dpr = opts.dpr ?? 1;
  const detail = opts.detail ?? 'full';
  const st = stateStyle(params);
  const pb = playbackState(params, opts.time ?? null);
  const live = opts.time !== null && opts.time !== undefined;
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (opts.background !== false) {
    ctx.fillStyle = PALETTE.graphite;
    ctx.fillRect(0, 0, size, size);
  }
  const cx = size / 2;
  const cy = size / 2;
  const R = size * 0.36;
  const breathe = live ? 0.9 + 0.2 * pb.envelope : 1;
  const resolution = params.semantic.resolution;

  if (detail === 'full') {
    // instrument markings: faint reference circle + 12 ticks
    ctx.strokeStyle = hsl(st.hue, 0.1, 0.45, 0.18);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, R * 1.12, 0, Math.PI * 2);
    ctx.stroke();
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * R * 1.12, cy + Math.sin(a) * R * 1.12);
      ctx.lineTo(cx + Math.cos(a) * R * 1.16, cy + Math.sin(a) * R * 1.16);
      ctx.stroke();
    }
    // inner texture rings (log-mel bands)
    for (const ring of geom.rings) {
      ctx.strokeStyle = hsl(st.hue, 0.35, 0.5, ring.alpha * 0.5 * st.alpha);
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.arc(cx, cy, ring.r * R * breathe, 0, Math.PI * 2);
      ctx.stroke();
    }
    // onset ticks
    for (const t of geom.ticks) {
      const glow = live ? pb.onsetGlow : 0;
      ctx.strokeStyle = hsl(st.hue + 20, 0.5, 0.6, (0.35 + 0.5 * glow) * st.alpha);
      ctx.lineWidth = 1 + glow;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(t.angle) * R * 0.98, cy + Math.sin(t.angle) * R * 0.98);
      ctx.lineTo(cx + Math.cos(t.angle) * R * (0.98 + t.len), cy + Math.sin(t.angle) * R * (0.98 + t.len));
      ctx.stroke();
    }
  }

  // outline
  ctx.beginPath();
  geom.outline.forEach((p, i) => {
    const x = cx + p.x * R * breathe;
    const y = cy + p.y * R * breathe;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.closePath();
  const light = 0.45 + 0.25 * (live ? pb.flux : 0) + 0.1 * params.geometry.sharpness;
  ctx.fillStyle = hsl(st.hue, 0.45, light, st.fill * (0.6 + resolution));
  ctx.fill();
  const frag = params.geometry.fragmentation;
  const dash = st.dash.length ? st.dash : frag > 0.35 ? [Math.max(2, 14 * (1 - frag)), 2 + 6 * frag] : [];
  ctx.setLineDash(dash);
  ctx.lineJoin = params.geometry.sharpness > 0.5 ? 'miter' : 'round';
  ctx.lineWidth = detail === 'full' ? 1.2 + 1.6 * params.geometry.energy : 1;
  ctx.strokeStyle = hsl(st.hue, 0.55, light + 0.15, st.alpha * (0.5 + 0.5 * resolution));
  ctx.stroke();
  ctx.setLineDash([]);
  if (params.semantic.state === 'unknown' && detail === 'full') {
    // second, offset dashed outline: an unresolved boundary
    ctx.strokeStyle = hsl(200, 0.3, 0.6, 0.35);
    ctx.setLineDash([2, 7]);
    ctx.beginPath();
    geom.outline.forEach((p, i) => {
      const x = cx + p.x * R * breathe * 1.06;
      const y = cy + p.y * R * breathe * 1.06;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.restore();
}

/** Static SVG export of the base outline + ticks (no animation). */
export function signatureSVG(params: VisualParams, geom: Geometry, size = 512): string {
  const st = stateStyle(params);
  const cx = size / 2;
  const R = size * 0.36;
  const pts = geom.outline.map((p) => `${(cx + p.x * R).toFixed(2)},${(cx + p.y * R).toFixed(2)}`).join(' ');
  const ticks = geom.ticks
    .map((t) => `<line x1="${(cx + Math.cos(t.angle) * R * 0.98).toFixed(2)}" y1="${(cx + Math.sin(t.angle) * R * 0.98).toFixed(2)}" x2="${(cx + Math.cos(t.angle) * R * (0.98 + t.len)).toFixed(2)}" y2="${(cx + Math.sin(t.angle) * R * (0.98 + t.len)).toFixed(2)}" stroke="${hsl(st.hue + 20, 0.5, 0.6, 0.6)}" stroke-width="1"/>`)
    .join('');
  const rings = geom.rings.map((r) => `<circle cx="${cx}" cy="${cx}" r="${(r.r * R).toFixed(2)}" fill="none" stroke="${hsl(st.hue, 0.35, 0.5, r.alpha * 0.5)}" stroke-width="0.8"/>`).join('');
  const dash = st.dash.length ? ` stroke-dasharray="${st.dash.join(' ')}"` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">` +
    `<desc>THE UNHEARD specimen · generator v${params.generator_version} · seed ${params.seed} · geometry ${params.geometry_hash.slice(0, 12)} · ${params.semantic.label ?? 'unnamed'} (${params.semantic.state})</desc>` +
    `<rect width="100%" height="100%" fill="${PALETTE.graphite}"/>${rings}${ticks}` +
    `<polygon points="${pts}" fill="${hsl(st.hue, 0.45, 0.5, st.fill)}" stroke="${hsl(st.hue, 0.55, 0.6, st.alpha)}" stroke-width="${(1.2 + 1.6 * params.geometry.energy).toFixed(2)}"${dash}/>` +
    `</svg>`;
}
