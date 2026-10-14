# RepoPilot Analyzer

The static-analysis backend for RepoPilot. It ingests public JavaScript/TypeScript
repositories, extracts functions and calls, builds a partial call graph, runs a
small set of suspicious-pattern rules, and serves verifiable source evidence
to the frontend and AI investigator.

The analyzer never executes, builds, or installs anything from an analyzed
repository.

- Frontend integration guide (start here): [`docs/frontend-integration.md`](docs/frontend-integration.md)
- API contract and examples: [`docs/api-contract.md`](docs/api-contract.md)
- JSON fixtures (validated in tests): [`docs/fixtures/`](docs/fixtures/)

## Status

| Phase | Area | State |
| --- | --- | --- |
| 0–1 | Shared contracts, FastAPI foundation, `/api/health` | Done |
| 4 | Repository ingestion and file filtering | Done |
| 5 | JS/TS parsing and extraction | Done |
| 6 | Call resolution, call graph, path search, `/graph` and `/paths` endpoints | Done |
| 8 | `POST /api/analyze`, `GET /api/analyses/{id}` (end-to-end HTTP workflow) | Done |
| 7 | Rule engine, `/findings`, source retention and `/source` | Done |

## Requirements

- Python 3.11+ (the macOS system `python3` 3.9 is too old)
- `git` on `PATH` (ingestion clones with it)
- macOS or Linux. The clone runner uses POSIX process groups.

## Setup

```bash
cd services/analyzer
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # optional
```

## Run

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Then open `http://localhost:8000/api/health` or `http://localhost:8000/api/docs`.

Analyze a public repository (the server needs network access to GitHub):

```bash
curl -X POST http://127.0.0.1:8000/api/analyze -H 'Content-Type: application/json' -d '{"repo_url": "https://github.com/expressjs/express"}'
```

For frontend work without GitHub, the demo server pre-loads the documented
example analysis (`4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a`) and serves exactly the
JSON in `docs/fixtures/`:

```bash
.venv/bin/python -m scripts.demo_server
```

### How an analysis runs

`POST /api/analyze` is **synchronous**. It runs these steps in one request:
1. **Validate** the request (`AnalyzeRequest`).
2. **Ingest:** hardened shallow clone into a temporary workspace that is
   always deleted, then a bounded scan.
3. **Parse** in the isolated worker process.
4. **Build the graph:** resolve calls and build the call graph.
5. **Summarize and store** the result in memory.

Time and load are bounded:
- **Time:** the request takes at most `clone_timeout_seconds` +
  `parse_time_budget_seconds` (plus graph building, which is bounded by the
  graph size caps).
- **Concurrency:** at most `max_concurrent_analyses` analyses run at once;
  more requests get 429 with `Retry-After`.

Failures before an analysis exists (invalid input, clone errors) return the
standard error envelope and store nothing. Otherwise the response is 201:
- **`completed`:** per-file problems are listed in `diagnostics`.
- **`failed`:** no file could be parsed, or graph building hit an internal
  error. `/graph` and `/paths` then return 409.

Analyses are kept **in memory only**: the `max_stored_analyses` most recently
used, and none survive a restart. An expired ID returns 404.

## Quality checks

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest
```

The test suite needs no network access. Git integration tests clone local
repositories over `file://`. It never crashes a native process: worker-failure
tests use controlled failures (SIGTERM, nonzero exit, hang, exception).

Three canary tests deliberately trigger native crashes (the tree-sitter
`Point` bug and a real SIGSEGV in the parser worker). They are skipped by
default. On macOS each run shows a "Python quit unexpectedly" dialog, so run
them only when checking a tree-sitter upgrade or the crash supervisor:

```bash
REPOPILOT_RUN_NATIVE_CRASH_CANARY=1 .venv/bin/pytest -m native_crash
```

## Using ingestion and parsing from code

```python
from app.config import get_settings
from app.ingestion.service import ingest_repository
from app.parsers.service import parse_repository

settings = get_settings()
ingested = ingest_repository("https://github.com/acme/shop-api", "main", settings)
parsed = parse_repository(ingested.files, settings)
```

`ingest_repository` raises an `IngestionError` subclass with an HTTP status and
a client-safe message (see the error table in the API contract).
`parse_repository` never raises for a bad file. Per-file problems are returned
as diagnostics.

## Call graph and path search

`app/graph/` turns parser output into a directed call graph:

- **`modules.py`** maps relative specifiers to analyzed files: extension
  probing, `index` files, and TypeScript's `./x.js` → `x.ts`. Several matches
  are ambiguous, never guessed. Bare packages are external, and paths that
  escape the repository are refused.
- **`resolver.py`** resolves calls through lexical scopes and imports only:
  - **Supported:** same-file calls, named/default/namespace imports,
    re-exports and `export *`, CommonJS `require`/`exports`, `this.m()` (unless
    a subclass redeclares `m`), `const x = new X(); x.m()`, static methods,
    and `new X()` to explicit constructors.
  - **Not resolved:** anything else stays an unresolved call with a reason.
    Names are never matched across files by spelling.
- **`builder.py`** builds the graph. There is one edge per caller/callee pair with
  all call sites, the ordering is deterministic, the IDs are stable, and the size
  is capped (`max_graph_nodes`, `max_graph_edges`). Malformed parser output is
  skipped with diagnostics.
- **`paths.py`** runs a BFS over simple paths, so cycles are safe. It is bounded by
  depth, path count and an exploration budget, and pruned by a reverse-BFS
  distance to the target.

`app/services/analysis.py` builds each analysis once and serves every read
endpoint from that stored result, so every response for an `analysis_id`
describes one commit. `app/storage/memory.py` keeps the last
`max_stored_analyses` analyses in memory (LRU, no persistence).

Documentation fixtures are regenerated from real output with
`.venv/bin/python -m scripts.doc_fixtures`. A test fails when they are stale.

## Findings and source evidence

`app/rules/` is a small, deterministic rule engine. It runs **inside the
parser step**, which means inside the isolated worker and under the per-file
timeout, because rules need the syntax tree. There are five syntax-aware rules
(see the table in the API contract): dynamic code execution, shell commands
built from `child_process` imports, SQL built by interpolation or
concatenation, disabled TLS verification, and hardcoded credentials.

- **Findings are leads, not verdicts.** Every finding is `needs_review` and
  lists its limitations. There is no taint analysis.
- **Errors are isolated:** a rule that raises is skipped for that file and
  reported as a warning; extraction and other rules continue.
- **Performance:** rules receive each node's parent from the engine and must
  not call `Node.parent`, which is O(depth) in Tree-sitter. A test enforces this.
- **Credential values are never shown:** they are redacted in finding
  evidence and in `/source` content, without shifting line numbers.

**Source retention.** Each stored analysis keeps the text of the files it
analyzed: files that passed ingestion filtering (secrets, keys, env files,
binaries and dependency or build directories are never read) and were parsed
successfully. Nothing else is retained.
- **Size:** retained text is bounded per file and per analysis by the
  existing ingestion limits.
- **Store budget:** the in-memory store also enforces
  `max_stored_source_bytes` (default 256 MB) across all analyses, evicting the
  least recently used. The newest analysis is always kept.
- **Logging:** source text is never logged.

## Ingestion safety model

1. **URL validation** (`app/ingestion/url.py`): only
   `https://<allowed-host>/<owner>/<repo>`. Credentials, ports, query strings,
   fragments, percent-encoding, non-ASCII and extra path segments are rejected.
   The URL handed to git is rebuilt from validated parts.
2. **SSRF check** (`app/ingestion/network.py`): the allowed host must resolve
   only to public addresses. git resolves the host again, so this is
   defense in depth behind the host allowlist, not protection against DNS
   rebinding.
3. **Hardened clone** (`app/ingestion/git.py`):
   - **Clone scope:** `--depth=1 --single-branch --no-tags --no-recurse-submodules`.
   - **Transports:** only https is allowed (`protocol.allow=never`) and HTTP redirects are refused.
   - **Disabled git features:** hooks, templates, symlinks, credential helpers and LFS downloads.
   - **Isolated environment:** git gets an empty one, with no user or system git config and no inherited tokens.
   - **Resource limits:** a wall-clock timeout and an on-disk size cap kill the whole process group.
4. **Temporary workspace** (`app/ingestion/workspace.py`): created per
   analysis and always deleted, on success or failure. Accepted source files
   are held in memory, so nothing stays on disk.
5. **File filtering** (`app/ingestion/scanner.py`, `filters.py`):
   - **Walk:** deterministic and bounded. Excluded and hidden directories are never walked, and symlinks are never followed (files are opened with `O_NOFOLLOW`).
   - **Never read:** secrets and keys, generated and minified files, `.d.ts`, binary and non-UTF-8 files.
   - **Limits:** file count, per-file size and total size are capped.

## Parsing and crash isolation

Parsing uses Tree-sitter (`tree-sitter` 0.26.0, `tree-sitter-javascript`
0.25.0, `tree-sitter-typescript` 0.23.2). The extractor (`app/parsers/extractor.py`)
records facts only: functions, classes, imports, exports, calls classified by
callee shape, and declared names per scope. Calls whose target can never be
determined statically are already marked unresolved. Resolving the rest is
the job of the graph layer.

Tree-sitter is native code processing untrusted input, so by default
(`REPOPILOT_PARSE_ISOLATION=subprocess`) it runs in a spawned worker process
(`app/parsers/worker.py`):

- **Native crash:** if the worker crashes (e.g. SIGSEGV), that file gets a
  diagnostic and a fresh worker continues with the next file. The API process is
  unaffected.
- **Hang:** a file that takes longer than `parse_file_timeout_seconds` has its
  worker killed and is reported. Tree-sitter 0.26 has no parse timeout of its own.
- **Structural limit:** `max_syntax_nodes_per_file` skips files with huge syntax
  trees, in addition to the byte limits.
- **Time budget:** `parse_time_budget_seconds` bounds the whole repository.

### Known dependency bug: `tree_sitter.Point`

In tree-sitter 0.26.0, reading `Point.row` or `Point.column` (from
`Node.start_point` / `end_point`) drops a reference to the returned int on
every access. Once the int is freed the interpreter heap is corrupted and the
process crashes later, often in unrelated code, with exit code 139 (SIGSEGV).
Index access (`point[0]`) is not affected.

The cause is upstream: the 0.26.0 getters return a borrowed reference
(`PyTuple_GetItem`) instead of a new one. It is fixed on py-tree-sitter `master`
(commit `afb3836b`, "fix(point): fix reference counting issues") but not
released yet. 0.25.2, whose `Point` is a `namedtuple`, is unaffected, and the
project suite passes on it apart from the canaries.

The analyzer therefore never uses `Point`. All positions are computed from
`start_byte`/`end_byte`. `tests/unit/parsers/test_tree_sitter_regression.py` checks, by default:
- every `Node` accessor the extractor uses is refcount-safe;
- the inputs that crashed the first extractor now complete;
- no code in `app/` or `scripts/` reads `start_point`, `end_point`, `range` or `byte_range`.

Opt-in only (`native_crash`), because they trigger the upstream bug: the
minimal crash reproducer and a refcount measurement. If those start failing
after an upgrade, the bug is fixed upstream and the workaround can be revisited.

## Configuration

All settings are environment variables with the `REPOPILOT_` prefix. See
`app/config.py`; `.env.example` lists every setting with its default. Do not
put tokens in `.env.example`.

## Layout

```
app/
  main.py          application factory (create_app) and ASGI app
  config.py        Settings (pydantic-settings)
  errors.py        domain errors mapped to HTTP status + error code
  api/             routes, dependencies, error handlers. No business logic here
  models/          shared data contracts (coordinate changes with Member 2)
  ingestion/       URL validation, SSRF check, hardened clone, workspace, scanner
  parsers/         Tree-sitter grammars, extractor, per-file parser, worker isolation
  graph/           module resolution, call resolver, graph builder, path search
  rules/           suspicious-pattern rule engine               (Phase 7)
  storage/         analysis store interface, bounded in-memory implementation
  services/        analysis orchestration and read models used by routes
tests/
  unit/  api/  helpers/
  fixtures/repos/  deterministic fixture repositories
scripts/
  doc_fixtures.py  regenerates the generated docs/fixtures files
  demo_server.py   local API with the example analysis pre-loaded (frontend dev)
docs/
  api-contract.md  fixtures/
```
