"""End-to-end ingestion with a fake cloner (no network, no git)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.errors import InvalidRepositoryUrlError, RepositoryUnavailableError
from app.ingestion.service import ingest_repository
from app.ingestion.workspace import temporary_workspace
from app.parsers.service import parse_repository
from tests.helpers import FIXTURE_REPOS, make_settings
from tests.helpers.fakes import FAKE_SHA as SHA
from tests.helpers.fakes import PUBLIC_ADDRESSES as PUBLIC
from tests.helpers.fakes import FakeCloner


def test_ingest_fixture_repository(tmp_path: Path) -> None:
    cloner = FakeCloner(FIXTURE_REPOS / "shop_api")
    settings = make_settings(workspace_root=tmp_path)

    ingested = ingest_repository(
        "https://github.com/acme/shop-api.git",
        "main",
        settings,
        cloner=cloner,
        resolver=lambda host: PUBLIC,
    )

    assert cloner.calls[0][0] == "https://github.com/acme/shop-api.git"
    assert cloner.calls[0][2] == "main"
    repo = ingested.repository
    assert (repo.url, repo.owner, repo.name, repo.ref, repo.commit_sha) == (
        "https://github.com/acme/shop-api",
        "acme",
        "shop-api",
        "main",
        SHA,
    )
    assert sorted(f.path for f in ingested.files) == [
        "src/auth/session.ts",
        "src/db.ts",
        "src/server.ts",
    ]
    assert ingested.scan.files_skipped == 2  # README.md, package.json
    assert list(tmp_path.iterdir()) == []  # workspace removed


def test_ingested_files_parse(tmp_path: Path) -> None:
    settings = make_settings(workspace_root=tmp_path)
    ingested = ingest_repository(
        "https://github.com/acme/shop-api",
        None,
        settings,
        cloner=FakeCloner(FIXTURE_REPOS / "shop_api"),
        resolver=lambda host: PUBLIC,
    )

    parsed = parse_repository(ingested.files, settings)

    assert len(parsed.files) == 3
    assert parsed.failed_files == []
    assert sum(len(f.functions) for f in parsed.files) == 9


def test_workspace_removed_when_clone_fails(tmp_path: Path) -> None:
    cloner = FakeCloner(error=RepositoryUnavailableError("nope"))

    with pytest.raises(RepositoryUnavailableError):
        ingest_repository(
            "https://github.com/acme/missing",
            None,
            make_settings(workspace_root=tmp_path),
            cloner=cloner,
            resolver=lambda host: PUBLIC,
        )
    assert list(tmp_path.iterdir()) == []


def test_invalid_url_fails_before_any_network_or_clone(tmp_path: Path) -> None:
    cloner = FakeCloner(FIXTURE_REPOS / "shop_api")

    def resolver(host: str) -> list[str]:
        raise AssertionError("must not resolve")

    with pytest.raises(InvalidRepositoryUrlError):
        ingest_repository(
            "https://github.com/acme/shop-api?x=1",
            None,
            make_settings(workspace_root=tmp_path),
            cloner=cloner,
            resolver=resolver,
        )
    assert cloner.calls == []


def test_private_resolution_blocks_clone(tmp_path: Path) -> None:
    cloner = FakeCloner(FIXTURE_REPOS / "shop_api")

    with pytest.raises(InvalidRepositoryUrlError):
        ingest_repository(
            "https://github.com/acme/shop-api",
            None,
            make_settings(workspace_root=tmp_path),
            cloner=cloner,
            resolver=lambda host: ["10.0.0.1"],
        )
    assert cloner.calls == []


def test_temporary_workspace_cleans_up_on_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), temporary_workspace(tmp_path) as workspace:
        (workspace / "file.txt").write_text("data")
        (workspace / "ro").mkdir()
        (workspace / "ro" / "pack").write_text("x")
        (workspace / "ro" / "pack").chmod(0o444)
        raise RuntimeError("boom")

    assert list(tmp_path.iterdir()) == []
