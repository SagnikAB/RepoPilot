"""Contract tests: fixtures in docs/fixtures must always validate against the models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.models import (
    AnalysisSummary,
    AnalyzeRequest,
    CallPath,
    ErrorResponse,
    FindingsResponse,
    FunctionNode,
    GraphResponse,
    PathsResponse,
    SourceReference,
    SourceResponse,
    ids,
)

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "fixtures"

FIXTURE_MODELS: dict[str, type[BaseModel]] = {
    "analyze_request.json": AnalyzeRequest,
    "analysis_summary.json": AnalysisSummary,
    "analysis_failed.json": AnalysisSummary,
    "graph.json": GraphResponse,
    "findings.json": FindingsResponse,
    "source.json": SourceResponse,
    "paths.json": PathsResponse,
    "error.json": ErrorResponse,
}


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_every_fixture_has_a_model() -> None:
    assert {p.name for p in FIXTURES.glob("*.json")} == set(FIXTURE_MODELS)


@pytest.mark.parametrize(("name", "model"), FIXTURE_MODELS.items())
def test_fixture_validates(name: str, model: type[BaseModel]) -> None:
    model.model_validate(_load(name))


def test_graph_fixture_is_internally_consistent() -> None:
    graph = GraphResponse.model_validate(_load("graph.json"))
    node_ids = {node.id for node in graph.nodes}

    for node in graph.nodes:
        expected = ids.function_id(
            node.path, node.qualified_name, node.start_line, node.start_column
        )
        assert node.id == expected
    for edge in graph.edges:
        assert {edge.source, edge.target} <= node_ids
        assert edge.id == ids.edge_id(edge.source, edge.target)
    assert {call.caller_id for call in graph.unresolved_calls} <= node_ids


def test_paths_and_findings_fixtures_reference_graph() -> None:
    graph = GraphResponse.model_validate(_load("graph.json"))
    paths = PathsResponse.model_validate(_load("paths.json"))
    findings = FindingsResponse.model_validate(_load("findings.json"))
    node_ids = {node.id for node in graph.nodes}
    edges = {edge.id: edge for edge in graph.edges}

    for path in paths.paths:
        assert path.node_ids[0] == paths.source
        assert path.node_ids[-1] == paths.target
        for i, edge_id in enumerate(path.edge_ids):
            assert (edges[edge_id].source, edges[edge_id].target) == (
                path.node_ids[i],
                path.node_ids[i + 1],
            )
    for finding in findings.findings:
        assert finding.function_id is None or finding.function_id in node_ids


@pytest.mark.parametrize(
    "path",
    ["", "/etc/passwd", "../secret", "src/../../x", "src//a.ts", "./src/a.ts", "src\\a.ts"],
)
def test_source_reference_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        SourceReference(path=path, start_line=1, end_line=1)


def test_source_reference_rejects_inverted_range() -> None:
    with pytest.raises(ValidationError):
        SourceReference(path="src/a.ts", start_line=5, end_line=4)


def test_source_reference_rejects_zero_line() -> None:
    with pytest.raises(ValidationError):
        SourceReference(path="src/a.ts", start_line=0, end_line=1)


def test_function_node_rejects_inverted_range() -> None:
    node = _load("graph.json")["nodes"][0]
    node["end_line"] = node["start_line"] - 1 if node["start_line"] > 1 else 0

    with pytest.raises(ValidationError):
        FunctionNode.model_validate(node)


def test_contracts_reject_unknown_fields() -> None:
    payload = _load("analyze_request.json") | {"token": "ghp_example"}

    with pytest.raises(ValidationError):
        AnalyzeRequest.model_validate(payload)


@pytest.mark.parametrize(
    "ref", ["--upload-pack=evil", "-b", "a..b", "main.lock", "x//y", "a b", ""]
)
def test_analyze_request_rejects_unsafe_refs(ref: str) -> None:
    with pytest.raises(ValidationError):
        AnalyzeRequest(repo_url="https://github.com/a/b", ref=ref)


@pytest.mark.parametrize("ref", ["main", "release/1.2", "v2.0.0", "feature_x-y"])
def test_analyze_request_accepts_normal_refs(ref: str) -> None:
    assert AnalyzeRequest(repo_url="https://github.com/a/b", ref=ref).ref == ref


def test_call_path_requires_n_minus_one_edges() -> None:
    with pytest.raises(ValidationError):
        CallPath(node_ids=["fn_0000000000000000", "fn_1111111111111111"], edge_ids=[])
