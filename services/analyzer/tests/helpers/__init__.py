"""Shared test utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings
from app.graph.builder import CallGraph, build_call_graph
from app.ingestion.types import SourceFile
from app.parsers.languages import grammar_for_path
from app.parsers.service import parse_source_file
from app.parsers.types import FileExtraction

TESTS_DIR = Path(__file__).resolve().parents[1]
FIXTURE_REPOS = TESTS_DIR / "fixtures" / "repos"


def make_settings(**overrides: Any) -> Settings:
    """Settings isolated from any local .env; parsing in-process unless overridden."""
    values: dict[str, Any] = {"parse_isolation": "inprocess"} | overrides
    return Settings(_env_file=None, **values)


def source_file(path: str, text: str) -> SourceFile:
    grammar = grammar_for_path(path)
    assert grammar is not None, f"unsupported test path {path}"
    return SourceFile(path, grammar, text, len(text.encode("utf-8")))


def extract(path: str, text: str, **overrides: Any) -> FileExtraction:
    return parse_source_file(source_file(path, text), make_settings(**overrides))


def build_graph(sources: dict[str, str], **overrides: Any) -> CallGraph:
    """Parse ``{path: code}`` in-process and build the call graph."""
    settings = make_settings(**overrides)
    files = [parse_source_file(source_file(p, code), settings) for p, code in sources.items()]
    return build_call_graph(files, settings)


def describe_edges(graph: CallGraph) -> set[tuple[str, str, str]]:
    """Edges as ``("file:qualified", "file:qualified", resolution)`` for readable asserts."""
    return {
        (_label(graph, e.source), _label(graph, e.target), e.resolution.value) for e in graph.edges
    }


def describe_unresolved(graph: CallGraph) -> dict[str, str]:
    """``{callee text: reason}`` (callee texts are unique in the tests that use this)."""
    return {u.callee: u.reason.value for u in graph.unresolved}


def _label(graph: CallGraph, node_id: str) -> str:
    node = graph.nodes[node_id]
    return f"{node.path}:{node.qualified_name}"
