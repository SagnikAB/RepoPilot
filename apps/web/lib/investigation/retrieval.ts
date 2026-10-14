import type { AnalysisSummary, Finding, FunctionNode, GraphResponse } from "../types";
import type { EvidenceFinding, EvidenceNode, EvidencePackage } from "./types";

const MAX_FINDINGS = 8;
const MAX_NODES = 12;
const MAX_QUESTION_CHARS = 2000;

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9_./-]+/)
    .filter((token) => token.length >= 3);
}

function scoreText(tokens: string[], ...fields: string[]): number {
  const haystack = fields.join("\n").toLowerCase();
  let score = 0;
  for (const token of tokens) {
    if (haystack.includes(token)) {
      score += 1;
    }
  }
  return score;
}

export function clampQuestion(question: string): string {
  return question.trim().slice(0, MAX_QUESTION_CHARS);
}

export function selectEvidence(
  question: string,
  summary: AnalysisSummary,
  graph: GraphResponse,
  findings: Finding[],
): { findings: EvidenceFinding[]; nodes: EvidenceNode[] } {
  const tokens = tokenize(question);
  const rankedFindings = findings
    .map((finding) => ({
      finding,
      score:
        scoreText(
          tokens,
          finding.title,
          finding.description,
          finding.rule_id,
          finding.evidence,
          finding.location.path,
          finding.next_step,
          finding.cwe_id ?? "",
        ) + (SEVERITY_BONUS[finding.severity] ?? 0),
    }))
    .sort((a, b) => b.score - a.score || a.finding.id.localeCompare(b.finding.id));

  const selectedFindings = rankedFindings.slice(0, MAX_FINDINGS).map(({ finding }) => toEvidenceFinding(finding));

  const findingNodeIds = new Set(
    selectedFindings.map((finding) => finding.function_id).filter((id): id is string => Boolean(id)),
  );

  const rankedNodes = graph.nodes
    .map((node) => ({
      node,
      score:
        scoreText(tokens, node.name, node.qualified_name, node.path, node.kind) +
        (findingNodeIds.has(node.id) ? 5 : 0),
    }))
    .sort((a, b) => b.score - a.score || a.node.id.localeCompare(b.node.id));

  const selectedNodes: EvidenceNode[] = [];
  const seen = new Set<string>();
  for (const id of findingNodeIds) {
    const node = graph.nodes.find((candidate) => candidate.id === id);
    if (node && !seen.has(node.id)) {
      selectedNodes.push(toEvidenceNode(node));
      seen.add(node.id);
    }
  }
  for (const { node } of rankedNodes) {
    if (selectedNodes.length >= MAX_NODES) {
      break;
    }
    if (!seen.has(node.id)) {
      selectedNodes.push(toEvidenceNode(node));
      seen.add(node.id);
    }
  }

  return { findings: selectedFindings, nodes: selectedNodes };
}

const SEVERITY_BONUS: Record<string, number> = {
  critical: 3,
  high: 2,
  medium: 1,
};

function toEvidenceFinding(finding: Finding): EvidenceFinding {
  return {
    id: finding.id,
    rule_id: finding.rule_id,
    title: finding.title,
    description: finding.description,
    severity: finding.severity,
    confidence: finding.confidence,
    location: finding.location,
    function_id: finding.function_id ?? null,
    evidence: finding.evidence,
    next_step: finding.next_step,
    limitations: finding.limitations,
    cwe_id: finding.cwe_id ?? null,
  };
}

function toEvidenceNode(node: FunctionNode): EvidenceNode {
  return {
    id: node.id,
    name: node.name,
    qualified_name: node.qualified_name,
    kind: node.kind,
    path: node.path,
    start_line: node.start_line,
    end_line: node.end_line,
  };
}

export function emptyPackage(summary: AnalysisSummary, graph: GraphResponse, findingsTruncated: boolean): EvidencePackage {
  return {
    analysis_id: summary.analysis_id,
    repository: {
      owner: summary.repository.owner,
      name: summary.repository.name,
      url: summary.repository.url,
      ref: summary.repository.ref ?? null,
      commit_sha: summary.repository.commit_sha ?? null,
    },
    warnings: summary.diagnostics.warnings,
    graph_limitations: graph.limitations,
    graph_truncated: graph.truncated,
    findings_truncated: findingsTruncated,
    findings: [],
    nodes: [],
    sources: [],
  };
}
