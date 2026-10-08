import { useEffect, useRef } from 'react';
import type { Features } from '../api/types';

/** Draws the server-computed min/max/rms buckets (no client-side DSP). */
export function Waveform({ wave, onsets }: { wave: Features['waveform']; onsets: number[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth || 600;
    const h = 140;
    c.width = Math.floor(w * dpr);
    c.height = Math.floor(h * dpr);
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.fillStyle = '#0d0e10';
    ctx.fillRect(0, 0, w, h);
    const mid = h / 2;
    ctx.strokeStyle = '#2c3035';
    ctx.beginPath();
    ctx.moveTo(0, mid);
    ctx.lineTo(w, mid);
    ctx.stroke();
    const n = wave.min.length;
    const bw = w / n;
    ctx.fillStyle = '#7a4c22';
    for (let i = 0; i < n; i++) {
      const y1 = mid - wave.max[i] * (mid - 2);
      const y2 = mid - wave.min[i] * (mid - 2);
      ctx.fillRect(i * bw, y1, Math.max(1, bw), Math.max(1, y2 - y1));
    }
    ctx.fillStyle = '#b87333';
    for (let i = 0; i < n; i++) {
      const r = wave.rms[i] * (mid - 2);
      ctx.fillRect(i * bw, mid - r, Math.max(1, bw), Math.max(1, 2 * r));
    }
    ctx.strokeStyle = 'rgba(63,167,160,0.8)';
    for (const t of onsets) {
      const x = (t / wave.duration_s) * w;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 10);
      ctx.stroke();
    }
  }, [wave, onsets]);
  return <canvas ref={ref} className="viz" role="img" aria-label={`waveform, ${wave.duration_s.toFixed(2)} seconds, ${onsets.length} onsets`} style={{ height: 140 }} />;
}
