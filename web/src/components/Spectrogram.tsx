import { useEffect, useRef } from 'react';
import type { Spectrogram as SpecData } from '../api/types';

// Copper → teal scientific ramp on graphite; dB mapped between the clip's 2nd and 99.5th percentile.
function ramp(t: number): [number, number, number] {
  const stops: [number, [number, number, number]][] = [
    [0, [13, 14, 16]],
    [0.35, [58, 42, 30]],
    [0.6, [184, 115, 51]],
    [0.8, [217, 164, 65]],
    [1, [63, 167, 160]],
  ];
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, a] = stops[i - 1];
      const [t1, b] = stops[i];
      const u = (t - t0) / (t1 - t0);
      return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
    }
  }
  return stops[stops.length - 1][1];
}

function percentile(sorted: Float64Array, p: number): number {
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(p * (sorted.length - 1))))];
}

export function Spectrogram({ data }: { data: SpecData }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const { n_bins, n_frames, values } = data;
    if (!n_bins || !n_frames) return;
    const flat = new Float64Array(n_bins * n_frames);
    let k = 0;
    for (const row of values) for (const v of row) flat[k++] = v;
    const sorted = flat.slice().sort();
    const lo = percentile(sorted, 0.02);
    const hi = Math.max(percentile(sorted, 0.995), lo + 1e-6);
    const img = new ImageData(n_frames, n_bins);
    for (let b = 0; b < n_bins; b++) {
      const y = n_bins - 1 - b; // low frequencies at the bottom
      for (let t = 0; t < n_frames; t++) {
        const v = Math.min(1, Math.max(0, (values[b][t] - lo) / (hi - lo)));
        const [r, g, bl] = ramp(v);
        const i = (y * n_frames + t) * 4;
        img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = bl; img.data[i + 3] = 255;
      }
    }
    const off = document.createElement('canvas');
    off.width = n_frames;
    off.height = n_bins;
    off.getContext('2d')!.putImageData(img, 0, 0);
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth || 600;
    const h = 220;
    c.width = Math.floor(w * dpr);
    c.height = Math.floor(h * dpr);
    const ctx = c.getContext('2d')!;
    ctx.imageSmoothingEnabled = false;
    ctx.scale(dpr, dpr);
    ctx.drawImage(off, 0, 0, w, h);
    // frequency ticks
    ctx.fillStyle = 'rgba(231,227,218,0.7)';
    ctx.font = '10px IBM Plex Mono, monospace';
    const ticks = data.kind === 'mel' ? [100, 500, 1000, 4000, 10000] : [1000, 5000, 10000, 20000];
    const fmax = data.freqs_hz[data.freqs_hz.length - 1];
    for (const f of ticks) {
      if (f > fmax) continue;
      // find nearest bin index
      let idx = 0;
      for (let i = 0; i < data.freqs_hz.length; i++) if (Math.abs(data.freqs_hz[i] - f) < Math.abs(data.freqs_hz[idx] - f)) idx = i;
      const y = h - ((idx + 0.5) / n_bins) * h;
      ctx.fillRect(0, y, 6, 1);
      ctx.fillText(f >= 1000 ? `${f / 1000}k` : `${f}`, 8, y + 3);
    }
  }, [data]);
  return (
    <canvas
      ref={ref}
      className="viz"
      role="img"
      aria-label={`${data.kind === 'mel' ? 'log-mel' : 'STFT'} spectrogram, ${data.n_bins} bands, ${data.n_frames} frames, ${data.min_db.toFixed(0)} to ${data.max_db.toFixed(0)} dB`}
      style={{ height: 220 }}
    />
  );
}
