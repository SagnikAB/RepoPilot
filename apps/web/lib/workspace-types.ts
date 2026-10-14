import type { CallEdge, Finding, FunctionNode, SourceResponse, UnresolvedCall } from "./types";

export type WorkspaceTab = "graph" | "findings" | "unresolved" | "paths" | "investigate";

export type SourceTarget = {
  path: string;
  start_line: number;
  end_line: number;
  highlight_start: number;
  highlight_end: number;
  label: string;
};

export type Selection =
  | { kind: "node"; node: FunctionNode }
  | { kind: "edge"; edge: CallEdge }
  | { kind: "finding"; finding: Finding }
  | { kind: "unresolved"; call: UnresolvedCall };

export type SourceState =
  | { status: "idle" }
  | { status: "loading"; target: SourceTarget }
  | { status: "ready"; target: SourceTarget; data: SourceResponse }
  | { status: "error"; target: SourceTarget; message: string };
