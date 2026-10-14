"""Bounded path search on hand-built adjacency (no parser involved)."""

from __future__ import annotations

import itertools
import time
from collections import defaultdict

import pytest

from app.graph.paths import find_paths, reachable_within

Edges = list[tuple[str, str]]


def _graph(edges: Edges) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[str]]]:
    successors: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    predecessors: defaultdict[str, list[str]] = defaultdict(list)
    for source, target in sorted(edges):
        successors[source].append((target, f"{source}>{target}"))
        predecessors[target].append(source)
    return dict(successors), dict(predecessors)


def _search(
    edges: Edges, source: str, target: str, *, max_depth: int = 8, max_paths: int = 10
) -> list[list[str]]:
    result = find_paths(*_graph(edges), source, target, max_depth=max_depth, max_paths=max_paths)
    return [list(p.node_ids) for p in result.paths]


DIAMOND = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("a", "d")]


def test_shortest_first_then_by_node_ids() -> None:
    assert _search(DIAMOND, "a", "d") == [["a", "d"], ["a", "b", "d"], ["a", "c", "d"]]


def test_edge_ids_connect_consecutive_nodes() -> None:
    result = find_paths(*_graph(DIAMOND), "a", "d")

    for path in result.paths:
        assert len(path.edge_ids) == len(path.node_ids) - 1
        for i, edge in enumerate(path.edge_ids):
            assert edge == f"{path.node_ids[i]}>{path.node_ids[i + 1]}"


def test_source_equal_to_target_is_the_zero_length_path() -> None:
    result = find_paths(*_graph([("a", "a"), ("a", "b"), ("b", "a")]), "a", "a")

    assert [(p.node_ids, p.edge_ids) for p in result.paths] == [(("a",), ())]
    assert not result.truncated


def test_no_path() -> None:
    result = find_paths(*_graph([("a", "b"), ("c", "d")]), "a", "d")

    assert result.paths == [] and not result.truncated


def test_unknown_nodes_simply_have_no_paths() -> None:
    assert _search(DIAMOND, "zzz", "d") == []
    assert _search(DIAMOND, "a", "zzz") == []


def test_cycles_terminate_and_paths_are_simple() -> None:
    cyclic = [("a", "b"), ("b", "a"), ("b", "c"), ("c", "b"), ("c", "d"), ("d", "a")]

    paths = _search(cyclic, "a", "d", max_depth=20, max_paths=100)

    assert paths == [["a", "b", "c", "d"]]
    assert all(len(set(p)) == len(p) for p in paths)


def test_self_loop_is_ignored_for_other_targets() -> None:
    assert _search([("a", "a"), ("a", "b")], "a", "b") == [["a", "b"]]


def test_max_depth_limits_path_length() -> None:
    chain = [(str(i), str(i + 1)) for i in range(10)]

    assert _search(chain, "0", "10", max_depth=10) == [[str(i) for i in range(11)]]
    assert _search(chain, "0", "10", max_depth=9) == []


def test_max_paths_truncates_deterministically() -> None:
    fan = [("s", f"m{i}") for i in range(5)] + [(f"m{i}", "t") for i in range(5)]

    first = find_paths(*_graph(fan), "s", "t", max_paths=2)
    again = find_paths(*_graph(fan), "s", "t", max_paths=2)
    exact = find_paths(*_graph(fan), "s", "t", max_paths=5)

    assert [p.node_ids for p in first.paths] == [("s", "m0", "t"), ("s", "m1", "t")]
    assert first.truncated and first.paths == again.paths
    assert len(exact.paths) == 5 and not exact.truncated


def test_dense_graph_is_bounded_by_the_expansion_budget() -> None:
    # 12 layers of 6 fully connected nodes: about 6**10 simple paths exist.
    layers = [[f"L{layer}n{i}" for i in range(6)] for layer in range(12)]
    edges = [(u, v) for a, b in itertools.pairwise(layers) for u in a for v in b]
    edges += [("src", n) for n in layers[0]] + [(n, "dst") for n in layers[-1]]
    started = time.monotonic()

    result = find_paths(
        *_graph(edges), "src", "dst", max_depth=20, max_paths=100, max_expansions=5_000
    )

    assert time.monotonic() - started < 5
    assert result.truncated and result.budget_exhausted
    assert result.expansions == 5_000


def test_invalid_limits_are_rejected() -> None:
    with pytest.raises(ValueError):
        find_paths(*_graph(DIAMOND), "a", "d", max_depth=0)
    with pytest.raises(ValueError):
        find_paths(*_graph(DIAMOND), "a", "d", max_paths=0)


def test_reachable_within_depth() -> None:
    successors, _ = _graph([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")])

    assert reachable_within(successors, "a", 1) == {"a", "b"}
    assert reachable_within(successors, "a", 3) == {"a", "b", "c", "d"}
