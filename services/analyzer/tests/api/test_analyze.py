"""End-to-end: POST /api/analyze -> GET summary/graph/paths, with fake cloning only.

Everything except the network clone is real: URL validation, the temporary
workspace and its cleanup, scanning, parsing (in-process or worker), call
resolution, graph building and storage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingestion.errors import (
    CloneTimeoutError,
    RefNotFoundError,
    RepositoryTooLargeError,
    RepositoryUnavailableError,
)
from app.main import create_app
from app.models.analysis import AnalysisSummary, SkipReason
from app.models.api import ErrorResponse
from app.models.findings import Severity
from app.models.graph import GraphResponse, PathsResponse
from app.parsers.file_parser import ParseFn, parse_source_file
from app.services import analysis as analysis_service
from app.services.analysis import (
    FINDINGS_NOT_COMPUTED_WARNING,
    NO_FILES_WARNING,
)
from tests.helpers import FIXTURE_REPOS, TESTS_DIR
from tests.helpers.fakes import FAKE_SHA, ClientFactory, write_repo
from tests.helpers.faulty_parsers import (
    CONTROLLED_EXIT_CODE,
    exit_on_marker,
    hang_on_marker,
    raise_on_marker,
    require_worker_process,
    terminate_on_marker,
)

DOCS_FIXTURES = TESTS_DIR.parent / "docs" / "fixtures"
URL = "https://github.com/acme/shop-api"


def _repo(tmp_path: Path, files: dict[str, str], base: Path | None = None) -> Path:
    return write_repo(tmp_path / "repo", dict(files), base)


def _analyze(client: TestClient, **body: Any) -> Any:
    return client.post("/api/analyze", json={"repo_url": URL, "ref": "main"} | body)


def _summary(response: Any) -> AnalysisSummary:
    assert response.status_code == 201, response.text
    return AnalysisSummary.model_validate(response.json())


def _error(response: Any, status: int, code: str) -> ErrorResponse:
    assert response.status_code == status, response.text
    error = ErrorResponse.model_validate(response.json())
    assert error.error.code == code
    return error


# -- success ---------------------------------------------------------------------------


def test_analyze_end_to_end(make_client: ClientFactory, workspace_root: Path) -> None:
    client = make_client()

    response = _analyze(client)

    summary = _summary(response)
    assert response.headers["location"] == f"/api/analyses/{summary.analysis_id}"
    assert summary.status.value == "completed" and summary.error is None
    assert summary.repository.commit_sha == FAKE_SHA and summary.repository.ref == "main"
    assert summary.completed_at is not None and summary.completed_at >= summary.created_at
    stats = summary.stats
    assert stats is not None
    assert (stats.files_analyzed, stats.functions, stats.call_edges, stats.unresolved_calls) == (
        3,
        9,
        5,
        18,
    )
    assert stats.findings == 2  # a computed count (the fixture's SQL + credential findings)
    assert stats.findings_by_severity == {Severity.HIGH: 1, Severity.MEDIUM: 1}
    assert FINDINGS_NOT_COMPUTED_WARNING not in summary.diagnostics.warnings
    assert list(workspace_root.iterdir()) == []  # clone workspace removed

    # The stored analysis is served consistently by every read endpoint.
    assert client.get(f"/api/analyses/{summary.analysis_id}").json() == response.json()
    graph = GraphResponse.model_validate(
        client.get(f"/api/analyses/{summary.analysis_id}/graph").json()
    )
    assert len(graph.nodes) == stats.functions and len(graph.edges) == stats.call_edges
    assert graph.unresolved_calls_total == stats.unresolved_calls
    ids = {n.qualified_name: n.id for n in graph.nodes}
    paths = client.get(
        f"/api/analyses/{summary.analysis_id}/paths",
        params={"source": ids["handleLogin"], "target": ids["runQuery"]},
    )
    assert PathsResponse.model_validate(paths.json()).paths[0].node_ids == [
        ids["handleLogin"],
        ids["findUserByEmail"],
        ids["runQuery"],
    ]


def test_response_matches_the_documented_example(make_client: ClientFactory) -> None:
    body = _analyze(make_client()).json()
    documented = json.loads((DOCS_FIXTURES / "analysis_summary.json").read_text())

    volatile = {"analysis_id", "created_at", "completed_at", "duration_ms"}
    for key in volatile:
        body.pop(key)
        documented.pop(key)
    body["repository"].pop("commit_sha")
    documented["repository"].pop("commit_sha")
    assert body == documented


def test_ref_is_optional(make_client: ClientFactory) -> None:
    client = make_client()

    summary = _summary(client.post("/api/analyze", json={"repo_url": URL}))

    assert summary.repository.ref is None


def test_skipped_file_accounting_is_consistent(make_client: ClientFactory) -> None:
    summary = _summary(_analyze(make_client()))

    assert summary.stats is not None
    stats, diagnostics = summary.stats, summary.diagnostics
    assert stats.files_discovered == stats.files_analyzed + stats.files_skipped
    assert sum(diagnostics.skipped_by_reason.values()) == stats.files_skipped


# -- request and ingestion failures --------------------------------------------------------


@pytest.mark.parametrize(
    "repo_url",
    [
        "http://github.com/acme/shop-api",
        "https://gitlab.com/acme/shop-api",
        "https://github.com/acme",
        "file:///etc/passwd",
        "https://user:ghp_secret@github.com/acme/shop-api",
    ],
)
def test_invalid_repository_url_is_400_and_nothing_is_cloned(
    make_client: ClientFactory, repo_url: str
) -> None:
    client = make_client()

    response = client.post("/api/analyze", json={"repo_url": repo_url})

    _error(response, 400, "invalid_repository_url")
    assert "ghp_secret" not in response.text
    ingest = client.app.state.analysis_pipeline.ingest  # type: ignore[attr-defined]
    assert ingest.cloner.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"repo_url": ""},
        {"repo_url": URL, "ref": "--upload-pack=evil"},
        {"repo_url": URL, "token": "ghp_secret"},
        {"repo_url": "x" * 600},
        {"repo_url": 42},
    ],
)
def test_malformed_request_is_422(make_client: ClientFactory, body: dict[str, Any]) -> None:
    response = make_client().post("/api/analyze", json=body)

    _error(response, 422, "validation_error")
    assert "ghp_secret" not in response.text and "upload-pack" not in response.text


def test_non_json_body_is_422(make_client: ClientFactory) -> None:
    response = make_client().post(
        "/api/analyze", content=b"repo_url=x", headers={"content-type": "text/plain"}
    )

    _error(response, 422, "validation_error")


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (
            RepositoryUnavailableError("The repository could not be cloned."),
            502,
            "repository_unavailable",
        ),
        (RefNotFoundError("Branch or tag 'nope' was not found"), 404, "ref_not_found"),
        (CloneTimeoutError("Cloning exceeded 60s"), 504, "clone_timeout"),
        (
            RepositoryTooLargeError("Repository exceeds the clone limit"),
            413,
            "repository_too_large",
        ),
    ],
)
def test_ingestion_failures_use_error_envelope_and_store_nothing(
    make_client: ClientFactory, workspace_root: Path, error: Exception, status: int, code: str
) -> None:
    client = make_client(error=error)

    _error(_analyze(client), status, code)

    assert len(client.app.state.analysis_store) == 0  # type: ignore[attr-defined]
    assert list(workspace_root.iterdir()) == []  # workspace removed on failure too


def test_unexpected_ingestion_bug_is_generic_500(make_client: ClientFactory) -> None:
    client = make_client(error=RuntimeError("internal detail /srv/secret"))

    response = _analyze(client)

    _error(response, 500, "internal_error")
    assert "/srv/secret" not in response.text


# -- empty, unsupported and failing repositories ----------------------------------------------


def test_empty_repository_completes_with_a_warning(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    client = make_client(_repo(tmp_path, {}))

    summary = _summary(_analyze(client))

    assert summary.status.value == "completed"
    assert summary.stats is not None and summary.stats.files_discovered == 0
    assert NO_FILES_WARNING in summary.diagnostics.warnings
    graph = client.get(f"/api/analyses/{summary.analysis_id}/graph").json()
    assert graph["nodes"] == [] and graph["edges"] == []


def test_repository_without_supported_files(make_client: ClientFactory, tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"README.md": "# hi\n", "main.py": "print(1)\n", ".env": "X=1\n"})

    summary = _summary(_analyze(make_client(repo)))

    assert summary.status.value == "completed"
    assert summary.stats is not None and summary.stats.files_analyzed == 0
    assert summary.diagnostics.skipped_by_reason == {
        SkipReason.UNSUPPORTED_EXTENSION: 2,
        SkipReason.SENSITIVE_FILE: 1,
    }
    assert NO_FILES_WARNING in summary.diagnostics.warnings


def test_production_app_parses_in_an_isolated_worker(
    make_client: ClientFactory, workspace_root: Path
) -> None:
    default_app = create_app(Settings(_env_file=None, workspace_root=workspace_root))
    assert default_app.state.settings.parse_isolation == "subprocess"
    assert default_app.state.analysis_pipeline.parse_fn is parse_source_file

    client = make_client(parse_fn=require_worker_process, parse_isolation="subprocess")
    summary = _summary(_analyze(client))

    assert summary.status.value == "completed" and summary.diagnostics.parse_errors == []


@pytest.mark.parametrize(
    ("marker_file", "parse_fn", "message"),
    [
        ("src/terminate.js", terminate_on_marker, "was terminated (SIGTERM)"),
        ("src/exit.js", exit_on_marker, f"exited unexpectedly (exit code {CONTROLLED_EXIT_CODE})"),
    ],
)
def test_worker_death_is_a_diagnostic_and_the_service_keeps_working(
    make_client: ClientFactory,
    tmp_path: Path,
    marker_file: str,
    parse_fn: ParseFn,
    message: str,
) -> None:
    repo = _repo(tmp_path, {marker_file: "function f() {}\n"}, base=FIXTURE_REPOS / "shop_api")
    client = make_client(repo, parse_fn=parse_fn, parse_isolation="subprocess")

    summary = _summary(_analyze(client))

    assert summary.status.value == "completed"
    assert summary.stats is not None and summary.stats.files_analyzed == 3
    assert summary.diagnostics.skipped_by_reason[SkipReason.PARSE_FAILED] == 1
    [failure] = [e for e in summary.diagnostics.parse_errors if e.path == marker_file]
    assert message in failure.message
    assert any(
        s.path == marker_file and s.reason is SkipReason.PARSE_FAILED
        for s in summary.diagnostics.skipped_files
    )
    # The API process is unaffected: it keeps serving and analyzing.
    assert client.get("/api/health").status_code == 200
    assert _summary(_analyze(client)).status.value == "completed"


def test_parser_timeout_is_reported(make_client: ClientFactory, tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"src/hang.js": "function hang() {}\n"}, base=FIXTURE_REPOS / "shop_api")
    client = make_client(
        repo, parse_fn=hang_on_marker, parse_isolation="subprocess", parse_file_timeout_seconds=1
    )

    summary = _summary(_analyze(client))

    assert summary.status.value == "completed"
    assert [(r.limit, r.value) for r in summary.diagnostics.limits_reached] == [
        ("parse_file_timeout_seconds", 1)
    ]
    assert any("per-file limit" in e.message for e in summary.diagnostics.parse_errors)


def test_all_files_failing_is_a_failed_analysis(make_client: ClientFactory, tmp_path: Path) -> None:
    client = make_client(_repo(tmp_path, {"src/boom.js": "x();\n"}), parse_fn=raise_on_marker)

    summary = _summary(_analyze(client))

    assert summary.status.value == "failed"
    assert summary.error is not None and summary.error.code == "parsing_failed"
    assert summary.stats is not None and summary.stats.functions == 0
    assert client.get(f"/api/analyses/{summary.analysis_id}").json()["status"] == "failed"
    _error(client.get(f"/api/analyses/{summary.analysis_id}/graph"), 409, "analysis_failed")
    params = {"source": "fn_0000000000000000", "target": "fn_0000000000000000"}
    _error(
        client.get(f"/api/analyses/{summary.analysis_id}/paths", params=params),
        409,
        "analysis_failed",
    )


def test_graph_construction_bug_is_a_failed_analysis(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("internal detail")

    monkeypatch.setattr(analysis_service, "build_call_graph", broken)

    response = _analyze(make_client())

    summary = _summary(response)
    assert summary.status.value == "failed"
    assert summary.error is not None and summary.error.code == "analysis_failed"
    assert "internal detail" not in response.text


# -- store, concurrency and lookups -------------------------------------------------------------


def test_store_capacity_evicts_oldest(make_client: ClientFactory) -> None:
    client = make_client(max_stored_analyses=2)

    first, second, third = (_summary(_analyze(client)).analysis_id for _ in range(3))

    _error(client.get(f"/api/analyses/{first}"), 404, "analysis_not_found")
    assert client.get(f"/api/analyses/{second}").status_code == 200
    assert client.get(f"/api/analyses/{third}").status_code == 200


def test_concurrency_limit_returns_429_and_slot_is_released(make_client: ClientFactory) -> None:
    client = make_client(max_concurrent_analyses=1)
    slots = client.app.state.analysis_slots  # type: ignore[attr-defined]

    assert slots.acquire(blocking=False)  # simulate an analysis in progress
    busy = _analyze(client)
    slots.release()

    _error(busy, 429, "too_many_analyses")
    assert busy.headers["retry-after"] == "30"
    assert _analyze(client).status_code == 201
    assert _analyze(client).status_code == 201  # the slot was released again


def test_slot_is_released_after_ingestion_failure(make_client: ClientFactory) -> None:
    client = make_client(error=RepositoryUnavailableError("nope"), max_concurrent_analyses=1)

    for _ in range(3):
        _error(_analyze(client), 502, "repository_unavailable")


@pytest.mark.parametrize("analysis_id", ["0" * 32, "not-an-id", "F" * 32])
def test_unknown_analysis_is_404(make_client: ClientFactory, analysis_id: str) -> None:
    _error(make_client().get(f"/api/analyses/{analysis_id}"), 404, "analysis_not_found")


def test_get_on_analyze_is_405(make_client: ClientFactory) -> None:
    _error(make_client().get("/api/analyze"), 405, "method_not_allowed")
