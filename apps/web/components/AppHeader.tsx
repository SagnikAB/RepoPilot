"use client";

import { Activity, GitBranch } from "lucide-react";
import { AnalyzeForm } from "./AnalyzeForm";
import { Badge, statusTone } from "./ui/Badge";
import { useInvestigation } from "./workspace/InvestigationProvider";

export function AppHeader() {
  const { health, analyzing, summary } = useInvestigation();

  return (
    <header className="border-b border-border bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <GitBranch className="h-5 w-5 text-accent" aria-hidden />
          <div>
            <p className="text-sm font-semibold tracking-tight">RepoPilot</p>
            <p className="text-xs text-muted">Codebase investigation workspace</p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs">
          <Activity className="h-3.5 w-3.5 text-muted" aria-hidden />
          {health.status === "checking" ? <Badge>Checking analyzer…</Badge> : null}
          {health.status === "ok" ? (
            <Badge tone="ok">{`${health.health.service} ${health.health.version}`}</Badge>
          ) : null}
          {health.status === "error" ? <Badge tone="danger">Analyzer unreachable</Badge> : null}
        </div>
      </div>
      <div className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-end">
        <AnalyzeForm />
        {summary ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <Badge tone={statusTone(summary.status)}>{summary.status}</Badge>
            <span>
              {summary.repository.owner}/{summary.repository.name}
            </span>
            {summary.repository.ref ? <span>@{summary.repository.ref}</span> : null}
            {summary.repository.commit_sha ? (
              <span className="font-mono">{summary.repository.commit_sha.slice(0, 12)}</span>
            ) : null}
          </div>
        ) : null}
      </div>
      {analyzing ? (
        <p className="mt-2 text-xs text-muted" role="status">
          Analysis is running. This request is synchronous and can take up to a few minutes. There is no
          live progress from the analyzer.
        </p>
      ) : null}
    </header>
  );
}
