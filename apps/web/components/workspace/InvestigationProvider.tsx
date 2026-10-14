"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { browserAnalyzer } from "@/lib/api/client";
import { AnalyzerApiError, InvalidResponseError, recoveryHint } from "@/lib/errors";
import { sourceWindowForLine, sourceWindowForLocation, sourceWindowForNode } from "@/lib/source";
import type {
  AnalysisSummary,
  CallEdge,
  Finding,
  FindingsResponse,
  FunctionNode,
  GraphResponse,
  HealthResponse,
  PathsResponse,
  UnresolvedCall,
} from "@/lib/types";
import type { SourceState, SourceTarget, WorkspaceTab } from "@/lib/workspace-types";

export type DisplayError = {
  code: string;
  message: string;
  hint: string | null;
  retryAfterSeconds: number | null;
};

type HealthState =
  | { status: "checking" }
  | { status: "ok"; health: HealthResponse }
  | { status: "error"; message: string };

type InvestigationContextValue = {
  health: HealthState;
  analyzing: boolean;
  analysisError: DisplayError | null;
  summary: AnalysisSummary | null;
  graph: GraphResponse | null;
  graphLoading: boolean;
  findings: FindingsResponse | null;
  findingsLoading: boolean;
  source: SourceState;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  selectedFindingId: string | null;
  selectedPathIndex: number | null;
  highlightedPathNodeIds: string[];
  highlightedPathEdgeIds: string[];
  paths: PathsResponse | null;
  pathsLoading: boolean;
  pathsError: DisplayError | null;
  graphPathPrefix: string;
  workspaceTab: WorkspaceTab;
  localReview: Record<string, string>;
  submitAnalysis: (repoUrl: string, ref: string) => Promise<void>;
  loadAnalysis: (analysisId: string) => Promise<void>;
  setGraphPathPrefix: (prefix: string) => void;
  setWorkspaceTab: (tab: WorkspaceTab) => void;
  selectNode: (node: FunctionNode, openSource?: boolean) => void;
  selectEdge: (edge: CallEdge) => void;
  selectFinding: (finding: Finding) => void;
  selectUnresolved: (call: UnresolvedCall) => void;
  openSource: (target: SourceTarget) => void;
  fetchPaths: (source: string, target: string, maxDepth?: number, maxPaths?: number) => Promise<void>;
  selectPath: (index: number) => void;
  setLocalReview: (findingId: string, status: string) => void;
  loadMoreSource: () => void;
};

const InvestigationContext = createContext<InvestigationContextValue | null>(null);

function toDisplayError(error: unknown): DisplayError {
  if (error instanceof AnalyzerApiError) {
    return {
      code: error.code,
      message: error.message,
      hint: recoveryHint(error.code),
      retryAfterSeconds: error.retryAfterSeconds,
    };
  }
  if (error instanceof InvalidResponseError) {
    return {
      code: "invalid_response",
      message: error.message,
      hint: "The analyzer may be a different version than this UI expects.",
      retryAfterSeconds: null,
    };
  }
  return {
    code: "unknown",
    message: "Something went wrong while talking to the analyzer.",
    hint: null,
    retryAfterSeconds: null,
  };
}

export function InvestigationProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<HealthState>({ status: "checking" });
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<DisplayError | null>(null);
  const [summary, setSummary] = useState<AnalysisSummary | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [findings, setFindings] = useState<FindingsResponse | null>(null);
  const [findingsLoading, setFindingsLoading] = useState(false);
  const [source, setSource] = useState<SourceState>({ status: "idle" });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [selectedPathIndex, setSelectedPathIndex] = useState<number | null>(null);
  const [paths, setPaths] = useState<PathsResponse | null>(null);
  const [pathsLoading, setPathsLoading] = useState(false);
  const [pathsError, setPathsError] = useState<DisplayError | null>(null);
  const [graphPathPrefix, setGraphPathPrefixState] = useState("");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("graph");
  const [localReview, setLocalReviewState] = useState<Record<string, string>>({});
  const analyzingRef = useRef(false);
  const prefixRef = useRef("");

  const checkHealth = useCallback(async () => {
    try {
      const result = await browserAnalyzer.health();
      setHealth({ status: "ok", health: result });
    } catch (error) {
      const display = toDisplayError(error);
      setHealth({ status: "error", message: display.message });
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    const id = window.setInterval(() => void checkHealth(), 20_000);
    return () => window.clearInterval(id);
  }, [checkHealth]);

  const resetDerived = useCallback(() => {
    setGraph(null);
    setFindings(null);
    setSource({ status: "idle" });
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setSelectedFindingId(null);
    setSelectedPathIndex(null);
    setPaths(null);
    setPathsError(null);
    setLocalReviewState({});
  }, []);

  const loadCompletedArtifacts = useCallback(async (analysisId: string, pathPrefix: string) => {
    setGraphLoading(true);
    setFindingsLoading(true);
    try {
      const [graphResult, findingsResult] = await Promise.all([
        browserAnalyzer.getGraph(analysisId, {
          path_prefix: pathPrefix || undefined,
          max_nodes: 2000,
          max_unresolved: 500,
        }),
        browserAnalyzer.getFindings(analysisId, { limit: 500 }),
      ]);
      setGraph(graphResult);
      setFindings(findingsResult);
    } catch (error) {
      setAnalysisError(toDisplayError(error));
    } finally {
      setGraphLoading(false);
      setFindingsLoading(false);
    }
  }, []);

  const applySummary = useCallback(
    async (next: AnalysisSummary) => {
      setSummary(next);
      setAnalysisError(null);
      resetDerived();
      const url = new URL(window.location.href);
      url.searchParams.set("analysis", next.analysis_id);
      window.history.replaceState(null, "", url);
      if (next.status === "failed") {
        setAnalysisError({
          code: next.error?.code ?? "analysis_failed",
          message: next.error?.message ?? "Analysis failed.",
          hint: "Diagnostics below describe what could not be parsed. Graph, findings, and source are not requested for failed analyses.",
          retryAfterSeconds: null,
        });
        return;
      }
      if (next.status === "completed") {
        await loadCompletedArtifacts(next.analysis_id, prefixRef.current);
      }
    },
    [loadCompletedArtifacts, resetDerived],
  );

  const submitAnalysis = useCallback(
    async (repoUrl: string, ref: string) => {
      if (analyzingRef.current) {
        return;
      }
      analyzingRef.current = true;
      setAnalyzing(true);
      setAnalysisError(null);
      try {
        const result = await browserAnalyzer.analyze({
          repo_url: repoUrl,
          ref: ref.trim() ? ref.trim() : undefined,
        });
        await applySummary(result);
      } catch (error) {
        setAnalysisError(toDisplayError(error));
      } finally {
        analyzingRef.current = false;
        setAnalyzing(false);
      }
    },
    [applySummary],
  );

  const loadAnalysis = useCallback(
    async (analysisId: string) => {
      setAnalysisError(null);
      try {
        const result = await browserAnalyzer.getAnalysis(analysisId);
        await applySummary(result);
      } catch (error) {
        setSummary(null);
        resetDerived();
        setAnalysisError(toDisplayError(error));
      }
    },
    [applySummary, resetDerived],
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const analysisId = params.get("analysis");
    if (analysisId && /^[0-9a-f]{32}$/.test(analysisId)) {
      void loadAnalysis(analysisId);
    }
    // Session restore from the URL only; IDs are not written to localStorage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setGraphPathPrefix = useCallback(
    (prefix: string) => {
      prefixRef.current = prefix;
      setGraphPathPrefixState(prefix);
      if (summary?.status === "completed") {
        setGraphLoading(true);
        void browserAnalyzer
          .getGraph(summary.analysis_id, {
            path_prefix: prefix || undefined,
            max_nodes: 2000,
            max_unresolved: 500,
          })
          .then(setGraph)
          .catch((error) => setAnalysisError(toDisplayError(error)))
          .finally(() => setGraphLoading(false));
      }
    },
    [summary],
  );

  const openSource = useCallback(
    (target: SourceTarget) => {
      if (!summary || summary.status !== "completed") {
        return;
      }
      setSource({ status: "loading", target });
      const query = {
        path: target.path,
        start_line: target.start_line,
        end_line: target.end_line,
      };
      void browserAnalyzer
        .getSource(summary.analysis_id, query)
        .then((data) => setSource({ status: "ready", target, data }))
        .catch((error) =>
          setSource({
            status: "error",
            target,
            message: toDisplayError(error).message,
          }),
        );
    },
    [summary],
  );

  const selectNode = useCallback(
    (node: FunctionNode, open = true) => {
      setSelectedNodeId(node.id);
      setSelectedEdgeId(null);
      if (open) {
        const window = sourceWindowForNode(node);
        openSource({
          path: node.path,
          start_line: window.start_line ?? node.start_line,
          end_line: window.end_line ?? node.end_line,
          highlight_start: node.start_line,
          highlight_end: node.end_line,
          label: node.qualified_name,
        });
      }
    },
    [openSource],
  );

  const selectEdge = useCallback(
    (edge: CallEdge) => {
      setSelectedEdgeId(edge.id);
      setSelectedNodeId(edge.source);
      const sourceNode = graph?.nodes.find((node) => node.id === edge.source);
      const site = edge.call_sites[0];
      if (sourceNode && site) {
        const window = sourceWindowForLine(sourceNode.path, site.line);
        openSource({
          path: sourceNode.path,
          start_line: window.start_line ?? site.line,
          end_line: window.end_line ?? site.line,
          highlight_start: site.line,
          highlight_end: site.line,
          label: `Call site → ${edge.target}`,
        });
      }
    },
    [graph, openSource],
  );

  const selectFinding = useCallback(
    (finding: Finding) => {
      setSelectedFindingId(finding.id);
      if (finding.function_id) {
        setSelectedNodeId(finding.function_id);
      }
      setWorkspaceTab("findings");
      const window = sourceWindowForLocation(finding.location);
      openSource({
        path: finding.location.path,
        start_line: window.start_line ?? finding.location.start_line,
        end_line: window.end_line ?? finding.location.end_line,
        highlight_start: finding.location.start_line,
        highlight_end: finding.location.end_line,
        label: finding.title,
      });
    },
    [openSource],
  );

  const selectUnresolved = useCallback(
    (call: UnresolvedCall) => {
      setSelectedNodeId(call.caller_id);
      const window = sourceWindowForLine(call.path, call.call_site.line);
      openSource({
        path: call.path,
        start_line: window.start_line ?? call.call_site.line,
        end_line: window.end_line ?? call.call_site.line,
        highlight_start: call.call_site.line,
        highlight_end: call.call_site.line,
        label: `Unresolved ${call.callee}`,
      });
    },
    [openSource],
  );

  const fetchPaths = useCallback(
    async (sourceId: string, targetId: string, maxDepth = 8, maxPaths = 10) => {
      if (!summary || summary.status !== "completed") {
        return;
      }
      setPathsLoading(true);
      setPathsError(null);
      setSelectedPathIndex(null);
      try {
        const result = await browserAnalyzer.getPaths(summary.analysis_id, {
          source: sourceId,
          target: targetId,
          max_depth: maxDepth,
          max_paths: maxPaths,
        });
        setPaths(result);
        if (result.paths.length > 0) {
          setSelectedPathIndex(0);
        }
      } catch (error) {
        setPaths(null);
        setPathsError(toDisplayError(error));
      } finally {
        setPathsLoading(false);
      }
    },
    [summary],
  );

  const selectPath = useCallback((index: number) => {
    setSelectedPathIndex(index);
  }, []);

  const setLocalReview = useCallback((findingId: string, status: string) => {
    setLocalReviewState((current) => ({ ...current, [findingId]: status }));
  }, []);

  const loadMoreSource = useCallback(() => {
    if (source.status !== "ready" || !source.data.truncated) {
      return;
    }
    openSource({
      ...source.target,
      start_line: source.data.end_line + 1,
      end_line: source.data.end_line + 500,
    });
  }, [openSource, source]);

  const { highlightedPathNodeIds, highlightedPathEdgeIds } = useMemo(() => {
    const path = paths?.paths[selectedPathIndex ?? -1];
    return {
      highlightedPathNodeIds: path?.node_ids ?? [],
      highlightedPathEdgeIds: path?.edge_ids ?? [],
    };
  }, [paths, selectedPathIndex]);

  const value = useMemo<InvestigationContextValue>(
    () => ({
      health,
      analyzing,
      analysisError,
      summary,
      graph,
      graphLoading,
      findings,
      findingsLoading,
      source,
      selectedNodeId,
      selectedEdgeId,
      selectedFindingId,
      selectedPathIndex,
      highlightedPathNodeIds,
      highlightedPathEdgeIds,
      paths,
      pathsLoading,
      pathsError,
      graphPathPrefix,
      workspaceTab,
      localReview,
      submitAnalysis,
      loadAnalysis,
      setGraphPathPrefix,
      setWorkspaceTab,
      selectNode,
      selectEdge,
      selectFinding,
      selectUnresolved,
      openSource,
      fetchPaths,
      selectPath,
      setLocalReview,
      loadMoreSource,
    }),
    [
      health,
      analyzing,
      analysisError,
      summary,
      graph,
      graphLoading,
      findings,
      findingsLoading,
      source,
      selectedNodeId,
      selectedEdgeId,
      selectedFindingId,
      selectedPathIndex,
      highlightedPathNodeIds,
      highlightedPathEdgeIds,
      paths,
      pathsLoading,
      pathsError,
      graphPathPrefix,
      workspaceTab,
      localReview,
      submitAnalysis,
      loadAnalysis,
      setGraphPathPrefix,
      selectNode,
      selectEdge,
      selectFinding,
      selectUnresolved,
      openSource,
      fetchPaths,
      selectPath,
      setLocalReview,
      loadMoreSource,
    ],
  );

  return <InvestigationContext.Provider value={value}>{children}</InvestigationContext.Provider>;
}

export function useInvestigation(): InvestigationContextValue {
  const value = useContext(InvestigationContext);
  if (!value) {
    throw new Error("useInvestigation must be used within InvestigationProvider");
  }
  return value;
}
