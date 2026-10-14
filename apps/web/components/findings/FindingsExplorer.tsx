"use client";

import { useMemo, useState } from "react";
import { KNOWN_SEVERITIES } from "@/lib/types";
import { countBy, filterFindings } from "@/lib/findings-filter";
import { Badge } from "../ui/Badge";
import { useInvestigation } from "../workspace/InvestigationProvider";

export function FindingsExplorer() {
  const { findings, findingsLoading, selectFinding, selectedFindingId, localReview, setLocalReview, graph, selectNode } =
    useInvestigation();
  const [severity, setSeverity] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [pathPrefix, setPathPrefix] = useState("");
  const [query, setQuery] = useState("");

  const visible = useMemo(
    () => filterFindings(findings?.findings ?? [], { severity, ruleId, pathPrefix, query }),
    [findings, pathPrefix, query, ruleId, severity],
  );

  if (findingsLoading) {
    return <p className="p-3 text-sm text-muted">Loading findings…</p>;
  }
  if (!findings) {
    return <p className="p-3 text-sm text-muted">Findings load after a completed analysis.</p>;
  }

  const severityCounts = countBy(findings.findings, (finding) => finding.severity);
  const reviewCounts = countBy(findings.findings, (finding) => localReview[finding.id] ?? finding.review_status);
  const rules = Array.from(new Set(findings.findings.map((finding) => finding.rule_id))).sort();

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-border px-3 py-2 text-xs">
        <p>
          {visible.length} shown · {findings.total} total
          {findings.truncated ? " · response truncated" : ""}
        </p>
        <p className="text-muted">
          Findings are potential issues for human review, not confirmed vulnerabilities. Local review
          actions are not saved to the analyzer.
        </p>
        <div className="flex flex-wrap gap-2">
          {Object.entries(severityCounts).map(([key, count]) => (
            <span key={key} className={`severity-${key}`}>
              {key}: {count}
            </span>
          ))}
          {Object.entries(reviewCounts).map(([key, count]) => (
            <span key={key}>
              {key}: {count}
            </span>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={severity}
            onChange={(event) => setSeverity(event.target.value)}
            className="rounded-md border border-border bg-surface px-2 py-1"
          >
            <option value="">All severities</option>
            {KNOWN_SEVERITIES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
            {Object.keys(severityCounts)
              .filter((item) => !KNOWN_SEVERITIES.includes(item as (typeof KNOWN_SEVERITIES)[number]))
              .map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
          </select>
          <select
            value={ruleId}
            onChange={(event) => setRuleId(event.target.value)}
            className="rounded-md border border-border bg-surface px-2 py-1"
          >
            <option value="">All rules</option>
            {rules.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <input
            value={pathPrefix}
            onChange={(event) => setPathPrefix(event.target.value)}
            placeholder="file or directory"
            className="rounded-md border border-border bg-surface px-2 py-1"
          />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search findings"
            className="rounded-md border border-border bg-surface px-2 py-1"
          />
        </div>
      </div>
      {visible.length === 0 ? (
        <p className="p-3 text-sm text-muted">No findings match these filters.</p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-auto">
          {visible.map((finding) => {
            const node = finding.function_id
              ? graph?.nodes.find((item) => item.id === finding.function_id)
              : undefined;
            const review = localReview[finding.id] ?? finding.review_status;
            return (
              <li
                key={finding.id}
                className={`border-b border-border px-3 py-2 ${selectedFindingId === finding.id ? "bg-surface-2" : ""}`}
              >
                <button type="button" className="w-full text-left" onClick={() => selectFinding(finding)}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`text-xs font-semibold severity-${finding.severity}`}>{finding.severity}</span>
                    <span className="text-sm font-medium">{finding.title}</span>
                    <Badge>{finding.rule_id}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted">{finding.description}</p>
                  <p className="mt-1 font-mono text-[11px] text-muted">
                    {finding.location.path}:{finding.location.start_line}–{finding.location.end_line}
                  </p>
                  <pre className="mt-1 overflow-auto whitespace-pre-wrap font-mono text-[11px]">{finding.evidence}</pre>
                </button>
                <p className="mt-1 text-[11px] text-muted">
                  confidence {finding.confidence}
                  {finding.cwe_id ? ` · ${finding.cwe_id}` : ""} · {finding.id}
                </p>
                {finding.next_step ? <p className="text-[11px]">Next: {finding.next_step}</p> : null}
                {finding.limitations.map((item) => (
                  <p key={item} className="text-[11px] text-muted">
                    Limitation: {item}
                  </p>
                ))}
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                  <label>
                    Local review
                    <select
                      className="ml-1 rounded border border-border bg-surface px-1 py-0.5"
                      value={review}
                      onChange={(event) => setLocalReview(finding.id, event.target.value)}
                    >
                      <option value="needs_review">needs_review</option>
                      <option value="confirmed">confirmed (local)</option>
                      <option value="dismissed">dismissed (local)</option>
                    </select>
                  </label>
                  {node ? (
                    <button type="button" className="text-accent" onClick={() => selectNode(node)}>
                      Open graph node
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
