/**
 * Microphone capture.
 *
 * Primary path (ADR-010): getUserMedia → AudioWorklet → Float32 PCM → 16-bit WAV at the
 * device's native sample rate. Lossless w.r.t. what the browser gives us.
 * Fallback: MediaRecorder (webm/opus on Chrome/Firefox, mp4/aac on Safari) when
 * AudioWorklet is unavailable or fails to load.
 */

import { encodeWav16 } from './wav';

export type CaptureMethod = 'audioworklet-wav' | 'mediarecorder';

export interface CaptureResult {
  blob: Blob;
  filename: string;
  method: CaptureMethod;
  mimeType: string;
  sampleRate: number | null;
  durationMs: number;
  constraintsHonored: Record<string, boolean | undefined>;
}

export interface LevelProbe {
  /** RMS level of the latest audio block, 0..1 */
  level: number;
  peak: number;
}

const AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: false,
  channelCount: 1,
};

/** Keep at most `maxSamples` samples (the recorder may overrun the limit by one block). */
export function trimChunks(chunks: Float32Array[], maxSamples: number): Float32Array[] {
  const out: Float32Array[] = [];
  let n = 0;
  for (const c of chunks) {
    if (n >= maxSamples) break;
    const keep = Math.min(c.length, maxSamples - n);
    out.push(keep === c.length ? c : c.subarray(0, keep));
    n += keep;
  }
  return out;
}

export function isSecureForMic(): boolean {
  return typeof window !== 'undefined' && (window.isSecureContext || location.hostname === 'localhost');
}

export function hasGetUserMedia(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

export class Recorder {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private media: MediaRecorder | null = null;
  private chunks: Float32Array[] = [];
  private mediaChunks: Blob[] = [];
  private startedAt = 0;
  private method: CaptureMethod = 'audioworklet-wav';
  private sampleRate: number | null = null;
  private probe: LevelProbe = { level: 0, peak: 0 };
  private maxMs: number;

  onLevel: ((p: LevelProbe) => void) | null = null;
  onAutoStop: (() => void) | null = null;
  private autoStopTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: { maxMs?: number } = {}) {
    this.maxMs = opts.maxMs ?? 30_000;
  }

  /** Ask for the microphone. Throws DOMException (NotAllowedError, NotFoundError, …). */
  async requestPermission(): Promise<MediaStream> {
    if (!hasGetUserMedia()) throw new Error('getUserMedia is not available in this browser');
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: AUDIO_CONSTRAINTS, video: false });
    return this.stream;
  }

  constraintsHonored(): Record<string, boolean | undefined> {
    const t = this.stream?.getAudioTracks()[0];
    const s = t?.getSettings() ?? {};
    return {
      echoCancellation: s.echoCancellation,
      noiseSuppression: s.noiseSuppression,
      autoGainControl: s.autoGainControl,
    };
  }

  async start(): Promise<CaptureMethod> {
    if (!this.stream) await this.requestPermission();
    const stream = this.stream!;
    this.chunks = [];
    this.mediaChunks = [];
    this.startedAt = performance.now();
    try {
      await this.startWorklet(stream);
      this.method = 'audioworklet-wav';
    } catch (e) {
      console.warn('[recorder] AudioWorklet unavailable, falling back to MediaRecorder', e);
      await this.teardownAudioGraph();
      this.startMediaRecorder(stream);
      this.method = 'mediarecorder';
    }
    // MediaRecorder cannot be trimmed afterwards, so stop it slightly early; the
    // AudioWorklet path is trimmed to exactly maxMs samples in stop().
    const stopAt = this.method === 'mediarecorder' ? Math.max(1000, this.maxMs - 500) : this.maxMs;
    this.autoStopTimer = setTimeout(() => this.onAutoStop?.(), stopAt);
    return this.method;
  }

  private async startWorklet(stream: MediaStream): Promise<void> {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) throw new Error('AudioContext unavailable');
    this.ctx = new Ctx();
    if (!this.ctx.audioWorklet) throw new Error('AudioWorklet unavailable');
    if (this.ctx.state === 'suspended') await this.ctx.resume();
    await this.ctx.audioWorklet.addModule(new URL('./capture-worklet.ts', import.meta.url));
    this.sampleRate = this.ctx.sampleRate;
    const source = this.ctx.createMediaStreamSource(stream);
    this.node = new AudioWorkletNode(this.ctx, 'unheard-capture', { numberOfInputs: 1, numberOfOutputs: 0 });
    this.node.port.onmessage = (e: MessageEvent<{ samples: Float32Array }>) => {
      const s = e.data.samples;
      this.chunks.push(s);
      let sum = 0;
      let peak = 0;
      for (let i = 0; i < s.length; i++) {
        const v = s[i];
        sum += v * v;
        const a = Math.abs(v);
        if (a > peak) peak = a;
      }
      this.probe = { level: Math.sqrt(sum / Math.max(1, s.length)), peak };
      this.onLevel?.(this.probe);
    };
    source.connect(this.node);
  }

  private startMediaRecorder(stream: MediaStream): void {
    if (typeof MediaRecorder === 'undefined') throw new Error('Neither AudioWorklet nor MediaRecorder is available');
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
    const mimeType = candidates.find((m) => MediaRecorder.isTypeSupported?.(m));
    this.media = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    this.media.ondataavailable = (e) => {
      if (e.data.size > 0) this.mediaChunks.push(e.data);
    };
    this.media.start(250);
  }

  async stop(): Promise<CaptureResult> {
    if (this.autoStopTimer) clearTimeout(this.autoStopTimer);
    const durationMs = performance.now() - this.startedAt;
    const honored = this.constraintsHonored();
    let result: CaptureResult;
    if (this.method === 'audioworklet-wav') {
      this.node?.port.postMessage('stop');
      await this.teardownAudioGraph();
      const sr = this.sampleRate ?? 48000;
      const chunks = trimChunks(this.chunks, Math.floor((this.maxMs / 1000) * sr));
      const samples = chunks.reduce((n, c) => n + c.length, 0);
      const blob = encodeWav16(chunks, sr);
      result = { blob, filename: `recording-${Date.now()}.wav`, method: this.method, mimeType: 'audio/wav', sampleRate: sr, durationMs: (samples / sr) * 1000, constraintsHonored: honored };
    } else {
      const media = this.media!;
      const blob = await new Promise<Blob>((resolve) => {
        media.onstop = () => resolve(new Blob(this.mediaChunks, { type: media.mimeType }));
        media.stop();
      });
      const ext = media.mimeType.includes('mp4') ? 'm4a' : media.mimeType.includes('ogg') ? 'ogg' : 'webm';
      result = { blob, filename: `recording-${Date.now()}.${ext}`, method: this.method, mimeType: media.mimeType, sampleRate: null, durationMs, constraintsHonored: honored };
    }
    this.releaseStream();
    this.chunks = [];
    this.mediaChunks = [];
    return result;
  }

  /** Abort without producing a file. */
  async cancel(): Promise<void> {
    if (this.autoStopTimer) clearTimeout(this.autoStopTimer);
    this.node?.port.postMessage('stop');
    await this.teardownAudioGraph();
    if (this.media && this.media.state !== 'inactive') this.media.stop();
    this.media = null;
    this.releaseStream();
    this.chunks = [];
    this.mediaChunks = [];
  }

  private async teardownAudioGraph(): Promise<void> {
    try {
      this.node?.disconnect();
    } catch {
      /* ignore */
    }
    this.node = null;
    if (this.ctx) {
      try {
        await this.ctx.close();
      } catch {
        /* ignore */
      }
    }
    this.ctx = null;
  }

  private releaseStream(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }
}
