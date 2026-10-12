"""FastAPI dependencies shared by route modules."""

from __future__ import annotations

import threading
from typing import cast

from fastapi import Request

from app.config import Settings
from app.services.analysis import AnalysisPipeline
from app.storage.memory import AnalysisStore


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_analysis_store(request: Request) -> AnalysisStore:
    return cast(AnalysisStore, request.app.state.analysis_store)


def get_analysis_pipeline(request: Request) -> AnalysisPipeline:
    return cast(AnalysisPipeline, request.app.state.analysis_pipeline)


def get_analysis_slots(request: Request) -> threading.BoundedSemaphore:
    """Limits concurrent synchronous analyses (each spawns git and a parser worker)."""
    return cast(threading.BoundedSemaphore, request.app.state.analysis_slots)
