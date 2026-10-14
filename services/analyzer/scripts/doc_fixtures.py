"""Regenerate the generated parts of docs/fixtures from the shop_api fixture repo.

Usage (from services/analyzer):  .venv/bin/python -m scripts.doc_fixtures

Generated from real pipeline output (``build_analysis`` on the fixture repo):
analysis_summary.json, graph.json, paths.json, findings.json and source.json.
Only the analysis ID, timestamps, duration and commit SHA are pinned, because
they are not deterministic. Hand-written examples: error.json,
analysis_failed.json, analyze_request.json.
``tests/unit/test_doc_fixtures.py`` fails if the generated files drift.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.ingestion.scanner import scan_repository
from app.ingestion.types import IngestedRepository
from app.models.analysis import RepositoryInfo
from app.services.analysis import (
    build_analysis,
    findings_response,
    graph_response,
    paths_response,
    source_response,
)
from app.storage.memory import StoredAnalysis

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = ROOT / "tests" / "fixtures" / "repos" / "shop_api"
DOCS_FIXTURES = ROOT / "docs" / "fixtures"

EXAMPLE_ANALYSIS_ID = "4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a"
EXAMPLE_REPOSITORY = RepositoryInfo(
    url="https://github.com/acme/shop-api",
    host="github.com",
    owner="acme",
    name="shop-api",
    ref="main",
    commit_sha="9b2e4c7a1d3f5e6b8c0a2d4f6e8b0c2a4d6f8e0b",
)
EXAMPLE_CREATED_AT = datetime(2026, 10, 12, 9, 15, 2, tzinfo=UTC)
EXAMPLE_COMPLETED_AT = datetime(2026, 10, 12, 9, 15, 6, tzinfo=UTC)
EXAMPLE_DURATION_MS = 4120
PATH_EXAMPLE = ("handleLogin", "runQuery")
SOURCE_EXAMPLE = ("src/db.ts", 5, 10)


def example_analysis(settings: Settings | None = None) -> StoredAnalysis:
    """The documented example analysis, built by the real pipeline from local files."""
    settings = settings or Settings(_env_file=None, parse_isolation="inprocess")
    files, scan = scan_repository(FIXTURE_REPO, settings)
    ingested = IngestedRepository(repository=EXAMPLE_REPOSITORY, files=files, scan=scan)
    analysis = build_analysis(
        ingested, settings, analysis_id=EXAMPLE_ANALYSIS_ID, created_at=EXAMPLE_CREATED_AT
    )
    pinned = analysis.summary.model_copy(
        update={"completed_at": EXAMPLE_COMPLETED_AT, "duration_ms": EXAMPLE_DURATION_MS}
    )
    return dataclasses.replace(analysis, summary=pinned)  # keeps graph, findings, sources


def generate() -> dict[str, Any]:
    """Return ``{file name: JSON value}`` for every generated fixture."""
    analysis = example_analysis()
    if analysis.graph is None:
        raise RuntimeError(f"The example analysis failed: {analysis.summary.error}")
    by_name = {node.qualified_name: node.id for node in analysis.graph.nodes.values()}
    return {
        "analysis_summary.json": analysis.summary.model_dump(mode="json"),
        "graph.json": graph_response(
            analysis, path_prefix=None, max_nodes=2_000, max_unresolved=500
        ).model_dump(mode="json"),
        "paths.json": paths_response(
            analysis,
            source=by_name[PATH_EXAMPLE[0]],
            target=by_name[PATH_EXAMPLE[1]],
            max_depth=8,
            max_paths=10,
        ).model_dump(mode="json"),
        "findings.json": findings_response(analysis).model_dump(mode="json"),
        "source.json": source_response(
            analysis,
            path=SOURCE_EXAMPLE[0],
            start_line=SOURCE_EXAMPLE[1],
            end_line=SOURCE_EXAMPLE[2],
        ).model_dump(mode="json"),
    }


def main() -> None:
    for name, value in generate().items():
        (DOCS_FIXTURES / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        print(f"wrote docs/fixtures/{name}")


if __name__ == "__main__":
    main()
