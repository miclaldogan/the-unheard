import { fetchAudio } from '../api/client';
import type { CompositionEvent } from '../api/types';

/** The subset of HTMLAudioElement that the specimen canvas needs to follow a clock. */
export interface AudioLike {
  readonly paused: boolean;
  readonly ended: boolean;
  readonly currentTime: number;
  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
}

/** Mute/solo → gain per track. Solo wins over mute; any solo silences every other track. */
export function effectiveGains(keys: string[], muted: ReadonlySet<string>, solo: ReadonlySet<string>): Record<string, number> {
  const out: Record<string, number> = {};
  const anySolo = keys.some((k) => solo.has(k));
  for (const k of keys) out[k] = anySolo ? (solo.has(k) ? 1 : 0) : muted.has(k) ? 0 : 1;
  return out;
}

/** Envelope (0…1) of one event at composition time t (0 when it is not sounding). */
export function eventLevel(e: CompositionEvent, t: number): number {
  const end = e.comp_start_s + e.comp_dur_s;
  if (t < e.comp_start_s || t >= end) return 0;
  const age = t - e.comp_start_s;
  if (e.kind === 'slice') return Math.exp(-age / Math.max(0.12, e.comp_dur_s * 0.45));
  const fi = Number(e.params.fade_in_s ?? 0.5);
  const fo = Number(e.params.fade_out_s ?? 0.5);
  const up = fi > 0 ? Math.min(1, age / fi) : 1;
  const down = fo > 0 ? Math.min(1, (end - t) / fo) : 1;
  return 0.6 * Math.min(up, down);
}

/** Activity per recording at time t, scaled by the live track gains (muted layers are dark). */
export function activityAt(
  events: CompositionEvent[],
  t: number,
  gains: Record<string, number>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const e of events) {
    if (t < e.comp_start_s || t >= e.comp_start_s + e.comp_dur_s) continue;
    const lv = eventLevel(e, t) * (gains[e.track_key] ?? 1);
    if (lv > (out[e.recording_id] ?? 0)) out[e.recording_id] = lv;
  }
  return out;
}

/** The excerpt of the *source recording* being heard at composition time t, if any. */
export function sourceTimeAt(events: CompositionEvent[], recordingId: string, t: number): number | null {
  let best: CompositionEvent | null = null;
  for (const e of events) {
    if (e.recording_id !== recordingId || t < e.comp_start_s || t >= e.comp_start_s + e.comp_dur_s) continue;
    if (!best || e.comp_start_s > best.comp_start_s) best = e;
  }
  if (!best) return null;
  const rate = Number(best.params.rate ?? 1);
  const span = best.source_end_s - best.source_start_s;
  const s = (t - best.comp_start_s) * rate;
  return best.source_start_s + (best.kind === 'loop' ? s % Math.max(span, 1e-3) : Math.min(s, span));
}

export interface PlayerContext {
  readonly currentTime: number;
  readonly state: string;
  readonly destination: unknown;
  resume(): Promise<void>;
  close(): Promise<void>;
  decodeAudioData(data: ArrayBuffer): Promise<AudioBuffer>;
  createGain(): GainNode;
  createBufferSource(): AudioBufferSourceNode;
}
export type ContextFactory = () => PlayerContext;
export type AudioFetcher = (url: string) => Promise<ArrayBuffer>;

/**
 * Multi-stem player on the Web Audio clock. Stems start together at one context time, so
 * mute/solo are instantaneous gain changes and `currentTime` is authoritative for visuals.
 * Behaves like a media element for listeners: 'play' | 'pause' | 'ended' | 'seeked'.
 */
export class OrchestraPlayer extends EventTarget implements AudioLike {
  paused = true;
  ended = false;
  duration = 0;
  private ctx: PlayerContext | null = null;
  private buffers = new Map<string, AudioBuffer>();
  private gains = new Map<string, GainNode>();
  private sources: AudioBufferSourceNode[] = [];
  private startedAt = 0;
  private offset = 0;
  private target: Record<string, number> = {};
  private endTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly makeContext: ContextFactory = () => new AudioContext() as unknown as PlayerContext,
    private readonly fetcher: AudioFetcher = fetchAudio,
  ) {
    super();
  }

  get currentTime(): number {
    if (this.paused || !this.ctx) return this.offset;
    return Math.min(this.duration, this.offset + (this.ctx.currentTime - this.startedAt));
  }

  /** Download + decode every stem. Resolves when playback can start. */
  async load(tracks: { key: string; url: string }[], duration: number): Promise<void> {
    this.stop();
    this.duration = duration;
    this.buffers.clear();
    this.ctx ??= this.makeContext();
    const ctx = this.ctx;
    await Promise.all(
      tracks.map(async (t) => {
        const raw = await this.fetcher(t.url);
        this.buffers.set(t.key, await ctx.decodeAudioData(raw));
      }),
    );
    this.target = Object.fromEntries(tracks.map((t) => [t.key, 1]));
  }

  get loaded(): boolean {
    return this.buffers.size > 0;
  }

  setGains(g: Record<string, number>): void {
    this.target = { ...g };
    for (const [k, node] of this.gains) {
      const v = g[k] ?? 1;
      const c = this.ctx;
      if (c && 'gain' in node && node.gain.setTargetAtTime) node.gain.setTargetAtTime(v, c.currentTime, 0.015);
      else node.gain.value = v;
    }
  }

  async play(): Promise<void> {
    if (!this.ctx || !this.loaded) return;
    if (this.ended || this.offset >= this.duration - 0.01) this.offset = 0;
    await this.ctx.resume();
    this.startSources(this.offset);
    this.paused = false;
    this.ended = false;
    this.dispatchEvent(new Event('play'));
  }

  pause(): void {
    if (this.paused) return;
    this.offset = this.currentTime;
    this.haltSources();
    this.paused = true;
    this.dispatchEvent(new Event('pause'));
  }

  stop(): void {
    const wasPlaying = !this.paused;
    this.haltSources();
    this.paused = true;
    this.ended = false;
    this.offset = 0;
    if (wasPlaying) this.dispatchEvent(new Event('pause'));
    this.dispatchEvent(new Event('seeked'));
  }

  seek(t: number): void {
    const clamped = Math.max(0, Math.min(this.duration, t));
    const wasPlaying = !this.paused;
    this.haltSources();
    this.offset = clamped;
    this.ended = false;
    if (wasPlaying && this.ctx) this.startSources(clamped);
    this.dispatchEvent(new Event('seeked'));
  }

  async dispose(): Promise<void> {
    this.haltSources();
    this.paused = true;
    await this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    this.buffers.clear();
  }

  private startSources(from: number): void {
    const ctx = this.ctx!;
    this.haltSources();
    this.startedAt = ctx.currentTime;
    this.offset = from;
    for (const [key, buf] of this.buffers) {
      const src = ctx.createBufferSource();
      const g = ctx.createGain();
      g.gain.value = this.target[key] ?? 1;
      src.buffer = buf;
      src.connect(g);
      g.connect(ctx.destination as AudioNode);
      src.start(0, Math.min(from, Math.max(0, buf.duration - 0.001)));
      this.sources.push(src);
      this.gains.set(key, g);
    }
    const remaining = Math.max(0, this.duration - from);
    this.endTimer = setTimeout(() => this.finish(), remaining * 1000 + 30);
  }

  private haltSources(): void {
    if (this.endTimer) clearTimeout(this.endTimer);
    this.endTimer = null;
    for (const s of this.sources) {
      try { s.stop(); s.disconnect(); } catch { /* already stopped */ }
    }
    this.sources = [];
    this.gains.clear();
  }

  private finish(): void {
    if (this.paused) return;
    this.haltSources();
    this.paused = true;
    this.ended = true;
    this.offset = this.duration;
    this.dispatchEvent(new Event('ended'));
  }
}

/** A per-recording clock: reports the position inside the *source* excerpt that is sounding. */
export class SourceClock implements AudioLike {
  private last = 0;
  constructor(
    private readonly player: OrchestraPlayer,
    private readonly events: CompositionEvent[],
    private readonly recordingId: string,
  ) {}
  get paused(): boolean { return this.player.paused; }
  get ended(): boolean { return this.player.ended; }
  get currentTime(): number {
    const s = sourceTimeAt(this.events, this.recordingId, this.player.currentTime);
    if (s !== null) this.last = s;
    return this.last;
  }
  addEventListener(type: string, l: EventListenerOrEventListenerObject): void { this.player.addEventListener(type, l); }
  removeEventListener(type: string, l: EventListenerOrEventListenerObject): void { this.player.removeEventListener(type, l); }
}
