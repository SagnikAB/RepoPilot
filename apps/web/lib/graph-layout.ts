import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";
import type { CallEdge, FunctionNode } from "./types";

export const NODE_WIDTH = 240;
export const NODE_HEIGHT = 78;

export function layoutGraph(functions: FunctionNode[], callEdges: CallEdge[]): {
  nodes: Node[];
  edges: Edge[];
} {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "LR", nodesep: 36, ranksep: 72, marginx: 24, marginy: 24 });

  for (const fn of functions) {
    graph.setNode(fn.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of callEdges) {
    graph.setEdge(edge.source, edge.target);
  }
  dagre.layout(graph);

  const nodes: Node[] = functions.map((fn) => {
    const laidOut = graph.node(fn.id);
    return {
      id: fn.id,
      type: "function",
      position: {
        x: laidOut.x - NODE_WIDTH / 2,
        y: laidOut.y - NODE_HEIGHT / 2,
      },
      data: { functionNode: fn },
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    };
  });

  const edges: Edge[] = callEdges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    data: { callEdge: edge },
    type: "smoothstep",
  }));

  return { nodes, edges };
}
