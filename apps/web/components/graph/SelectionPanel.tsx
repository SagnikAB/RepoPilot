"use client";

import { useInvestigation } from "../workspace/InvestigationProvider";

export function SelectionPanel() {
  const { graph, selectedNodeId, selectedEdgeId, selectNode } = useInvestigation();
  if (!graph) {
    return null;
  }
  const node = graph.nodes.find((item) => item.id === selectedNodeId);
  const edge = graph.edges.find((item) => item.id === selectedEdgeId);
  if (!node && !edge) {
    return <p className="p-3 text-xs text-muted">Select a graph node or resolved edge.</p>;
  }
  const target = edge ? graph.nodes.find((item) => item.id === edge.target) : null;
  return (
    <div className="space-y-2 p-3 text-xs">
      {node ? (
        <div>
          <p className="font-medium">{node.qualified_name}</p>
          <p className="font-mono text-muted">{node.id}</p>
          <p>
            {node.kind} · {node.language} · {node.path}:{node.start_line}–{node.end_line}
          </p>
          <p>
            exported: {String(node.is_exported)} · anonymous: {String(node.is_anonymous)}
          </p>
        </div>
      ) : null}
      {edge ? (
        <div>
          <p className="font-medium">Resolved edge {edge.resolution}</p>
          <p className="font-mono text-muted">{edge.id}</p>
          <ul>
            {edge.call_sites.map((site) => (
              <li key={`${site.line}:${site.column}`}>
                line {site.line}, column {site.column}
              </li>
            ))}
          </ul>
          {target ? (
            <button type="button" className="text-accent" onClick={() => selectNode(target)}>
              Open target {target.qualified_name}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
