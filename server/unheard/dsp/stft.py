"""Short-time Fourier transform and mel filterbank (pure NumPy/SciPy, float64).

Definitions
-----------
* Frames: ``x`` is centre-padded by ``n_fft//2`` with reflection, then sliced into frames
  of ``win_length`` samples every ``hop`` samples. Frame ``t`` is centred on sample
  ``t*hop``. A periodic Hann window is applied; frames are zero-padded to ``n_fft``.
* ``stft_magnitude`` returns ``|X[k, t]|`` with ``k`` in ``0..n_fft//2`` (one-sided rfft).
* Mel scale (HTK): ``mel(f) = 2595 * log10(1 + f/700)``. Filters are triangular between
  successive mel-spaced edges, each scaled by ``2/(f_hi - f_lo)`` ("Slaney" area
  normalisation) so a flat spectrum gives roughly equal band energies.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.signal import get_window


def frame_signal(
    x: NDArray[np.float64], *, n_fft: int, hop: int, win_length: int | None = None
) -> NDArray[np.float64]:
    """Return a (n_frames, win_length) view of centred frames (reflect padded)."""
    win_length = win_length or n_fft
    pad = n_fft // 2
    if x.size == 0:
        raise ValueError("empty signal")
    if x.size <= pad:
        # reflect padding needs at least pad+1 samples; fall back to zero padding
        xp = np.concatenate([np.zeros(pad), x, np.zeros(pad)])
    else:
        xp = np.pad(x, pad, mode="reflect")
    # window centred inside the n_fft frame
    offset = (n_fft - win_length) // 2
    n_frames = 1 + (xp.size - n_fft) // hop
    idx = np.arange(win_length)[None, :] + offset + hop * np.arange(n_frames)[:, None]
    return np.asarray(xp[idx], dtype=np.float64)


def stft_magnitude(
    x: NDArray[np.float64], *, n_fft: int, hop: int, win_length: int | None = None
) -> NDArray[np.float64]:
    """One-sided STFT magnitude, shape (n_fft//2 + 1, n_frames)."""
    win_length = win_length or n_fft
    frames = frame_signal(x, n_fft=n_fft, hop=hop, win_length=win_length)
    window = get_window("hann", win_length, fftbins=True).astype(np.float64)
    spec = np.fft.rfft(frames * window, n=n_fft, axis=1)
    return np.asarray(np.abs(spec).T, dtype=np.float64)


def fft_frequencies(sr: int, n_fft: int) -> NDArray[np.float64]:
    return np.fft.rfftfreq(n_fft, d=1.0 / sr)


def frame_times(n_frames: int, sr: int, hop: int) -> NDArray[np.float64]:
    return np.arange(n_frames, dtype=np.float64) * hop / sr


def hz_to_mel(f: NDArray[np.float64] | float) -> NDArray[np.float64]:
    return np.asarray(2595.0 * np.log10(1.0 + np.asarray(f, dtype=np.float64) / 700.0))


def mel_to_hz(m: NDArray[np.float64] | float) -> NDArray[np.float64]:
    return np.asarray(700.0 * (10.0 ** (np.asarray(m, dtype=np.float64) / 2595.0) - 1.0))


def mel_frequencies(n_mels: int, fmin: float, fmax: float) -> NDArray[np.float64]:
    """n_mels + 2 edge frequencies in Hz, uniformly spaced on the HTK mel scale."""
    return mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2))


def mel_filterbank(
    sr: int, n_fft: int, n_mels: int, fmin: float, fmax: float
) -> NDArray[np.float64]:
    """Triangular mel filterbank, shape (n_mels, n_fft//2 + 1), area-normalised."""
    if fmax > sr / 2:
        raise ValueError("fmax exceeds Nyquist")
    freqs = fft_frequencies(sr, n_fft)
    edges = mel_frequencies(n_mels, fmin, fmax)
    fb = np.zeros((n_mels, freqs.size), dtype=np.float64)
    for m in range(n_mels):
        lo, mid, hi = edges[m], edges[m + 1], edges[m + 2]
        rising = (freqs - lo) / max(mid - lo, 1e-12)
        falling = (hi - freqs) / max(hi - mid, 1e-12)
        fb[m] = np.maximum(0.0, np.minimum(rising, falling)) * (2.0 / (hi - lo))
    return fb


def power_to_db(power: NDArray[np.float64], amin: float = 1e-10) -> NDArray[np.float64]:
    """10 * log10(max(power, amin)); absolute reference (1.0), no per-clip normalisation."""
    return np.asarray(10.0 * np.log10(np.maximum(power, amin)))
