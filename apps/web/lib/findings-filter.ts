import { SEVERITY_RANK, type Finding } from "./types";

export type FindingFilters = {
  severity: string;
  ruleId: string;
  pathPrefix: string;
  query: string;
};

export function sortFindings(findings: Finding[]): Finding[] {
  return [...findings].sort((a, b) => {
    const severityDelta = (SEVERITY_RANK[b.severity] ?? -1) - (SEVERITY_RANK[a.severity] ?? -1);
    if (severityDelta !== 0) {
      return severityDelta;
    }
    if (a.location.path !== b.location.path) {
      return a.location.path.localeCompare(b.location.path);
    }
    return a.location.start_line - b.location.start_line;
  });
}

export function filterFindings(findings: Finding[], filters: FindingFilters): Finding[] {
  const q = filters.query.trim().toLowerCase();
  return sortFindings(findings).filter((finding) => {
    if (filters.severity && finding.severity !== filters.severity) {
      return false;
    }
    if (filters.ruleId && finding.rule_id !== filters.ruleId) {
      return false;
    }
    if (filters.pathPrefix) {
      const prefix = filters.pathPrefix.replace(/\/$/, "");
      const path = finding.location.path;
      if (path !== prefix && !path.startsWith(`${prefix}/`)) {
        return false;
      }
    }
    if (!q) {
      return true;
    }
    const haystack = [
      finding.title,
      finding.description,
      finding.rule_id,
      finding.evidence,
      finding.location.path,
      finding.cwe_id ?? "",
      finding.next_step,
    ]
      .join("\n")
      .toLowerCase();
    return haystack.includes(q);
  });
}

export function countBy(findings: Finding[], key: (finding: Finding) => string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const finding of findings) {
    const value = key(finding);
    counts[value] = (counts[value] ?? 0) + 1;
  }
  return counts;
}
