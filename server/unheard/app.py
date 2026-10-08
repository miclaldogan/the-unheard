"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from unheard import __version__
from unheard.api import health, intelligence, recordings
from unheard.api.deps import Services
from unheard.config import Settings, get_settings
from unheard.errors import AppError

log = logging.getLogger(__name__)

PROBLEM = "application/problem+json"


def create_app(settings: Settings | None = None, *, web_dist: Path | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = Services.build(settings)
        app.state.services = services
        if settings.worker_enabled:
            services.worker.start()
        log.info("unheard %s ready; data_dir=%s", __version__, settings.data_dir.resolve())
        try:
            yield
        finally:
            services.close()

    app = FastAPI(
        title="THE UNHEARD",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(recordings.router, prefix="/api")
    app.include_router(intelligence.router, prefix="/api")

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            exc.to_problem(str(request.url.path)), status_code=exc.status, media_type=PROBLEM
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = {
            "type": "urn:unheard:error:validation_failed",
            "title": "Validation Failed",
            "status": 422,
            "detail": "request validation failed",
            "code": "VALIDATION_FAILED",
            "errors": jsonable_encoder(exc.errors(), custom_encoder={Exception: str}),
            "instance": str(request.url.path),
        }
        return JSONResponse(body, status_code=422, media_type=PROBLEM)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            AppError("internal server error").to_problem(str(request.url.path)),
            status_code=500,
            media_type=PROBLEM,
        )

    dist = (
        web_dist if web_dist is not None else Path(__file__).resolve().parents[2] / "web" / "dist"
    )
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


app = create_app()
