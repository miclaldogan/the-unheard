"""Numerical tests for dsp v1. Tolerances are justified inline."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tests.fixtures import synth
from unheard.dsp import DSP_VERSION, extract_features
from unheard.dsp.features import STFT_HOP, STFT_N_FFT
from unheard.dsp.stft import mel_filterbank, mel_frequencies, stft_magnitude

SR = 48_000
# STFT bin width at n_fft 2048 / 48 kHz = 23.4 Hz; a Hann main lobe spans ±2 bins.
BIN_HZ = SR / STFT_N_FFT


def test_version_is_one() -> None:
    assert DSP_VERSION == 1


def test_sine_centroid_near_frequency() -> None:
    f = extract_features(synth.sine(440.0, SR, 3.0), SR)
    c = f.summary["spectral_centroid_hz"]["median"]
    # Hann sidelobes and reflect-padding edge frames pull the amplitude-weighted mean
    # slightly; allow 2 bins (≈47 Hz) around 440 Hz.
    assert abs(c - 440.0) < 2 * BIN_HZ
    assert f.summary["spectral_flatness"]["median"] < 0.05  # pure tone → near 0
    assert f.summary["spectral_bandwidth_hz"]["median"] < 150.0
    assert abs(f.summary["spectral_rolloff_hz"]["median"] - 440.0) < 2 * BIN_HZ


def test_sine_rms_and_peak() -> None:
    f = extract_features(synth.sine(440.0, SR, 3.0, amp=0.5), SR)
    # RMS of A·sin = A/√2; exact up to one partial cycle at the end (3 s = 1320 full cycles)
    assert f.summary["rms"] == pytest.approx(0.5 / np.sqrt(2), rel=1e-3)
    assert f.summary["peak"] == pytest.approx(0.5, rel=1e-3)
    assert f.summary["clipping_ratio"] == 0.0
    assert f.summary["rms_dbfs"] == pytest.approx(20 * np.log10(0.5 / np.sqrt(2)), abs=0.05)
    # constant amplitude → flat RMS envelope (ignore the edge frames affected by padding)
    env = f.arrays["rms_envelope_db"][3:-3]
    assert env.max() - env.min() < 0.5


def test_sine_zero_crossing_rate() -> None:
    x = synth.sine(1000.0, SR, 3.0)
    f = extract_features(x, SR)
    # 2 crossings per cycle → 2f/sr per sample = 2000 crossings/s. Tolerance: sampling
    # jitter at the zero crossings, ±1 crossing per second.
    assert f.summary["zero_crossings_per_s"] == pytest.approx(2000.0, abs=2.0)


def test_silence_is_well_defined() -> None:
    f = extract_features(synth.silence(SR, 3.0), SR)
    assert f.summary["rms"] == 0.0
    assert f.summary["peak"] == 0.0
    assert f.summary["active_frame_ratio"] == 0.0
    assert f.summary["onset_count"] == 0
    assert np.all(np.isfinite(f.arrays["log_mel_db"]))
    assert np.all(np.isfinite(f.arrays["flatness"]))
    assert f.arrays["flatness"].max() <= 1.0
    assert f.summary["spectral_centroid_hz"]["mean"] == 0.0  # no active frames → stats are 0


def test_white_noise_is_flat_and_bright() -> None:
    f = extract_features(synth.white_noise(SR, 3.0, seed=42), SR)
    # Geometric/arithmetic mean of a chi-square(2) spectrum: E ≈ exp(-γ) ≈ 0.56 per frame.
    assert f.summary["spectral_flatness"]["median"] > 0.4
    # White noise centroid ≈ Nyquist/2 (= 12 kHz); allow ±1 kHz for finite-sample variance.
    assert abs(f.summary["spectral_centroid_hz"]["median"] - SR / 4) < 1000.0
    # Rolloff: 85 % of energy below ≈ 0.85·Nyquist.
    assert abs(f.summary["spectral_rolloff_hz"]["median"] - 0.85 * SR / 2) < 1000.0
    # Stationary noise → low flux relative to its magnitude; no onsets expected.
    assert f.summary["onset_count"] <= 2


def test_multi_sine_rolloff_and_centroid_between_components() -> None:
    f = extract_features(synth.multi_sine([300.0, 3000.0], SR, 3.0), SR)
    c = f.summary["spectral_centroid_hz"]["median"]
    # Equal-amplitude partials → amplitude-weighted mean ≈ 1650 Hz
    assert abs(c - 1650.0) < 3 * BIN_HZ
    # 85 % energy requires the second partial → rolloff lands on it
    assert abs(f.summary["spectral_rolloff_hz"]["median"] - 3000.0) < 2 * BIN_HZ


def test_click_train_onsets_recovered() -> None:
    x = synth.click_train(4.0, SR, 3.0)
    f = extract_features(x, SR)
    # 12 clicks in 3 s (t = 0, 0.25, …, 2.75)
    assert f.summary["onset_density_per_s"] == pytest.approx(4.0, abs=0.4)
    expected = np.arange(0, 3.0, 0.25)
    got = f.arrays["onset_times_s"]
    assert got.size == pytest.approx(12, abs=1)
    for t in got:
        # Within ±20 ms (two 10 ms mel hops) of a true click
        assert np.min(np.abs(expected - t)) <= 0.020 + 1e-9
    # transients → high flux relative to a stationary signal
    assert f.summary["spectral_flux"]["max"] > 10 * f.summary["spectral_flux"]["median"]


def test_clipped_sine_reports_clipping() -> None:
    f = extract_features(synth.clipped_sine(440.0, SR, 3.0, gain=3.0), SR)
    # A sine scaled ×3 and clipped at 1 exceeds 0.99 for ≈ 1 - (2/π)·asin(0.33) ≈ 78 % of samples
    assert f.summary["clipping_ratio"] > 0.7
    assert f.summary["peak"] == 1.0
    # clipping adds odd harmonics → flatness and bandwidth rise versus the clean tone
    clean = extract_features(synth.sine(440.0, SR, 3.0), SR)
    assert (
        f.summary["spectral_bandwidth_hz"]["median"]
        > clean.summary["spectral_bandwidth_hz"]["median"]
    )


@pytest.mark.parametrize("sr", [16_000, 44_100, 48_000])
def test_other_sample_rates(sr: int) -> None:
    f = extract_features(synth.sine(1000.0, sr, 3.0), sr)
    assert f.summary["sample_rate"] == sr
    assert f.summary["duration_s"] == pytest.approx(3.0, abs=1 / sr)
    assert abs(f.summary["spectral_centroid_hz"]["median"] - 1000.0) < 2 * sr / STFT_N_FFT
    assert f.arrays["log_mel_db"].shape[0] == 64


def test_stereo_input_rejected_by_dsp_and_downmix_matches_mono() -> None:
    from unheard.ingest.decode import downmix

    left = synth.sine(440.0, SR, 3.0)
    right = synth.sine(440.0, SR, 3.0)
    with pytest.raises(ValueError):
        extract_features(synth.stereo(left, right), SR)
    mono = downmix(synth.stereo(left, right))
    np.testing.assert_allclose(mono, left, atol=1e-12)


def test_log_mel_peak_bin_for_1khz() -> None:
    x = synth.sine(1000.0, SR, 3.0)
    f = extract_features(x, SR)
    lm = f.arrays["log_mel_db"]
    centres = f.arrays["mel_freqs_hz"]
    band = int(np.argmax(lm.mean(axis=1)))
    assert abs(centres[band] - 1000.0) < (centres[band + 1] - centres[band - 1])
    assert f.summary["log_mel"]["dominant_band_hz"] == pytest.approx(centres[band])


def test_mel_filterbank_shape_and_coverage() -> None:
    fb = mel_filterbank(SR, 2048, 64, 20.0, SR / 2)
    assert fb.shape == (64, 1025)
    assert np.all(fb >= 0)
    assert np.all(fb.sum(axis=1) > 0)  # every band covers at least one bin
    edges = mel_frequencies(64, 20.0, SR / 2)
    assert edges[0] == pytest.approx(20.0) and edges[-1] == pytest.approx(SR / 2)


def test_stft_energy_consistency() -> None:
    # Parseval-style sanity: for a stationary sine, per-frame spectral energy is ~constant.
    x = synth.sine(440.0, SR, 2.0)
    mag = stft_magnitude(x, n_fft=STFT_N_FFT, hop=STFT_HOP)
    e = (mag**2).sum(axis=0)[4:-4]
    assert e.std() / e.mean() < 0.01


def test_determinism_two_runs_identical() -> None:
    x = synth.environmental_like(SR, 4.0)
    a = extract_features(x, SR)
    b = extract_features(x, SR)
    assert a.summary_hash() == b.summary_hash()
    assert a.to_npz_bytes() == b.to_npz_bytes()
    json.dumps(a.summary)  # serialisable


def test_rejects_nan_and_empty() -> None:
    with pytest.raises(ValueError):
        extract_features(np.array([]), SR)
    with pytest.raises(ValueError):
        extract_features(np.array([0.0, np.nan, 0.1]), SR)


def test_short_signal_does_not_crash() -> None:
    f = extract_features(synth.sine(440.0, SR, 0.01), SR)  # 480 samples < n_fft
    assert np.all(np.isfinite(f.arrays["log_mel_db"]))
    assert f.summary["n_samples"] == 480
