# RepoPilot

**AI-Powered Codebase Investigation and Evidence-Based Code Intelligence**

RepoPilot helps developers understand unfamiliar codebases, explore function dependencies, investigate suspicious code paths, and obtain AI-assisted explanations backed by source-code evidence.

Instead of relying on an AI-generated summary alone, RepoPilot combines static analysis, a navigable call graph, rule-based findings, and evidence-grounded investigation.

> **Project status:** Hackathon MVP in development.

## Overview

Understanding an unfamiliar codebase can require hours of navigating files, following function calls, and investigating potentially unsafe behavior.

RepoPilot aims to make this process faster by providing a unified workspace for code exploration and investigation.

### Key Features

- **Repository Analysis:** Index supported source files and extract functions, imports, and function-call relationships.
- **Interactive Dependency Graph:** Explore functions and their relationships visually.
- **Code Path Investigation:** Trace statically resolvable call paths between selected functions.
- **Suspicious Pattern Detection:** Identify selected potentially unsafe coding patterns using explicit analysis rules.
- **AI-Assisted Investigation:** Ask questions about a repository and receive explanations supported by source references.
- **Evidence Navigation:** Open cited files and inspect the relevant line ranges.
- **Investigation Reports:** Export findings, evidence, and recommended next steps.
- **Bounded Repository Processing:** Apply limits to repository size, file types, and analysis time.

## How It Works

1. Submit a supported repository URL or source-code archive.
2. RepoPilot indexes eligible source files.
3. The analysis engine extracts functions, imports, and resolvable call relationships.
4. The graph engine constructs a directed function-call graph.
5. Detection rules identify suspicious code patterns.
6. The retrieval layer selects relevant source snippets and analysis results.
7. The AI investigator generates an explanation using the retrieved evidence.
8. The interface displays findings, graph paths, source references, and report exports.

## Architecture

```text
Next.js Frontend
       |
       v
FastAPI Backend
       |
       +---- Repository Ingestion
       |
       +---- Static Analysis
       |        |
       |        +---- AST Parsing
       |        +---- Function Extraction
       |        +---- Call Graph
       |        +---- Detection Rules
       |
       +---- Evidence Retrieval
       |
       +---- AI Investigation
       |
       v
Structured Findings and Reports
```

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | Next.js, React, TypeScript |
| Styling | Tailwind CSS, shadcn/ui |
| Graph Visualization | React Flow |
| Backend | Python, FastAPI, Pydantic |
| Source Analysis | Tree-sitter or TypeScript Compiler API |
| Detection | Custom static-analysis rules |
| AI | LLM API with structured outputs |
| Storage | SQLite initially; PostgreSQL/Supabase if required |
| Testing | pytest, Vitest, Playwright |
| Deployment | Vercel and a Python-capable hosting service |

The exact stack and supported features may evolve during development.

## Getting Started

### Prerequisites

- Node.js and npm
- Python 3.11 or a compatible version supported by the project dependencies
- Git
- An LLM API key only if AI investigation is enabled

### Installation

Clone the repository:

```bash
git clone https://github.com/<your-username>/repopilot.git
cd repopilot
```

Install frontend dependencies:

```bash
cd apps/web
npm install
```

Start the frontend:

```bash
npm run dev
```

In a separate terminal, create and activate a Python virtual environment:

```bash
cd services/analyzer
python -m venv .venv
```

On macOS or Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Start the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

Open the frontend at `http://localhost:3000` and the API documentation at `http://localhost:8000/docs`.

**Note:** These commands describe the intended project setup. Adjust directory names, dependencies, environment variables, and scripts to match the actual implementation before publishing the README.

## Environment Variables

Create a local environment file using the project's example configuration.

```dotenv
# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000

# Backend
LLM_API_KEY=
LLM_MODEL=
```

Use the actual provider-specific variable names required by the implementation. Never commit real credentials or expose secret API keys through `NEXT_PUBLIC_*` variables.

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/analyze` | Start repository analysis |
| GET | `/api/analyses/{id}` | Retrieve analysis status |
| GET | `/api/analyses/{id}/graph` | Retrieve graph data |
| GET | `/api/analyses/{id}/findings` | Retrieve findings |
| POST | `/api/analyses/{id}/investigate` | Ask a repository question |
| GET | `/api/analyses/{id}/report` | Export an investigation report |

These endpoints represent the intended API design and should be updated to reflect the implemented routes.

## Example Use Cases

- Understand how an unfamiliar application processes requests.
- Explore function dependencies and call relationships.
- Investigate whether input-controlled values may reach sensitive operations.
- Review potentially unsafe code patterns.
- Produce a source-referenced investigation report.
- Accelerate initial code review and repository onboarding.

## Security and Limitations

RepoPilot is an investigation aid, not a replacement for a full security audit.

- Static analysis can miss dynamic behavior and unresolved function calls.
- Rule-based findings may include false positives.
- A call path does not by itself prove that data flows through every intermediate operation.
- AI-generated explanations must be verified against their source evidence.
- Analysis should not execute repository code.
- Repository ingestion must enforce URL validation, resource limits, and protections against server-side request forgery.
- Secrets and sensitive files should be excluded from indexing wherever possible.

Findings should be treated as leads for review rather than definitive proof of exploitability.

## Roadmap

- [ ] Repository ingestion and file filtering
- [ ] Function and import extraction
- [ ] Function-call graph generation
- [ ] Interactive graph visualization
- [ ] Rule-based suspicious-pattern detection
- [ ] Source-to-sink call-path exploration
- [ ] Evidence-grounded AI question answering
- [ ] Citation validation and source navigation
- [ ] Markdown and JSON report export
- [ ] Automated tests and CI
- [ ] Additional language support
- [ ] Optional persistent project history

## Contributing

Contributions, bug reports, and feature suggestions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make a focused change.
4. Add or update tests.
5. Open a pull request describing the change and its validation.


## Acknowledgments

RepoPilot is being developed as a hackathon project exploring static code analysis, software dependency visualization, and evidence-grounded AI assistance.

---

**RepoPilot — Understand the code. Trace the evidence. Investigate with confidence.**
