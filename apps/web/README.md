# RepoPilot Web Workspace

The Next.js web application for **RepoPilot** — providing an interactive codebase investigation workspace powered by static analysis and grounded AI insights.

---

## Architecture Overview

RepoPilot Web provides a single-pane investigation interface containing:
- **Repository Ingestion & Status**: Synchronous analysis submission and real-time backend health monitoring.
- **Interactive Call Graph**: Function node visualization, caller/callee relationships, and node selection with `@xyflow/react`.
- **Findings Explorer**: Static analysis finding triage with severity filters, rules, search queries, and local human review tracking.
- **Source Code Viewer**: Line-numbered syntax-highlighted excerpts with highlighted target lines and dynamic window paging.
- **Unresolved Calls Panel**: Diagnostic list of dynamic invocations and unresolved imports with jump-to-call-site actions.
- **Call Paths Explorer**: Shortest call path search connecting source functions to sensitive targets.
- **Evidence-Grounded AI Investigator**: Strict citation validation ensuring every answer is backed by retrieved findings, nodes, and source lines.

---

## Getting Started

### 1. Prerequisites
- **Node.js**: v20 or v22 LTS
- **Python**: 3.11+ (for the analyzer service in `services/analyzer`)

### 2. Analyzer Startup

Start the Python analyzer backend service on port 8000:

```bash
# From the repository root
cd services/analyzer

# Create virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start demo analyzer server
python -m app.main
# Or run with uvicorn:
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Verify backend health at `http://127.0.0.1:8000/api/health`.

### 3. Frontend Configuration

Copy the example environment template in `apps/web`:

```bash
cd apps/web
cp .env.example .env.local
```

Configure your environment variables in `.env.local`:

| Variable | Description | Default |
|---|---|---|
| `ANALYZER_API_URL` | Base URL of the Python analyzer service | `http://127.0.0.1:8000` |
| `OPENAI_API_KEY` | OpenAI API key for grounded AI investigation | *(optional)* |
| `OPENAI_BASE_URL` | Optional custom base URL for OpenAI-compatible proxies | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | Optional model name | `gpt-4o-mini` |

> **Note**: AI configuration is optional. When `OPENAI_API_KEY` is omitted, graph exploration, findings browsing, and source viewing remain fully functional, while the AI investigator panel clearly reports that the AI provider is unconfigured instead of generating fabricated answers.

### 4. Frontend Startup

Install dependencies and launch the Next.js development server:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## Development Scripts

| Command | Action |
|---|---|
| `npm run dev` | Launch local development server with Turbopack |
| `npm run typecheck` | Run the TypeScript compiler (`tsc --noEmit`) to verify all types |
| `npm run lint` | Run ESLint CLI (`eslint .`) using the configured ESLint 9 flat config |
| `npm run test` | Run test suites via Vitest (`vitest run`) |
| `npm run build` | Compile and build production Next.js bundle |
| `npm start` | Start production Next.js server |

---

## Key Concepts & Limitations

### In-Memory Analysis Storage
The analyzer stores analysis runs, parsed ASTs, call graphs, and extracted findings in an in-memory session cache.
- Analysis IDs are 32-character hexadecimal strings (e.g., `4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a`).
- If the analyzer service restarts, previously computed analyses expire and must be re-submitted.
- Failed analyses produce diagnostics and error codes; graph and findings endpoints are not requested for failed runs.

### Real Analyzer Data vs. Test Fixtures vs. Local Review State
- **Production Analyzer Data**: In production, the UI calls the analyzer via Next.js proxy/server routes (`/api/proxy/...` and `/api/investigate`). Data is immutable and reflects the analyzed repository ref.
- **Unit Test Fixtures**: Frontend tests use mock fixtures matching the backend contract to verify component behavior in isolation without external dependencies.
- **Local Review State**: The "Local Review" dropdown actions (`needs_review`, `confirmed`, `dismissed`) in the Findings panel are stored purely in client-side React state for the duration of the user session. They do not mutate analyzer data on the backend.
