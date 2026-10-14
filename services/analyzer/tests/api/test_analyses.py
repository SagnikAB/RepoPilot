"""GET /api/analyses/{id}/graph and /paths against a real fixture analysis."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.api import ErrorResponse
from app.models.graph import GraphResponse, PathsResponse
from app.storage.memory import StoredAnalysis
from tests.helpers.fakes import analyze_fixture, require_graph


@pytest.fixture(scope="module")
def analysis() -> StoredAnalysis:
    return analyze_fixture()


@pytest.fixture
def stored(app: FastAPI, analysis: StoredAnalysis) -> StoredAnalysis:
    app.state.analysis_store.save(analysis)
    return analysis


def _id(analysis: StoredAnalysis, qualified_name: str) -> str:
    return next(
        n.id for n in require_graph(analysis).nodes.values() if n.qualified_name == qualified_name
    )


def _error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert ErrorResponse.model_validate(response.json()).error.code == code


# -- graph -------------------------------------------------------------------------------


def test_graph_returns_the_stored_graph(client: TestClient, stored: StoredAnalysis) -> None:
    response = client.get(f"/api/analyses/{stored.analysis_id}/graph")

    assert response.status_code == 200
    body = GraphResponse.model_validate(response.json())
    assert body.analysis_id == stored.analysis_id
    assert [n.id for n in body.nodes] == list(require_graph(stored).nodes)
    assert body.edges == require_graph(stored).edges
    assert body.unresolved_calls == require_graph(stored).unresolved
    assert body.unresolved_calls_total == len(require_graph(stored).unresolved)
    node_ids = {n.id for n in body.nodes}
    assert all(e.source in node_ids and e.target in node_ids for e in body.edges)
    assert not body.truncated


def test_graph_is_identical_across_requests(client: TestClient, stored: StoredAnalysis) -> None:
    url = f"/api/analyses/{stored.analysis_id}/graph"

    assert client.get(url).json() == client.get(url).json()


def test_graph_path_prefix_keeps_a_consistent_subgraph(
    client: TestClient, stored: StoredAnalysis
) -> None:
    response = client.get(
        f"/api/analyses/{stored.analysis_id}/graph", params={"path_prefix": "src/auth"}
    )

    body = GraphResponse.model_validate(response.json())
    assert {n.path for n in body.nodes} == {"src/auth/session.ts"}
    node_ids = {n.id for n in body.nodes}
    assert all(e.source in node_ids and e.target in node_ids for e in body.edges)
    assert all(u.caller_id in node_ids for u in body.unresolved_calls)
    assert any("Filtered to 'src/auth'" in item for item in body.limitations)


def test_graph_node_and_unresolved_limits(client: TestClient, stored: StoredAnalysis) -> None:
    response = client.get(
        f"/api/analyses/{stored.analysis_id}/graph", params={"max_nodes": 2, "max_unresolved": 1}
    )

    body = GraphResponse.model_validate(response.json())
    assert len(body.nodes) == 2 and body.truncated
    assert len(body.unresolved_calls) == 1
    assert body.unresolved_calls_total >= 1


@pytest.mark.parametrize(
    "params",
    [
        {"max_nodes": 0},
        {"max_nodes": 20_001},
        {"max_unresolved": -1},
        {"path_prefix": "../etc"},
        {"path_prefix": "/abs"},
        {"path_prefix": "src/"},
    ],
)
def test_graph_rejects_invalid_parameters(
    client: TestClient, stored: StoredAnalysis, params: dict[str, Any]
) -> None:
    _error(
        client.get(f"/api/analyses/{stored.analysis_id}/graph", params=params),
        422,
        "validation_error",
    )


@pytest.mark.parametrize("analysis_id", ["0" * 32, "not-an-id", "A" * 32, "x" * 500])
def test_graph_unknown_or_malformed_analysis_is_404(
    client: TestClient, stored: StoredAnalysis, analysis_id: str
) -> None:
    _error(client.get(f"/api/analyses/{analysis_id}/graph"), 404, "analysis_not_found")


def test_traversal_in_analysis_id_never_reaches_the_handler(client: TestClient) -> None:
    # The URL is normalized before routing, so no analysis route matches.
    _error(client.get("/api/analyses/../../etc/graph"), 404, "not_found")


# -- paths ------------------------------------------------------------------------------------


def test_paths_returns_real_node_and_edge_ids(client: TestClient, stored: StoredAnalysis) -> None:
    source, target = _id(stored, "handleLogin"), _id(stored, "runQuery")

    response = client.get(
        f"/api/analyses/{stored.analysis_id}/paths", params={"source": source, "target": target}
    )

    assert response.status_code == 200
    body = PathsResponse.model_validate(response.json())
    assert (body.source, body.target, body.max_depth, body.max_paths) == (source, target, 8, 10)
    [path] = body.paths
    assert path.node_ids == [source, _id(stored, "findUserByEmail"), target]
    edges = {e.id: e for e in require_graph(stored).edges}
    for i, edge in enumerate(path.edge_ids):
        assert (edges[edge].source, edges[edge].target) == (path.node_ids[i], path.node_ids[i + 1])
    assert any("does not prove" in item for item in body.limitations)
    assert any("unresolved call(s)" in item for item in body.limitations)


def test_paths_source_equals_target(client: TestClient, stored: StoredAnalysis) -> None:
    node = _id(stored, "runQuery")

    response = client.get(
        f"/api/analyses/{stored.analysis_id}/paths", params={"source": node, "target": node}
    )

    body = PathsResponse.model_validate(response.json())
    assert [(p.node_ids, p.edge_ids) for p in body.paths] == [([node], [])]


def test_paths_no_path(client: TestClient, stored: StoredAnalysis) -> None:
    response = client.get(
        f"/api/analyses/{stored.analysis_id}/paths",
        params={"source": _id(stored, "runQuery"), "target": _id(stored, "handleLogin")},
    )

    body = PathsResponse.model_validate(response.json())
    assert body.paths == [] and not body.truncated


def test_paths_respect_max_depth(client: TestClient, stored: StoredAnalysis) -> None:
    params = {
        "source": _id(stored, "handleLogin"),
        "target": _id(stored, "runQuery"),
        "max_depth": 1,
    }

    body = PathsResponse.model_validate(
        client.get(f"/api/analyses/{stored.analysis_id}/paths", params=params).json()
    )

    assert body.paths == [] and body.max_depth == 1


def test_paths_unknown_function_is_404(client: TestClient, stored: StoredAnalysis) -> None:
    params = {"source": "fn_0000000000000000", "target": _id(stored, "runQuery")}

    _error(
        client.get(f"/api/analyses/{stored.analysis_id}/paths", params=params),
        404,
        "function_not_found",
    )


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"source": "fn_0000000000000000"},
        {"source": "not-an-id", "target": "fn_0000000000000000"},
        {"source": "fn_0000000000000000", "target": "fn_0000000000000000", "max_depth": 0},
        {"source": "fn_0000000000000000", "target": "fn_0000000000000000", "max_depth": 21},
        {"source": "fn_0000000000000000", "target": "fn_0000000000000000", "max_paths": 101},
    ],
)
def test_paths_reject_invalid_parameters(
    client: TestClient, stored: StoredAnalysis, params: dict[str, Any]
) -> None:
    _error(
        client.get(f"/api/analyses/{stored.analysis_id}/paths", params=params),
        422,
        "validation_error",
    )


def test_paths_unknown_analysis_is_404(client: TestClient) -> None:
    params = {"source": "fn_0000000000000000", "target": "fn_0000000000000000"}

    _error(client.get(f"/api/analyses/{'0' * 32}/paths", params=params), 404, "analysis_not_found")
