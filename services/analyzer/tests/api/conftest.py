"""Shared API fixtures: an app wired to the real pipeline with fake cloning only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.parsers.file_parser import ParseFn, parse_source_file
from app.services.analysis import AnalysisPipeline
from tests.helpers import FIXTURE_REPOS, make_settings
from tests.helpers.fakes import ClientFactory, fake_ingestor


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "workspaces"
    root.mkdir()
    return root


@pytest.fixture
def make_client(workspace_root: Path) -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def factory(
        source: Path | None = FIXTURE_REPOS / "shop_api",
        *,
        error: Exception | None = None,
        parse_fn: ParseFn = parse_source_file,
        **overrides: Any,
    ) -> TestClient:
        app = create_app(make_settings(workspace_root=workspace_root, **overrides))
        app.state.analysis_pipeline = AnalysisPipeline(
            ingest=fake_ingestor(source, error), parse_fn=parse_fn
        )
        client = TestClient(app, raise_server_exceptions=False)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
