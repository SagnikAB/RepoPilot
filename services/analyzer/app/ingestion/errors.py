"""Ingestion failures. Messages are safe to show to API clients."""

from __future__ import annotations

from app.errors import AppError


class IngestionError(AppError):
    status_code = 500
    code = "ingestion_failed"


class InvalidRepositoryUrlError(IngestionError):
    status_code = 400
    code = "invalid_repository_url"


class RepositoryUnavailableError(IngestionError):
    status_code = 502
    code = "repository_unavailable"


class RefNotFoundError(IngestionError):
    status_code = 404
    code = "ref_not_found"


class RepositoryTooLargeError(IngestionError):
    status_code = 413
    code = "repository_too_large"


class CloneTimeoutError(IngestionError):
    status_code = 504
    code = "clone_timeout"


class GitUnavailableError(IngestionError):
    status_code = 503
    code = "git_unavailable"
