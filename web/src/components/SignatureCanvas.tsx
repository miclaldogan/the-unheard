import { useEffect, useMemo, useRef } from 'react';
import type { VisualParams } from '../api/types';
import type { AudioLike } from '../audio/orchestra';
import { buildGeometry, drawSignature } from '../visual/signature';

interface Props {
  params: VisualParams;
  size?: number; // css px; defaults to container width
  /** audio element to synchronise with (currentTime while playing) */
  audio?: AudioLike | null;
  detail?: 'full' | 'glyph';
  className?: string;
  ariaLabel?: string;
}

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/** Draws the signature; animates only while the linked audio element is playing. */
export function SignatureCanvas({ params, size, audio, detail = 'full', className, ariaLabel }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const geom = useMemo(() => buildGeometry(params, detail === 'glyph' ? 64 : 256), [params, detail]);
  const reduced = prefersReducedMotion();

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    let raf = 0;
    let disposed = false;
    const render = (time: number | null) => {
      const css = size ?? Math.max(120, canvas.clientWidth || 320);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      if (canvas.width !== Math.floor(css * dpr)) {
        canvas.width = Math.floor(css * dpr);
        canvas.height = Math.floor(css * dpr);
      }
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      drawSignature(ctx, params, geom, { size: css, dpr, time, detail });
    };
    const tick = () => {
      if (disposed) return;
      if (audio && !audio.paused && !audio.ended) {
        render(reduced ? null : audio.currentTime);
        raf = requestAnimationFrame(tick);
      } else {
        render(audio && audio.currentTime > 0 && !reduced ? audio.currentTime : null);
        raf = 0;
      }
    };
    render(null);
    const onPlay = () => { if (!raf) raf = requestAnimationFrame(tick); };
    const onStop = () => { render(audio && !reduced ? audio.currentTime : null); };
    audio?.addEventListener('play', onPlay);
    audio?.addEventListener('pause', onStop);
    audio?.addEventListener('ended', onStop);
    audio?.addEventListener('seeked', onStop);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => render(null)) : null;
    if (ro && !size) ro.observe(canvas);
    return () => {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      audio?.removeEventListener('play', onPlay);
      audio?.removeEventListener('pause', onStop);
      audio?.removeEventListener('ended', onStop);
      audio?.removeEventListener('seeked', onStop);
      ro?.disconnect();
    };
  }, [params, geom, audio, size, detail, reduced]);

  return <canvas ref={ref} className={className ?? 'signature'} role="img" aria-label={ariaLabel ?? `acoustic signature, ${params.semantic.label ?? 'unnamed'}, ${params.semantic.state}`} style={size ? { width: size, height: size } : undefined} />;
}
