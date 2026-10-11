import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import '@fontsource/instrument-serif/latin-400.css';
import '@fontsource/instrument-serif/latin-400-italic.css';
import '@fontsource/space-grotesk/latin-500.css';
import '@fontsource/space-grotesk/latin-700.css';
import {C, FPS, LINES, H, W} from './theme';

export const F = {serif: "'Instrument Serif', serif", sans: "'Space Grotesk', sans-serif"};

export const fade = (frame: number, from: number, dur: number, inF = 12, outF = 12) =>
  interpolate(frame, [from, from + inF, from + dur - outF, from + dur], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

/** A screenshot that slowly pushes toward a point. cx/cy are image-pixel coordinates (of the 2400-wide image). */
export const Shot: React.FC<{
  src: string;
  imgW: number; // natural width
  showW: number; // displayed width at zoom 1
  from: {cx: number; cy: number; z: number};
  to: {cx: number; cy: number; z: number};
  dur: number;
  radius?: number;
}> = ({src, imgW, showW, from, to, dur, radius = 14}) => {
  const f = useCurrentFrame();
  const p = interpolate(f, [0, dur], [0, 1], {easing: Easing.inOut(Easing.cubic), extrapolateRight: 'clamp'});
  const cx = from.cx + (to.cx - from.cx) * p;
  const cy = from.cy + (to.cy - from.cy) * p;
  const z = from.z + (to.z - from.z) * p;
  const k = (showW / imgW) * z; // image px -> screen px
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Img
        src={staticFile(src)}
        style={{
          position: 'absolute',
          width: imgW * k,
          left: W / 2 - cx * k,
          top: H / 2 - cy * k,
          borderRadius: radius,
          boxShadow: '0 30px 120px rgba(0,0,0,.65)',
        }}
      />
    </AbsoluteFill>
  );
};

export const Vignette: React.FC = () => (
  <AbsoluteFill
    style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,.72) 100%)', pointerEvents: 'none'}}
  />
);

export const Caption: React.FC = () => {
  const f = useCurrentFrame();
  const line = LINES.find((l) => f >= (l.t - 0.1) * FPS && f <= (l.t + l.d + 0.3) * FPS);
  if (!line) return null;
  const a = fade(f, (line.t - 0.1) * FPS, (line.d + 0.4) * FPS, 6, 8);
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 64, display: 'flex', justifyContent: 'center', opacity: a}}>
      <div
        style={{
          fontFamily: F.sans,
          fontWeight: 500,
          fontSize: 36,
          color: C.ink,
          background: 'rgba(8,10,9,.78)',
          padding: '14px 28px',
          borderRadius: 10,
          maxWidth: 1500,
          textAlign: 'center',
          lineHeight: 1.3,
        }}
      >
        {line.text}
      </div>
    </div>
  );
};

export const Tag: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
  <div
    style={{
      fontFamily: F.sans,
      fontWeight: 700,
      fontSize: 22,
      letterSpacing: 4,
      textTransform: 'uppercase',
      color: C.amber,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Stat: React.FC<{label: string; value: string; sub: string; color: string; style?: React.CSSProperties}> = ({
  label,
  value,
  sub,
  color,
  style,
}) => (
  <div
    style={{
      background: 'rgba(11,14,13,.92)',
      border: `2px solid ${color}`,
      borderRadius: 14,
      padding: '18px 28px',
      width: 400,
      ...style,
    }}
  >
    <div style={{fontFamily: F.sans, fontWeight: 700, fontSize: 20, letterSpacing: 3, color, textTransform: 'uppercase'}}>{label}</div>
    <div style={{fontFamily: F.serif, fontSize: 84, color: C.ink, lineHeight: 1.05}}>{value}</div>
    <div style={{fontFamily: F.sans, fontWeight: 500, fontSize: 26, color: C.dim}}>{sub}</div>
  </div>
);
