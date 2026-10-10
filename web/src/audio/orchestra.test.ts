import { describe, expect, it, vi } from "vitest";
import type { CompositionEvent } from "../api/types";
import {
  OrchestraPlayer,
  SourceClock,
  activityAt,
  effectiveGains,
  eventLevel,
  sourceTimeAt,
  type PlayerContext,
} from "./orchestra";

const ev = (o: Partial<CompositionEvent>): CompositionEvent => ({
  seq: 0,
  track_key: "t1",
  recording_id: "r1",
  kind: "slice",
  role: "percussion",
  section: "discovery",
  comp_start_s: 1,
  comp_dur_s: 0.5,
  source_start_s: 2,
  source_end_s: 2.5,
  params: { rate: 1 },
  ...o,
});

describe("mute / solo", () => {
  const keys = ["t1", "t2", "t3"];
  it("is all on by default and mute silences only that track", () => {
    expect(effectiveGains(keys, new Set(), new Set())).toEqual({
      t1: 1,
      t2: 1,
      t3: 1,
    });
    expect(effectiveGains(keys, new Set(["t2"]), new Set())).toEqual({
      t1: 1,
      t2: 0,
      t3: 1,
    });
  });
  it("solo isolates and wins over mute", () => {
    expect(effectiveGains(keys, new Set(), new Set(["t3"]))).toEqual({
      t1: 0,
      t2: 0,
      t3: 1,
    });
    expect(
      effectiveGains(keys, new Set(["t3"]), new Set(["t3", "t1"])),
    ).toEqual({ t1: 1, t2: 0, t3: 1 });
  });
});

describe("timeline activity (driven by real events)", () => {
  it("slices decay, loops fade in and out, nothing outside the event window", () => {
    const s = ev({});
    expect(eventLevel(s, 0.9)).toBe(0);
    expect(eventLevel(s, 1.0)).toBeCloseTo(1);
    expect(eventLevel(s, 1.3)).toBeLessThan(eventLevel(s, 1.05));
    expect(eventLevel(s, 1.5)).toBe(0);
    const l = ev({
      kind: "loop",
      comp_start_s: 0,
      comp_dur_s: 10,
      params: { fade_in_s: 2, fade_out_s: 2 },
    });
    expect(eventLevel(l, 0.5)).toBeLessThan(eventLevel(l, 5));
    expect(eventLevel(l, 9.5)).toBeLessThan(eventLevel(l, 5));
  });
  it("muted layers are dark and the loudest event per recording wins", () => {
    const events = [
      ev({ seq: 1 }),
      ev({ seq: 2, track_key: "t2", recording_id: "r2", comp_start_s: 1 }),
    ];
    expect(
      Object.keys(activityAt(events, 1.01, { t1: 1, t2: 1 })).sort(),
    ).toEqual(["r1", "r2"]);
    expect(activityAt(events, 1.01, { t1: 0, t2: 1 }).r1 ?? 0).toBe(0);
    expect(activityAt(events, 3, { t1: 1, t2: 1 })).toEqual({});
  });
  it("maps composition time to the position inside the source excerpt", () => {
    const e = ev({ params: { rate: 2 } });
    expect(sourceTimeAt([e], "r1", 1.1)).toBeCloseTo(2.2);
    expect(sourceTimeAt([e], "r1", 5)).toBeNull();
    expect(sourceTimeAt([e], "other", 1.1)).toBeNull();
    const loop = ev({
      kind: "loop",
      comp_start_s: 0,
      comp_dur_s: 20,
      source_start_s: 1,
      source_end_s: 3,
      params: { rate: 1 },
    });
    expect(sourceTimeAt([loop], "r1", 5)).toBeCloseTo(2); // wraps inside the 2 s window
  });
});

function fakeContext() {
  const state = {
    now: 0,
    started: [] as { key: number; offset: number }[],
    stopped: 0,
    resumed: 0,
    gains: [] as { value: number }[],
  };
  const ctx = {
    get currentTime() {
      return state.now;
    },
    state: "running",
    destination: {},
    resume: vi.fn(async () => {
      state.resumed++;
    }),
    close: vi.fn(async () => undefined),
    decodeAudioData: vi.fn(
      async (b: ArrayBuffer) =>
        ({ duration: 10, byteLength: b.byteLength }) as unknown as AudioBuffer,
    ),
    createGain: () => {
      const g = { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() };
      state.gains.push(g.gain);
      return g as unknown as GainNode;
    },
    createBufferSource: () => {
      let id = state.started.length;
      return {
        buffer: null,
        connect: vi.fn(),
        disconnect: vi.fn(),
        stop: () => {
          state.stopped++;
        },
        start: (_w: number, offset: number) => {
          state.started.push({ key: id++, offset });
        },
      } as unknown as AudioBufferSourceNode;
    },
  };
  return { ctx: ctx as unknown as PlayerContext, state };
}

describe("OrchestraPlayer", () => {
  const tracks = [
    { key: "t1", url: "/a" },
    { key: "t2", url: "/b" },
  ];
  const fetcher = async () => new ArrayBuffer(8);

  it("loads stems, plays them from one clock, pauses and resumes where it left off", async () => {
    const { ctx, state } = fakeContext();
    const p = new OrchestraPlayer(() => ctx, fetcher);
    await p.load(tracks, 10);
    expect(p.loaded).toBe(true);
    const events: string[] = [];
    ["play", "pause", "ended", "seeked"].forEach((n) =>
      p.addEventListener(n, () => events.push(n)),
    );
    await p.play();
    expect(p.paused).toBe(false);
    expect(state.started).toHaveLength(2);
    expect(state.started.every((s) => s.offset === 0)).toBe(true);
    state.now = 3;
    expect(p.currentTime).toBeCloseTo(3);
    p.pause();
    expect(p.paused).toBe(true);
    expect(p.currentTime).toBeCloseTo(3);
    state.now = 9; // time passing while paused must not move the playhead
    expect(p.currentTime).toBeCloseTo(3);
    await p.play();
    expect(
      state.started.slice(2).every((s) => Math.abs(s.offset - 3) < 1e-6),
    ).toBe(true);
    expect(events).toEqual(["play", "pause", "play"]);
    await p.dispose();
  });

  it("seeks while playing and while paused", async () => {
    const { ctx, state } = fakeContext();
    const p = new OrchestraPlayer(() => ctx, fetcher);
    await p.load(tracks, 10);
    p.seek(4);
    expect(p.currentTime).toBe(4);
    await p.play();
    expect(state.started.slice(0, 2).every((s) => s.offset === 4)).toBe(true);
    state.now = 1;
    p.seek(8);
    expect(state.started.slice(2).every((s) => s.offset === 8)).toBe(true);
    p.seek(99);
    expect(p.currentTime).toBeLessThanOrEqual(10);
    await p.dispose();
  });

  it("applies mute/solo gains instantly, including to new playback", async () => {
    const { ctx, state } = fakeContext();
    const p = new OrchestraPlayer(() => ctx, fetcher);
    await p.load(tracks, 10);
    await p.play();
    p.setGains({ t1: 0, t2: 1 });
    expect(state.gains.map((g) => g.value)).toEqual([0, 1]);
    p.pause();
    await p.play();
    expect(state.gains.slice(2).map((g) => g.value)).toEqual([0, 1]);
    await p.dispose();
  });

  it("keeps mute decisions when master volume changes and does not finish on a suspended clock", async () => {
    vi.useFakeTimers();
    const { ctx, state } = fakeContext();
    const p = new OrchestraPlayer(() => ctx, fetcher);
    try {
      await p.load(tracks, 2);
      await p.play();
      p.setGains({ t1: 0, t2: 1 });
      p.setVolume(0.4);
      expect(state.gains.map((g) => g.value)).toEqual([0, 0.4]);
      Object.defineProperty(ctx, "state", {
        value: "suspended",
        configurable: true,
      });
      vi.advanceTimersByTime(2100);
      expect(p.ended).toBe(false);
      expect(p.currentTime).toBe(0);
      state.now = 2.1;
      vi.advanceTimersByTime(300);
      expect(p.ended).toBe(true);
    } finally {
      await p.dispose();
      vi.useRealTimers();
    }
  });

  it("fires ended at the end of the piece and restarts from the top", async () => {
    vi.useFakeTimers();
    try {
      const { ctx, state } = fakeContext();
      const p = new OrchestraPlayer(() => ctx, fetcher);
      await p.load(tracks, 2);
      const ended = vi.fn();
      p.addEventListener("ended", ended);
      await p.play();
      state.now = 2.5;
      vi.advanceTimersByTime(2100);
      expect(ended).toHaveBeenCalledTimes(1);
      expect(p.ended && p.paused).toBe(true);
      await p.play();
      expect(state.started.at(-1)!.offset).toBe(0);
      await p.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it("refuses to play before anything is loaded and surfaces fetch failures", async () => {
    const { ctx } = fakeContext();
    const p = new OrchestraPlayer(
      () => ctx,
      async () => {
        throw new Error("offline");
      },
    );
    await p.play();
    expect(p.paused).toBe(true);
    await expect(p.load(tracks, 10)).rejects.toThrow("offline");
    await p.dispose();
  });

  it("SourceClock follows the excerpt that is sounding", async () => {
    const { ctx, state } = fakeContext();
    const p = new OrchestraPlayer(() => ctx, fetcher);
    await p.load(tracks, 10);
    const clock = new SourceClock(p, [ev({})], "r1");
    await p.play();
    state.now = 1.2;
    expect(clock.currentTime).toBeCloseTo(2.2);
    state.now = 5; // no event sounding: keeps the last position
    expect(clock.currentTime).toBeCloseTo(2.2);
    expect(clock.paused).toBe(false);
    await p.dispose();
  });
});
