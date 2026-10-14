import { describe, it, expect, vi, beforeEach } from "vitest";
import { validateCitations } from "@/lib/investigation/citations";
import { completeJson, ProviderError } from "@/lib/investigation/provider";
import { runInvestigation } from "@/lib/investigation/service";
import * as configModule from "@/lib/config";
import * as providerModule from "@/lib/investigation/provider";
import type { EvidencePackage, ModelInvestigation } from "@/lib/investigation/types";
import type { AnalysisSummary, GraphResponse, FindingsResponse, SourceResponse } from "@/lib/types";
import type { createAnalyzerClient } from "@/lib/api/client";

describe("validateCitations", () => {
  const baseEvidence: EvidencePackage = {
    analysis_id: "0123456789abcdef0123456789abcdef",
    repository: {
      owner: "test-owner",
      name: "test-repo",
      url: "https://github.com/test-owner/test-repo",
      ref: "main",
      commit_sha: "abcdef123456",
    },
    warnings: [],
    graph_limitations: [],
    graph_truncated: false,
    findings_truncated: false,
    findings: [
      {
        id: "fd_0123456789abcdef",
        rule_id: "sql_injection",
        title: "SQL Injection",
        description: "Unsanitized user input",
        severity: "high",
        confidence: "high",
        location: { path: "src/db.ts", start_line: 10, end_line: 15 },
        function_id: "fn_0123456789abcdef",
        evidence: "db.query(input)",
        next_step: "Use parameterized queries",
        limitations: [],
        cwe_id: "CWE-89",
      },
    ],
    nodes: [
      {
        id: "fn_0123456789abcdef",
        name: "queryDb",
        qualified_name: "db.queryDb",
        kind: "function_declaration",
        path: "src/db.ts",
        start_line: 8,
        end_line: 25,
      },
    ],
    sources: [
      {
        path: "src/db.ts",
        start_line: 5,
        end_line: 30,
        total_lines: 100,
        truncated: false,
        redacted_values: 0,
        content: "function queryDb() { ... }",
      },
      {
        path: "src/truncated.ts",
        start_line: 1,
        end_line: 20, // Content was truncated at 4000 chars to line 20
        total_lines: 150,
        truncated: true,
        redacted_values: 0,
        content: "truncated source content up to line 20",
      },
      {
        path: "src/empty.ts",
        start_line: 1,
        end_line: 0,
        total_lines: 0,
        truncated: false,
        redacted_values: 0,
        content: "",
      },
    ],
  };

  it("accepts valid finding, node, and source citations", () => {
    const modelOutput: ModelInvestigation = {
      answer: "The code has a SQL injection vulnerability.",
      observed_facts: ["db.query takes input directly"],
      interpretations: ["Possible remote code execution"],
      unknowns: [],
      limitations: [],
      citations: [
        { type: "finding", id: "fd_0123456789abcdef" },
        { type: "node", id: "fn_0123456789abcdef" },
        { type: "source", path: "src/db.ts", start_line: 10, end_line: 15 },
      ],
    };

    const result = validateCitations(modelOutput, baseEvidence);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.citations).toHaveLength(3);
      expect(result.citations).toEqual(modelOutput.citations);
    }
  });

  it("rejects empty citations array", () => {
    const modelOutput: ModelInvestigation = {
      answer: "Grounded answer without citations.",
      observed_facts: [],
      interpretations: [],
      unknowns: [],
      limitations: [],
      citations: [],
    };

    const result = validateCitations(modelOutput, baseEvidence);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reasons[0]).toMatch(/at least one citation/i);
    }
  });

  it("rejects unknown finding ID and unknown node ID", () => {
    const modelOutput: ModelInvestigation = {
      answer: "Test",
      observed_facts: [],
      interpretations: [],
      unknowns: [],
      limitations: [],
      citations: [
        { type: "finding", id: "fd_unknown99999999" },
        { type: "node", id: "fn_unknown99999999" },
      ],
    };

    const result = validateCitations(modelOutput, baseEvidence);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reasons).toEqual([
        "Unknown finding id fd_unknown99999999",
        "Unknown node id fn_unknown99999999",
      ]);
    }
  });

  it("rejects source citations outside the truncated excerpt", () => {
    // src/truncated.ts has start_line: 1, end_line: 20
    const validExcerptCitation: ModelInvestigation = {
      answer: "Valid citation within truncated excerpt",
      observed_facts: [],
      interpretations: [],
      unknowns: [],
      limitations: [],
      citations: [{ type: "source", path: "src/truncated.ts", start_line: 5, end_line: 15 }],
    };

    const validResult = validateCitations(validExcerptCitation, baseEvidence);
    expect(validResult.ok).toBe(true);

    const outsideExcerptCitation: ModelInvestigation = {
      answer: "Citation outside truncated excerpt",
      observed_facts: [],
      interpretations: [],
      unknowns: [],
      limitations: [],
      citations: [{ type: "source", path: "src/truncated.ts", start_line: 25, end_line: 35 }],
    };

    const invalidResult = validateCitations(outsideExcerptCitation, baseEvidence);
    expect(invalidResult.ok).toBe(false);
    if (!invalidResult.ok) {
      expect(invalidResult.reasons[0]).toContain("is not in the retrieved evidence");
    }
  });

  it("rejects invalid line ranges and citations on empty files", () => {
    const invalidRanges: ModelInvestigation = {
      answer: "Invalid line ranges",
      observed_facts: [],
      interpretations: [],
      unknowns: [],
      limitations: [],
      citations: [
        { type: "source", path: "src/db.ts", start_line: 20, end_line: 10 }, // inverted range
        { type: "source", path: "src/empty.ts", start_line: 1, end_line: 1 }, // empty file
      ],
    };

    const result = validateCitations(invalidRanges, baseEvidence);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reasons[0]).toContain("Invalid line range 20-10");
      expect(result.reasons[1]).toContain("is not in the retrieved evidence");
    }
  });
});

describe("AI provider completeJson and error handling", () => {
  const config = {
    apiKey: "sk-test-secret-key-12345",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("handles 401/403 authentication error without leaking API key", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ error: { message: "Invalid API key" } }),
    } as unknown as Response);

    await expect(completeJson(config, [{ role: "user", content: "hello" }])).rejects.toThrow(
      new ProviderError("provider_auth", "The AI provider rejected the configured credentials."),
    );
  });

  it("handles 429 rate limit error", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      statusText: "Too Many Requests",
    } as unknown as Response);

    await expect(completeJson(config, [{ role: "user", content: "hello" }])).rejects.toThrow(
      new ProviderError("provider_rate_limited", "The AI provider rate-limited the request."),
    );
  });

  it("handles provider timeout and network failure", async () => {
    const timeoutErr = new DOMException("The operation timed out.", "TimeoutError");
    global.fetch = vi.fn().mockRejectedValue(timeoutErr);

    await expect(completeJson(config, [{ role: "user", content: "hello" }])).rejects.toThrow(
      new ProviderError("provider_timeout", "The AI provider timed out."),
    );

    global.fetch = vi.fn().mockRejectedValue(new Error("Connection refused"));
    await expect(completeJson(config, [{ role: "user", content: "hello" }])).rejects.toThrow(
      new ProviderError("provider_unavailable", "The AI provider could not be reached."),
    );
  });

  it("handles malformed model output (empty or invalid JSON)", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        choices: [{ message: { content: "This is not JSON at all!" } }],
      }),
    } as unknown as Response);

    await expect(completeJson(config, [{ role: "user", content: "hello" }])).rejects.toThrow(
      new ProviderError("malformed_model_output", "The model did not return valid JSON."),
    );
  });

  it("handles schema validation failure when required fields are missing", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        choices: [{ message: { content: JSON.stringify({ wrong_key: "value" }) } }],
      }),
    } as unknown as Response);

    await expect(completeJson(config, [{ role: "user", content: "hello" }])).rejects.toThrow(
      new ProviderError(
        "schema_validation_failed",
        "The model JSON did not match the investigation schema.",
      ),
    );
  });
});

describe("runInvestigation workflow and bounded correction", () => {
  const analysisId = "0123456789abcdef0123456789abcdef";

  const mockSummary: AnalysisSummary = {
    analysis_id: analysisId,
    status: "completed",
    repository: {
      url: "https://github.com/test-owner/test-repo",
      host: "github.com",
      owner: "test-owner",
      name: "test-repo",
    },
    created_at: "2026-10-12T00:00:00Z",
    diagnostics: {
      parse_errors: [],
      skipped_files: [],
      skipped_by_reason: {},
      limits_reached: [],
      warnings: [],
      truncated: false,
    },
  };

  const mockGraph: GraphResponse = {
    analysis_id: analysisId,
    nodes: [
      {
        id: "fn_0123456789abcdef",
        name: "testFn",
        qualified_name: "mod.testFn",
        kind: "function_declaration",
        language: "typescript",
        path: "src/test.ts",
        start_line: 1,
        end_line: 20,
        start_column: 1,
        is_anonymous: false,
        is_exported: true,
      },
    ],
    edges: [],
    unresolved_calls: [],
    unresolved_calls_total: 0,
    truncated: false,
    limitations: [],
  };

  const mockFindings: FindingsResponse = {
    analysis_id: analysisId,
    findings: [],
    total: 0,
    truncated: false,
  };

  const mockSource: SourceResponse = {
    analysis_id: analysisId,
    path: "src/test.ts",
    language: "typescript",
    start_line: 1,
    end_line: 20,
    total_lines: 20,
    content: "function testFn() {}",
    truncated: false,
    redacted_values: 0,
  };

  const mockAnalyzer = {
    getAnalysis: vi.fn().mockResolvedValue(mockSummary),
    getGraph: vi.fn().mockResolvedValue(mockGraph),
    getFindings: vi.fn().mockResolvedValue(mockFindings),
    getSource: vi.fn().mockResolvedValue(mockSource),
  } as unknown as ReturnType<typeof createAnalyzerClient>;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fails early if AI provider is not configured", async () => {
    vi.spyOn(configModule, "getAiProviderConfig").mockReturnValue(null);

    const result = await runInvestigation(mockAnalyzer, {
      analysisId,
      question: "Where is testFn defined and what does it do?",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("ai_not_configured");
    }
  });

  it("handles bounded correction attempt when model corrects citation", async () => {
    vi.spyOn(configModule, "getAiProviderConfig").mockReturnValue({
      apiKey: "test-key",
      baseUrl: "https://api.openai.com/v1",
      model: "gpt-4o-mini",
    });

    // 1st attempt: invalid citation (unknown node ID)
    const invalidOutput: ModelInvestigation = {
      answer: "Initial answer with invalid citation",
      observed_facts: [],
      interpretations: [],
      unknowns: [],
      limitations: [],
      citations: [{ type: "node", id: "fn_unknown_id_123" }],
    };

    // 2nd attempt: corrected citation
    const validOutput: ModelInvestigation = {
      answer: "Corrected answer",
      observed_facts: ["Observed testFn"],
      interpretations: [],
      unknowns: [],
      limitations: [],
      citations: [{ type: "node", id: "fn_0123456789abcdef" }],
    };

    const completeSpy = vi
      .spyOn(providerModule, "completeJson")
      .mockResolvedValueOnce(invalidOutput)
      .mockResolvedValueOnce(validOutput);

    const result = await runInvestigation(mockAnalyzer, {
      analysisId,
      question: "Where is testFn defined?",
    });

    expect(completeSpy).toHaveBeenCalledTimes(2);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.result.citations).toEqual([{ type: "node", id: "fn_0123456789abcdef" }]);
    }
  });

  it("fails explicitly when second correction attempt still has invalid citations", async () => {
    vi.spyOn(configModule, "getAiProviderConfig").mockReturnValue({
      apiKey: "test-key",
      baseUrl: "https://api.openai.com/v1",
      model: "gpt-4o-mini",
    });

    const invalidOutput: ModelInvestigation = {
      answer: "Still invalid",
      observed_facts: [],
      interpretations: [],
      unknowns: [],
      limitations: [],
      citations: [{ type: "node", id: "fn_unknown_id_123" }],
    };

    vi.spyOn(providerModule, "completeJson")
      .mockResolvedValueOnce(invalidOutput)
      .mockResolvedValueOnce(invalidOutput);

    const result = await runInvestigation(mockAnalyzer, {
      analysisId,
      question: "Where is testFn defined?",
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("citation_validation_failed");
    }
  });
});
