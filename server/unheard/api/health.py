from __future__ import annotations

import platform
import shutil

from fastapi import APIRouter, Depends

from unheard import __version__
from unheard.api.deps import Services, get_services
from unheard.api.schemas import HealthResponse
from unheard.dsp import DSP_VERSION
from unheard.storage.repos import RecordingRepo

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(services: Services = Depends(get_services)) -> HealthResponse:
    s = services.settings
    with services.db.connection() as conn:
        count = RecordingRepo.count(conn)
    try:
        free = shutil.disk_usage(s.data_dir).free
    except OSError:
        free = None
    return HealthResponse(
        version=__version__,
        dsp_version=DSP_VERSION,
        schema_version=services.db.schema_version,
        decoder={
            "ffmpeg_available": services.decoder.ffmpeg_available(),
            "ffmpeg_version": services.decoder.ffmpeg_version(),
            "fallback": "soundfile (wav/flac/ogg only)",
        },
        limits={
            "max_upload_bytes": s.max_upload_bytes,
            "min_duration_s": s.min_duration_s,
            "max_duration_s": s.max_duration_s,
            "canonical_sample_rate": s.canonical_sample_rate,
            "silence_dbfs": s.silence_dbfs,
            "supported_containers": ["wav", "webm", "mp4", "ogg", "flac", "mp3"],
        },
        recordings=count,
        free_disk_bytes=free,
        python=platform.python_version(),
    )
