"""Deterministic offline renderer (RENDER_VERSION 1).

Pure NumPy/SciPy. Operations per plan event: ``slice`` (one-shot excerpt), ``loop``
(sustained excerpt tiled with equal-power crossfades) and ``grains`` (seeded granular cloud).
Each event: cut the exact source window → resample by ``rate`` (Catmull-Rom cubic after an
anti-alias low-pass when rate > 1) → Butterworth low-pass → gain → raised-cosine fades → equal-
power pan → add into the track's stereo stem. Each stem gets its own short reverb (decaying
noise impulse response seeded from the plan seed) so that **stems sum to the master**.

Master = Σ stems, then ONE global gain (towards −20 LUFS-style target, never exceeding a
−1 dBFS sample-peak ceiling) applied identically to master and stems. There is no per-source
normalisation. Sample rate is the canonical 48 kHz throughout; the only resampling is the
explicit per-event ``rate`` (pitch/tempo transform).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage, signal

from unheard.music.planner import rng_for

SR = 48_000
PEAK_CEILING = 10 ** (-1.0 / 20)
TARGET_LUFS = -18.0
LIMIT_LOOKAHEAD_S = 0.005
MAX_LIMITER_DB = 5.0
REVERB_S = 1.6

Mono = NDArray[np.float64]
Stereo = NDArray[np.float64]


def _fade_env(n: int, fi: int, fo: int) -> Mono:
    env = np.ones(n)
    fi, fo = min(fi, n // 2), min(fo, n // 2)
    if fi > 0:
        env[:fi] = 0.5 - 0.5 * np.cos(np.pi * np.arange(fi) / fi)
    if fo > 0:
        env[n - fo :] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(fo) / fo)
    return env


def _resample(x: Mono, rate: float) -> Mono:
    """Play ``x`` at ``rate`` (>1 = higher/faster). Catmull-Rom interpolation."""
    if abs(rate - 1.0) < 1e-6 or x.size < 4:
        return x.copy()
    if rate > 1.0:
        sos = signal.butter(4, min(0.45, 0.45 / rate) * 2 * 0.5 * 1.0, output="sos")
        x = signal.sosfiltfilt(sos, x) if x.size > 24 else x
    n_out = max(1, int(x.size / rate))
    pos = np.arange(n_out) * rate
    i = np.floor(pos).astype(np.int64)
    f = pos - i
    xp = np.pad(x, (1, 2), mode="edge")
    p0, p1, p2, p3 = xp[i], xp[i + 1], xp[i + 2], xp[i + 3]
    return 0.5 * (
        2 * p1
        + (-p0 + p2) * f
        + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f**2
        + (-p0 + 3 * p1 - 3 * p2 + p3) * f**3
    )


def _lowpass(x: Mono, hz: float | None) -> Mono:
    if not hz or hz >= SR / 2 * 0.95 or x.size < 16:
        return x
    sos = signal.butter(2, hz / (SR / 2), output="sos")
    return np.asarray(signal.sosfilt(sos, x))


def _highpass(x: Mono, hz: float | None) -> Mono:
    if not hz or hz <= 20 or x.size < 16:
        return x
    sos = signal.butter(2, hz / (SR / 2), btype="highpass", output="sos")
    return np.asarray(signal.sosfilt(sos, x))


def _pan(x: Mono, pan: float) -> Stereo:
    th = (np.clip(pan, -1, 1) + 1) * np.pi / 4
    return np.stack([x * np.cos(th), x * np.sin(th)], axis=1)


def _db(g: float) -> float:
    return float(10 ** (g / 20))


def _excerpt(src: Mono, a: float, b: float) -> Mono:
    i0 = int(max(0, round(a * SR)))
    i1 = int(min(src.size, round(b * SR)))
    return src[i0:i1].copy() if i1 > i0 else np.zeros(0)


def _window_gain(x: Mono) -> float:
    """Per-window loudness compensation (partial: 40 % of the distance to −24 dBFS, ±6 dB)."""
    if x.size == 0:
        return 1.0
    rms = float(np.sqrt(np.mean(x * x)))
    db = 20 * np.log10(max(rms, 1e-6))
    return _db(float(np.clip(0.4 * (-24.0 - db), -6.0, 6.0)))


def _crest_soften(x: Mono, crest: float = 3.0) -> Mono:
    """Gently round peaks above ``crest`` × RMS (tanh knee) so one footstep cannot set the master level."""
    if x.size == 0:
        return x
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 1e-9:
        return x
    tau = crest * rms
    return np.asarray(np.tanh(x / tau) * tau)


def sola_stretch(x: Mono, n_out: int, win: int = 1536, seek: int = 384) -> Mono:
    """WSOLA time-stretch to exactly ``n_out`` samples (pitch unchanged). For short pitched notes."""
    n_in = x.size
    if n_out <= 0 or n_in < win * 2 or abs(n_out - n_in) < 32:
        out = np.zeros(max(n_out, 0))
        m = min(n_in, n_out)
        out[:m] = x[:m]
        return out
    hop_s = win // 2
    hop_a = hop_s * n_in / n_out
    window = np.hanning(win)
    pad = np.concatenate([np.zeros(seek), x, np.zeros(win + seek + hop_s)])
    out = np.zeros(n_out + 2 * win)
    norm = np.zeros_like(out)
    prev = seek
    n_frames = int(np.ceil(n_out / hop_s)) + 1
    for k in range(n_frames):
        target = int(round(k * hop_a)) + seek
        if k == 0:
            pos = target
        else:
            ref = pad[prev + hop_s : prev + hop_s + win]
            best, pos = -np.inf, target
            for d in range(-seek, seek + 1, 4):
                cand = target + d
                if cand < 0 or cand + win > pad.size:
                    continue
                seg = pad[cand : cand + win : 4]
                score = float(np.dot(seg, ref[::4]))
                if score > best:
                    best, pos = score, cand
        frame = pad[pos : pos + win]
        if frame.size < win:
            frame = np.pad(frame, (0, win - frame.size))
        o = k * hop_s
        out[o : o + win] += frame * window
        norm[o : o + win] += window
        prev = pos
    out = out / np.maximum(norm, 1e-6)
    return out[:n_out]


def _loop(seg: Mono, n_out: int, xf: int) -> Mono:
    if seg.size <= 2 * xf + 8:
        reps = int(np.ceil(n_out / max(seg.size, 1)))
        return np.tile(seg, reps)[:n_out]
    out = seg.copy()
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(xf) / xf)
    cin, cout = np.sqrt(ramp), np.sqrt(1 - ramp)
    while out.size < n_out + xf:
        tail = out[-xf:] * cout + seg[:xf] * cin
        out = np.concatenate([out[:-xf], tail, seg[xf:]])
    return out[:n_out]


def _add(buf: Stereo, x: Stereo, at: int) -> None:
    if at >= buf.shape[0] or x.shape[0] == 0:
        return
    end = min(buf.shape[0], at + x.shape[0])
    buf[at:end] += x[: end - at]


def render_event(ev: dict[str, Any], src: Mono, pan: float, seed: int, buf: Stereo) -> None:
    t = ev["t"]
    at = int(round(t * SR))
    gain = _db(ev["gain_db"])
    kind = ev["kind"]
    if kind == "slice":
        x = _excerpt(src, ev["source_start_s"], ev["source_end_s"])
        if x.size < 8:
            return
        n0 = x.size
        g_win = _window_gain(x)  # measured on the source excerpt (as in M4/M4.5)
        x = _resample(x, ev.get("rate", 1.0))
        if ev.get("preserve_duration"):  # pitch moved, length kept (tonal notes)
            x = sola_stretch(x, n0)
        x = _crest_soften(x) * g_win
        x = _highpass(_lowpass(x, ev.get("lowpass_hz")), ev.get("highpass_hz"))
        fi = max(int(ev.get("fade_in_s", 0.005) * SR), 48)
        fo = max(int(ev.get("fade_out_s", 0.02) * SR), 96)
        x = x * _fade_env(x.size, fi, fo) * gain
        _add(buf, _pan(x, pan), at)
    elif kind == "loop":
        seg = _excerpt(src, ev["source_start_s"], ev["source_end_s"])
        if seg.size < 8:
            return
        seg = _resample(seg, ev.get("rate", 1.0))
        n_out = int(ev["dur"] * SR)
        x = _loop(seg, n_out, int(ev.get("crossfade_s", 0.8) * SR))
        x = x * _window_gain(seg)
        x = _highpass(_lowpass(x, ev.get("lowpass_hz")), ev.get("highpass_hz"))
        x = x * _fade_env(x.size, int(ev["fade_in_s"] * SR), int(ev["fade_out_s"] * SR)) * gain
        _add(buf, _pan(x, pan), at)
    elif kind == "grains":
        seg = _excerpt(src, ev["source_start_s"], ev["source_end_s"])
        if seg.size < 64:
            return
        rng = np.random.Generator(np.random.PCG64(int(ev["grain_seed"])))
        glen = int(ev["grain_s"] * SR)
        n_grains = int(ev["dur"] * ev["grain_density_hz"])
        win = np.hanning(glen)
        layer = np.zeros((int(ev["dur"] * SR) + glen, 2))
        for _ in range(n_grains):
            p = int(rng.integers(0, max(1, seg.size - glen)))
            g = seg[p : p + glen]
            if g.size < glen:
                continue
            st = float(rng.uniform(-ev["pitch_jitter_st"], ev["pitch_jitter_st"]))
            g = _resample(g, 2 ** (st / 12))
            g = np.pad(g, (0, max(0, glen - g.size)))[:glen] * win
            pos = int(rng.integers(0, max(1, layer.shape[0] - glen)))
            _add(layer, _pan(g, float(rng.uniform(-0.8, 0.8))), pos)
        mono = layer.mean(axis=1)
        env = _fade_env(layer.shape[0], int(ev["fade_in_s"] * SR), int(ev["fade_out_s"] * SR))
        layer = layer * (env * gain * _window_gain(seg))[:, None]
        for ch in range(2):
            layer[:, ch] = _highpass(
                _lowpass(layer[:, ch], ev.get("lowpass_hz")), ev.get("highpass_hz")
            )
        del mono
        # per-track pan offset on top of the grain scatter
        layer = (
            layer
            * np.array([np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)])
            * np.sqrt(2)
        )
        _add(buf, layer, at)
    else:  # pragma: no cover - plans are validated upstream
        raise ValueError(f"unknown event kind {kind!r}")


def reverb_ir(seed: int) -> NDArray[np.float64]:
    rng = rng_for(seed, "reverb-ir")
    n = int(REVERB_S * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal((n, 2)) * np.exp(-t / 0.42)[:, None]
    ir[: int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))[:, None]
    sos = signal.butter(2, 6500 / (SR / 2), output="sos")
    ir = signal.sosfilt(sos, ir, axis=0)
    return np.asarray(ir / np.sqrt(np.sum(ir**2, axis=0, keepdims=True)))


def k_weight(x: Mono) -> Mono:
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    return np.asarray(signal.lfilter(b2, a2, signal.lfilter(b1, a1, x)))


def loudness_lufs(stereo: Stereo) -> float:
    """BS.1770-style integrated loudness (K-weighted, 400 ms blocks, 75 % overlap, two gates)."""
    if stereo.shape[0] < int(0.4 * SR):
        return -70.0
    k = np.stack([k_weight(stereo[:, 0]), k_weight(stereo[:, 1])], axis=1)
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    ms = []
    for s in range(0, k.shape[0] - blk + 1, hop):
        ms.append(float(np.sum(np.mean(k[s : s + blk] ** 2, axis=0))))
    z = np.array(ms)
    lk = -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    z1 = z[lk > -70.0]
    if z1.size == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(np.mean(z1)) - 10.0
    z2 = z[lk > rel]
    if z2.size == 0:
        return -70.0
    return float(-0.691 + 10 * np.log10(np.mean(z2)))


def limiter_gain(x: Stereo) -> Mono:
    """Smooth look-ahead peak limiter gain envelope (≤ 1) keeping |x·g| ≤ PEAK_CEILING."""
    peak = np.max(np.abs(x), axis=1)
    need = np.minimum(1.0, PEAK_CEILING / np.maximum(peak, 1e-12))
    w = max(3, int(LIMIT_LOOKAHEAD_S * SR) | 1)
    g = ndimage.minimum_filter1d(need, size=2 * w + 1, mode="nearest")
    kernel = np.hanning(2 * w + 1)
    kernel /= kernel.sum()
    g = np.convolve(np.pad(g, (w, w), mode="edge"), kernel, mode="valid")
    # every smoothed sample averages values that are each ≤ need[n] (|m−n| ≤ w), so g ≤ need
    return np.asarray(g)


def duck_envelope(plan: dict[str, Any], n: int) -> Mono | None:
    """Gain (≤ 1) dipping under every trigger-layer slice: fast attack, hold, raised-cosine release."""
    d = plan.get("ducking")
    if not d or not d["targets"] or not d["triggers"]:
        return None
    depths = d.get("depths", {})
    att, rel = int(d["attack_s"] * SR), int(d["release_s"] * SR)
    env = np.ones(n)
    trig = set(d["triggers"])
    for ev in plan["events"]:
        if ev["track"] not in trig or ev["kind"] != "slice":
            continue
        depth = 10 ** (-depths.get(ev["track"], d["depth_db"]) / 20)
        a0 = int(ev["t"] * SR)
        hold = int(min(ev["dur"], d["max_hold_s"]) * SR)
        total = att + hold + rel
        if a0 >= n:
            continue
        shape = np.concatenate(
            [
                np.linspace(0.0, 1.0, att, endpoint=False),
                np.ones(hold),
                0.5 + 0.5 * np.cos(np.pi * np.arange(rel) / max(rel, 1)),
            ]
        )
        g = 1.0 - (1.0 - depth) * shape
        end = min(n, a0 + total)
        env[a0:end] = np.minimum(env[a0:end], g[: end - a0])
    return env


def render_plan(
    plan: dict[str, Any], sources: dict[str, Mono]
) -> tuple[dict[str, Stereo], Stereo, dict[str, Any]]:
    """Render ``plan`` → (stems by track id, master, metrics). Raises KeyError for missing sources."""
    n = int((plan["duration_s"] + plan["tail_s"]) * SR)
    ir = reverb_ir(plan["seed"])
    stems: dict[str, Stereo] = {}
    for tr in plan["tracks"]:
        buf = np.zeros((n, 2))
        src = sources[tr["source"]]
        for ev in plan["events"]:
            if ev["track"] == tr["id"]:
                render_event(ev, src, tr["pan"], plan["seed"], buf)
        send = tr["reverb_send"]
        if send > 0:
            wet = np.stack(
                [signal.fftconvolve(buf[:, ch], ir[:, ch])[:n] for ch in range(2)], axis=1
            )
            buf = buf + send * wet
        stems[tr["id"]] = buf

    duck = duck_envelope(plan, n)
    if duck is not None:
        for tid in plan["ducking"]["targets"]:
            stems[tid] = stems[tid] * duck[:, None]

    master = np.zeros((n, 2))
    for s in stems.values():
        master += s
    # One makeup gain towards the loudness target, then ONE smooth look-ahead peak limiter whose
    # gain envelope is applied identically to master and every stem (so stems still sum to master).
    lufs = loudness_lufs(master)
    db = float(np.clip(TARGET_LUFS - lufs, -12.0, 24.0)) if lufs > -69 else 0.0
    for _ in range(6):  # back off until the limiter works lightly (≤ MAX_LIMITER_DB)
        makeup = 10 ** (db / 20)
        env = limiter_gain(master * makeup)
        red = float(-20 * np.log10(max(float(env.min()), 1e-9))) if n else 0.0
        if red <= MAX_LIMITER_DB:
            break
        db -= red - MAX_LIMITER_DB + 0.25
    edge_in = _fade_env(n, int(0.01 * SR), int(0.06 * SR))[:, None]
    gain = (env * makeup)[:, None] * edge_in
    master = master * gain
    stems = {k: v * gain for k, v in stems.items()}
    g = float(makeup)
    reduction_db = float(-20 * np.log10(max(float(env.min()), 1e-9))) if n else 0.0
    metrics = measure(master, stems, plan)
    metrics["makeup_gain_db"] = float(20 * np.log10(g)) if g > 0 else None
    metrics["limiter_max_reduction_db"] = reduction_db
    return stems, master, metrics


def measure(master: Stereo, stems: dict[str, Stereo], plan: dict[str, Any]) -> dict[str, Any]:
    n = master.shape[0]
    mono = master.mean(axis=1)
    peak = float(np.max(np.abs(master))) if n else 0.0
    rms = float(np.sqrt(np.mean(master**2))) if n else 0.0
    blk = int(0.1 * SR)
    nb = n // blk
    rms_blocks = (
        np.sqrt(np.mean(mono[: nb * blk].reshape(nb, blk) ** 2, axis=1)) if nb else np.zeros(1)
    )
    silence_ratio = float(np.mean(rms_blocks < 10 ** (-60 / 20)))
    disc = float(np.max(np.abs(np.diff(mono)))) if n > 1 else 0.0
    clip = float(np.mean(np.abs(master) >= 0.999))
    sec_rms = []
    for s in plan["sections"]:
        a, b = int(s["start_s"] * SR), int(s["end_s"] * SR)
        seg = master[a:b]
        sec_rms.append(
            {
                "section": s["name"],
                "rms_dbfs": float(
                    20 * np.log10(max(np.sqrt(np.mean(seg**2)) if seg.size else 0, 1e-9))
                ),
            }
        )
    contrib = {k: float(np.sqrt(np.mean(v**2))) for k, v in stems.items()}
    tot = sum(contrib.values()) or 1.0
    # bar-level envelope repetition
    bar = int(plan["bar_s"] * SR)
    envs = []
    for i in range(int(plan["duration_s"] * SR) // bar):
        seg = mono[i * bar : (i + 1) * bar]
        if seg.size == bar:
            envs.append(np.sqrt(np.mean(seg[: bar // 16 * 16].reshape(16, -1) ** 2, axis=1)))
    sims = []
    for i in range(len(envs) - 1):
        e0, e1 = envs[i], envs[i + 1]
        d = float(np.linalg.norm(e0) * np.linalg.norm(e1))
        sims.append(float(np.dot(e0, e1) / d) if d > 0 else 1.0)
    bounds_bad = sum(
        1 for e in plan["events"] if e["t"] < -1e-6 or e["t"] > plan["duration_s"] + 1e-6
    )
    empty = []
    for s in plan["sections"]:
        a, b = int(s["start_s"] * SR), int(s["end_s"] * SR)
        if a < b and np.sqrt(np.mean(master[a:b] ** 2)) < 10 ** (-60 / 20):
            empty.append(s["name"])
    return {
        "duration_s": n / SR,
        "peak_dbfs": float(20 * np.log10(max(peak, 1e-9))),
        "rms_dbfs": float(20 * np.log10(max(rms, 1e-9))),
        "lufs_approx": loudness_lufs(master),
        "clipping_ratio": clip,
        "silence_ratio": silence_ratio,
        "max_sample_step": disc,
        "section_rms": sec_rms,
        "track_contribution": {k: v / tot for k, v in contrib.items()},
        "mean_bar_similarity": float(np.mean(sims)) if sims else None,
        "highly_repetitive": bool(sims and np.mean(np.array(sims) > 0.995) > 0.8),
        "events_out_of_bounds": bounds_bad,
        "empty_sections": empty,
        "sample_rate": SR,
    }


def to_pcm16(x: Stereo) -> NDArray[np.int16]:
    return np.asarray(np.round(np.clip(x, -1.0, 1.0) * 32767.0), dtype=np.int16)
