import type { EvidencePackage, InvestigationCitation, ModelInvestigation } from "./types";

export type CitationValidation =
  | { ok: true; citations: InvestigationCitation[] }
  | { ok: false; reasons: string[] };

export function validateCitations(
  result: ModelInvestigation,
  evidence: EvidencePackage,
): CitationValidation {
  const findingIds = new Set(evidence.findings.map((finding) => finding.id));
  const nodeIds = new Set(evidence.nodes.map((node) => node.id));
  const reasons: string[] = [];
  const accepted: InvestigationCitation[] = [];
  const seenKey = new Set<string>();

  if (!result.citations || result.citations.length === 0) {
    return {
      ok: false,
      reasons: ["Investigation result must contain at least one citation grounded in the retrieved evidence."],
    };
  }

  for (const citation of result.citations) {
    if (citation.type === "finding") {
      if (!findingIds.has(citation.id)) {
        reasons.push(`Unknown finding id ${citation.id}`);
        continue;
      }
      const key = `finding:${citation.id}`;
      if (!seenKey.has(key)) {
        seenKey.add(key);
        accepted.push(citation);
      }
      continue;
    }
    if (citation.type === "node") {
      if (!nodeIds.has(citation.id)) {
        reasons.push(`Unknown node id ${citation.id}`);
        continue;
      }
      const key = `node:${citation.id}`;
      if (!seenKey.has(key)) {
        seenKey.add(key);
        accepted.push(citation);
      }
      continue;
    }
    if (citation.type === "source") {
      if (citation.start_line < 1 || citation.end_line < citation.start_line) {
        reasons.push(
          `Invalid line range ${citation.start_line}-${citation.end_line} for source citation ${citation.path}`,
        );
        continue;
      }
      const source = evidence.sources.find(
        (item) =>
          item.path === citation.path &&
          item.end_line > 0 &&
          citation.start_line >= item.start_line &&
          citation.end_line <= item.end_line,
      );
      if (!source) {
        reasons.push(
          `Source citation ${citation.path}:${citation.start_line}-${citation.end_line} is not in the retrieved evidence`,
        );
        continue;
      }
      const key = `source:${citation.path}:${citation.start_line}-${citation.end_line}`;
      if (!seenKey.has(key)) {
        seenKey.add(key);
        accepted.push(citation);
      }
      continue;
    }
    reasons.push(`Unknown citation type ${(citation as { type: string }).type}`);
  }

  if (reasons.length > 0) {
    return { ok: false, reasons };
  }
  if (accepted.length === 0) {
    return {
      ok: false,
      reasons: ["At least one valid citation is required."],
    };
  }
  return { ok: true, citations: accepted };
}

export function evidenceIsInsufficient(evidence: EvidencePackage): boolean {
  return evidence.findings.length === 0 && evidence.nodes.length === 0 && evidence.sources.length === 0;
}
