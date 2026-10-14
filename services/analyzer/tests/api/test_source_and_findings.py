"""GET /source and /findings on analyses created through POST /api/analyze."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.analysis import AnalysisSummary
from app.models.api import ErrorResponse, SourceResponse
from app.models.findings import FindingsResponse
from app.models.graph import GraphResponse
from app.services.analysis import MAX_SOURCE_LINES
from tests.helpers.fakes import ClientFactory, write_repo
from tests.helpers.faulty_parsers import raise_on_marker

SECRET = "hunter2-correct-horse"  # noqa: S105 - fake secret: rule test input
APP_TS = f"""import {{ exec }} from "child_process";

const DB_PASSWORD = "{SECRET}";

export function find(id: string) {{
  const sql = `SELECT * FROM users WHERE id = ${{id}}`;
  exec("ls " + id);
  return eval(id);
}}
"""  # noqa: S608 - deliberately vulnerable sample: rule test input
LONG_LINES = 1_200

FILES: dict[str, str | bytes] = {
    "src/app.ts": APP_TS,
    "src/clean.js": "export function ok() { return 1; }\n",
    "src/empty.js": "",
    "src/no-newline.js": "first();\nsecond();",
    "src/long.js": "".join(f"line{i}();\n" for i in range(1, LONG_LINES + 1)),
    "src/boom.js": "function boom() {}\n",  # parse fails (raise_on_marker)
    "README.md": "# repo\n",
    ".env": f"PASSWORD={SECRET}\n",
    "config/server.pem": "-----BEGIN PRIVATE KEY-----\n",
    "node_modules/pkg/index.js": "eval(x);\n",
    "dist/bundle.js": "eval(x);\n",
    "assets/logo.png": b"\x89PNG\x00\x00",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return write_repo(tmp_path / "repo", FILES)


@pytest.fixture
def client(make_client: ClientFactory, repo: Path) -> TestClient:
    return make_client(repo, parse_fn=raise_on_marker)


@pytest.fixture
def analysis_id(client: TestClient) -> str:
    response = client.post("/api/analyze", json={"repo_url": "https://github.com/acme/demo"})
    assert response.status_code == 201, response.text
    return str(response.json()["analysis_id"])


def _source(client: TestClient, analysis_id: str, **params: Any) -> Any:
    return client.get(f"/api/analyses/{analysis_id}/source", params=params)


def _ok(response: Any) -> SourceResponse:
    assert response.status_code == 200, response.text
    return SourceResponse.model_validate(response.json())


def _error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert ErrorResponse.model_validate(response.json()).error.code == code


# -- source: retrieval ---------------------------------------------------------------------


def test_whole_file_with_secret_redacted(client: TestClient, analysis_id: str) -> None:
    body = _ok(_source(client, analysis_id, path="src/app.ts"))

    expected = APP_TS.replace(SECRET, f"[REDACTED len={len(SECRET)}]")
    assert (body.path, body.language.value, body.start_line) == ("src/app.ts", "typescript", 1)
    assert (body.end_line, body.total_lines) == (9, 9)
    assert body.content == expected
    assert SECRET not in body.content
    assert body.redacted_values == 1 and not body.truncated


def test_line_selection(client: TestClient, analysis_id: str) -> None:
    body = _ok(_source(client, analysis_id, path="src/app.ts", start_line=5, end_line=7))

    assert (body.start_line, body.end_line) == (5, 7)
    assert body.content == "".join(APP_TS.splitlines(keepends=True)[4:7])
    assert body.redacted_values == 0  # the secret is on line 3


def test_end_line_beyond_file_is_clamped(client: TestClient, analysis_id: str) -> None:
    body = _ok(_source(client, analysis_id, path="src/app.ts", start_line=8, end_line=500))

    assert (body.start_line, body.end_line, body.truncated) == (8, 9, False)


def test_long_files_are_returned_in_bounded_windows(client: TestClient, analysis_id: str) -> None:
    first = _ok(_source(client, analysis_id, path="src/long.js"))
    explicit = _ok(_source(client, analysis_id, path="src/long.js", start_line=1, end_line=1200))
    rest = _ok(_source(client, analysis_id, path="src/long.js", start_line=1001))

    assert (first.end_line, first.truncated) == (MAX_SOURCE_LINES, True)
    assert first.content.count("\n") == MAX_SOURCE_LINES
    assert (explicit.end_line, explicit.truncated) == (MAX_SOURCE_LINES, True)
    assert (rest.start_line, rest.end_line, rest.truncated) == (1001, LONG_LINES, False)
    assert rest.content.startswith("line1001();\n") and rest.content.endswith("line1200();\n")


def test_file_without_trailing_newline(client: TestClient, analysis_id: str) -> None:
    body = _ok(_source(client, analysis_id, path="src/no-newline.js"))

    assert (body.total_lines, body.content) == (2, "first();\nsecond();")


def test_empty_file(client: TestClient, analysis_id: str) -> None:
    body = _ok(_source(client, analysis_id, path="src/empty.js"))

    assert (body.start_line, body.end_line, body.total_lines, body.content) == (1, 0, 0, "")
    _error(
        _source(client, analysis_id, path="src/empty.js", start_line=2), 400, "invalid_line_range"
    )


# -- source: refusals ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".env",  # secret file: excluded at ingestion, never stored
        "config/server.pem",
        "node_modules/pkg/index.js",  # dependency directory: never walked
        "dist/bundle.js",
        "assets/logo.png",
        "README.md",  # unsupported extension
        "src/boom.js",  # eligible, but its parse failed: not indexed
        "src/missing.ts",
        "SRC/APP.TS",  # paths are case-sensitive
    ],
)
def test_files_outside_the_index_are_404(client: TestClient, analysis_id: str, path: str) -> None:
    response = _source(client, analysis_id, path=path)

    _error(response, 404, "file_not_found")
    assert SECRET not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "src/../../etc/passwd",
        "/etc/passwd",
        "src//app.ts",
        "./src/app.ts",
        "src/./app.ts",
        "src\\app.ts",
        "src/app.ts\x00",
        "",
        "a/" * 600,
    ],
)
def test_invalid_and_traversal_paths_are_422(
    client: TestClient, analysis_id: str, path: str
) -> None:
    _error(_source(client, analysis_id, path=path), 422, "validation_error")


def test_missing_path_is_422(client: TestClient, analysis_id: str) -> None:
    _error(client.get(f"/api/analyses/{analysis_id}/source"), 422, "validation_error")


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"start_line": 10}, 400, "invalid_line_range"),  # file has 9 lines
        ({"start_line": 5, "end_line": 4}, 400, "invalid_line_range"),
        ({"start_line": 0}, 422, "validation_error"),
        ({"end_line": 0}, 422, "validation_error"),
        ({"start_line": -1}, 422, "validation_error"),
        ({"start_line": "x"}, 422, "validation_error"),
        ({"start_line": 10**12}, 422, "validation_error"),
    ],
)
def test_invalid_line_ranges(
    client: TestClient, analysis_id: str, params: dict[str, Any], status: int, code: str
) -> None:
    _error(_source(client, analysis_id, path="src/app.ts", **params), status, code)


def test_unknown_analysis(client: TestClient) -> None:
    unknown = "0" * 32
    _error(_source(client, unknown, path="src/app.ts"), 404, "analysis_not_found")
    _error(client.get(f"/api/analyses/{unknown}/findings"), 404, "analysis_not_found")


def test_evicted_analysis_sources_are_gone(make_client: ClientFactory, repo: Path) -> None:
    client = make_client(repo, max_stored_analyses=1)
    url = "https://github.com/acme/demo"
    first = client.post("/api/analyze", json={"repo_url": url}).json()["analysis_id"]
    client.post("/api/analyze", json={"repo_url": url})

    _error(_source(client, first, path="src/app.ts"), 404, "analysis_not_found")
    _error(client.get(f"/api/analyses/{first}/findings"), 404, "analysis_not_found")


def test_failed_analysis_has_no_source_or_findings(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    client = make_client(
        write_repo(tmp_path / "bad", {"src/boom.js": "x();\n"}), parse_fn=raise_on_marker
    )
    summary = client.post("/api/analyze", json={"repo_url": "https://github.com/a/b"}).json()

    assert summary["status"] == "failed" and summary["stats"]["findings"] is None
    _error(_source(client, summary["analysis_id"], path="src/boom.js"), 409, "analysis_failed")
    _error(client.get(f"/api/analyses/{summary['analysis_id']}/findings"), 409, "analysis_failed")


# -- findings ------------------------------------------------------------------------------------


def _findings(client: TestClient, analysis_id: str, **params: Any) -> FindingsResponse:
    response = client.get(f"/api/analyses/{analysis_id}/findings", params=params)
    assert response.status_code == 200, response.text
    return FindingsResponse.model_validate(response.json())


def test_findings_are_real_ordered_and_redacted(client: TestClient, analysis_id: str) -> None:
    body = _findings(client, analysis_id)

    assert body.total == len(body.findings) == 4 and not body.truncated
    assert [(f.rule_id, f.location.start_line) for f in body.findings] == [
        ("js.hardcoded-credential", 3),
        ("js.sql-string-construction", 6),
        ("js.shell-command-construction", 7),
        ("js.dynamic-code-execution", 8),
    ]
    assert all(f.location.path == "src/app.ts" for f in body.findings)
    assert SECRET not in client.get(f"/api/analyses/{analysis_id}/findings").text


def test_every_finding_points_at_retrievable_source(client: TestClient, analysis_id: str) -> None:
    graph = GraphResponse.model_validate(client.get(f"/api/analyses/{analysis_id}/graph").json())
    node_ids = {n.id for n in graph.nodes}

    for finding in _findings(client, analysis_id).findings:
        loc = finding.location
        body = _ok(
            _source(
                client, analysis_id, path=loc.path, start_line=loc.start_line, end_line=loc.end_line
            )
        )
        first_evidence_line = finding.evidence.split("\n")[0]
        assert first_evidence_line in body.content
        assert finding.function_id is None or finding.function_id in node_ids


def test_findings_summary_counts_match(client: TestClient, analysis_id: str) -> None:
    summary = AnalysisSummary.model_validate(client.get(f"/api/analyses/{analysis_id}").json())
    body = _findings(client, analysis_id)

    assert summary.stats is not None and summary.stats.findings == body.total
    by_severity: dict[str, int] = {}
    for finding in body.findings:
        by_severity[finding.severity.value] = by_severity.get(finding.severity.value, 0) + 1
    assert {k.value: v for k, v in summary.stats.findings_by_severity.items()} == by_severity
    # Partial coverage is reported, not hidden.
    assert any("Rules did not run on 1 file(s)" in w for w in summary.diagnostics.warnings)


def test_findings_filters_and_limit(client: TestClient, analysis_id: str) -> None:
    high = _findings(client, analysis_id, severity="high")
    sql = _findings(client, analysis_id, rule_id="js.sql-string-construction")
    elsewhere = _findings(client, analysis_id, path_prefix="lib")
    limited = _findings(client, analysis_id, limit=1)

    assert {f.severity.value for f in high.findings} == {"high"} and high.total == 3
    assert [f.rule_id for f in sql.findings] == ["js.sql-string-construction"]
    assert (elsewhere.total, elsewhere.findings) == (0, [])
    assert (limited.total, len(limited.findings), limited.truncated) == (4, 1, True)


@pytest.mark.parametrize(
    "params",
    [
        {"severity": "urgent"},
        {"rule_id": "../x"},
        {"rule_id": "Bad Rule"},
        {"limit": 0},
        {"limit": 1001},
        {"path_prefix": "../src"},
    ],
)
def test_findings_invalid_parameters(
    client: TestClient, analysis_id: str, params: dict[str, Any]
) -> None:
    response = client.get(f"/api/analyses/{analysis_id}/findings", params=params)

    _error(response, 422, "validation_error")


def test_findings_are_identical_across_requests(client: TestClient, analysis_id: str) -> None:
    url = f"/api/analyses/{analysis_id}/findings"

    assert client.get(url).json() == client.get(url).json()


def test_clean_repository_reports_zero_findings_not_null(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    client = make_client(write_repo(tmp_path / "clean", {"src/ok.ts": "export const ok = 1;\n"}))
    summary = client.post("/api/analyze", json={"repo_url": "https://github.com/a/b"}).json()

    assert summary["stats"]["findings"] == 0 and summary["stats"]["findings_by_severity"] == {}
    body = _findings(client, summary["analysis_id"])
    assert (body.total, body.findings) == (0, [])


def test_graph_and_paths_still_work_alongside_findings(
    client: TestClient, analysis_id: str
) -> None:
    graph = client.get(f"/api/analyses/{analysis_id}/graph")
    assert graph.status_code == 200
    node = graph.json()["nodes"][0]["id"]
    paths = client.get(
        f"/api/analyses/{analysis_id}/paths", params={"source": node, "target": node}
    )
    assert paths.status_code == 200 and paths.json()["paths"] == [
        {"node_ids": [node], "edge_ids": []}
    ]
