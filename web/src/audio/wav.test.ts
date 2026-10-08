import { describe, expect, it } from 'vitest';
import { encodeWav16 } from './wav';
import { trimChunks } from './recorder';

describe('encodeWav16', () => {
  it('writes a valid 16-bit mono RIFF header and clamps samples', async () => {
    const blob = encodeWav16([new Float32Array([0, 0.5, -0.5, 2, -2])], 48000);
    const buf = new DataView(await blob.arrayBuffer());
    const str = (o: number, n: number) => String.fromCharCode(...new Uint8Array(buf.buffer, o, n));
    expect(str(0, 4)).toBe('RIFF');
    expect(str(8, 4)).toBe('WAVE');
    expect(buf.getUint16(20, true)).toBe(1);
    expect(buf.getUint16(22, true)).toBe(1);
    expect(buf.getUint32(24, true)).toBe(48000);
    expect(buf.getUint16(34, true)).toBe(16);
    expect(buf.getUint32(40, true)).toBe(10);
    expect(buf.getInt16(44, true)).toBe(0);
    expect(buf.getInt16(46, true)).toBe(Math.round(0.5 * 0x7fff));
    expect(buf.getInt16(48, true)).toBe(-0x4000);
    expect(buf.getInt16(50, true)).toBe(0x7fff);
    expect(buf.getInt16(52, true)).toBe(-0x8000);
    expect(blob.type).toBe('audio/wav');
  });
});

describe('trimChunks', () => {
  it('keeps exactly maxSamples across chunk boundaries', () => {
    const chunks = [new Float32Array(128), new Float32Array(128), new Float32Array(128)];
    const out = trimChunks(chunks, 300);
    expect(out.reduce((n, c) => n + c.length, 0)).toBe(300);
    expect(out.length).toBe(3);
    expect(trimChunks(chunks, 1000).reduce((n, c) => n + c.length, 0)).toBe(384);
  });
});
