"""Application factory and ASGI entry point (`uvicorn app.main:app`)."""

from __future__ import annotations

import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.config import Settings, get_settings
from app.logging_config import configure_logging
from app.services.analysis import AnalysisPipeline
from app.storage.memory import InMemoryAnalysisStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RepoPilot Analyzer",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.analysis_store = InMemoryAnalysisStore(
        settings.max_stored_analyses, settings.max_stored_source_bytes
    )
    app.state.analysis_pipeline = AnalysisPipeline()
    app.state.analysis_slots = threading.BoundedSemaphore(settings.max_concurrent_analyses)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
