"use client";

import { useMemo, useState } from "react";
import { useInvestigation } from "../workspace/InvestigationProvider";

export function UnresolvedCalls() {
  const { graph, selectUnresolved, selectNode } = useInvestigation();
  const [reason, setReason] = useState("");
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    if (!graph) {
      return [];
    }
    const q = query.trim().toLowerCase();
    return graph.unresolved_calls.filter((call) => {
      if (reason && call.reason !== reason) {
        return false;
      }
      if (!q) {
        return true;
      }
      return `${call.callee} ${call.path} ${call.reason}`.toLowerCase().includes(q);
    });
  }, [graph, query, reason]);

  if (!graph) {
    return <p className="p-3 text-sm text-muted">Unresolved calls appear after a completed analysis.</p>;
  }

  const reasons = Array.from(new Set(graph.unresolved_calls.map((call) => call.reason))).sort();

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-border px-3 py-2 text-xs">
        <p>
          Showing {rows.length} of {graph.unresolved_calls.length} (total {graph.unresolved_calls_total}).
          Unresolved calls are not confirmed edges.
        </p>
        <div className="flex flex-wrap gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter callee or path"
            className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
          />
          <select
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
          >
            <option value="">All reasons</option>
            {reasons.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </div>
      <ul className="min-h-0 flex-1 overflow-auto text-sm">
        {rows.map((call, index) => {
          const caller = graph.nodes.find((node) => node.id === call.caller_id);
          return (
            <li key={`${call.caller_id}-${call.path}-${call.call_site.line}-${call.call_site.column}-${index}`} className="border-b border-border px-3 py-2">
              <button type="button" className="w-full text-left" onClick={() => selectUnresolved(call)}>
                <p className="font-mono text-xs">{call.callee}</p>
                <p className="text-[11px] text-muted">
                  {call.path}:{call.call_site.line}:{call.call_site.column} · {call.reason}
                </p>
                {caller ? (
                  <p className="text-[11px] text-muted">caller {caller.qualified_name}</p>
                ) : (
                  <p className="text-[11px] text-muted">caller {call.caller_id}</p>
                )}
              </button>
              {caller ? (
                <button
                  type="button"
                  className="mt-1 text-[11px] text-accent"
                  onClick={() => selectNode(caller)}
                >
                  Select caller node
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
