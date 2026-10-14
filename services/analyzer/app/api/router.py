"""Aggregates all /api routes. Coordinate with Member 2 before adding routes here."""

from fastapi import APIRouter

from app.api.routes import analyses, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(analyses.router)
