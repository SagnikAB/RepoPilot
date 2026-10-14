"""Build the directed call graph from parser output and resolver results."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.config import Settings
from app.graph.resolver import Resolver
from app.models.analysis import LimitReached
from app.models.graph import CallEdge, CallSite, FunctionNode, ResolutionMethod, UnresolvedCall
from app.models.ids import edge_id
from app.parsers.types import FileExtraction

logger = logging.getLogger(__name__)

BASE_LIMITATIONS = (
    "Only statically resolvable calls are edges; absence of an edge does not prove absence "
    "of a call.",
    "Edges are call relationships, not data flow.",
    "Not resolved: dynamic dispatch, callbacks and higher-order functions, inherited methods, "
    "tsconfig path aliases and calls into external packages.",
)

# Deterministic tie-break when one (source, target) pair is reached in several ways.
_METHOD_ORDER = {method: rank for rank, method in enumerate(ResolutionMethod)}


@dataclass(frozen=True, slots=True)
class ResolutionStats:
    calls_total: int
    call_sites_resolved: int
    implicit_constructor_calls: int
    unresolved_by_reason: dict[str, int]
    resolved_by_method: dict[str, int]


@dataclass(slots=True)
class CallGraph:
    """An immutable-by-convention call graph for one analysis run."""

    nodes: dict[str, FunctionNode]  # ordered by (path, start_line, start_column, id)
    edges: list[CallEdge]  # ordered by (source order, target order)
    unresolved: list[UnresolvedCall]  # ordered by (path, line, column, callee)
    successors: dict[str, list[tuple[str, str]]]  # source -> [(target, edge id)], target order
    predecessors: dict[str, list[str]]  # target -> sources
    unresolved_by_caller: Counter[str]
    stats: ResolutionStats
    diagnostics: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: list(BASE_LIMITATIONS))
    truncated: bool = False
    limits_reached: list[LimitReached] = field(default_factory=list)


def build_call_graph(
    files: Sequence[FileExtraction],
    settings: Settings,
    *,
    unparsed_paths: Sequence[str] = (),
) -> CallGraph:
    diagnostics: list[str] = []
    limits: list[LimitReached] = []
    valid_files = _unique_files(files, diagnostics)

    nodes_by_id: dict[str, FunctionNode] = {}
    for extraction in valid_files:
        for record in extraction.functions:
            if record.node.id in nodes_by_id:
                diagnostics.append(f"Duplicate function id {record.node.id} ignored")
                continue
            if record.node.path != extraction.path:
                diagnostics.append(f"Function {record.node.id} has a mismatched path; ignored")
                continue
            nodes_by_id[record.node.id] = record.node

    ordered = sorted(
        nodes_by_id.values(), key=lambda n: (n.path, n.start_line, n.start_column, n.id)
    )
    truncated = len(ordered) > settings.max_graph_nodes
    if truncated:
        diagnostics.append(f"Graph truncated to {settings.max_graph_nodes} functions")
        limits.append(LimitReached(limit="max_graph_nodes", value=settings.max_graph_nodes))
        ordered = ordered[: settings.max_graph_nodes]
    nodes = {node.id: node for node in ordered}
    rank = {node_id: position for position, node_id in enumerate(nodes)}

    resolver = Resolver(valid_files)
    sites: defaultdict[tuple[str, str], list[CallSite]] = defaultdict(list)
    methods: dict[tuple[str, str], ResolutionMethod] = {}
    unresolved: list[UnresolvedCall] = []
    calls_total = resolved_sites = implicit = 0
    by_method: Counter[str] = Counter()

    for extraction in valid_files:
        for call in extraction.calls:
            calls_total += 1
            if call.caller_id not in nodes:
                if call.caller_id not in nodes_by_id:
                    diagnostics.append(
                        f"Call at {extraction.path}:{call.site.line} has an unknown caller; ignored"
                    )
                continue  # caller dropped by truncation or malformed input
            result = resolver.resolve(extraction.path, call)
            if result.implicit:
                implicit += 1
                continue
            if result.target_id is not None and result.method is not None:
                if result.target_id not in nodes:
                    if result.target_id not in nodes_by_id:
                        diagnostics.append(f"Resolved target {result.target_id} missing; ignored")
                    continue
                key = (call.caller_id, result.target_id)
                sites[key].append(call.site)
                previous = methods.get(key)
                if previous is None or _METHOD_ORDER[result.method] < _METHOD_ORDER[previous]:
                    methods[key] = result.method
                resolved_sites += 1
                by_method[result.method.value] += 1
                continue
            if result.reason is None:
                continue  # unreachable: a CallResolution always carries one outcome
            unresolved.append(
                UnresolvedCall(
                    caller_id=call.caller_id,
                    path=extraction.path,
                    callee=call.callee,
                    call_site=call.site,
                    reason=result.reason,
                )
            )

    edge_keys = sorted(sites, key=lambda k: (rank[k[0]], rank[k[1]]))
    if len(edge_keys) > settings.max_graph_edges:
        diagnostics.append(f"Graph truncated to {settings.max_graph_edges} edges")
        limits.append(LimitReached(limit="max_graph_edges", value=settings.max_graph_edges))
        edge_keys = edge_keys[: settings.max_graph_edges]
        truncated = True
    edges = [
        CallEdge(
            id=edge_id(source, target),
            source=source,
            target=target,
            resolution=methods[(source, target)],
            call_sites=sorted(set(sites[(source, target)]), key=lambda s: (s.line, s.column)),
        )
        for source, target in edge_keys
    ]

    successors: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    predecessors: defaultdict[str, list[str]] = defaultdict(list)
    for edge in edges:
        successors[edge.source].append((edge.target, edge.id))
        predecessors[edge.target].append(edge.source)

    unresolved.sort(key=lambda u: (u.path, u.call_site.line, u.call_site.column, u.callee))
    limitations = list(BASE_LIMITATIONS)
    if unparsed_paths:
        limitations.append(
            f"{len(unparsed_paths)} file(s) could not be parsed; calls into them are unresolved."
        )
    if diagnostics:
        logger.warning("Call graph built with %d diagnostics", len(diagnostics))

    return CallGraph(
        nodes=nodes,
        edges=edges,
        unresolved=unresolved,
        successors=dict(successors),
        predecessors=dict(predecessors),
        unresolved_by_caller=Counter(u.caller_id for u in unresolved),
        stats=ResolutionStats(
            calls_total=calls_total,
            call_sites_resolved=resolved_sites,
            implicit_constructor_calls=implicit,
            unresolved_by_reason=dict(Counter(u.reason.value for u in unresolved)),
            resolved_by_method=dict(by_method),
        ),
        diagnostics=diagnostics,
        limitations=limitations,
        truncated=truncated,
        limits_reached=limits,
    )


def _unique_files(files: Sequence[FileExtraction], diagnostics: list[str]) -> list[FileExtraction]:
    seen: set[str] = set()
    unique: list[FileExtraction] = []
    for extraction in sorted(files, key=lambda f: f.path):
        if extraction.path in seen:
            diagnostics.append(f"Duplicate file {extraction.path} ignored")
            continue
        seen.add(extraction.path)
        unique.append(extraction)
    return unique
