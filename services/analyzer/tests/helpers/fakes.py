"""Test doubles for ingestion (no network, no git)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.graph.builder import CallGraph
from app.ingestion.git import CloneResult
from app.ingestion.service import ingest_repository
from app.ingestion.types import IngestedRepository
from app.services.analysis import Ingestor, build_analysis
from app.storage.memory import StoredAnalysis
from tests.helpers import FIXTURE_REPOS, make_settings

PUBLIC_ADDRESSES = ["140.82.112.3"]
FAKE_SHA = "0" * 39 + "1"


class FakeCloner:
    """Copies a local directory instead of cloning."""

    def __init__(self, source: Path | None = None, error: Exception | None = None) -> None:
        self.source = source
        self.error = error
        self.calls: list[tuple[str, Path, str | None]] = []

    def clone(self, url: str, dest: Path, ref: str | None) -> CloneResult:
        self.calls.append((url, dest, ref))
        if self.error is not None:
            raise self.error
        assert self.source is not None
        shutil.copytree(self.source, dest, symlinks=True)
        return CloneResult(commit_sha=FAKE_SHA)


def analyze_fixture(name: str = "shop_api", **overrides: Any) -> StoredAnalysis:
    """Run ingestion, parsing and graph building on a fixture repository."""
    settings = make_settings(**overrides)
    ingested = ingest_repository(
        f"https://github.com/acme/{name.replace('_', '-')}",
        "main",
        settings,
        cloner=FakeCloner(FIXTURE_REPOS / name),
        resolver=lambda host: PUBLIC_ADDRESSES,
    )
    return build_analysis(ingested, settings)


def require_graph(analysis: StoredAnalysis) -> CallGraph:
    assert analysis.graph is not None, f"analysis failed: {analysis.summary.error}"
    return analysis.graph


def fake_ingestor(source: Path | None = None, error: Exception | None = None) -> Ingestor:
    """The real ingestion service (validation, workspace, scan, cleanup) with a fake clone."""
    cloner = FakeCloner(source, error)

    def ingest(repo_url: str, ref: str | None, settings: Settings) -> IngestedRepository:
        return ingest_repository(
            repo_url, ref, settings, cloner=cloner, resolver=lambda host: PUBLIC_ADDRESSES
        )

    ingest.cloner = cloner  # type: ignore[attr-defined]  # lets tests inspect clone calls
    return ingest


ClientFactory = Callable[..., TestClient]


def write_repo(root: Path, files: dict[str, str | bytes], base: Path | None = None) -> Path:
    """Create a repository directory (optionally copying ``base``) with extra files."""
    if base is not None:
        shutil.copytree(base, root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return root
