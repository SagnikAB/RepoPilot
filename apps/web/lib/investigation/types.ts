import { z } from "zod";

export const InvestigationCitationSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("finding"), id: z.string() }),
  z.object({ type: z.literal("node"), id: z.string() }),
  z.object({
    type: z.literal("source"),
    path: z.string(),
    start_line: z.number().int().min(1),
    end_line: z.number().int().min(0),
  }),
]);

export const ModelInvestigationSchema = z.object({
  answer: z.string().min(1).max(8000),
  observed_facts: z.array(z.string()).max(20).default([]),
  interpretations: z.array(z.string()).max(20).default([]),
  unknowns: z.array(z.string()).max(20).default([]),
  limitations: z.array(z.string()).max(20).default([]),
  citations: z.array(InvestigationCitationSchema).max(30).default([]),
});

export type InvestigationCitation = z.infer<typeof InvestigationCitationSchema>;
export type ModelInvestigation = z.infer<typeof ModelInvestigationSchema>;

export type EvidenceFinding = {
  id: string;
  rule_id: string;
  title: string;
  description: string;
  severity: string;
  confidence: string;
  location: { path: string; start_line: number; end_line: number };
  function_id: string | null;
  evidence: string;
  next_step: string;
  limitations: string[];
  cwe_id: string | null;
};

export type EvidenceNode = {
  id: string;
  name: string;
  qualified_name: string;
  kind: string;
  path: string;
  start_line: number;
  end_line: number;
};

export type EvidenceSource = {
  path: string;
  start_line: number;
  end_line: number;
  total_lines: number;
  truncated: boolean;
  redacted_values: number;
  content: string;
};

export type EvidencePackage = {
  analysis_id: string;
  repository: { owner: string; name: string; url: string; ref: string | null; commit_sha: string | null };
  warnings: string[];
  graph_limitations: string[];
  graph_truncated: boolean;
  findings_truncated: boolean;
  findings: EvidenceFinding[];
  nodes: EvidenceNode[];
  sources: EvidenceSource[];
};

export type InvestigationSuccess = {
  ok: true;
  analysis_id: string;
  model: string;
  result: ModelInvestigation;
  evidence_counts: { findings: number; nodes: number; sources: number };
};

export type InvestigationFailure = {
  ok: false;
  error: {
    code: string;
    message: string;
  };
};

export type InvestigationResult = InvestigationSuccess | InvestigationFailure;
