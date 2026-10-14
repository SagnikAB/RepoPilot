"""The generated documentation fixtures must match real pipeline output."""

from __future__ import annotations

import json

import pytest

from scripts.doc_fixtures import DOCS_FIXTURES, generate


@pytest.mark.parametrize(
    "name",
    ["analysis_summary.json", "graph.json", "paths.json", "findings.json", "source.json"],
)
def test_generated_fixture_is_up_to_date(name: str) -> None:
    documented = json.loads((DOCS_FIXTURES / name).read_text(encoding="utf-8"))

    assert documented == generate()[name], (
        f"docs/fixtures/{name} is stale; run: .venv/bin/python -m scripts.doc_fixtures"
    )


def test_hand_written_findings_reference_real_graph_nodes() -> None:
    graph = json.loads((DOCS_FIXTURES / "graph.json").read_text(encoding="utf-8"))
    findings = json.loads((DOCS_FIXTURES / "findings.json").read_text(encoding="utf-8"))
    node_ids = {node["id"] for node in graph["nodes"]}

    for finding in findings["findings"]:
        assert finding["function_id"] is None or finding["function_id"] in node_ids
