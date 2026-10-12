"""Graph construction: integrity, determinism, aggregation, limits, malformed input."""

from __future__ import annotations

import dataclasses

from app.graph.builder import CallGraph, build_call_graph
from app.models.graph import CallSite
from app.models.ids import edge_id, function_id
from app.parsers.types import CalleeKind, CallRecord, ExportRecord, FileExtraction
from tests.helpers import build_graph, describe_edges, extract, make_settings

SOURCES = {
    "src/a.ts": 'import { b } from "./b";\nexport function a() { b(); b(); a2(); }\n'
    "function a2() { a(); }\n",
    "src/b.ts": 'import { a } from "./a";\nexport function b() { a(); }\n',
}


def _files() -> list[FileExtraction]:
    return [extract(path, code) for path, code in SOURCES.items()]


def _dump(graph: CallGraph) -> list[list[dict[str, object]]]:
    return [
        [n.model_dump(mode="json") for n in graph.nodes.values()],
        [e.model_dump(mode="json") for e in graph.edges],
        [u.model_dump(mode="json") for u in graph.unresolved],
    ]


def test_every_edge_references_existing_nodes_and_stable_ids() -> None:
    graph = build_call_graph(_files(), make_settings())

    for edge in graph.edges:
        assert edge.source in graph.nodes and edge.target in graph.nodes
        assert edge.id == edge_id(edge.source, edge.target)
    for node in graph.nodes.values():
        assert node.id == function_id(
            node.path, node.qualified_name, node.start_line, node.start_column
        )
    assert {u.caller_id for u in graph.unresolved} <= set(graph.nodes)


def test_cycles_and_duplicate_call_sites_collapse_into_one_edge() -> None:
    graph = build_call_graph(_files(), make_settings())

    assert describe_edges(graph) == {
        ("src/a.ts:a", "src/b.ts:b", "import"),
        ("src/a.ts:a", "src/a.ts:a2", "same_file"),
        ("src/a.ts:a2", "src/a.ts:a", "same_file"),
        ("src/b.ts:b", "src/a.ts:a", "import"),
    }
    [to_b] = [e for e in graph.edges if graph.nodes[e.target].name == "b"]
    assert [(s.line, s.column) for s in to_b.call_sites] == [(2, 23), (2, 28)]
    assert len({(e.source, e.target) for e in graph.edges}) == len(graph.edges)


def test_graph_is_identical_regardless_of_input_order() -> None:
    files = _files()
    shuffled = files[::-1]

    first = build_call_graph(files, make_settings())
    second = build_call_graph(shuffled, make_settings())

    assert _dump(first) == _dump(second)
    positions = [(n.path, n.start_line, n.start_column, n.id) for n in first.nodes.values()]
    assert positions == sorted(positions)


def test_unresolved_calls_never_become_edges() -> None:
    graph = build_graph({"src/x.js": "function f(g) { g(); unknown(); f.call(); }\n"})

    assert graph.edges == []
    assert len(graph.unresolved) == 3
    assert graph.stats.calls_total == 3 and graph.stats.call_sites_resolved == 0


def test_node_and_edge_limits_truncate_deterministically() -> None:
    code = (
        "".join(f"function f{i}() {{ f{i + 1}(); }}\n" for i in range(20)) + "function f20() {}\n"
    )

    by_nodes = build_graph({"src/chain.js": code}, max_graph_nodes=5)
    by_edges = build_graph({"src/chain.js": code}, max_graph_edges=3)

    assert by_nodes.truncated and len(by_nodes.nodes) == 5
    assert all(e.source in by_nodes.nodes and e.target in by_nodes.nodes for e in by_nodes.edges)
    assert len(by_nodes.edges) == 4
    assert by_edges.truncated and len(by_edges.edges) == 3
    assert any("truncated" in d for d in by_nodes.diagnostics)


# -- malformed or incomplete parser output -------------------------------------------------


def test_call_with_unknown_caller_is_ignored_with_a_diagnostic() -> None:
    broken = extract("src/a.js", "function f() { f(); }\n")
    bogus = CallRecord(
        "fn_0000000000000000",
        "f",
        CalleeKind.IDENTIFIER,
        "f",
        None,
        CallSite(line=1, column=1),
        None,
    )
    broken.calls.append(bogus)

    graph = build_call_graph([broken], make_settings())

    assert len(graph.edges) == 1
    assert any("unknown caller" in d for d in graph.diagnostics)


def test_export_pointing_at_missing_function_stays_unresolved() -> None:
    lib = extract("src/lib.js", "export function real() {}\n")
    lib.exports.append(ExportRecord("ghost", None, "fn_ffffffffffffffff", None, 1))
    app = extract(
        "src/app.js", 'import { ghost, real } from "./lib";\nfunction run() { ghost(); real(); }\n'
    )

    graph = build_call_graph([lib, app], make_settings())

    assert describe_edges(graph) == {("src/app.js:run", "src/lib.js:real", "import")}
    assert {u.callee: u.reason.value for u in graph.unresolved} == {"ghost": "unresolved_import"}


def test_duplicate_files_and_function_ids_are_ignored_with_diagnostics() -> None:
    first = extract("src/a.js", "function f() {}\n")
    duplicate_file = extract("src/a.js", "function g() {}\n")
    other = extract("src/b.js", "function h() {}\n")
    other.functions.append(dataclasses.replace(other.functions[0]))  # same id twice

    graph = build_call_graph([first, duplicate_file, other], make_settings())

    assert sorted(n.name for n in graph.nodes.values()) == ["f", "h"]  # first file wins
    assert any("Duplicate file" in d for d in graph.diagnostics)
    assert any("Duplicate function id" in d for d in graph.diagnostics)


def test_imports_into_unparsed_files_are_unresolved_and_noted() -> None:
    app = extract("src/app.js", 'import { x } from "./failed";\nfunction run() { x(); }\n')

    graph = build_call_graph([app], make_settings(), unparsed_paths=["src/failed.js"])

    assert {u.callee: u.reason.value for u in graph.unresolved} == {"x": "unresolved_import"}
    assert any("could not be parsed" in limitation for limitation in graph.limitations)


def test_empty_input() -> None:
    graph = build_call_graph([], make_settings())

    assert graph.nodes == {} and graph.edges == [] and graph.unresolved == []
