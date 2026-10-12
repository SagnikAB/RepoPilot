"""Domain errors. Each maps to an HTTP status and a stable error ``code``.

Defined outside ``app.api`` so ingestion, parsing and other services can raise
them without depending on the HTTP layer.
"""

from __future__ import annotations

from app.models.api import ErrorDetail


class AppError(Exception):
    """Base class for errors that map to a specific HTTP response."""

    status_code = 500
    code = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: list[ErrorDetail] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details
        self.headers = headers


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class InvalidRequestError(AppError):
    status_code = 400
    code = "invalid_request"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class TooManyRequestsError(AppError):
    status_code = 429
    code = "too_many_requests"
