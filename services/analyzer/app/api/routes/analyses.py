"""Analysis endpoints. Business logic lives in app.services.analysis."""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    get_analysis_pipeline,
    get_analysis_slots,
    get_analysis_store,
    get_app_settings,
)
from app.config import Settings
from app.errors import TooManyRequestsError
from app.graph.paths import DEFAULT_MAX_DEPTH, DEFAULT_MAX_PATHS, MAX_DEPTH_LIMIT, MAX_PATHS_LIMIT
from app.models.analysis import AnalysisSummary
from app.models.api import AnalyzeRequest, SourceResponse
from app.models.common import RepoPath
from app.models.findings import FindingsResponse, Severity
from app.models.graph import GraphResponse, NodeId, PathsResponse
from app.services.analysis import (
    DEFAULT_FINDINGS_LIMIT,
    MAX_FINDINGS_LIMIT,
    AnalysisPipeline,
    analyze_repository,
    findings_response,
    get_analysis,
    graph_response,
    paths_response,
    source_response,
)
from app.storage.memory import AnalysisStore

router = APIRouter(tags=["analyses"])

RETRY_AFTER_SECONDS = 30

DEFAULT_GRAPH_NODES = 2_000
MAX_GRAPH_NODES = 20_000
DEFAULT_UNRESOLVED = 500
MAX_UNRESOLVED = 5_000

Store = Annotated[AnalysisStore, Depends(get_analysis_store)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
Pipeline = Annotated[AnalysisPipeline, Depends(get_analysis_pipeline)]
Slots = Annotated[threading.BoundedSemaphore, Depends(get_analysis_slots)]


@router.post(
    "/analyze",
    response_model=AnalysisSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a public repository (synchronous)",
)
def analyze(
    body: AnalyzeRequest,
    response: Response,
    settings: AppSettings,
    store: Store,
    pipeline: Pipeline,
    slots: Slots,
) -> AnalysisSummary:
    """Clone, parse and graph a repository, then store the result.

    Blocks until done; bounded by ``clone_timeout_seconds`` plus
    ``parse_time_budget_seconds``. Check ``status`` in the response:
    ``failed`` analyses are stored too, with ``error`` set.
    """
    if not slots.acquire(blocking=False):
        raise TooManyRequestsError(
            "Too many analyses are running; retry shortly",
            code="too_many_analyses",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )
    try:
        analysis = analyze_repository(body, settings, pipeline)
    finally:
        slots.release()
    store.save(analysis)
    response.headers["Location"] = f"/api/analyses/{analysis.analysis_id}"
    return analysis.summary


@router.get("/analyses/{analysis_id}", response_model=AnalysisSummary)
def get_analysis_summary(analysis_id: str, store: Store) -> AnalysisSummary:
    return get_analysis(store, analysis_id).summary


@router.get("/analyses/{analysis_id}/graph", response_model=GraphResponse)
def get_graph(
    analysis_id: str,
    store: Store,
    path_prefix: Annotated[
        RepoPath | None, Query(description="Only functions in this directory or file")
    ] = None,
    max_nodes: Annotated[int, Query(ge=1, le=MAX_GRAPH_NODES)] = DEFAULT_GRAPH_NODES,
    max_unresolved: Annotated[int, Query(ge=0, le=MAX_UNRESOLVED)] = DEFAULT_UNRESOLVED,
) -> GraphResponse:
    analysis = get_analysis(store, analysis_id)
    return graph_response(
        analysis, path_prefix=path_prefix, max_nodes=max_nodes, max_unresolved=max_unresolved
    )


@router.get("/analyses/{analysis_id}/paths", response_model=PathsResponse)
def get_paths(
    analysis_id: str,
    store: Store,
    source: Annotated[NodeId, Query(description="Function id where paths start")],
    target: Annotated[NodeId, Query(description="Function id where paths end")],
    max_depth: Annotated[int, Query(ge=1, le=MAX_DEPTH_LIMIT)] = DEFAULT_MAX_DEPTH,
    max_paths: Annotated[int, Query(ge=1, le=MAX_PATHS_LIMIT)] = DEFAULT_MAX_PATHS,
) -> PathsResponse:
    analysis = get_analysis(store, analysis_id)
    return paths_response(
        analysis, source=source, target=target, max_depth=max_depth, max_paths=max_paths
    )


MAX_LINE_NUMBER = 10_000_000
RuleIdFilter = Annotated[
    str | None, Query(max_length=100, pattern=r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
]


@router.get("/analyses/{analysis_id}/source", response_model=SourceResponse)
def get_source(
    analysis_id: str,
    store: Store,
    path: Annotated[RepoPath, Query(description="Repository-relative path of an analyzed file")],
    start_line: Annotated[int, Query(ge=1, le=MAX_LINE_NUMBER)] = 1,
    end_line: Annotated[int | None, Query(ge=1, le=MAX_LINE_NUMBER)] = None,
) -> SourceResponse:
    analysis = get_analysis(store, analysis_id)
    return source_response(analysis, path=path, start_line=start_line, end_line=end_line)


@router.get("/analyses/{analysis_id}/findings", response_model=FindingsResponse)
def get_findings(
    analysis_id: str,
    store: Store,
    severity: Annotated[Severity | None, Query()] = None,
    rule_id: RuleIdFilter = None,
    path_prefix: Annotated[RepoPath | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_FINDINGS_LIMIT)] = DEFAULT_FINDINGS_LIMIT,
) -> FindingsResponse:
    analysis = get_analysis(store, analysis_id)
    return findings_response(
        analysis, severity=severity, rule_id=rule_id, path_prefix=path_prefix, limit=limit
    )
