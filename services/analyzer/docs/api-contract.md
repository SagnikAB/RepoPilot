# RepoPilot Analyzer — API Contract (v0.1, draft)

Audience: Member 2 (frontend, graph visualization, AI investigator).
Source of truth for shapes: `app/models/`. Every example below is a real file in
[`docs/fixtures/`](fixtures/) and is validated against the models by
`tests/unit/test_models.py`, so this document cannot silently drift.

The examples describe the fixture repository `tests/fixtures/repos/shop_api`.

- **Generated from real pipeline output:** `analysis_summary.json`,
  `graph.json`, `paths.json`, `findings.json` and `source.json`. Only the
  analysis ID, timestamps, duration and commit SHA are pinned. Regenerate with `.venv/bin/python -m scripts.doc_fixtures`;
  `tests/unit/test_doc_fixtures.py` fails if they drift. The demo server
  (`.venv/bin/python -m scripts.demo_server`) serves these exact responses.
- **Hand-written examples, validated against the models:** `analysis_failed.json`,
  `error.json` and `analyze_request.json`.

> **Change policy.** Adding an optional field is non-breaking. Renaming,
> removing, or changing the type/meaning of a field, or changing an endpoint
> shape, needs agreement from both members first. Enum values may be added
> (see the changelog); clients should show unknown values as plain text rather
> than fail.

## Changelog

| Version | Change | Compatibility |
| --- | --- | --- |
| Phase 6 | `CallEdge.resolution` gains `constructor` and `instance_method` | Additive: needs Member 2's acknowledgement |
| Phase 6 | `UnresolvedCall.reason` gains `unresolved_import` | Additive: needs Member 2's acknowledgement |
| Phase 6 | `/graph` and `/paths` implemented; `/graph` takes `path_prefix`, `max_nodes`, `max_unresolved` | As planned |
| Phase 8 | `AnalysisStats.findings` is `integer \| null`; `null` = not computed (rule engine not built yet) | **Type change: needs Member 2's acknowledgement** |
| Phase 8 | `SkipReason` gains `parse_failed` (file accepted but the parser crashed, timed out or raised) | Additive: needs Member 2's acknowledgement |
| Phase 8 | New error codes `analysis_failed` (409) and `too_many_analyses` (429); `AnalysisSummary.error.code` values `parsing_failed`, `analysis_failed` | Additive: needs Member 2's acknowledgement |
| Phase 8 | `POST /api/analyze` and `GET /api/analyses/{id}` implemented; failed analyses are stored and returned with `status: "failed"` | As planned, with the semantics below |
| Phase 7 | `/findings` and `/source` implemented. `stats.findings` is now a real count (including `0`) for `completed` analyses, and `null` only for `failed` ones | As planned |
| Phase 7 | `SourceResponse.end_line` may be `0`, **only** for an empty file (`start_line: 1`, `total_lines: 0`, `content: ""`) | **Relaxed constraint: needs Member 2's acknowledgement** |
| Phase 7 | `SourceResponse.redacted_values` (integer, default 0): number of credential-like values replaced in `content` | Additive: needs Member 2's acknowledgement |
| Phase 7 | `/source` `content` is **redacted** (credential-like values replaced by `[REDACTED len=N]`); the earlier draft said raw | Behavior change: needs Member 2's acknowledgement |
| Phase 7 | New error codes `file_not_found` (404) and `invalid_line_range` (400); `analysis_failed` (409) also applies to `/findings` and `/source` | Additive: needs Member 2's acknowledgement |

## Implementation status

| Endpoint | Status |
| --- | --- |
| `GET /api/health` | **Implemented** (Phase 1) |
| `POST /api/analyze` | **Implemented** (Phase 8), synchronous |
| `GET /api/analyses/{analysis_id}` | **Implemented** (Phase 8) |
| `GET /api/analyses/{analysis_id}/graph` | **Implemented** (Phase 6) |
| `GET /api/analyses/{analysis_id}/findings` | **Implemented** (Phase 7) |
| `GET /api/analyses/{analysis_id}/source` | **Implemented** (Phase 7) |
| `GET /api/analyses/{analysis_id}/paths` | **Implemented** (Phase 6) |

All endpoints in this contract are implemented.

## Core principles

1. **Deterministic analysis produces evidence; the AI layer explains it.** The
   AI investigator should cite node IDs, finding IDs, and `SourceReference`s
   from these responses rather than re-deriving them.
2. **The call graph is partial by design.** Only statically resolved calls
   become edges. Everything else appears in `unresolved_calls` with a reason.
   No edge ≠ no call.
3. **A path is not a data flow.** `/paths` returns call chains. It does not do
   taint analysis.
4. **A finding is a lead, not proof.** Every finding starts as
   `review_status: "needs_review"` and includes `limitations`.
5. **Repository text is untrusted.** `content`, `evidence`, function names and
   `callee` strings come from arbitrary repositories. Render them as plain text
   (never `dangerouslySetInnerHTML`). When you pass them to an LLM, mark them
   as data so instructions hidden in comments cannot steer the model.

## Conventions

- JSON only, `snake_case` fields, UTC ISO-8601 timestamps.
- **Lines are 1-based and inclusive. Columns are 1-based, counted in Unicode
  code points** (not bytes). JavaScript strings index UTF-16 units, so a column
  differs from a JS string offset only after astral characters such as emoji.
- **Paths** are POSIX-style and relative to the repository root (`src/db.ts`).
  They never start with `/` and never contain `.` or `..` segments.
- **IDs** are opaque strings, stable for identical source:
  `analysis_id` is 32 lowercase hex characters; function nodes are `fn_<16 hex>`,
  call edges `ce_<16 hex>`, findings `fd_<16 hex>`. Do not parse them.
- Lists that may be large carry a `truncated` flag and, where useful, a total.

## Errors

Every non-2xx response has this shape ([`fixtures/error.json`](fixtures/error.json)):

```json
{ "error": { "code": "analysis_not_found", "message": "No analysis exists with id 4f2c…" } }
```

`details` is present for validation errors:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [{ "loc": ["query", "limit"], "message": "Input should be less than or equal to 10", "type": "less_than_equal" }]
  }
}
```

Submitted values are never echoed back, because they may contain credentials.

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request`, `invalid_repository_url`, `invalid_line_range` | Well-formed request that the server refuses. `invalid_line_range`: `start_line` past the end of the file, or `end_line < start_line` |
| 404 | `not_found`, `ref_not_found`, `analysis_not_found`, `function_not_found`, `file_not_found` | Unknown route or resource. A malformed analysis ID is also `analysis_not_found`, and so is an expired one (evicted from memory or lost on restart). `file_not_found`: the path is not an analyzed file of this analysis |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 409 | `analysis_failed` | `/graph`, `/paths`, `/findings` or `/source` requested for an analysis whose `status` is `failed` |
| 413 | `repository_too_large` | Clone exceeded `max_clone_bytes` |
| 422 | `validation_error` | Body/query/path failed schema validation (missing or extra fields, wrong types, unsafe `ref`, non-JSON body) |
| 429 | `too_many_analyses` | `max_concurrent_analyses` analyses are already running; a `Retry-After` header (seconds) is included |
| 500 | `internal_error`, `ingestion_failed` | Bug; message is intentionally generic |
| 502 | `repository_unavailable` | Clone failed (missing, private, unreachable host) |
| 503 | `git_unavailable` | Server misconfiguration: `git` not installed |
| 504 | `clone_timeout` | Clone exceeded `clone_timeout_seconds` |
| other 4xx | `bad_request`, `payload_too_large`, `unsupported_media_type`, `http_error` | Generic framework-level HTTP errors; not raised by the endpoints themselves, but handle them as plain errors |

Per-file problems (syntax errors, parser crashes, timeouts, limits) never fail
the request; they become `diagnostics` entries. See `POST /api/analyze` for
when an analysis as a whole is `failed`.

## Endpoints

### `GET /api/health` — implemented

```json
{ "status": "ok", "service": "repopilot-analyzer", "version": "0.1.0" }
```

### `POST /api/analyze` — implemented

Clones, parses and graphs a public repository, stores the result in memory,
and returns its `AnalysisSummary`. **The request is synchronous**: it returns
when the analysis is finished. Set a client timeout of at least
`clone_timeout_seconds + parse_time_budget_seconds + 30` seconds (210 s with
the defaults). Repository code is never executed, built or installed.

Request ([`fixtures/analyze_request.json`](fixtures/analyze_request.json)),
`Content-Type: application/json`:

```json
{ "repo_url": "https://github.com/acme/shop-api", "ref": "main" }
```

- `repo_url` (required): HTTPS URL on an allowed host (`github.com` by
  default) in the form `https://github.com/<owner>/<repo>`, optionally ending
  in `.git` or `/`. Rejected with 400 `invalid_repository_url`: other schemes
  (`http`, `ssh`, `git@…`, `file`), credentials, ports, query strings,
  fragments, extra path segments (`/tree/main`), percent-encoding, non-ASCII
  characters, and hosts that resolve to private, loopback or link-local
  (cloud metadata) addresses.
- `ref` (optional): a **branch or tag** name; the default branch if omitted or
  `null`. Commit SHAs are not supported (the clone is shallow): a SHA returns
  404 `ref_not_found`. A `ref` starting with `-` or containing `..` is 422.
- Unknown fields are rejected (422).

**Responses**

| HTTP | Body | Meaning |
| --- | --- | --- |
| **201** | `AnalysisSummary`, plus a `Location: /api/analyses/{id}` header | An analysis was created and stored. **Always check `status`.** |
| 400 / 404 / 413 / 502 / 503 / 504 | `ErrorResponse` | The repository could not be fetched (see the error table). Nothing is stored |
| 422 | `ErrorResponse` | Invalid request body |
| 429 | `ErrorResponse` | Too many concurrent analyses; retry after `Retry-After` seconds |
| 500 | `ErrorResponse` | Unexpected server error before an analysis existed |

**`status` in a 201 response**

| `status` | When | `error` | `/graph`, `/paths` |
| --- | --- | --- | --- |
| `completed` | A call graph was built. Individual files may still have failed or been skipped; see `diagnostics` | `null` | 200 |
| `failed` | Eligible files existed but none could be parsed (`error.code: "parsing_failed"`), or graph construction hit an internal error (`"analysis_failed"`) | set | 409 `analysis_failed` |

A repository with **no supported files** is `completed`, with zero counts, an
empty graph and the warning
`"No JavaScript or TypeScript files were analyzed; see skipped_files."`.
`queued` and `running` are reserved for a future asynchronous mode and are
never returned today.

Successful response, abridged (full version:
[`fixtures/analysis_summary.json`](fixtures/analysis_summary.json)):

```json
{
  "analysis_id": "4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a",
  "status": "completed",
  "repository": {
    "url": "https://github.com/acme/shop-api", "host": "github.com",
    "owner": "acme", "name": "shop-api", "ref": "main",
    "commit_sha": "9b2e4c7a1d3f5e6b8c0a2d4f6e8b0c2a4d6f8e0b"
  },
  "created_at": "2026-10-12T09:15:02Z",
  "completed_at": "2026-10-12T09:15:06Z",
  "duration_ms": 4120,
  "stats": {
    "files_discovered": 5, "files_analyzed": 3, "files_skipped": 2,
    "functions": 9, "call_edges": 5, "unresolved_calls": 18,
    "findings": 2, "findings_by_severity": { "medium": 1, "high": 1 },
    "files_by_language": { "typescript": 3 }
  },
  "diagnostics": {
    "parse_errors": [],
    "skipped_files": [
      { "path": "README.md", "reason": "unsupported_extension" },
      { "path": "package.json", "reason": "unsupported_extension" }
    ],
    "skipped_by_reason": { "unsupported_extension": 2 },
    "limits_reached": [],
    "warnings": [
      "Call graph is partial: member calls, dynamic dispatch and external packages are reported as unresolved."
    ],
    "truncated": false
  },
  "error": null
}
```

Failed analysis: see [`fixtures/analysis_failed.json`](fixtures/analysis_failed.json).

Error examples:

```json
{ "error": { "code": "invalid_repository_url", "message": "Repository URLs must not contain credentials" } }
{ "error": { "code": "ref_not_found", "message": "Branch or tag 'nope' was not found in the repository" } }
{ "error": { "code": "repository_unavailable", "message": "The repository could not be cloned. Check that it exists and is public." } }
{ "error": { "code": "clone_timeout", "message": "Cloning exceeded 60s" } }
{ "error": { "code": "too_many_analyses", "message": "Too many analyses are running; retry shortly" } }
```

### `GET /api/analyses/{analysis_id}` — implemented

Returns the same `AnalysisSummary` that `POST /api/analyze` returned, with
status 200, for `completed` and `failed` analyses alike. An unknown, malformed
or expired ID returns 404 `analysis_not_found`.

- `repository.commit_sha`: the exact commit analyzed. Every endpoint for this
  `analysis_id` describes this one commit.
- `created_at`: when the request was received. `completed_at` and
  `duration_ms` cover the whole pipeline (clone, parse, graph).
- `stats`: counts of files, functions, edges, unresolved calls and findings.
  `files_discovered = files_analyzed + files_skipped`, and `files_skipped`
  equals the sum of `diagnostics.skipped_by_reason`.
  - **`findings`:** the number of rule findings for a `completed` analysis.
    `0` is a real result: no rule matched in the analyzed files. `null` means
    "not computed", which only happens for `failed` analyses.
  - **`findings_by_severity`:** counts per severity, matching `/findings`.
  - **Coverage:** rules run only on files that were parsed. If some could not
    be parsed, a warning says
    `"Rules did not run on N file(s) that could not be parsed; findings may be incomplete."`.
- `diagnostics`: what could not be analyzed (parse errors, skipped files,
  limits reached, warnings). Show these to users so that they understand what
  coverage the analysis had.
  - `skipped_files` is a bounded sample. `skipped_by_reason` has the full counts.
  - Excluded directories are not walked and their files are not counted:
    every directory starting with `.` (including `.git/`), plus `node_modules`,
    `bower_components`, `jspm_packages`, `vendor`, `dist`, `build`, `out`,
    `coverage`, `target`, `tmp`, `temp`, `__pycache__`, `venv`, `storybook-static`.
  - `parse_errors` lists syntax errors (Tree-sitter recovers, and the rest of
    the file is still analyzed) and files that could not be parsed at all, for
    example `"Parser process crashed (SIGSEGV) while parsing this file; file skipped"`.
  - `limits_reached` names each limit that cut the analysis short, with its
    value, for example `{"limit": "parse_file_timeout_seconds", "value": 15}`.
  - `warnings` holds analysis-wide notes: partial call graph, files without
    rule coverage, rule errors (`"Rules: <path>: <rule_id>: internal error; rule skipped"`),
    and `"Findings were not computed because the analysis failed."`.
  - `truncated: true` means one of these lists was capped.

**Storage and restarts.** Analyses live **in memory only**:
- **Capacity:** the server keeps the `max_stored_analyses` (default 20) most
  recently used, and evicts the oldest.
- **Restarts:** everything is lost when the server restarts.
- **Expired IDs:** an expired ID gives 404 `analysis_not_found`; re-run `POST /api/analyze`.
- **Frontend handling:** don't persist analysis IDs long-term.

**Skip reasons**

| `reason` | Meaning |
| --- | --- |
| `unsupported_extension` | Not `.js .jsx .mjs .cjs .ts .mts .cts .tsx` |
| `excluded_pattern` | Generated or declaration-only (`*.min.js`, `*.bundle.js`, `*.chunk.js`, `*.d.ts`, …), or an unrepresentable path |
| `sensitive_file` | Secrets and keys (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `.npmrc`, `*credentials*.json`, …). Never read |
| `too_large` | Over `max_file_bytes`, or a syntax tree over `max_syntax_nodes_per_file` |
| `binary` | Contains NUL bytes or is not valid UTF-8 |
| `symlink` | Symbolic links are never followed |
| `limit_reached` | A repository-wide limit (file count, total bytes, parse time) was hit first |
| `parse_failed` | Accepted for analysis, but the parser crashed, timed out or raised. Details in `parse_errors` |
| `excluded_directory` | Reserved; **not currently emitted**. Excluded directories are not walked, so their files are never counted |

### `GET /api/analyses/{analysis_id}/graph` — implemented

Returns a `GraphResponse` ([`fixtures/graph.json`](fixtures/graph.json)).

| Query parameter | Default | Bounds | Effect |
| --- | --- | --- | --- |
| `path_prefix` | none | repo-relative path, no trailing `/` | Only functions in that directory or file |
| `max_nodes` | 2000 | 1–20000 | Node budget; `truncated: true` if more exist |
| `max_unresolved` | 500 | 0–5000 | Length of `unresolved_calls`; `unresolved_calls_total` has the full count |

The response is always a self-consistent graph: every edge's `source` and
`target` is in `nodes`, and every `unresolved_calls[].caller_id` is too. Edges
crossing the `path_prefix` or `max_nodes` boundary are omitted, and
`limitations` says so. Ordering is deterministic: nodes by
`(path, start_line, start_column)`, edges by source then target node order,
and unresolved calls by `(path, line, column)`. Repeated requests return
identical JSON. For React Flow, map `nodes[].id` → node `id` and
`edges[].source`/`target` → edge `source`/`target`.

**FunctionNode**

| Field | Notes |
| --- | --- |
| `id` | `fn_…`, unique within the analysis |
| `name` | Short name, `<anonymous>` if none (`is_anonymous: true`), `<module>` for module nodes |
| `qualified_name` | e.g. `SessionManager.create` |
| `kind` | `module`, `function_declaration`, `function_expression`, `arrow_function`, `method`, `constructor` |
| `language` | `javascript` or `typescript` (`.jsx`/`.tsx` included) |
| `path`, `start_line`, `end_line`, `start_column` | Declaration location |
| `is_exported` | Exported from its module |

A `module` node represents a file's top-level code. It exists only for files
that make top-level calls, so that those calls have a caller.

How functions are named:

| Source | `name` / `qualified_name` |
| --- | --- |
| `function f() {}` | `f` |
| `const f = () => {}` / `const f = function () {}` | `f` |
| `class A { m() {} }`, `class A { h = () => {} }` | `m` / `A.m`, `h` / `A.h` |
| `const o = { k() {}, v: () => {} }` | `k` / `o.k`, `v` / `o.v` |
| `module.exports.go = function () {}` | `go` / `module.exports.go` |
| nested `function outer() { function inner() {} }` | `inner` / `outer.inner` |
| callbacks such as `list.map(() => …)` | `<anonymous>` / `outer.<anonymous>` |

TypeScript overload signatures, `declare function`, interface members and
abstract methods have no body and are not function nodes.

**CallEdge.** There is one edge per `(source, target)` pair, so it's safe to
draw directly. Every call site is listed in `call_sites`.

| `resolution` | Meaning |
| --- | --- |
| `same_file` | `f()` (or `Class.staticMethod()`) where the name is declared in an enclosing scope of the same file |
| `import` | Reached through a relative `import`/`require`, including re-exports, `export *`, namespaces (`ns.f()`) and CommonJS `exports`/`module.exports` |
| `this_method` | `this.m()` in a class member (or an arrow inside one) where the class declares `m` and no subclass redeclares it |
| `constructor` | `new X()` where `X` has an explicit `constructor` (or is an ES5 constructor function) |
| `instance_method` | `x.m()` where `x` is a `const` bound to `new X(...)` (same file or imported) and `X` declares `m` |

If one pair is reached in several ways, the first in this table wins.
`new X()` without an explicit constructor links nothing; it is neither an
edge nor an unresolved call.

**UnresolvedCall.** Every call that is not an edge is listed, with a reason:

| `reason` | Meaning | Typical example |
| --- | --- | --- |
| `unknown_symbol` | Name not declared in any enclosing scope or import, or member not declared on the resolved class (may be inherited) | `setTimeout()`, `console.log()`, `this.inheritedMethod()` |
| `ambiguous_symbol` | Several candidate declarations, modules, or a possible subclass override | duplicate declarations; `./x` matching `x.ts` and `x.js`; overridden `this.hook()` |
| `member_call` | Receiver's value or type is not statically known | `req.json()`, `obj.method()`, `this.m()` in a plain function |
| `dynamic_call` | Callee is computed, or a parameter/variable holding a function | `handlers[k]()`, `callback()` |
| `external_module` | Comes from a package outside the repository | `express()`, `new Pool()` |
| `unsupported_syntax` | A shape the resolver does not model | `(function () {})()`, `super.m()`, calling a class without `new` |
| `unresolved_import` | Relative import/re-export that matches no analyzed file or export | import of a skipped, unparsed or missing file |

Names are never matched across files by spelling. A global call such as
`helper()` is not linked to some file's `helper` unless that file is imported.

`require("…")` and `import("…")` are treated as module loading, not as calls.
JSX elements (`<Foo />`) and decorators without parentheses are not recorded
as calls.

### `GET /api/analyses/{analysis_id}/findings` — implemented

Returns a `FindingsResponse` ([`fixtures/findings.json`](fixtures/findings.json)):
the findings produced by the rule engine for this analysis. **A finding is a
potential issue for human review, not a confirmed vulnerability.**

| Query parameter | Default | Bounds | Effect |
| --- | --- | --- | --- |
| `severity` | none | `info`, `low`, `medium`, `high`, `critical` | Only findings of exactly this severity |
| `rule_id` | none | e.g. `js.sql-string-construction` | Only findings of this rule |
| `path_prefix` | none | repo-relative path, no trailing `/` | Only findings in this directory or file |
| `limit` | 500 | 1–1000 | Page size; `total` is the full filtered count, `truncated: true` if more exist |

- **Ordering is deterministic:** by `(path, start_line, end_line, rule_id, id)`.
  Repeated requests return identical JSON.
- **Locations are real:** every `location` is a line range of an analyzed file,
  retrievable from `/source`.
- **Linked to the graph:** every non-null `function_id` is a node in `/graph`.

| Field | Notes |
| --- | --- |
| `id`, `rule_id` | e.g. `fd_…`, `js.sql-string-construction`. IDs are stable for identical source |
| `title`, `description` | Human-readable explanation; descriptions say "may" because matches are leads |
| `severity` | `info < low < medium < high < critical` |
| `confidence` | `low`, `medium`, `high`: how likely the match is what the rule describes |
| `location` | `SourceReference` (`path`, `start_line`, `end_line`) |
| `function_id` | Innermost enclosing function node, the file's `<module>` node at top level, or `null` if that file has no module node |
| `evidence` | The matched line(s), up to 3 lines and 500 chars. **Credential-like values are redacted** (`[REDACTED len=33]`) |
| `review_status` | `needs_review`, `confirmed` or `dismissed`. The backend always sends `needs_review`; the other values are reserved for review state, which the client tracks for now |
| `next_step` | Suggested investigation, which is good input for the AI investigator |
| `limitations` | What the rule cannot know |
| `cwe_id` | e.g. `CWE-89` |

**Rules**

| `rule_id` | Detects | Severity | CWE |
| --- | --- | --- | --- |
| `js.dynamic-code-execution` | `eval(...)`, `Function(...)`, `new Function(...)` (also via `window`/`globalThis`), and strings passed to `setTimeout`/`setInterval` | high; low when the code is a constant string | CWE-95 |
| `js.shell-command-construction` | `exec`/`execSync` with a non-constant command, or the `spawn`/`execFile` family with `shell: true` and non-constant input, when the function comes from a visible `child_process` import or `require` | high | CWE-78 |
| `js.sql-string-construction` | Template literals or `+` concatenations with non-constant values whose text starts like SQL (`SELECT … FROM`, `INSERT INTO`, `UPDATE … SET`, `DELETE FROM`, DDL). Tagged templates are skipped, since libraries often parameterize them | high | CWE-89 |
| `js.tls-verification-disabled` | `rejectUnauthorized: false`, `strictSSL: false`, `….rejectUnauthorized = false`, `NODE_TLS_REJECT_UNAUTHORIZED = "0"` | high | CWE-295 |
| `js.hardcoded-credential` | String literals assigned to names ending in a secret word (`password`, `secret`, `token`, `apiKey`, `privateKey`, …), and literals matching known token formats (AWS, GitHub, Slack, Stripe live, Google API keys, PEM private keys) | medium (by name); high (token format) | CWE-798 |

Rules inspect the syntax tree; regexes are applied only to string-literal
content. Nothing is executed. Rules run in the isolated parser worker, under
the same per-file timeout as parsing. At most `max_findings_per_file`
(default 100) findings are kept per file; beyond that, `limits_reached`
includes `max_findings_per_file`.

### `GET /api/analyses/{analysis_id}/source?path=…&start_line=…&end_line=…` — implemented

Returns a `SourceResponse` ([`fixtures/source.json`](fixtures/source.json)):
lines of a file **as analyzed in this analysis's commit**.

| Query parameter | Default | Bounds |
| --- | --- | --- |
| `path` | required | Repository-relative POSIX path, as in `nodes[].path` and `findings[].location.path`. Absolute paths, `..`/`.` segments, `//`, backslashes and NUL bytes return 422 |
| `start_line` | 1 | 1-based, inclusive, at most 10,000,000 |
| `end_line` | end of file | Inclusive, at most 10,000,000; clamped to the last line |

- **Which files are served:** only files that were **analyzed** (accepted
  by ingestion filtering and successfully parsed). Anything else returns 404
  `file_not_found`. That includes excluded secrets (`.env*`, keys),
  dependency/build directories, binaries, unsupported files and files whose
  parse failed. Paths are case-sensitive.
- **At most 500 lines per response:** `truncated: true` means the requested
  range (or, without `end_line`, the rest of the file) continues. Request the
  next window with `start_line = end_line + 1`.
- **Line ranges:**
  - `start_line` past the last line, or `end_line < start_line`, returns 400 `invalid_line_range`.
  - `start_line`/`end_line` below 1 return 422.
  - An empty file returns `start_line: 1, end_line: 0, total_lines: 0, content: ""`.
- **How lines are split:** on `\n` only, matching node and finding line numbers.
  `content` includes the newline that ends each returned line. The last line of
  a file without a trailing newline has none.
- **Redaction:** values that the credential rule matched are replaced by
  `[REDACTED len=N]`. Line numbers never shift, because redacted values keep
  their newlines. `redacted_values` counts replacements in the returned lines.
- **Still untrusted:** `content` is repository text. Render it as plain text,
  and mark it as data when passing it to an LLM.

### `GET /api/analyses/{analysis_id}/paths?source=…&target=…&max_depth=…&max_paths=…` — implemented

Returns a `PathsResponse` ([`fixtures/paths.json`](fixtures/paths.json)).

| Query parameter | Default | Bounds |
| --- | --- | --- |
| `source`, `target` | required | `fn_` + 16 hex characters; malformed returns 422, unknown returns 404 `function_not_found` |
| `max_depth` | 8 | 1–20 edges per path |
| `max_paths` | 10 | 1–100 |

- Only simple paths (no repeated function) along resolved edges are returned,
  so cycles are safe. Results are shortest first, then ordered by node IDs.
- `source == target` returns the single zero-length path `{"node_ids": [id], "edge_ids": []}`.
- No path returns `paths: []`. Check `limitations`: it reports how many
  unresolved calls occur in functions reachable from `source`, through which
  real paths may exist.
- `truncated: true` means more paths may exist (`max_paths` or the server's
  exploration budget was reached).
- `edge_ids[i]` connects `node_ids[i]` → `node_ids[i+1]`.
- A path shows possible call chains only. It does not prove runtime
  execution, data flow or exploitability.

## Frontend workflow

```
POST /api/analyze {repo_url, ref}
  └─ 201 AnalysisSummary (analysis_id, status)
       ├─ GET /api/analyses/{id}                      summary, revision, diagnostics
       ├─ GET /api/analyses/{id}/graph                nodes, edges, unresolved calls
       │     └─ node ids ─┐
       ├─ GET /api/analyses/{id}/paths?source=&target=   paths of node and edge ids
       ├─ GET /api/analyses/{id}/findings             rule findings; function_id → graph node
       └─ GET /api/analyses/{id}/source?path=…        text for a node or finding location
```

- **One ID for everything:** every read endpoint takes the same `analysis_id`
  and describes the same commit.
- **IDs link the responses:** node IDs from `/graph` are the `source`/`target`
  of `/paths`. Findings point at nodes via `function_id` and at code via
  `location` (`path`, `start_line`, `end_line`). That location is the input to
  `/source`, the same shape as each node's `path`/`start_line`/`end_line`.
- **Order of calls:** call `/graph` only when `status` is `completed`.

Try it locally without GitHub:

```bash
.venv/bin/python -m scripts.demo_server     # serves the example analysis on 127.0.0.1:8000
```

The demo server pre-loads analysis `4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a`, built
by the real pipeline from `tests/fixtures/repos/shop_api`. Its responses are
exactly the JSON in `docs/fixtures/`:

```bash
curl http://127.0.0.1:8000/api/analyses/4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a
curl http://127.0.0.1:8000/api/analyses/4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a/graph
curl "http://127.0.0.1:8000/api/analyses/4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a/paths?source=fn_63a298464ab84151&target=fn_24417c4e8adf123b"
```

Analyze a real public repository (requires network access from the server):

```bash
curl -X POST http://127.0.0.1:8000/api/analyze -H 'Content-Type: application/json' -d '{"repo_url": "https://github.com/expressjs/express"}'
```

## Running locally

See [`../README.md`](../README.md). Interactive docs are at `http://localhost:8000/api/docs`.
CORS allows `http://localhost:3000` by default (`REPOPILOT_CORS_ALLOWED_ORIGINS`).
