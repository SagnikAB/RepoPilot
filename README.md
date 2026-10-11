# RepoPilot

### AI-Powered Codebase Investigation & Code Intelligence

**Understand the code. Trace the evidence. Investigate with confidence.**

RepoPilot is an AI-powered codebase investigation tool designed to help developers understand unfamiliar repositories, explore function dependencies, trace code paths, and investigate potentially unsafe code with evidence-backed explanations.

By combining static code analysis, interactive dependency graphs, rule-based detection, and AI-assisted investigation, RepoPilot aims to make complex codebases easier to navigate and reason about.

> **Project status:** Early development · Hackathon MVP

---

## The Problem

Understanding an unfamiliar codebase can be time-consuming.

Developers often need to manually navigate files, trace function calls, understand execution paths, and investigate suspicious behavior before they can confidently modify or review a project.

Traditional code search helps locate individual symbols, while AI-generated summaries may not provide enough structural context or verifiable evidence to support an investigation.

## The Solution

RepoPilot aims to bring these workflows into one investigation workspace.

Instead of simply summarizing source code, RepoPilot combines structural analysis with evidence-grounded AI assistance to help developers explore how a codebase works and investigate specific questions.

The goal is simple: **turn an unfamiliar repository into an understandable, navigable, and evidence-backed system.**

---

## Core Features

The following features define the project's intended MVP and development roadmap.

### 1. Repository Intelligence

Analyze a supported source-code repository to identify files, functions, imports, and relationships between components.

- Repository ingestion and source-file indexing
- Function and method extraction
- Import and dependency analysis
- Source locations with file paths and line numbers

### 2. Interactive Code Dependency Graph

Visualize relationships between functions and explore how different parts of a codebase connect.

- Navigate function-call relationships
- Explore callers and callees
- Inspect source locations from graph nodes
- Highlight selected paths through the codebase

### 3. Code Path Investigation

Trace statically resolvable call paths between selected functions to help investigate how execution may move through an application.

- Explore paths between relevant functions
- Identify potential paths from input-handling code to sensitive operations
- Highlight unresolved or ambiguous relationships
- Inspect the source code behind each step

A discovered call path is an investigation lead, not automatic proof of a vulnerability or complete runtime data flow.

### 4. AI-Assisted Investigation

Ask natural-language questions about an analyzed repository.

Example questions:

- Where is user input processed?
- Which functions call this method?
- How does this request reach the database layer?
- Can request-controlled data reach a shell execution function?
- What additional evidence is needed to confirm this finding?

RepoPilot is designed to ground its answers in retrieved source code and analysis results rather than relying on generated explanations alone.

### 5. Rule-Based Code Analysis

Identify selected suspicious coding patterns using explicit, testable rules.

Potential checks include:

- Unsafe command execution patterns
- Potentially unsafe SQL query construction
- Dynamic code execution
- Hardcoded credential-like values
- Disabled or weakened security checks

Findings should include the applicable rule, source location, evidence, and limitations. Rule matches require contextual review and may produce false positives.

### 6. Evidence-Backed Findings

Make investigation results easier to verify.

- File paths and source-line references
- Relevant code snippets
- Explanation of why a pattern was flagged
- Investigation paths and unresolved relationships
- Clear distinction between observed evidence and AI-generated interpretation

### 7. Investigation Reports

Generate structured investigation reports containing findings, source references, possible risks, and recommended next steps.

Planned export formats include Markdown and JSON.

---

## How It Works

```text
             Source Repository
                     |
                     v
             Repository Ingestion
                     |
                     v
              Source Analysis
                     |
           +---------+---------+
           |                   |
           v                   v
      AST Parsing         Rule Engine
           |                   |
           v                   v
      Function Nodes       Findings
           |
           v
       Call Graph
           |
           +-------------------+
                               |
                               v
                       Evidence Retrieval
                               |
                               v
                       AI Investigation
                               |
                               v
                   Evidence-Backed Results
                               |
                               v
                    Interactive Workspace
```

The analysis engine is responsible for extracting code structure and identifying rule matches. The AI layer uses relevant analysis results and source evidence to explain findings and answer investigation questions.

This separation is intended to make RepoPilot's results easier to validate, test, and improve.

---

## Technology Stack

| Layer | Planned Technology |
|---|---|
| Frontend | Next.js, React, TypeScript |
| UI and styling | Tailwind CSS, shadcn/ui |
| Graph visualization | React Flow |
| Backend API | Python, FastAPI |
| Source-code parsing | Tree-sitter and/or TypeScript Compiler API |
| Analysis | Custom static-analysis rules and graph algorithms |
| AI investigation | LLM API with structured responses |
| Data validation | Pydantic and TypeScript types |
| Storage | SQLite initially, with PostgreSQL/Supabase as an option |
| Testing | pytest, Vitest, Playwright |
| Deployment | Vercel and a Python-compatible backend host |

The final stack may evolve as implementation and testing progress.

---

## Architecture Principles

### Static analysis first

Use deterministic analysis for source locations, known function relationships, and rule matches wherever possible.

### Evidence before explanation

AI-generated answers should reference retrieved repository evidence. Unsupported claims should be identified as uncertain rather than presented as facts.

### Explainable results

Users should be able to inspect the source code behind a finding and understand why the analysis produced it.

### Modular design

Keep repository ingestion, language parsing, graph generation, detection rules, evidence retrieval, and AI orchestration as separate components.

### Safe by default

Treat analyzed repositories as untrusted input. Static analysis should not execute the repository's code or install its dependencies.

---

## Intended Use Cases

- Understanding an unfamiliar open-source project
- Onboarding to a large or legacy codebase
- Exploring function dependencies and execution paths
- Investigating potentially unsafe code
- Supporting initial code-review workflows
- Producing source-referenced technical investigation reports
- Accelerating software architecture exploration

RepoPilot is intended to complement developers, code-review tools, and security-analysis workflows—not replace them.

---

## Project Structure

The planned repository structure is organized around independent application and analysis components.

```text
repopilot/
├── apps/
│   └── web/
│       ├── app/
│       ├── components/
│       │   ├── graph/
│       │   ├── findings/
│       │   └── investigator/
│       └── lib/
├── services/
│   └── analyzer/
│       ├── app/
│       │   ├── api/
│       │   ├── ingestion/
│       │   ├── parsers/
│       │   ├── graph/
│       │   ├── rules/
│       │   ├── retrieval/
│       │   └── investigator/
│       └── tests/
├── fixtures/
│   └── demo-repository/
├── docs/
├── .env.example
├── .gitignore
└── README.md
```

This structure is a design target and will be updated as the codebase takes shape.

---

## Development Roadmap

### Phase 1 — Repository Foundation
- [ ] Establish the frontend and backend applications
- [ ] Define shared data contracts
- [ ] Add repository ingestion and file filtering
- [ ] Create a repeatable demonstration fixture

### Phase 2 — Static Analysis
- [ ] Extract functions and imports
- [ ] Build function-call relationships
- [ ] Record source locations
- [ ] Implement graph serialization
- [ ] Add analysis tests

### Phase 3 — Investigation Engine
- [ ] Implement selected detection rules
- [ ] Add graph-based call-path exploration
- [ ] Retrieve relevant source snippets
- [ ] Structure findings and evidence references

### Phase 4 — Interactive Interface
- [ ] Build the repository workspace
- [ ] Visualize the dependency graph
- [ ] Add source navigation and findings panels
- [ ] Connect the frontend to the analysis API

### Phase 5 — AI Integration
- [ ] Add evidence-grounded question answering
- [ ] Validate source citations
- [ ] Handle insufficient evidence and model failures
- [ ] Add Markdown and JSON exports

### Phase 6 — Reliability and Expansion
- [ ] Add end-to-end testing
- [ ] Harden repository ingestion
- [ ] Add resource limits and error handling
- [ ] Evaluate detection precision and analysis accuracy
- [ ] Explore support for additional programming languages

---

## Security Considerations

RepoPilot is intended to inspect source code without executing it.

Repository ingestion and analysis must be designed to address risks such as:

- Server-side request forgery when retrieving remote repositories
- Oversized repositories and resource exhaustion
- Malicious filenames, archives, and unexpected file types
- Accidental indexing of credentials or private keys
- Prompt injection embedded in comments, documentation, or source files
- Exposure of API keys or sensitive analysis data

Repository retrieval should use URL validation, bounded resource usage, and safe Git operations. Analysis results and AI-generated explanations should be treated as untrusted until verified.

---

## Limitations

RepoPilot is an investigation aid, not a complete program verifier or a replacement for professional security review.

- Dynamic dispatch and reflection can prevent reliable call resolution.
- Static call paths do not automatically establish runtime data flow.
- Pattern-based findings can produce false positives and false negatives.
- AI-generated explanations may be incomplete even when source references are valid.
- Findings require contextual review before they can be treated as confirmed vulnerabilities.
- Language and framework support will depend on the implemented parsers and analysis rules.

The project will prioritize transparent evidence and clearly communicated uncertainty over unsupported claims of complete accuracy.

---

## Contributing

Contributions, issues, and technical suggestions are welcome as the project develops.

1. Fork the repository.
2. Create a focused feature branch.
3. Make your change.
4. Add or update tests where appropriate.
5. Submit a pull request describing the change and its validation.

Development guidelines and contribution requirements will be expanded as the project matures.

---

## License

A license has not yet been selected.

An appropriate open-source license will be added before the project is distributed under explicit open-source terms. Until then, do not assume unrestricted permission to reuse, modify, or redistribute the code.

---

## Vision

RepoPilot aims to make codebase investigation more transparent, explainable, and accessible by combining structural code intelligence with AI-assisted reasoning.

**Understand the code. Trace the evidence. Investigate with confidence.**
