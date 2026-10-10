"""Runtime configuration.

All values can be overridden with ``UNHEARD_*`` environment variables (or a ``.env``
file in the working directory). Limits below are the documented M1 limits; see the
repository README section "Limits".
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UNHEARD_", env_file=".env", extra="ignore")

    # Storage
    data_dir: Path = Field(default=Path("data"), description="Root for SQLite + audio files")
    db_filename: str = "unheard.sqlite3"

    # Network
    host: str = "127.0.0.1"
    port: int = 8000
    api_token: str | None = Field(
        default=None,
        description="If set, all /api routes except /api/health require "
        "'Authorization: Bearer <token>'. Use when binding to the LAN.",
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "https://localhost:5173"]
    )

    # Audio limits (doc 03 §1 and doc 08: 3–30 s, 25 MB cap)
    max_upload_bytes: int = 25 * 1024 * 1024
    min_duration_s: float = 3.0
    max_duration_s: float = 30.0
    canonical_sample_rate: int = 48_000
    min_source_sample_rate: int = 8_000
    max_source_sample_rate: int = 192_000
    silence_dbfs: float = -60.0  # RMS below this -> rejected as silent
    clipping_peak: float = 0.99  # |x| >= this counts as clipped
    clipping_flag_ratio: float = 0.005  # >0.5 % clipped samples -> quality flag

    # Tooling
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    ffmpeg_timeout_s: float = 30.0

    # Audio model (M2). "none" disables inference; recordings still get DSP features.
    model_name: str = "laion/clap-htsat-unfused"
    device: str = Field(default="cpu", description="'cpu' or 'cuda' (needs a CUDA torch build)")
    allow_model_download: bool = Field(
        default=False,
        description="Permit downloading weights from the Hugging Face Hub at runtime. "
        "Off by default: fetch once with `uv run unheard fetch-model`.",
    )
    torch_threads: int | None = None
    auto_infer: bool = Field(default=True, description="Queue model inference after DSP")
    # Memory / fusion (empirical; see docs/M2-REPORT.md)
    fusion_k: int = 7
    fusion_t_mem: float = 0.07
    fusion_kappa: float = 3.0
    fusion_t_base: float = 0.05
    fusion_tau_novel: float = 0.55
    fusion_tau_margin: float = 0.60
    fusion_tau_entropy: float = 0.25
    fusion_tau_memory_strong: float = 0.75
    max_label_name_len: int = 48
    max_labels_per_annotation: int = 6
    max_descriptors: int = 10

    # M5 narrative: local Gemma via Ollama (words only; state comes from the database)
    narrative_gemma: bool = Field(
        default=True, description="Allow Gemma narration (the player can also toggle it)"
    )
    narrative_runtime_url: str = "http://127.0.0.1:11434"
    narrative_model: str = Field(
        default="",
        description="Ollama model tag. Empty = first installed of narrative_model_preference.",
    )
    narrative_model_preference: list[str] = Field(
        default_factory=lambda: ["gemma3:4b", "gemma4:e4b-it-qat"]
    )
    narrative_timeout_s: float = 30.0  # per generation attempt (includes a cold model load)
    narrative_max_output_tokens: int = 220
    narrative_keep_alive: str = "2m"  # how long Ollama keeps the model in RAM after a call
    narrative_num_ctx: int = 2048
    narrative_temperature: float = 0.7

    # Processing
    worker_enabled: bool = True
    worker_poll_s: float = 0.25
    max_job_attempts: int = 3

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
