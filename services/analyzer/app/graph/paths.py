"""Bounded, deterministic search for call paths between two functions.

Paths are *simple* (no function repeats), so cycles cannot cause unbounded
traversal. Search is breadth-first: shorter paths come first, and paths of the
same length are ordered by their node IDs. Every search is bounded by
``max_depth`` (edges per path), ``max_paths`` and ``max_expansions``.

A path means each function contains a resolved call to the next. It does not
prove that the path executes at runtime, that data flows along it, or that
anything is exploitable.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DEFAULT_MAX_DEPTH = 8
MAX_DEPTH_LIMIT = 20
DEFAULT_MAX_PATHS = 10
MAX_PATHS_LIMIT = 100
DEFAULT_MAX_EXPANSIONS = 200_000

Successors = Mapping[str, Sequence[tuple[str, str]]]  # node -> [(next node, edge id)]
Predecessors = Mapping[str, Sequence[str]]


@dataclass(frozen=True, slots=True)
class FoundPath:
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PathSearchResult:
    paths: list[FoundPath]
    truncated: bool  # more paths may exist (max_paths or expansion budget reached)
    budget_exhausted: bool
    expansions: int


def find_paths(
    successors: Successors,
    predecessors: Predecessors,
    source: str,
    target: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_paths: int = DEFAULT_MAX_PATHS,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
) -> PathSearchResult:
    """Find up to ``max_paths`` simple paths from ``source`` to ``target``.

    The caller must check that both IDs exist. ``source == target`` yields the
    single zero-length path; cycles through the source are not enumerated.
    """
    if max_depth < 1 or max_paths < 1 or max_expansions < 1:
        raise ValueError("max_depth, max_paths and max_expansions must be positive")
    if source == target:
        return PathSearchResult([FoundPath((source,), ())], False, False, 0)

    distance = _distances_to(target, predecessors, max_depth)
    if source not in distance:
        return PathSearchResult([], False, False, 0)

    found: list[FoundPath] = []
    queue: deque[tuple[tuple[str, ...], tuple[str, ...]]] = deque([((source,), ())])
    expansions = 0
    budget_exhausted = False
    while queue:
        if expansions >= max_expansions:
            budget_exhausted = True
            break
        nodes, edges = queue.popleft()
        expansions += 1
        for next_node, edge in successors.get(nodes[-1], ()):
            remaining = distance.get(next_node)
            if remaining is None or next_node in nodes:
                continue  # cannot reach the target, or would revisit (cycle)
            if len(edges) + 1 + remaining > max_depth:
                continue  # even the shortest continuation is too long
            path = ((*nodes, next_node), (*edges, edge))
            if next_node == target:
                found.append(FoundPath(*path))
                if len(found) > max_paths:
                    break
            else:
                queue.append(path)
        if len(found) > max_paths:
            break

    found.sort(key=lambda p: (len(p.edge_ids), p.node_ids))
    truncated = budget_exhausted or len(found) > max_paths
    return PathSearchResult(found[:max_paths], truncated, budget_exhausted, expansions)


def reachable_within(successors: Successors, source: str, max_depth: int) -> set[str]:
    """Functions reachable from ``source`` in at most ``max_depth`` resolved calls."""
    seen = {source}
    frontier = [source]
    for _ in range(max_depth):
        next_frontier = []
        for node in frontier:
            for next_node, _edge in successors.get(node, ()):
                if next_node not in seen:
                    seen.add(next_node)
                    next_frontier.append(next_node)
        if not next_frontier:
            break
        frontier = next_frontier
    return seen


def _distances_to(target: str, predecessors: Predecessors, max_depth: int) -> dict[str, int]:
    """Shortest edge count from each node to ``target`` (reverse BFS, bounded)."""
    distance = {target: 0}
    frontier = [target]
    for depth in range(1, max_depth + 1):
        next_frontier = []
        for node in frontier:
            for previous in predecessors.get(node, ()):
                if previous not in distance:
                    distance[previous] = depth
                    next_frontier.append(previous)
        if not next_frontier:
            break
        frontier = next_frontier
    return distance
