# RepoPilot backend: frontend integration guide

For Member 2 (Next.js frontend, graph view, AI investigator). This is the
practical summary; [`api-contract.md`](api-contract.md) is the full
reference, and every JSON shape below is a real file in [`fixtures/`](fixtures/).

## 1. Run the backend locally

Requires Python 3.11+ and `git`. All commands run from `services/analyzer`.

**One-time setup:** needs network access to PyPI.
```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

**Option A: demo server.** No GitHub and no network needed. It pre-loads the
documented example analysis:
```bash
.venv/bin/python -m scripts.demo_server --port 8000
```
Analysis `4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a` is then available, and every read
endpoint returns exactly the JSON in `docs/fixtures/`. `POST /api/analyze` also
works here, but it clones from GitHub, so it needs network access.

**Option B: the real API**, with an empty store:
```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Checks:**
- `curl http://127.0.0.1:8000/api/health` returns `{"status":"ok",...}`.
- Interactive docs are at `http://127.0.0.1:8000/api/docs`.
- The OpenAPI schema is at `http://127.0.0.1:8000/api/openapi.json`.

**CORS.** The allowed origin by default is `http://localhost:3000` only.
`http://127.0.0.1:3000` is a *different* origin and is rejected. Either open
the frontend at `http://localhost:3000`, or start the backend with:
```bash
REPOPILOT_CORS_ALLOWED_ORIGINS='["http://localhost:3000","http://127.0.0.1:3000"]' .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Alternatively, proxy `/api/*` through Next.js `rewrites` to avoid CORS entirely.

**TypeScript types.** Generate them from the live schema rather than writing
them by hand, so they can't drift. This runs on the frontend side and wasn't
run as part of the backend checks:
```bash
npx openapi-typescript http://127.0.0.1:8000/api/openapi.json -o src/types/repopilot.ts
```

## 2. Endpoints

Base URL `http://127.0.0.1:8000`. All responses are JSON.

| Method & path | Success | Response | Example |
| --- | --- | --- | --- |
| `POST /api/analyze` | 201 + `Location` header | `AnalysisSummary` | [analyze_request.json](fixtures/analyze_request.json) → [analysis_summary.json](fixtures/analysis_summary.json) |
| `GET /api/analyses/{id}` | 200 | `AnalysisSummary` | [analysis_summary.json](fixtures/analysis_summary.json), [analysis_failed.json](fixtures/analysis_failed.json) |
| `GET /api/analyses/{id}/graph` | 200 | `GraphResponse` | [graph.json](fixtures/graph.json) |
| `GET /api/analyses/{id}/paths?source=&target=` | 200 | `PathsResponse` | [paths.json](fixtures/paths.json) |
| `GET /api/analyses/{id}/findings` | 200 | `FindingsResponse` | [findings.json](fixtures/findings.json) |
| `GET /api/analyses/{id}/source?path=` | 200 | `SourceResponse` | [source.json](fixtures/source.json) |
| `GET /api/health` | 200 | `{status, service, version}` | |

**`POST /api/analyze` body:** `{"repo_url": "https://github.com/<owner>/<repo>", "ref": "main"}`
- `ref` is optional and must be a branch or tag. Commit SHAs aren't supported.
- Unknown fields are rejected.

**Query parameters:**

| Endpoint | Parameters (default, bounds) |
| --- | --- |
| `/graph` | `path_prefix` (none); `max_nodes` (2000, 1–20000); `max_unresolved` (500, 0–5000) |
| `/paths` | `source`, `target` (required `fn_` + 16 hex chars); `max_depth` (8, 1–20); `max_paths` (10, 1–100) |
| `/findings` | `severity` (exact match); `rule_id`; `path_prefix`; `limit` (500, 1–1000) |
| `/source` | `path` (required); `start_line` (1); `end_line` (end of file). At most 500 lines per response |

## 3. Fields you will use

**AnalysisSummary:**
- **Identity and state:** `analysis_id`, `status` (`completed` or `failed`; `queued` and `running` are reserved), `error` (`{code, message}` or `null`).
- **Revision:** `repository` (`url`, `owner`, `name`, `ref`, `commit_sha`).
- **Timing:** `created_at`, `completed_at`, `duration_ms`.
- **`stats`:**
  - files: `files_discovered`, `files_analyzed`, `files_skipped`;
  - graph: `functions`, `call_edges`, `unresolved_calls`;
  - findings: `findings` (a number; `null` only when `status` is `failed`), `findings_by_severity`;
  - `files_by_language`.
- **`diagnostics`:** `parse_errors[]`, `skipped_files[]` (a sample), `skipped_by_reason`, `limits_reached[]`, `warnings[]`, `truncated`. Show these: they explain what the analysis did *not* cover.

**GraphResponse:**
- **`nodes[]`:** `id`, `name`, `qualified_name`, `kind`, `language`, `path`, `start_line`, `end_line`, `start_column`, `is_anonymous`, `is_exported`.
- **`edges[]`:** `id`, `source`, `target`, `resolution`, `call_sites[]` (`line`, `column`).
- **Unresolved calls:** `unresolved_calls[]` (`caller_id`, `path`, `callee`, `call_site`, `reason`) and `unresolved_calls_total`.
- **Also:** `truncated`, `limitations[]`.
- **For React Flow:** use `nodes[].id` as the node `id` and `edges[].source`/`target` directly. Every edge endpoint is guaranteed to be in `nodes`.

**PathsResponse:** `paths[]` holds `{node_ids[], edge_ids[]}`, shortest first. `edge_ids[i]` connects `node_ids[i]` → `node_ids[i+1]`. Also `truncated` and `limitations[]`.

**FindingsResponse:**
- **Top level:** `findings[]`, `total`, `truncated`.
- **Each finding:** `id`, `rule_id`, `title`, `description`, `severity`, `confidence`, `location` (`path`, `start_line`, `end_line`), `function_id`, `evidence`, `review_status`, `next_step`, `limitations[]`, `cwe_id`.

**SourceResponse:** `path`, `language`, `start_line`, `end_line`, `total_lines`, `content`, `truncated`, `redacted_values`.

Enum values may be added over time. Show unknown values as plain text rather
than failing.

## 4. Errors

Every non-2xx response is `{"error": {"code": "...", "message": "...", "details": [...]?}}`.
Branch on `error.code`, not on `message`.

| Status | Codes | What the UI should do |
| --- | --- | --- |
| 400 | `invalid_repository_url`, `invalid_line_range`, `invalid_request` | Show the message; fix the input |
| 404 | `analysis_not_found` | The analysis expired or the server restarted: offer "Analyze again" |
| 404 | `ref_not_found`, `function_not_found`, `file_not_found` | Show the message; nothing to retry |
| 409 | `analysis_failed` | The analysis exists but failed: show its `error` from `GET /api/analyses/{id}`; don't request the graph |
| 413 / 502 / 504 | `repository_too_large`, `repository_unavailable`, `clone_timeout` | Show the message; the repository can't be analyzed as given |
| 422 | `validation_error` | A client bug or bad input; `details[].loc` points at the field |
| 429 | `too_many_analyses` | The server is busy; retry after the `Retry-After` header (seconds) |
| 500 / 503 | `internal_error`, `ingestion_failed`, `git_unavailable` | Server-side problem; show a generic error |

## 5. Loading behavior

- **`POST /api/analyze` is synchronous.** It returns only when the analysis is
  done, with no progress events:
  - **Timeout:** use a client timeout of at least **210 s** (the default limits).
  - **While waiting:** show a determinate "analyzing" state and disable re-submission.
  - **Busy server:** at most 2 analyses run at once; more requests get 429.
- **A 201 can still be a failure.** Check `status`. If it's `failed`, show
  `error.message` and `diagnostics`, and don't call `/graph`, `/paths`,
  `/findings` or `/source` (they return 409).
- **After 201 + `completed`:** fetch `/graph` and `/findings` in parallel. Each
  is a single response that depends only on the analysis ID.
- **Analyses are in memory only.** The server keeps the 20 most recently used
  (and at most 256 MB of source), and **loses everything on restart**. Treat a
  404 `analysis_not_found` as normal and don't persist IDs long-term.
- **Large repositories:**
  - **`/graph`:** returns at most `max_nodes` nodes, with `truncated: true`.
    Use `path_prefix` to drill into a directory.
  - **`/findings`:** paginates with `limit` and `total`.
  - **`/source`:** returns 500-line windows with `truncated: true`.

## 6. Source-citation navigation

Every location is `path` + 1-based inclusive lines into the **same commit**
(`repository.commit_sha`). Lines are split on `\n` only, so they match
`/source` exactly.

| From | Fields | Source request |
| --- | --- | --- |
| A finding | `location.path`, `location.start_line`, `location.end_line` | `/source?path={path}&start_line={max(1, start-5)}&end_line={end+5}`, then highlight `start_line..end_line` |
| A graph node | `path`, `start_line`, `end_line` | `/source?path={path}&start_line={start_line}&end_line={end_line}` |
| An edge's call site | the source node's `path`, plus `call_sites[].line` | Fetch around that line; `column` is 1-based, in Unicode code points |
| An unresolved call | `path`, `call_site.line` | Same as above; `reason` explains why it has no edge |
| A finding → its function | `function_id` (`null` at module level without a module node) | Look it up in `/graph` `nodes[]` to select and highlight it |
| A path | `node_ids[]` | Map IDs through `/graph` `nodes[]`, then open each node's source |

**Rendering notes:**
- **Columns:** they count code points, while JavaScript strings index UTF-16
  units, so columns differ only on lines containing emoji or other astral
  characters.
- **Context windows:** `end_line` is clamped to the file length, so a context
  window past the end is safe. `start_line` past the end returns 400
  `invalid_line_range`.
- **Redaction:** `content` and `evidence` have credential values replaced by
  `[REDACTED len=N]`, and line numbers never shift.
- **Untrusted text:** render all repository text (`content`, `evidence`,
  `callee`, names) as **plain text**, never as HTML. When sending it to the AI
  investigator, mark it as data, not instructions.
- **Graph paths:** a graph path or finding is a lead, not proof. Show
  `limitations` near paths and findings.

## 7. Example IDs (demo server or fixtures)

| What | ID |
| --- | --- |
| Analysis | `4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a` |
| `handleLogin` → `findUserByEmail` → `runQuery` path | `fn_63a298464ab84151` → `fn_ab5be50968456b8e` → `fn_24417c4e8adf123b` |
| SQL finding (`src/db.ts` line 6) | `fd_3a1a105fef08bbf6` |
| Credential finding (`src/auth/session.ts` line 3, redacted) | `fd_9a1efc510b916112` |

```bash
A=http://127.0.0.1:8000/api/analyses/4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a
curl "$A"
curl "$A/graph"
curl "$A/findings"
curl "$A/paths?source=fn_63a298464ab84151&target=fn_24417c4e8adf123b"
curl "$A/source?path=src/db.ts&start_line=5&end_line=10"
```
