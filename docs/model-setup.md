# Audio model setup (M2)

ECHO-0's "ears" are **LAION-CLAP** (`laion/clap-htsat-unfused`, revision
`8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`) run locally through `transformers` + `torch`
on the CPU. Nothing is sent anywhere: the only network use is the one-time weight download.

## Install

```bash
cd server
uv sync --extra ml                 # torch (CPU wheels from download.pytorch.org/whl/cpu) + transformers
uv run unheard fetch-model         # downloads ~600 MB into ~/.cache/huggingface/hub (explicit step)
uv run unheard serve               # model loads lazily on the first inference job (~6 s)
```

Without `--extra ml`, or with `UNHEARD_MODEL_NAME=none`, the server runs exactly as in M1
(features, archive, annotations without memory) and `/api/model` reports `disabled`.

Runtime downloads are **off** by default (`HF_HUB_OFFLINE=1` is set by the adapter). Set
`UNHEARD_ALLOW_MODEL_DOWNLOAD=1` only if you want the server itself to fetch weights.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `UNHEARD_MODEL_NAME` | `laion/clap-htsat-unfused` | Hub id; `none` disables inference |
| `UNHEARD_DEVICE` | `cpu` | `cuda` needs a CUDA build of torch installed into the venv manually (`uv pip install torch --index-url https://download.pytorch.org/whl/cu126`); CLAP needs ≈1 GB VRAM |
| `UNHEARD_TORCH_THREADS` | unset (torch default) | limit CPU threads |
| `UNHEARD_AUTO_INFER` | `true` | queue inference automatically after DSP |
| `UNHEARD_FUSION_*` | see `config.py` | memory/fusion parameters (k, temperatures, κ, τ) |

## Measured on the development laptop (i7-13700H, CPU only, torch 2.14+cpu)

| Measurement | Value |
|---|---|
| Load time | 6.3 s |
| RSS before / after load / peak during benchmark | 47 MB / 482 MB / 1082 MB |
| VRAM | 0 (CPU); not measured on GPU |
| Cold inference, 5 s clip (incl. 44.1→48 kHz resample) | 525 ms |
| Warm inference, 5 s clip | p50 202 ms, p95 224 ms |
| Real 17 s microphone recording (3 windows) | ≈ 0.7 s |
| Embedding | 512-d, L2-normalised |
| Text prompts for 39 vocabulary labels | 306 ms |

## Preprocessing contract (`preprocessing_version = 1`)

Canonical 48 kHz mono float PCM → 10 s windows, 5 s hop (a ≤10 s recording is one window;
a final partial window ≥ 2 s is kept and repeat-padded by the processor) → per-window
`get_audio_features` → L2-normalise → recording embedding = normalised mean. Label score per
window = cosine(audio, text("The sound of …")); recording-level score = max over windows.

## Licensing

- Code: LAION-AI/CLAP is Apache-2.0; `transformers` Apache-2.0; `torch` BSD-3.
- Weights: the Hub model card for `laion/clap-htsat-unfused` states Apache-2.0. The model was
  trained on LAION-Audio-630K and AudioSet whose underlying clips carry mixed licences.
  THE UNHEARD downloads the weights on the user's machine and never redistributes them.
- Evaluation data: ESC-50 (CC BY-NC 3.0) is downloaded into `server/data/eval/` (gitignored)
  for local evaluation only.

## Rejected alternatives (M2 gate)

- **YAMNet**: needs TensorFlow (large wheel) or an unofficial ONNX export; closed 521-class
  vocabulary, so user-named sounds would have no text prior. Not installed.
- **PANNs / AST / BEATs**: also torch-based with no text tower; no advantage over CLAP for
  open-vocabulary naming. Not installed.
- **GPU**: the laptop reported in doc 01 (RTX 4050, 6 GB) is actually an RTX 3050 Ti with
  4 GB; CPU latency (~0.2 s per 10 s window) is already well under the doc 03 target, so the
  CUDA wheel set (~3 GB) was not installed.
