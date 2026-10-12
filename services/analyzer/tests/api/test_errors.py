"""Every failure must be rendered with the shared ErrorResponse envelope."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from app.api.errors import InvalidRequestError, NotFoundError
from app.models.api import ErrorResponse


@pytest.fixture
def client_with_probe_routes(app: FastAPI) -> TestClient:
    @app.get("/probe/not-found")
    def not_found() -> None:
        raise NotFoundError("No analysis exists", code="analysis_not_found")

    @app.get("/probe/invalid")
    def invalid() -> None:
        raise InvalidRequestError("Bad input")

    @app.get("/probe/validated")
    def validated(limit: int = Query(ge=1, le=10)) -> dict[str, int]:
        return {"limit": limit}

    @app.get("/probe/crash")
    def crash() -> None:
        raise RuntimeError("secret internal detail")

    return TestClient(app, raise_server_exceptions=False)


def _error(response_json: object) -> ErrorResponse:
    return ErrorResponse.model_validate(response_json)


def test_unknown_route_returns_error_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert _error(response.json()).error.code == "not_found"


def test_app_error_uses_its_status_and_code(client_with_probe_routes: TestClient) -> None:
    response = client_with_probe_routes.get("/probe/not-found")

    assert response.status_code == 404
    error = _error(response.json()).error
    assert error.code == "analysis_not_found"
    assert error.message == "No analysis exists"


def test_invalid_request_error_is_400(client_with_probe_routes: TestClient) -> None:
    response = client_with_probe_routes.get("/probe/invalid")

    assert response.status_code == 400
    assert _error(response.json()).error.code == "invalid_request"


def test_validation_error_lists_details_without_echoing_input(
    client_with_probe_routes: TestClient,
) -> None:
    response = client_with_probe_routes.get("/probe/validated", params={"limit": "999"})

    assert response.status_code == 422
    error = _error(response.json()).error
    assert error.code == "validation_error"
    assert error.details is not None
    assert error.details[0].loc == ["query", "limit"]
    assert "999" not in response.text


def test_missing_query_param_is_validation_error(client_with_probe_routes: TestClient) -> None:
    response = client_with_probe_routes.get("/probe/validated")

    assert response.status_code == 422
    assert _error(response.json()).error.code == "validation_error"


def test_unexpected_error_is_generic_500(client_with_probe_routes: TestClient) -> None:
    response = client_with_probe_routes.get("/probe/crash")

    assert response.status_code == 500
    error = _error(response.json()).error
    assert error.code == "internal_error"
    assert "secret internal detail" not in response.text
