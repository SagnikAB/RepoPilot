import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import HomePage from "@/app/page";
import { browserAnalyzer } from "@/lib/api/client";
import type {
  AnalysisSummary,
  GraphResponse,
  FindingsResponse,
  SourceResponse,
  PathsResponse,
} from "@/lib/types";

// Mock browserAnalyzer client
vi.mock("@/lib/api/client", () => {
  return {
    browserAnalyzer: {
      health: vi.fn(),
      analyze: vi.fn(),
      getAnalysis: vi.fn(),
      getGraph: vi.fn(),
      getFindings: vi.fn(),
      getSource: vi.fn(),
      getPaths: vi.fn(),
    },
  };
});

describe("RepoPilot Investigation Workspace", () => {
  const mockAnalysisId = "4f2c9e1a7b3d4c5e8f9a0b1c2d3e4f5a";

  const mockSummaryCompleted: AnalysisSummary = {
    analysis_id: mockAnalysisId,
    status: "completed",
    repository: {
      url: "https://github.com/expressjs/express",
      host: "github.com",
      owner: "expressjs",
      name: "express",
      ref: "main",
      commit_sha: "abcdef1234567890",
    },
    created_at: "2026-10-12T00:00:00Z",
    completed_at: "2026-10-12T00:01:00Z",
    duration_ms: 60000,
    stats: {
      files_discovered: 50,
      files_analyzed: 45,
      files_skipped: 5,
      functions: 120,
      call_edges: 85,
      unresolved_calls: 15,
      findings: 3,
      findings_by_severity: { high: 1, medium: 2 },
      files_by_language: { typescript: 45 },
    },
    diagnostics: {
      parse_errors: [],
      skipped_files: [],
      skipped_by_reason: {},
      limits_reached: [],
      warnings: ["Test warning about dynamic imports"],
      truncated: false,
    },
  };

  const mockGraph: GraphResponse = {
    analysis_id: mockAnalysisId,
    nodes: [
      {
        id: "fn_0000000000000001",
        name: "handleRequest",
        qualified_name: "server.handleRequest",
        kind: "function_declaration",
        language: "typescript",
        path: "src/server.ts",
        start_line: 10,
        end_line: 40,
        start_column: 1,
        is_anonymous: false,
        is_exported: true,
      },
      {
        id: "fn_0000000000000002",
        name: "authenticate",
        qualified_name: "auth.authenticate",
        kind: "function_declaration",
        language: "typescript",
        path: "src/auth.ts",
        start_line: 5,
        end_line: 25,
        start_column: 1,
        is_anonymous: false,
        is_exported: true,
      },
    ],
    edges: [
      {
        id: "ce_0000000000000001",
        source: "fn_0000000000000001",
        target: "fn_0000000000000002",
        resolution: "import",
        call_sites: [{ line: 15, column: 5 }],
      },
    ],
    unresolved_calls: [
      {
        caller_id: "fn_0000000000000001",
        path: "src/server.ts",
        callee: "process.env.PORT",
        call_site: { line: 12, column: 10 },
        reason: "dynamic_property",
      },
    ],
    unresolved_calls_total: 1,
    truncated: false,
    limitations: ["No eval analysis"],
  };

  const mockFindings: FindingsResponse = {
    analysis_id: mockAnalysisId,
    findings: [
      {
        id: "fd_0000000000000001",
        rule_id: "sec_hardcoded_secret",
        title: "Potential Hardcoded Secret",
        description: "Found token literal in configuration",
        severity: "high",
        confidence: "high",
        location: { path: "src/auth.ts", start_line: 10, end_line: 12 },
        function_id: "fn_0000000000000002",
        evidence: "const SECRET = 'xyz123';",
        review_status: "needs_review",
        next_step: "Rotate key and use environment variable",
        limitations: [],
        cwe_id: "CWE-798",
      },
    ],
    total: 1,
    truncated: false,
  };

  const mockSourceResponse: SourceResponse = {
    analysis_id: mockAnalysisId,
    path: "src/auth.ts",
    language: "typescript",
    start_line: 1,
    end_line: 20,
    total_lines: 50,
    content: "function authenticate() {\n  const SECRET = 'xyz123';\n  return true;\n}",
    truncated: false,
    redacted_values: 0,
  };

  const mockPathsResponse: PathsResponse = {
    analysis_id: mockAnalysisId,
    source: "fn_0000000000000001",
    target: "fn_0000000000000002",
    max_depth: 8,
    max_paths: 10,
    paths: [
      {
        node_ids: ["fn_0000000000000001", "fn_0000000000000002"],
        edge_ids: ["ce_0000000000000001"],
      },
    ],
    truncated: false,
    limitations: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/");
    vi.mocked(browserAnalyzer.health).mockResolvedValue({
      status: "ok",
      service: "analyzer",
      version: "0.1.0",
    });
    vi.mocked(browserAnalyzer.getAnalysis).mockResolvedValue(mockSummaryCompleted);
    vi.mocked(browserAnalyzer.getGraph).mockResolvedValue(mockGraph);
    vi.mocked(browserAnalyzer.getFindings).mockResolvedValue(mockFindings);
  });

  it("renders the provider-wrapped workspace entry point with empty state", async () => {
    render(<HomePage />);

    expect(screen.getByText("RepoPilot")).toBeInTheDocument();
    expect(screen.getByText("Codebase investigation workspace")).toBeInTheDocument();
    expect(screen.getByText(/Submit a public GitHub repository to start an analysis/i)).toBeInTheDocument();

    // Verify all tabs are present
    expect(screen.getByRole("tab", { name: /Call Graph/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Findings/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Unresolved Calls/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Call Paths/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /AI Investigator/i })).toBeInTheDocument();

    // Verify Source Viewer empty state
    expect(screen.getByText(/Select a finding, graph node, call site, or path step/i)).toBeInTheDocument();
  });

  it("handles repository submission and renders failed analysis error banner", async () => {
    vi.mocked(browserAnalyzer.analyze).mockResolvedValue({
      analysis_id: "failed12345678901234567890123456",
      status: "failed",
      repository: {
        url: "https://github.com/bad/repo",
        host: "github.com",
        owner: "bad",
        name: "repo",
      },
      created_at: "2026-10-12T00:00:00Z",
      error: {
        code: "clone_timeout",
        message: "Repository cloning exceeded the timeout limit.",
      },
      diagnostics: {
        parse_errors: [],
        skipped_files: [],
        skipped_by_reason: {},
        limits_reached: [],
        warnings: [],
        truncated: false,
      },
    });

    render(<HomePage />);

    const input = screen.getByPlaceholderText("https://github.com/owner/repo");
    fireEvent.change(input, { target: { value: "https://github.com/bad/repo" } });

    const submitBtn = screen.getByRole("button", { name: "Analyze" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText("clone_timeout:")).toBeInTheDocument();
      expect(screen.getByText("Repository cloning exceeded the timeout limit.")).toBeInTheDocument();
    });
  });

  it("handles successful analysis and renders graph, findings, and diagnostics", async () => {
    vi.mocked(browserAnalyzer.analyze).mockResolvedValue(mockSummaryCompleted);
    vi.mocked(browserAnalyzer.getGraph).mockResolvedValue(mockGraph);
    vi.mocked(browserAnalyzer.getFindings).mockResolvedValue(mockFindings);

    render(<HomePage />);

    const input = screen.getByPlaceholderText("https://github.com/owner/repo");
    fireEvent.change(input, { target: { value: "https://github.com/expressjs/express" } });

    const submitBtn = screen.getByRole("button", { name: "Analyze" });
    fireEvent.click(submitBtn);

    // Summary header should appear
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "expressjs/express" })).toBeInTheDocument();
      expect(screen.getByText("Test warning about dynamic imports")).toBeInTheDocument();
    });

    // CallGraph rendered
    expect(screen.getByText(/2 nodes · 1 edges/i)).toBeInTheDocument();
    expect(screen.getByText("No eval analysis")).toBeInTheDocument();

    // Switch to Findings tab
    const findingsTab = screen.getByRole("tab", { name: /Findings/i });
    fireEvent.click(findingsTab);

    // Findings explorer should display finding
    expect(screen.getByText("Potential Hardcoded Secret")).toBeInTheDocument();
    expect(screen.getAllByText("sec_hardcoded_secret").length).toBeGreaterThan(0);
  });

  it("handles source navigation and highlighting when finding is selected", async () => {
    vi.mocked(browserAnalyzer.analyze).mockResolvedValue(mockSummaryCompleted);
    vi.mocked(browserAnalyzer.getGraph).mockResolvedValue(mockGraph);
    vi.mocked(browserAnalyzer.getFindings).mockResolvedValue(mockFindings);
    vi.mocked(browserAnalyzer.getSource).mockResolvedValue(mockSourceResponse);

    render(<HomePage />);

    const input = screen.getByPlaceholderText("https://github.com/owner/repo");
    fireEvent.change(input, { target: { value: "https://github.com/expressjs/express" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "expressjs/express" })).toBeInTheDocument();
    });

    // Switch to findings tab
    fireEvent.click(screen.getByRole("tab", { name: /Findings/i }));

    // Click on finding to open source
    const findingBtn = screen.getByText("Potential Hardcoded Secret");
    fireEvent.click(findingBtn);

    await waitFor(() => {
      expect(browserAnalyzer.getSource).toHaveBeenCalledWith(
        mockAnalysisId,
        expect.objectContaining({ path: "src/auth.ts" }),
      );
      expect(screen.getByText(/lines 1–20 of 50/i)).toBeInTheDocument();
    });
  });

  it("handles unresolved calls exploration", async () => {
    vi.mocked(browserAnalyzer.analyze).mockResolvedValue(mockSummaryCompleted);
    vi.mocked(browserAnalyzer.getGraph).mockResolvedValue(mockGraph);
    vi.mocked(browserAnalyzer.getFindings).mockResolvedValue(mockFindings);
    vi.mocked(browserAnalyzer.getSource).mockResolvedValue(mockSourceResponse);

    render(<HomePage />);

    const input = screen.getByPlaceholderText("https://github.com/owner/repo");
    fireEvent.change(input, { target: { value: "https://github.com/expressjs/express" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "expressjs/express" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("tab", { name: /Unresolved Calls/i }));

    expect(screen.getByText("process.env.PORT")).toBeInTheDocument();
    expect(screen.getAllByText(/dynamic_property/i).length).toBeGreaterThan(0);

    // Click unresolved call to inspect call site
    fireEvent.click(screen.getByText("process.env.PORT"));
    await waitFor(() => {
      expect(browserAnalyzer.getSource).toHaveBeenCalled();
    });
  });

  it("handles call paths exploration", async () => {
    vi.mocked(browserAnalyzer.analyze).mockResolvedValue(mockSummaryCompleted);
    vi.mocked(browserAnalyzer.getGraph).mockResolvedValue(mockGraph);
    vi.mocked(browserAnalyzer.getFindings).mockResolvedValue(mockFindings);
    vi.mocked(browserAnalyzer.getPaths).mockResolvedValue(mockPathsResponse);

    render(<HomePage />);

    const input = screen.getByPlaceholderText("https://github.com/owner/repo");
    fireEvent.change(input, { target: { value: "https://github.com/expressjs/express" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "expressjs/express" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("tab", { name: /Call Paths/i }));

    const sourceSelect = screen.getByLabelText("Source function");
    const targetSelect = screen.getByLabelText("Target function");

    fireEvent.change(sourceSelect, { target: { value: "fn_0000000000000001" } });
    fireEvent.change(targetSelect, { target: { value: "fn_0000000000000002" } });

    fireEvent.click(screen.getByRole("button", { name: "Find paths" }));

    await waitFor(() => {
      expect(screen.getByText(/Path 1 \(2 nodes\)/i)).toBeInTheDocument();
    });
  });

  it("handles AI investigator failure and success states", async () => {
    vi.mocked(browserAnalyzer.analyze).mockResolvedValue(mockSummaryCompleted);
    vi.mocked(browserAnalyzer.getGraph).mockResolvedValue(mockGraph);
    vi.mocked(browserAnalyzer.getFindings).mockResolvedValue(mockFindings);
    vi.mocked(browserAnalyzer.getSource).mockResolvedValue(mockSourceResponse);

    render(<HomePage />);

    const input = screen.getByPlaceholderText("https://github.com/owner/repo");
    fireEvent.change(input, { target: { value: "https://github.com/expressjs/express" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "expressjs/express" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("tab", { name: /AI Investigator/i }));

    // Mock fetch for /api/investigate failing with ai_not_configured
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({
        ok: false,
        error: {
          code: "ai_not_configured",
          message: "AI provider not configured.",
        },
      }),
    } as unknown as Response);

    const questionInput = screen.getByPlaceholderText(/Where is user input processed/i);
    fireEvent.change(questionInput, {
      target: { value: "Where is authentication handled in this repository?" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Investigate" }));

    await waitFor(() => {
      expect(screen.getByText("ai_not_configured")).toBeInTheDocument();
      expect(screen.getByText("AI provider not configured.")).toBeInTheDocument();
    });

    // Mock fetch for /api/investigate succeeding with validated citations
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        analysis_id: mockAnalysisId,
        model: "gpt-4o-mini",
        result: {
          answer: "Authentication is implemented in src/auth.ts authenticate function.",
          observed_facts: ["authenticate function is defined in src/auth.ts"],
          interpretations: ["Hardcoded secret is present"],
          unknowns: [],
          limitations: [],
          citations: [
            { type: "node", id: "fn_0000000000000002" },
            { type: "finding", id: "fd_0000000000000001" },
            { type: "source", path: "src/auth.ts", start_line: 10, end_line: 12 },
          ],
        },
        evidence_counts: { findings: 1, nodes: 1, sources: 1 },
      }),
    } as unknown as Response);

    fireEvent.click(screen.getByRole("button", { name: "Investigate" }));

    await waitFor(() => {
      expect(screen.getByText(/Authentication is implemented in src\/auth.ts/i)).toBeInTheDocument();
      expect(screen.getByText("node:fn_0000000000000002")).toBeInTheDocument();
      expect(screen.getByText("finding:fd_0000000000000001")).toBeInTheDocument();
      expect(screen.getByText("src/auth.ts:10-12")).toBeInTheDocument();
    });

    // Clicking a citation navigates to that citation
    fireEvent.click(screen.getByText("finding:fd_0000000000000001"));
    await waitFor(() => {
      expect(browserAnalyzer.getSource).toHaveBeenCalled();
    });
  });

  it("supports responsive and mobile-friendly tab navigation", async () => {
    render(<HomePage />);

    const tabs = ["Call Graph", "Findings", "Unresolved Calls", "Call Paths", "AI Investigator"];

    for (const tabName of tabs) {
      const tab = screen.getByRole("tab", { name: new RegExp(tabName, "i") });
      fireEvent.click(tab);
      expect(tab).toHaveAttribute("aria-selected", "true");
    }
  });
});
