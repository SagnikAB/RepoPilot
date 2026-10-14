"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { FunctionNode } from "@/lib/types";

export type FunctionFlowData = { functionNode: FunctionNode; selected?: boolean; onPath?: boolean };

export function FunctionFlowNode({ data, selected }: NodeProps) {
  const node = (data as FunctionFlowData).functionNode;
  const onPath = Boolean((data as FunctionFlowData).onPath);
  return (
    <div
      className={`rounded-md border bg-surface px-2.5 py-1.5 text-left shadow-sm ${
        selected ? "border-accent" : onPath ? "border-ok" : "border-border"
      }`}
      style={{ width: 240 }}
    >
      <Handle type="target" position={Position.Left} />
      <p className="truncate font-mono text-xs font-medium">{node.name}</p>
      <p className="truncate text-[11px] text-muted">{node.qualified_name}</p>
      <p className="truncate text-[10px] text-muted">
        {node.kind} · {node.path}:{node.start_line}
      </p>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
