"""Structured application errors rendered as RFC 7807 ``application/problem+json``.

Every error carries a stable machine-readable ``code`` (doc 08 "Errors").
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status: int = 500
    code: str = "INTERNAL_ERROR"
    retryable: bool = False

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}

    def to_problem(self, instance: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"urn:unheard:error:{self.code.lower()}",
            "title": self.code.replace("_", " ").title(),
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
        }
        if instance:
            body["instance"] = instance
        body.update(self.extra)
        return body


class NotFound(AppError):
    status = 404
    code = "NOT_FOUND"


class Unauthorized(AppError):
    status = 401
    code = "UNAUTHORIZED"


class ValidationFailed(AppError):
    status = 422
    code = "VALIDATION_FAILED"


class AudioRejected(AppError):
    """Base for ingest rejections (422). Subclasses set a stable code."""

    status = 422
    code = "AUDIO_REJECTED"


class AudioEmpty(AudioRejected):
    code = "AUDIO_EMPTY"


class AudioTooLarge(AudioRejected):
    status = 413
    code = "AUDIO_TOO_LARGE"


class AudioUnsupportedFormat(AudioRejected):
    status = 415
    code = "AUDIO_UNSUPPORTED_FORMAT"


class AudioUndecodable(AudioRejected):
    code = "AUDIO_UNDECODABLE"


class AudioTooShort(AudioRejected):
    code = "AUDIO_TOO_SHORT"


class AudioTooLong(AudioRejected):
    code = "AUDIO_TOO_LONG"


class AudioSilent(AudioRejected):
    code = "AUDIO_SILENT"


class AudioBadSampleRate(AudioRejected):
    code = "AUDIO_BAD_SAMPLE_RATE"


class AudioInvalidSamples(AudioRejected):
    code = "AUDIO_INVALID_SAMPLES"


class DuplicateRecording(AppError):
    status = 409
    code = "DUPLICATE_RECORDING"


class DecoderUnavailable(AppError):
    status = 503
    code = "DECODER_UNAVAILABLE"
    retryable = True


class NotReady(AppError):
    status = 409
    code = "NOT_READY"


class ProcessingFailed(AppError):
    status = 500
    code = "PROCESSING_FAILED"
