import { ANALYZE_TIMEOUT_MS, DEFAULT_FETCH_TIMEOUT_MS } from "../config";
import {
  AnalysisSummarySchema,
  FindingsResponseSchema,
  GraphResponseSchema,
  HealthResponseSchema,
  PathsResponseSchema,
  SourceResponseSchema,
  type AnalysisSummary,
  type FindingsResponse,
  type GraphResponse,
  type HealthResponse,
  type PathsResponse,
  type SourceResponse,
} from "../types";
import { fetchJson, serializeQuery } from "./fetch-json";

export const BROWSER_ANALYZER_PREFIX = "/api/proxy";

export type GraphQuery = {
  path_prefix?: string;
  max_nodes?: number;
  max_unresolved?: number;
};

export type FindingsQuery = {
  severity?: string;
  rule_id?: string;
  path_prefix?: string;
  limit?: number;
};

export type SourceQuery = {
  path: string;
  start_line?: number;
  end_line?: number;
};

export type PathsQuery = {
  source: string;
  target: string;
  max_depth?: number;
  max_paths?: number;
};

export function createAnalyzerClient(baseUrl: string) {
  const root = baseUrl.replace(/\/$/, "");

  return {
    health(signal?: AbortSignal): Promise<HealthResponse> {
      return fetchJson(`${root}/api/health`, HealthResponseSchema, {
        timeoutMs: 8_000,
        signal,
      });
    },

    analyze(body: { repo_url: string; ref?: string | null }, signal?: AbortSignal): Promise<AnalysisSummary> {
      const payload: { repo_url: string; ref?: string } = { repo_url: body.repo_url };
      if (body.ref) {
        payload.ref = body.ref;
      }
      return fetchJson(`${root}/api/analyze`, AnalysisSummarySchema, {
        method: "POST",
        body: payload,
        timeoutMs: ANALYZE_TIMEOUT_MS,
        signal,
      });
    },

    getAnalysis(analysisId: string, signal?: AbortSignal): Promise<AnalysisSummary> {
      return fetchJson(`${root}/api/analyses/${encodeURIComponent(analysisId)}`, AnalysisSummarySchema, {
        timeoutMs: DEFAULT_FETCH_TIMEOUT_MS,
        signal,
      });
    },

    getGraph(analysisId: string, query: GraphQuery = {}, signal?: AbortSignal): Promise<GraphResponse> {
      return fetchJson(
        `${root}/api/analyses/${encodeURIComponent(analysisId)}/graph${serializeQuery(query)}`,
        GraphResponseSchema,
        { timeoutMs: DEFAULT_FETCH_TIMEOUT_MS, signal },
      );
    },

    getFindings(analysisId: string, query: FindingsQuery = {}, signal?: AbortSignal): Promise<FindingsResponse> {
      return fetchJson(
        `${root}/api/analyses/${encodeURIComponent(analysisId)}/findings${serializeQuery(query)}`,
        FindingsResponseSchema,
        { timeoutMs: DEFAULT_FETCH_TIMEOUT_MS, signal },
      );
    },

    getSource(analysisId: string, query: SourceQuery, signal?: AbortSignal): Promise<SourceResponse> {
      return fetchJson(
        `${root}/api/analyses/${encodeURIComponent(analysisId)}/source${serializeQuery(query)}`,
        SourceResponseSchema,
        { timeoutMs: DEFAULT_FETCH_TIMEOUT_MS, signal },
      );
    },

    getPaths(analysisId: string, query: PathsQuery, signal?: AbortSignal): Promise<PathsResponse> {
      return fetchJson(
        `${root}/api/analyses/${encodeURIComponent(analysisId)}/paths${serializeQuery(query)}`,
        PathsResponseSchema,
        { timeoutMs: DEFAULT_FETCH_TIMEOUT_MS, signal },
      );
    },
  };
}

export const browserAnalyzer = createAnalyzerClient(BROWSER_ANALYZER_PREFIX);
