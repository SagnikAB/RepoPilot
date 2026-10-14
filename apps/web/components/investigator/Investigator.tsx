"use client";

import { FormEvent, useState } from "react";
import { AnalysisIdSchema } from "@/lib/types";
import type { InvestigationResult } from "@/lib/investigation/types";
import { useInvestigation } from "../workspace/InvestigationProvider";
import type { SourceTarget } from "@/lib/workspace-types";

export function Investigator() {
  const { summary, graph, findings, selectFinding, selectNode, openSource } = useInvestigation();
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<InvestigationResult | null>(null);

  if (!summary || summary.status !== "completed") {
    return (
      <p className="p-3 text-sm text-muted">
        The AI investigator needs a completed analysis. Graph exploration still works without an AI provider.
      </p>
    );
  }

  const parsedAnalysisId = AnalysisIdSchema.safeParse(summary.analysis_id);
  if (!parsedAnalysisId.success) {
    return (
      <p className="p-3 text-sm text-danger">
        Invalid analysis ID.
      </p>
    );
  }
  const analysisId = parsedAnalysisId.data;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setResult(null);
    try {
      const response = await fetch("/api/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ analysis_id: analysisId, question }),
      });
      const payload = (await response.json()) as InvestigationResult;
      setResult(payload);
    } catch {
      setResult({
        ok: false,
        error: { code: "investigation_failed", message: "Could not reach the investigation route." },
      });
    } finally {
      setLoading(false);
    }
  }

  function goToCitation(citation: {
    type: string;
    id?: string;
    path?: string;
    start_line?: number;
    end_line?: number;
  }) {
    if (citation.type === "finding" && citation.id) {
      const finding = findings?.findings.find((item) => item.id === citation.id);
      if (finding) {
        selectFinding(finding);
      }
    }
    if (citation.type === "node" && citation.id) {
      const node = graph?.nodes.find((item) => item.id === citation.id);
      if (node) {
        selectNode(node);
      }
    }
    if (citation.type === "source" && citation.path && citation.start_line && citation.end_line) {
      const target: SourceTarget = {
        path: citation.path,
        start_line: Math.max(1, citation.start_line - 5),
        end_line: citation.end_line + 5,
        highlight_start: citation.start_line,
        highlight_end: citation.end_line,
        label: `${citation.path}:${citation.start_line}-${citation.end_line}`,
      };
      openSource(target);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <form onSubmit={onSubmit} className="space-y-2 border-b border-border px-3 py-2">
        <p className="text-xs text-muted">
          Answers are grounded in retrieved analyzer evidence. Citations are validated before they reach
          this panel. Missing an AI key shows a configuration error instead of a fake answer.
        </p>
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={3}
          required
          minLength={8}
          maxLength={2000}
          placeholder="Where is user input processed, and which findings are nearby?"
          className="w-full rounded-md border border-border bg-surface px-2 py-1 text-sm"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-md bg-accent px-3 py-1.5 text-sm text-accent-foreground disabled:opacity-60"
        >
          {loading ? "Investigating…" : "Investigate"}
        </button>
      </form>
      <div className="min-h-0 flex-1 overflow-auto p-3 text-sm">
        {result && !result.ok ? (
          <div className="rounded-md border border-danger/40 bg-danger/10 p-3">
            <p className="font-medium">{result.error.code}</p>
            <p>{result.error.message}</p>
            {result.error.code === "ai_not_configured" ? (
              <p className="mt-2 text-xs text-muted">
                Create apps/web/.env.local with OPENAI_API_KEY, optional OPENAI_BASE_URL, and optional
                OPENAI_MODEL, then restart next.
              </p>
            ) : null}
          </div>
        ) : null}
        {result?.ok ? (
          <div className="space-y-3">
            <p className="text-xs text-muted">
              Model {result.model} · evidence {result.evidence_counts.findings} findings,{" "}
              {result.evidence_counts.nodes} nodes, {result.evidence_counts.sources} source windows
            </p>
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Interpretation</h3>
              <p className="mt-1 whitespace-pre-wrap">{result.result.answer}</p>
            </section>
            <List title="Observed facts" items={result.result.observed_facts} />
            <List title="Plausible interpretations" items={result.result.interpretations} />
            <List title="Unknowns" items={result.result.unknowns} />
            <List title="Limitations" items={result.result.limitations} />
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Validated citations</h3>
              <ul className="mt-1 space-y-1">
                {result.result.citations.map((citation, index) => (
                  <li key={index}>
                    <button type="button" className="font-mono text-xs text-accent" onClick={() => goToCitation(citation)}>
                      {citation.type === "source"
                        ? `${citation.path}:${citation.start_line}-${citation.end_line}`
                        : `${citation.type}:${citation.id}`}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      <ul className="mt-1 list-disc pl-4">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
