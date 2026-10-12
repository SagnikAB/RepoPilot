"""Ingestion entry point: validate, clone into a temp workspace, scan, clean up."""

from __future__ import annotations

import logging
import time

from app.config import Settings
from app.ingestion.git import Cloner, GitCloner
from app.ingestion.network import Resolver, ensure_public_host, system_resolver
from app.ingestion.scanner import scan_repository
from app.ingestion.types import IngestedRepository
from app.ingestion.url import parse_repository_url
from app.ingestion.workspace import temporary_workspace
from app.models.analysis import RepositoryInfo

logger = logging.getLogger(__name__)


def ingest_repository(
    repo_url: str,
    ref: str | None,
    settings: Settings,
    *,
    cloner: Cloner | None = None,
    resolver: Resolver = system_resolver,
) -> IngestedRepository:
    """Clone a public repository and load its analyzable source files into memory.

    The workspace is deleted before returning, on success and on failure.
    Raises an ``IngestionError`` subclass with a client-safe message on failure.
    """
    url = parse_repository_url(repo_url, settings.allowed_git_hosts)
    ensure_public_host(url.host, resolver)
    cloner = cloner or GitCloner(settings)

    started = time.monotonic()
    logger.info("Ingesting %s/%s/%s (ref=%s)", url.host, url.owner, url.name, ref or "default")
    with temporary_workspace(settings.workspace_root) as workspace:
        checkout = workspace / "repo"
        clone = cloner.clone(url.clone_url, checkout, ref)
        files, report = scan_repository(checkout, settings)

    logger.info(
        "Ingested %s/%s: %d source files, %d skipped, %.2fs",
        url.owner,
        url.name,
        len(files),
        report.files_skipped,
        time.monotonic() - started,
    )
    repository = RepositoryInfo(
        url=url.canonical_url,
        host=url.host,
        owner=url.owner,
        name=url.name,
        ref=ref,
        commit_sha=clone.commit_sha,
    )
    return IngestedRepository(repository=repository, files=files, scan=report)
