"use client";

import { AppHeader } from "@/components/AppHeader";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RepositoryOverview } from "@/components/RepositoryOverview";
import { CallGraph } from "@/components/graph/CallGraph";
import { UnresolvedCalls } from "@/components/graph/UnresolvedCalls";
import { SelectionPanel } from "@/components/graph/SelectionPanel";
import { FindingsExplorer } from "@/components/findings/FindingsExplorer";
import { SourceViewer } from "@/components/source/SourceViewer";
import { PathExplorer } from "@/components/paths/PathExplorer";
import { Investigator } from "@/components/investigator/Investigator";
import {
  InvestigationProvider,
  useInvestigation,
} from "@/components/workspace/InvestigationProvider";
import type { WorkspaceTab } from "@/lib/workspace-types";

function WorkspaceContent() {
  const {
    workspaceTab,
    setWorkspaceTab,
    graph,
    findings,
    source,
    paths,
  } = useInvestigation();

  const tabs: Array<{ id: WorkspaceTab; label: string; count?: number | string | null }> = [
    {
      id: "graph",
      label: "Call Graph",
      count: graph?.nodes.length ? `${graph.nodes.length} nodes` : null,
    },
    {
      id: "findings",
      label: "Findings",
      count: findings ? findings.total : null,
    },
    {
      id: "unresolved",
      label: "Unresolved Calls",
      count: graph?.unresolved_calls_total ?? (graph?.unresolved_calls.length || null),
    },
    {
      id: "paths",
      label: "Call Paths",
      count: paths?.paths.length ? `${paths.paths.length} paths` : null,
    },
    {
      id: "investigate",
      label: "AI Investigator",
    },
  ];

  return (
    <div className="flex min-h-screen flex-col bg-bg text-text">
      <AppHeader />
      <ErrorBanner />
      <RepositoryOverview />

      <main className="flex flex-1 min-h-0 flex-col lg:flex-row">
        {/* Left Column: Investigation Tools & Tabs */}
        <section
          aria-label="Investigation tools"
          className="flex flex-1 min-w-0 flex-col border-b border-border lg:border-b-0 lg:border-r"
        >
          {/* Navigation tab bar */}
          <nav
            aria-label="Workspace tabs"
            className="flex flex-wrap items-center gap-1 border-b border-border bg-surface px-3 py-1.5"
          >
            {tabs.map((tab) => {
              const active = workspaceTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setWorkspaceTab(tab.id)}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                    active
                      ? "border border-border bg-surface-2 font-semibold text-accent shadow-xs"
                      : "text-muted hover:bg-surface-2/60 hover:text-text"
                  }`}
                  aria-selected={active}
                  role="tab"
                >
                  <span>{tab.label}</span>
                  {tab.count !== null && tab.count !== undefined ? (
                    <span
                      className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                        active
                          ? "bg-accent/20 font-semibold text-accent"
                          : "bg-surface-2 text-muted"
                      }`}
                    >
                      {tab.count}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </nav>

          {/* Active Tab Panel */}
          <div className="flex flex-1 min-h-[420px] flex-col overflow-auto bg-surface/50 lg:min-h-[500px]">
            {workspaceTab === "graph" && (
              <div className="flex h-full min-h-[420px] flex-1 flex-col">
                <div className="min-h-[360px] flex-1">
                  <CallGraph />
                </div>
                <div className="border-t border-border bg-surface-2/50">
                  <SelectionPanel />
                </div>
              </div>
            )}
            {workspaceTab === "findings" && <FindingsExplorer />}
            {workspaceTab === "unresolved" && <UnresolvedCalls />}
            {workspaceTab === "paths" && <PathExplorer />}
            {workspaceTab === "investigate" && <Investigator />}
          </div>
        </section>

        {/* Right Column: Source Viewer */}
        <section
          aria-label="Source code viewer"
          className="flex min-h-[380px] w-full flex-col bg-surface lg:min-h-[500px] lg:w-[48%] xl:w-[44%]"
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs">
            <span className="font-semibold uppercase tracking-wide text-muted">
              Source Code
            </span>
            {source.status === "ready" ? (
              <span className="max-w-[20rem] truncate font-mono text-[11px] text-accent">
                {source.data.path}:{source.target.highlight_start}–{source.target.highlight_end}
              </span>
            ) : source.status === "loading" ? (
              <span className="text-[11px] text-muted">Loading excerpt…</span>
            ) : null}
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <SourceViewer />
          </div>
        </section>
      </main>
    </div>
  );
}

export default function HomePage() {
  return (
    <InvestigationProvider>
      <WorkspaceContent />
    </InvestigationProvider>
  );
}
