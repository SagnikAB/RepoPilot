import { AnalyzerApiError } from "../errors";
import type { createAnalyzerClient } from "../api/client";
import { sourceWindowForLocation, sourceWindowForNode, splitSourceLines } from "../source";
import { getAiProviderConfig } from "../config";
import { validateCitations } from "./citations";
import { completeJson, ProviderError, type ChatMessage } from "./provider";
import { SYSTEM_INSTRUCTIONS, buildCorrectionPrompt, buildUserPrompt } from "./prompt";
import { clampQuestion, emptyPackage, selectEvidence } from "./retrieval";
import type { EvidencePackage, InvestigationResult } from "./types";

type Analyzer = ReturnType<typeof createAnalyzerClient>;

const MAX_SOURCE_CHARS = 4000;
const MAX_SOURCES = 6;

export async function runInvestigation(
  analyzer: Analyzer,
  input: { analysisId: string; question: string },
): Promise<InvestigationResult> {
  const provider = getAiProviderConfig();
  if (!provider) {
    return {
      ok: false,
      error: {
        code: "ai_not_configured",
        message:
          "AI provider not configured. Set OPENAI_API_KEY (and optionally OPENAI_BASE_URL and OPENAI_MODEL) in apps/web/.env.local.",
      },
    };
  }

  const question = clampQuestion(input.question);
  if (question.length < 8) {
    return {
      ok: false,
      error: { code: "invalid_request", message: "Ask a more specific investigation question." },
    };
  }

  try {
    const summary = await analyzer.getAnalysis(input.analysisId);
    if (summary.status !== "completed") {
      return {
        ok: false,
        error: {
          code: "analysis_not_completed",
          message: "Investigation requires a completed analysis. Failed analyses have no graph or findings.",
        },
      };
    }

    const [graph, findingsResponse] = await Promise.all([
      analyzer.getGraph(input.analysisId, { max_nodes: 2000, max_unresolved: 200 }),
      analyzer.getFindings(input.analysisId, { limit: 200 }),
    ]);

    const selected = selectEvidence(question, summary, graph, findingsResponse.findings);
    const evidence = emptyPackage(summary, graph, findingsResponse.truncated);
    evidence.findings = selected.findings;
    evidence.nodes = selected.nodes;

    const sourceKeys = new Map<string, { path: string; start_line: number; end_line: number }>();
    for (const finding of selected.findings) {
      const window = sourceWindowForLocation(finding.location);
      sourceKeys.set(`${window.path}:${window.start_line}:${window.end_line ?? ""}`, {
        path: window.path,
        start_line: window.start_line ?? 1,
        end_line: window.end_line ?? finding.location.end_line,
      });
    }
    for (const node of selected.nodes.slice(0, 4)) {
      const window = sourceWindowForNode(node);
      sourceKeys.set(`${window.path}:${window.start_line}:${window.end_line ?? ""}`, {
        path: window.path,
        start_line: window.start_line ?? node.start_line,
        end_line: window.end_line ?? node.end_line,
      });
    }

    for (const query of Array.from(sourceKeys.values()).slice(0, MAX_SOURCES)) {
      try {
        const source = await analyzer.getSource(input.analysisId, query);
        const isCharTruncated = source.content.length > MAX_SOURCE_CHARS;
        const content = isCharTruncated ? source.content.slice(0, MAX_SOURCE_CHARS) : source.content;
        let endLine = source.end_line;
        if (isCharTruncated) {
          const lines = splitSourceLines(content);
          endLine = lines.length > 0 ? source.start_line + lines.length - 1 : 0;
        }
        evidence.sources.push({
          path: source.path,
          start_line: source.start_line,
          end_line: endLine,
          total_lines: source.total_lines,
          truncated: source.truncated || isCharTruncated,
          redacted_values: source.redacted_values,
          content,
        });
      } catch {
        evidence.warnings.push(`Source was unavailable for ${query.path}.`);
      }
    }

    if (evidence.findings.length === 0 && evidence.nodes.length === 0) {
      return {
        ok: false,
        error: {
          code: "insufficient_evidence",
          message:
            "Not enough retrieved graph or finding evidence to ground an answer. Try a more specific question about a function, file, or finding.",
        },
      };
    }

    const messages: ChatMessage[] = [
      { role: "system", content: SYSTEM_INSTRUCTIONS },
      { role: "user", content: buildUserPrompt(question, evidence) },
    ];

    let modelResult = await completeJson(provider, messages);
    let validation = validateCitations(modelResult, evidence);
    if (!validation.ok) {
      messages.push({ role: "assistant", content: JSON.stringify(modelResult) });
      messages.push({ role: "user", content: buildCorrectionPrompt(validation.reasons) });
      modelResult = await completeJson(provider, messages);
      validation = validateCitations(modelResult, evidence);
    }
    if (!validation.ok) {
      return {
        ok: false,
        error: {
          code: "citation_validation_failed",
          message: `Investigation citations could not be verified: ${validation.reasons.join("; ")}`,
        },
      };
    }

    return {
      ok: true,
      analysis_id: summary.analysis_id,
      model: provider.model,
      result: { ...modelResult, citations: validation.citations },
      evidence_counts: {
        findings: evidence.findings.length,
        nodes: evidence.nodes.length,
        sources: evidence.sources.length,
      },
    };
  } catch (error) {
    return failureFromUnknown(error);
  }
}

function failureFromUnknown(error: unknown): InvestigationResult {
  if (error instanceof ProviderError) {
    return { ok: false, error: { code: error.code, message: error.message } };
  }
  if (error instanceof AnalyzerApiError) {
    return { ok: false, error: { code: error.code, message: error.message } };
  }
  return {
    ok: false,
    error: { code: "investigation_failed", message: "Investigation failed before an answer could be validated." },
  };
}

export function evidenceSnapshot(evidence: EvidencePackage): EvidencePackage {
  return evidence;
}
