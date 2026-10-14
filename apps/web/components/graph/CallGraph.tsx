"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { layoutGraph } from "@/lib/graph-layout";
import { useInvestigation } from "../workspace/InvestigationProvider";
import { FunctionFlowNode } from "./FunctionFlowNode";

const nodeTypes = { function: FunctionFlowNode };

function GraphCanvas() {
  const {
    graph,
    graphLoading,
    selectedNodeId,
    selectedEdgeId,
    highlightedPathNodeIds,
    highlightedPathEdgeIds,
    selectNode,
    selectEdge,
    graphPathPrefix,
    setGraphPathPrefix,
  } = useInvestigation();
  const { fitView } = useReactFlow();
  const [query, setQuery] = useState("");

  const laidOut = useMemo(() => {
    if (!graph) {
      return { nodes: [] as Node[], edges: [] as Edge[] };
    }
    return layoutGraph(graph.nodes, graph.edges);
  }, [graph]);

  const nodes = useMemo(
    () =>
      laidOut.nodes.map((node) => ({
        ...node,
        selected: node.id === selectedNodeId,
        data: {
          ...node.data,
          onPath: highlightedPathNodeIds.includes(node.id),
        },
      })),
    [highlightedPathNodeIds, laidOut.nodes, selectedNodeId],
  );

  const edges = useMemo(
    () =>
      laidOut.edges.map((edge) => ({
        ...edge,
        selected: edge.id === selectedEdgeId,
        style: {
          stroke: highlightedPathEdgeIds.includes(edge.id)
          ? "var(--ok)"
            : edge.id === selectedEdgeId
            ? "var(--accent)"
            : "var(--border)",
          strokeWidth: highlightedPathEdgeIds.includes(edge.id) ? 2.5 : 1.25,
        },
      })),
    [highlightedPathEdgeIds, laidOut.edges, selectedEdgeId],
  );

  useEffect(() => {
    if (nodes.length > 0) {
      const frame = window.requestAnimationFrame(() => fitView({ padding: 0.2 }));
      return () => window.cancelAnimationFrame(frame);
    }
    return undefined;
  }, [fitView, graph?.analysis_id, graphPathPrefix, nodes.length]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !graph) {
      return [];
    }
    return graph.nodes.filter((node) =>
      `${node.name} ${node.qualified_name} ${node.path}`.toLowerCase().includes(q),
    );
  }, [graph, query]);

  if (graphLoading) {
    return <p className="p-4 text-sm text-muted">Loading call graph…</p>;
  }
  if (!graph) {
    return <p className="p-4 text-sm text-muted">No graph for this analysis.</p>;
  }
  if (graph.nodes.length === 0) {
    return (
      <div className="p-4 text-sm text-muted">
        No function nodes were returned. The repository may have no supported files, or the current path
        filter excluded them.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[22rem] flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-xs">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search functions"
          className="w-48 rounded-md border border-border bg-surface px-2 py-1 text-sm"
        />
        <label className="flex items-center gap-1 text-muted">
          path_prefix
          <input
            value={graphPathPrefix}
            onChange={(event) => setGraphPathPrefix(event.target.value.trim())}
            placeholder="src"
            className="w-40 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text"
          />
        </label>
        <span className="text-muted">
          {graph.nodes.length} nodes · {graph.edges.length} edges
        </span>
        {graph.truncated ? <span className="text-warn">Graph truncated (max_nodes)</span> : null}
      </div>
      {graph.limitations.length > 0 ? (
        <ul className="border-b border-border bg-surface-2 px-3 py-2 text-[11px] text-muted">
          {graph.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {query && matches.length > 0 ? (
        <div className="flex max-h-24 flex-wrap gap-1 overflow-auto border-b border-border px-3 py-1">
          {matches.slice(0, 12).map((node) => (
            <button
              key={node.id}
              type="button"
              className="rounded border border-border px-1.5 py-0.5 font-mono text-[11px]"
              onClick={() => selectNode(node)}
            >
              {node.qualified_name}
            </button>
          ))}
        </div>
      ) : null}
      <div className="min-h-0 flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          minZoom={0.2}
          maxZoom={1.6}
          nodesDraggable={false}
          onNodeClick={(_, node) => {
            const fn = graph.nodes.find((item) => item.id === node.id);
            if (fn) {
              selectNode(fn);
            }
          }}
          onEdgeClick={(_, edge) => {
            const call = graph.edges.find((item) => item.id === edge.id);
            if (call) {
              selectEdge(call);
            }
          }}
        >
          <Background />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>
    </div>
  );
}

export function CallGraph() {
  return (
    <ReactFlowProvider>
      <GraphCanvas />
    </ReactFlowProvider>
  );
}
