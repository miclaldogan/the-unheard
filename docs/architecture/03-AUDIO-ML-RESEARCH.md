# 03 — Audio Capture, DSP and Model Research

Legend: **[V]** verified in this session · **[M]** from maintainers' public docs as I remember them, *must be re-verified* (no network fetch of model cards was done) · **[E]** estimate · **[H]** hypothesis.

## 1. Capture pipeline
| Concern | Decision |
|---|---|
| Recorder | `AudioWorklet` capturing Float32 PCM → client-side 16-bit mono WAV at the device's native rate. Fallback: `MediaRecorder` (Chrome/Android gives webm/opus, iOS Safari gives mp4/aac) [M] |
| Why not MediaRecorder-first | Codec differs per browser; lossy codecs smear transients that onset features need. |
| Constraints | `getUserMedia({audio:{echoCancellation:false, noiseSuppression:false, autoGainControl:false}})` — these defaults destroy ambient sound. Browsers may ignore; log which were honored. |
| Normalization (server, ffmpeg [V present]) | → 48 kHz, mono, s16 (CLAP input rate [M]); derived 16 kHz copy for YAMNet fallback. Stereo is downmixed after storing channel correlation. |
| Length | Min 3 s, default 10 s, max 30 s. Models were trained on ~10 s clips [M]. Longer ⇒ segment into 10 s windows with 50 % hop, mean-pool embeddings. |
| Latency target [E→measure] | Ingest <1 s; DSP <1 s; embedding <2 s CPU for 10 s clip; end-to-end <5 s. Measured in M0 script. |
| Quality assessment | Reject/flag: duration<3 s; peak ≥0.99 for >0.5 % samples (clipping); RMS < −60 dBFS (silence); DC offset; noise floor estimate = 10th-percentile frame RMS. |
| VAD / silence | **No speech VAD gating** (we are not transcribing). Silence is trimmed only at edges (−55 dBFS). Speech presence is a *label* from the model, and triggers the privacy hint (doc 10). |
| Overlap | Treated as multi-label by design (§3). |

## 2. Feature selection (only what has a consumer)
| Feature | Meaning | Consumer | Cost | Failure case | Test |
|---|---|---|---|---|---|
| Log-mel spectrogram (64 bands, 25 ms/10 ms) | perceptual energy over time-frequency | model input (YAMNet fallback), spectrogram view, visual texture | low | wind-rumble dominates low bands | shape/NaN test; sine at 1 kHz peaks in expected mel bin |
| STFT magnitude (n_fft 2048, hop 512) | basis for all spectral stats | internal | low | — | Parseval/energy consistency |
| RMS (dB) envelope | loudness over time | visual scale, music dynamics, quality | trivial | AGC phones flatten it | constant-amplitude sine → flat |
| Spectral centroid | "brightness" (amplitude-weighted mean frequency) | visual sharpness, orchestration register | low | meaningless on near-silence | sine at f → ≈f |
| Spectral flatness | geometric/arithmetic mean ratio; 1 = noise, 0 = tone | tonal-vs-noisy gate for melody (§Music) and visual regularity | low | broadband tones | white noise ≈ high, sine ≈ ~0 |
| Spectral flux | frame-to-frame spectral change | visual fragmentation | low | codec artifacts | stationary noise → low, clicks → high |
| Onset strength + peaks | novelty function; peak-picked | percussion timing, rhythm grid | low | reverb, wind gusts give false onsets | synthetic click train recovered within ±20 ms |
| Onset density, IOI histogram | events/sec; inter-onset regularity | rhythm pattern, visual repetition | trivial | — | click train 4 Hz → 4/s |
| f0 contour (pYIN-style, only where flatness is low) | pitch track | melody | medium | noise → octave errors; **only used if voiced ratio ≥0.4** | synthetic glide recovered ±1 semitone |
| MFCC (13, mean+std) | compact timbre | *not required*; kept only as DSP-only emergency fallback for similarity | low | — | — |
| Rolloff, bandwidth, ZCR, tempo | redundant with above / unreliable for non-music | **dropped from MVP** | | | |
| Entropy / ACI soundscape indices | ecoacoustics | **deferred** (could feed atlas "environment" axis) | | | |

Features are versioned `dsp_version`; same input + version ⇒ bit-identical output (float64, no threads-order nondeterminism; tested).

## 3. Model candidates (licenses must be re-verified before release)
| Model | Role | License [M] | Size/runtime [M/E] | Notes |
|---|---|---|---|---|
| **LAION-CLAP** (HTSAT audio + text, HF `transformers`) | embeddings + open-vocab | Apache-2.0 code; weights on HF — VERIFY | ~150 M params [M]; CPU feasible, GPU optional [E] | One model: 512-d audio embedding **and** text embedding so user-invented labels get a prior from their *name*. Zero-shot scores are weakly calibrated [H]. |
| PANNs CNN14 | AudioSet 527-class multi-label + 2048-d embedding | MIT code; checkpoint license VERIFY | ~80 M params [M] | Strong AudioSet tagger; closed vocabulary. |
| YAMNet | 521-class, 1024-d embedding | Apache-2.0 [M] | ~3.7 M params, MobileNet-v1 [M] — smallest | TF-native; ONNX conversions exist but are unofficial. Only candidate with realistic browser/phone future. |
| BEATs | SSL embeddings | MIT code [M] | ~90 M | Needs fine-tuned heads for tags; more integration work. |
| AST | AudioSet transformer | BSD code, HF weights VERIFY | ~87 M | Heavier, fixed 10 s input. |

### Recommendation
- **Primary:** LAION-CLAP (via `transformers` on CPU/GPU). Reason: user-created labels (Act V "the sound I cannot name") need open-vocabulary + embedding in one model; kNN memory sits on its embedding.
- **Fallback:** YAMNet (CPU, tiny) — 521-class multi-label + embedding. If CLAP fails the M0 gate (below) or wheels don't install on the chosen Python, switch via `AudioModel` adapter with no other code changes.
- **Rejected for MVP:** BEATs/AST (more plumbing, no unique benefit), browser inference (a bigger unknown; see ADR-005).

### M0 gate (decides primary vs fallback; ~2 h)
`scripts/bench_models.py` on 30 clips (own recordings + freely licensed ESC-50 [M] subset): report (a) install success on Py3.12, (b) peak RSS, (c) p50/p95 seconds per 10 s clip on CPU and GPU, (d) top-1/top-3 accuracy of zero-shot on ESC-50 subset, (e) whether same-class clips are nearer in embedding space than different-class (recall@5 of kNN). **Pass: install OK, p95 ≤ 4 s CPU, kNN recall@5 ≥ the YAMNet baseline.** Numbers are not claimed anywhere until this exists.

## 4. Capability map (A–F from brief)
- **A Recognition:** CLAP zero-shot over a label vocabulary (AudioSet ontology names + user labels) → per-label sigmoid-like scores; YAMNet native.
- **B Embedding:** L2-normalised 512-d (CLAP) per window; recording embedding = mean of windows, re-normalised. Cosine similarity.
- **C Open vocabulary:** text embedding of a label name vs audio embedding gives a prior for categories with **zero** exemplars.
- **D Multi-label:** scores are independent per label (not softmax); the memory step (doc 04) also emits per-label scores. A recording can carry several human labels.
- **E Uncertainty:** novelty = low max-cosine to any exemplar **and** low base margin (doc 04 §4).
- **F Personalization:** retrieval memory; no gradient updates.

## 5. Failure analysis
Wind noise on phone mics saturates low bands and dominates embeddings [H]; mitigation: record-quality flag + user can mark "wind" as its own label. Traffic masks birds; windowed pooling can help but max-pooling of per-window label scores is used for *presence*. Phones' AGC is the largest cross-device variance — memory is therefore partly device-specific [H]; evaluation includes a cross-device split if two devices are available.
