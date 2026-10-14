"use client";

import { FormEvent, useState } from "react";
import { useInvestigation } from "../workspace/InvestigationProvider";

export function PathExplorer() {
  const {
    graph,
    selectedNodeId,
    paths,
    pathsLoading,
    pathsError,
    fetchPaths,
    selectPath,
    selectedPathIndex,
    selectNode,
  } = useInvestigation();
  const [source, setSource] = useState(selectedNodeId ?? "");
  const [target, setTarget] = useState("");

  if (!graph) {
    return <p className="p-3 text-sm text-muted">Call paths require a completed graph.</p>;
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void fetchPaths(source, target);
  }

  return (
    <div className="flex h-full flex-col">
      <form onSubmit={onSubmit} className="space-y-2 border-b border-border px-3 py-2 text-xs">
        <p className="text-muted">
          A path is a possible resolved call chain. It is not proof of runtime execution, data flow, or
          exploitability.
        </p>
        <label className="block">
          Source function
          <select
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 text-sm"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          >
            <option value="">Select source</option>
            {graph.nodes.map((node) => (
              <option key={node.id} value={node.id}>
                {node.qualified_name} ({node.id.slice(0, 10)}…)
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          Target function
          <select
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 text-sm"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          >
            <option value="">Select target</option>
            {graph.nodes.map((node) => (
              <option key={node.id} value={node.id}>
                {node.qualified_name} ({node.id.slice(0, 10)}…)
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={!source || !target || pathsLoading}
          className="rounded-md bg-accent px-3 py-1.5 text-sm text-accent-foreground disabled:opacity-60"
        >
          {pathsLoading ? "Searching…" : "Find paths"}
        </button>
      </form>
      {pathsError ? (
        <p className="p-3 text-sm text-danger">
          {pathsError.code}: {pathsError.message}
        </p>
      ) : null}
      {paths ? (
        <div className="min-h-0 flex-1 overflow-auto p-3 text-sm">
          {paths.truncated ? <p className="text-warn">Path search was truncated.</p> : null}
          {paths.limitations.map((item) => (
            <p key={item} className="text-xs text-muted">
              {item}
            </p>
          ))}
          {paths.paths.length === 0 ? (
            <p className="mt-2">No resolved path exists between these functions.</p>
          ) : (
            <ol className="mt-2 space-y-2">
              {paths.paths.map((path, index) => (
                <li key={path.edge_ids.join("-") || path.node_ids.join("-")}>
                  <button
                    type="button"
                    className={`w-full rounded-md border px-2 py-2 text-left ${
                      selectedPathIndex === index ? "border-ok" : "border-border"
                    }`}
                    onClick={() => selectPath(index)}
                  >
                    Path {index + 1} ({path.node_ids.length} nodes)
                    <ol className="mt-1 space-y-1 font-mono text-[11px]">
                      {path.node_ids.map((id, step) => {
                        const node = graph.nodes.find((item) => item.id === id);
                        return (
                          <li key={`${id}-${step}`}>
                            {node ? (
                              <span
                                role="link"
                                tabIndex={0}
                                className="text-accent"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  selectNode(node);
                                }}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter") {
                                    selectNode(node);
                                  }
                                }}
                              >
                                {node.qualified_name}
                              </span>
                            ) : (
                              <span>{id} (not in current graph window)</span>
                            )}
                          </li>
                        );
                      })}
                    </ol>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      ) : null}
    </div>
  );
}
