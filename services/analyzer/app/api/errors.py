"""Exception handlers that render every failure as an ErrorResponse."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import AppError, InvalidRequestError, NotFoundError
from app.models.api import ErrorBody, ErrorDetail, ErrorResponse

__all__ = ["AppError", "InvalidRequestError", "NotFoundError", "register_exception_handlers"]

logger = logging.getLogger(__name__)

_HTTP_STATUS_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    429: "too_many_requests",
    415: "unsupported_media_type",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=headers,
    )


# Starlette types handlers as taking ``Exception``; each one below is only
# registered for the class it casts to.


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    app_exc = cast(AppError, exc)
    return error_response(
        app_exc.status_code, app_exc.code, app_exc.message, app_exc.details, app_exc.headers
    )


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(StarletteHTTPException, exc)
    code = _HTTP_STATUS_CODES.get(http_exc.status_code, "http_error")
    message = http_exc.detail if isinstance(http_exc.detail, str) else "Request failed"
    return error_response(http_exc.status_code, code, message, headers=http_exc.headers)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    validation_exc = cast(RequestValidationError, exc)
    # The offending input is deliberately not echoed back: it may contain
    # credentials (for example a token embedded in a repository URL).
    details = [_to_error_detail(error) for error in validation_exc.errors()]
    return error_response(422, "validation_error", "Request validation failed", details)


async def _handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s", type(exc).__name__)
    return error_response(500, "internal_error", "An unexpected error occurred")


def _to_error_detail(error: Any) -> ErrorDetail:
    loc = [part for part in error.get("loc", ()) if isinstance(part, str | int)]
    return ErrorDetail(loc=loc or None, message=str(error.get("msg", "")), type=error.get("type"))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
