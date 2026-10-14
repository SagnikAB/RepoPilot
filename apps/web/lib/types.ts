import { z } from "zod";

/** Opaque IDs. Pattern-checked but treated as opaque in the UI. */
export const AnalysisIdSchema = z.string().regex(/^[0-9a-f]{32}$/);
export const NodeIdSchema = z.string().regex(/^fn_[0-9a-f]{16}$/);
export const EdgeIdSchema = z.string().regex(/^ce_[0-9a-f]{16}$/);
export const FindingIdSchema = z.string().regex(/^fd_[0-9a-f]{16}$/);

export const RepoPathSchema = z
  .string()
  .min(1)
  .max(1024)
  .refine((value) => !value.startsWith("/") && !value.includes("\\") && !value.includes("\0"), {
    message: "path must be repository-relative POSIX",
  })
  .refine((value) => !value.split("/").some((segment) => segment === "" || segment === "." || segment === ".."), {
    message: "path must be normalized",
  });

const LineNumberSchema = z.number().int().min(1);
const ColumnNumberSchema = z.number().int().min(1);

/** Enums may grow; keep known values for styling but accept unknown strings. */
export const AnalysisStatusSchema = z.string().min(1);
export const SkipReasonSchema = z.string().min(1);
export const FunctionKindSchema = z.string().min(1);
export const ResolutionMethodSchema = z.string().min(1);
export const UnresolvedReasonSchema = z.string().min(1);
export const SeveritySchema = z.string().min(1);
export const ConfidenceSchema = z.string().min(1);
export const ReviewStatusSchema = z.string().min(1);
export const LanguageSchema = z.string().min(1);

export const SourceReferenceSchema = z.object({
  path: RepoPathSchema,
  start_line: LineNumberSchema,
  end_line: LineNumberSchema,
});

export const ErrorDetailSchema = z.object({
  loc: z.array(z.union([z.string(), z.number()])).nullable().optional(),
  message: z.string(),
  type: z.string().nullable().optional(),
});

export const ErrorBodySchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.array(ErrorDetailSchema).nullable().optional(),
});

export const ErrorResponseSchema = z.object({
  error: ErrorBodySchema,
});

export const HealthResponseSchema = z.object({
  status: z.string(),
  service: z.string(),
  version: z.string(),
});

export const ParseDiagnosticSchema = z.object({
  path: RepoPathSchema,
  line: LineNumberSchema.nullable().optional(),
  message: z.string(),
});

export const SkippedFileSchema = z.object({
  path: RepoPathSchema,
  reason: SkipReasonSchema,
});

export const LimitReachedSchema = z.object({
  limit: z.string(),
  value: z.number().int(),
});

export const AnalysisDiagnosticsSchema = z.object({
  parse_errors: z.array(ParseDiagnosticSchema).default([]),
  skipped_files: z.array(SkippedFileSchema).default([]),
  skipped_by_reason: z.record(z.string(), z.number()).default({}),
  limits_reached: z.array(LimitReachedSchema).default([]),
  warnings: z.array(z.string()).default([]),
  truncated: z.boolean().default(false),
});

export const RepositoryInfoSchema = z.object({
  url: z.string(),
  host: z.string(),
  owner: z.string(),
  name: z.string(),
  ref: z.string().nullable().optional(),
  commit_sha: z.string().nullable().optional(),
});

export const AnalysisStatsSchema = z.object({
  files_discovered: z.number().int().nonnegative(),
  files_analyzed: z.number().int().nonnegative(),
  files_skipped: z.number().int().nonnegative(),
  functions: z.number().int().nonnegative(),
  call_edges: z.number().int().nonnegative(),
  unresolved_calls: z.number().int().nonnegative(),
  findings: z.number().int().nonnegative().nullable(),
  findings_by_severity: z.record(z.string(), z.number()).default({}),
  files_by_language: z.record(z.string(), z.number()).default({}),
});

export const AnalysisErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
});

export const AnalysisSummarySchema = z.object({
  analysis_id: z.string(),
  status: AnalysisStatusSchema,
  repository: RepositoryInfoSchema,
  created_at: z.string(),
  completed_at: z.string().nullable().optional(),
  duration_ms: z.number().int().nonnegative().nullable().optional(),
  stats: AnalysisStatsSchema.nullable().optional(),
  diagnostics: AnalysisDiagnosticsSchema.default({
    parse_errors: [],
    skipped_files: [],
    skipped_by_reason: {},
    limits_reached: [],
    warnings: [],
    truncated: false,
  }),
  error: AnalysisErrorSchema.nullable().optional(),
});

export const FunctionNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  qualified_name: z.string(),
  kind: FunctionKindSchema,
  language: LanguageSchema,
  path: RepoPathSchema,
  start_line: LineNumberSchema,
  end_line: LineNumberSchema,
  start_column: ColumnNumberSchema,
  is_anonymous: z.boolean().default(false),
  is_exported: z.boolean().default(false),
});

export const CallSiteSchema = z.object({
  line: LineNumberSchema,
  column: ColumnNumberSchema,
});

export const CallEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  resolution: ResolutionMethodSchema,
  call_sites: z.array(CallSiteSchema).min(1),
});

export const UnresolvedCallSchema = z.object({
  caller_id: z.string(),
  path: RepoPathSchema,
  callee: z.string(),
  call_site: CallSiteSchema,
  reason: UnresolvedReasonSchema,
});

export const GraphResponseSchema = z.object({
  analysis_id: z.string(),
  nodes: z.array(FunctionNodeSchema),
  edges: z.array(CallEdgeSchema),
  unresolved_calls: z.array(UnresolvedCallSchema),
  unresolved_calls_total: z.number().int().nonnegative(),
  truncated: z.boolean().default(false),
  limitations: z.array(z.string()).default([]),
});

export const CallPathSchema = z.object({
  node_ids: z.array(z.string()).min(1),
  edge_ids: z.array(z.string()),
});

export const PathsResponseSchema = z.object({
  analysis_id: z.string(),
  source: z.string(),
  target: z.string(),
  max_depth: z.number().int(),
  max_paths: z.number().int(),
  paths: z.array(CallPathSchema),
  truncated: z.boolean().default(false),
  limitations: z.array(z.string()).default([]),
});

export const FindingSchema = z.object({
  id: z.string(),
  rule_id: z.string(),
  title: z.string(),
  description: z.string(),
  severity: SeveritySchema,
  confidence: ConfidenceSchema,
  location: SourceReferenceSchema,
  function_id: z.string().nullable().optional(),
  evidence: z.string(),
  review_status: ReviewStatusSchema,
  next_step: z.string(),
  limitations: z.array(z.string()).default([]),
  cwe_id: z.string().nullable().optional(),
});

export const FindingsResponseSchema = z.object({
  analysis_id: z.string(),
  findings: z.array(FindingSchema),
  total: z.number().int().nonnegative(),
  truncated: z.boolean().default(false),
});

export const SourceResponseSchema = z.object({
  analysis_id: z.string(),
  path: RepoPathSchema,
  language: LanguageSchema,
  start_line: LineNumberSchema,
  end_line: z.number().int().nonnegative(),
  total_lines: z.number().int().nonnegative(),
  content: z.string(),
  truncated: z.boolean().default(false),
  redacted_values: z.number().int().nonnegative().default(0),
});

export type AnalysisSummary = z.infer<typeof AnalysisSummarySchema>;
export type GraphResponse = z.infer<typeof GraphResponseSchema>;
export type FunctionNode = z.infer<typeof FunctionNodeSchema>;
export type CallEdge = z.infer<typeof CallEdgeSchema>;
export type UnresolvedCall = z.infer<typeof UnresolvedCallSchema>;
export type PathsResponse = z.infer<typeof PathsResponseSchema>;
export type CallPath = z.infer<typeof CallPathSchema>;
export type FindingsResponse = z.infer<typeof FindingsResponseSchema>;
export type Finding = z.infer<typeof FindingSchema>;
export type SourceResponse = z.infer<typeof SourceResponseSchema>;
export type HealthResponse = z.infer<typeof HealthResponseSchema>;
export type ErrorBody = z.infer<typeof ErrorBodySchema>;
export type SourceReference = z.infer<typeof SourceReferenceSchema>;

export const KNOWN_SEVERITIES = ["info", "low", "medium", "high", "critical"] as const;
export const SEVERITY_RANK: Record<string, number> = {
  info: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

export const KNOWN_FUNCTION_KINDS = [
  "module",
  "function_declaration",
  "function_expression",
  "arrow_function",
  "method",
  "constructor",
] as const;

export const KNOWN_RESOLUTIONS = [
  "same_file",
  "import",
  "this_method",
  "constructor",
  "instance_method",
] as const;
