from __future__ import annotations

import json
from pathlib import Path

from app.models.graph import FunctionKind, UnresolvedReason
from app.models.ids import function_id
from app.parsers.service import parse_repository
from app.parsers.types import CalleeKind, FileExtraction, ImportKind
from tests.helpers import FIXTURE_REPOS, TESTS_DIR, extract, make_settings

DOCS_FIXTURES = TESTS_DIR.parent / "docs" / "fixtures"


def _qualified(result: FileExtraction) -> list[tuple[str, str]]:
    return [(r.node.qualified_name, r.node.kind.value) for r in result.functions]


def _name_of(result: FileExtraction, fid: str) -> str:
    return next(r.node.qualified_name for r in result.functions if r.node.id == fid)


# -- functions -------------------------------------------------------------------


def test_function_kinds_and_qualified_names() -> None:
    result = extract(
        "src/kinds.js",
        """function decl() {}
function* gen() {}
const arrow = () => 1;
const expr = function inner() {};
let named = function own() {};
class Svc {
  constructor() {}
  method() {}
  static create() {}
  get value() { return 1; }
  #secret() {}
  handler = () => 1;
}
const obj = { m() {}, p: function () {}, q: () => 2, "quoted key": () => 3 };
function outer() { function nested() {} return () => nested; }
""",
    )

    assert _qualified(result) == [
        ("decl", "function_declaration"),
        ("gen", "function_declaration"),
        ("arrow", "arrow_function"),
        ("expr", "function_expression"),
        ("named", "function_expression"),
        ("Svc.constructor", "constructor"),
        ("Svc.method", "method"),
        ("Svc.create", "method"),
        ("Svc.value", "method"),
        ("Svc.#secret", "method"),
        ("Svc.handler", "arrow_function"),
        ("obj.m", "method"),
        ("obj.p", "function_expression"),
        ("obj.q", "arrow_function"),
        ("obj.quoted key", "arrow_function"),
        ("outer", "function_declaration"),
        ("outer.nested", "function_declaration"),
        ("outer.<anonymous>", "arrow_function"),
    ]
    anonymous = [r.node for r in result.functions if r.node.is_anonymous]
    assert [(n.name, n.qualified_name) for n in anonymous] == [("<anonymous>", "outer.<anonymous>")]


def test_exact_source_ranges_and_ids() -> None:
    result = extract(
        "src/ranges.ts",
        "// header\n\nexport async function load(id: string) {\n  return id;\n}\n",
    )

    node = result.functions[0].node
    assert (node.start_line, node.end_line, node.start_column) == (3, 5, 8)
    assert node.id == function_id("src/ranges.ts", "load", 3, 8)
    assert node.path == "src/ranges.ts"
    assert node.language.value == "typescript"
    assert result.line_count == 5


def test_columns_count_characters_not_bytes() -> None:
    result = extract("src/u.js", "const é = '日本'; function ü() { go(); }\n")

    node = result.functions[0].node
    assert node.start_column == 17  # byte column would be 22
    call = result.calls[0]
    assert (call.site.line, call.site.column) == (1, 32)


def test_duplicate_names_get_distinct_ids() -> None:
    a = extract("src/a.js", "function handler() {}\nclass A { run() {} }\nclass B { run() {} }\n")
    b = extract("src/b.js", "function handler() {}\n")
    c = extract("src/c.js", "[1].map(() => 1); [2].map(() => 2);\n")

    ids = [r.node.id for r in a.functions + b.functions + c.functions]
    assert len(ids) == len(set(ids))
    assert [r.node.name for r in a.functions] == ["handler", "run", "run"]
    assert [r.node.qualified_name for r in c.functions[1:]] == ["<anonymous>", "<anonymous>"]


def test_overloads_signatures_and_interfaces_are_not_functions() -> None:
    result = extract(
        "src/types.ts",
        """function ov(a: string): void;
function ov(a: any) {}
declare function ambient(): void;
interface I { f(): void }
type T = () => void;
abstract class D { abstract z(): void; m(): void {} }
""",
    )

    assert _qualified(result) == [("ov", "function_declaration"), ("D.m", "method")]


def test_this_binding_for_methods_and_arrows() -> None:
    result = extract(
        "src/this.js",
        """class Svc {
  run() { const cb = () => this.x(); function plain() {} }
  static make() {}
  field = () => this.x();
}
""",
    )
    this_of = {r.node.qualified_name: r.this_class for r in result.functions}

    assert this_of == {
        "Svc.run": "Svc",
        "Svc.run.cb": "Svc",  # arrows inherit `this`
        "Svc.run.plain": None,  # function declarations rebind `this`
        "Svc.make": None,  # static: `this` is the constructor
        "Svc.field": "Svc",
    }


def test_parent_scope_and_binding_names() -> None:
    result = extract(
        "src/scope.js",
        "function outer(a, { b, c: d }, [e, ...f], g = 1) {\n"
        "  const inner = () => 1;\n  let value = 2;\n  try {} catch (err) {}\n}\n",
    )
    records = {r.node.qualified_name: r for r in result.functions}

    assert records["outer"].parent_id == result.module_id
    assert records["outer"].binding_name == "outer"
    assert records["outer.inner"].parent_id == records["outer"].node.id
    assert records["outer.inner"].binding_name == "inner"
    assert result.scope_locals[records["outer"].node.id] == frozenset(
        {"a", "b", "d", "e", "f", "g", "value", "err"}
    )


# -- module node -------------------------------------------------------------------


def test_module_node_only_when_top_level_calls_exist() -> None:
    quiet = extract("src/quiet.js", "function f() { g(); }\n")
    noisy = extract("src/noisy.js", "function f() {}\nf();\n")

    assert all(r.node.kind is not FunctionKind.MODULE for r in quiet.functions)
    module = noisy.functions[0].node
    assert module.kind is FunctionKind.MODULE
    assert (module.name, module.start_line, module.end_line) == ("<module>", 1, 2)
    assert noisy.calls[0].caller_id == module.id == noisy.module_id


# -- calls ---------------------------------------------------------------------------


def test_call_classification() -> None:
    result = extract(
        "src/calls.js",
        """function f() {
  helper();
  this.method();
  ns.run();
  a.b.c();
  arr[0]();
  (function () {})();
  getFn()();
  new Service();
  new ns.Thing();
  maybe?.();
  require("./x");
  import("./y");
}
""",
    )
    shapes = [(c.callee, c.kind, c.name, c.receiver, c.unresolved_reason) for c in result.calls]

    assert shapes == [
        ("helper", CalleeKind.IDENTIFIER, "helper", None, None),
        ("this.method", CalleeKind.THIS_MEMBER, "method", None, None),
        ("ns.run", CalleeKind.MEMBER, "run", "ns", None),
        ("a.b.c", CalleeKind.OTHER, "c", None, UnresolvedReason.MEMBER_CALL),
        ("arr[0]", CalleeKind.OTHER, None, None, UnresolvedReason.DYNAMIC_CALL),
        ("(function () {})", CalleeKind.OTHER, None, None, UnresolvedReason.UNSUPPORTED_SYNTAX),
        ("getFn()", CalleeKind.OTHER, None, None, UnresolvedReason.DYNAMIC_CALL),
        ("getFn", CalleeKind.IDENTIFIER, "getFn", None, None),
        ("Service", CalleeKind.NEW, "Service", None, None),
        ("ns.Thing", CalleeKind.OTHER, None, None, UnresolvedReason.MEMBER_CALL),
        ("maybe", CalleeKind.IDENTIFIER, "maybe", None, None),
    ]


def test_calls_are_attributed_to_innermost_function() -> None:
    result = extract(
        "src/attr.js",
        "function outer() {\n  a();\n  [1].map(function () { b(); });\n  const c = () => d();\n}\n",
    )
    callers = [(_name_of(result, c.caller_id), c.callee) for c in result.calls]

    assert callers == [
        ("outer", "a"),
        ("outer", "[1].map"),
        ("outer.<anonymous>", "b"),
        ("outer.c", "d"),
    ]


def test_long_callee_text_is_clipped() -> None:
    long_name = "x" * 500
    result = extract("src/long.js", f"{long_name}();\n")

    assert len(result.calls[0].callee) == 200
    assert result.calls[0].callee.endswith("...")


def test_jsx_and_tsx_calls() -> None:
    jsx = extract("src/App.jsx", "const App = () => <b onClick={() => go()}>{render()}</b>;\n")
    tsx = extract("src/App.tsx", "export const App = (): JSX.Element => <i>{render<T>()}</i>;\n")

    assert [c.callee for c in jsx.calls] == ["go", "render"]
    assert [c.callee for c in tsx.calls] == ["render"]
    assert tsx.functions[0].node.is_exported


# -- imports / exports -----------------------------------------------------------------


def test_imports() -> None:
    result = extract(
        "src/imports.ts",
        """import def, { a, b as c, type T, "x-y" as xy } from "./mod";
import * as ns from "../ns";
import type { Only } from "./types";
import "./side-effect";
import lib from "lodash";
const req = require("./req");
const { p, q: r } = require("./pq");
""",
    )
    imports = [(i.kind, i.source, i.imported_name, i.local_name) for i in result.imports]

    assert imports == [
        (ImportKind.DEFAULT, "./mod", "default", "def"),
        (ImportKind.NAMED, "./mod", "a", "a"),
        (ImportKind.NAMED, "./mod", "b", "c"),
        (ImportKind.NAMED, "./mod", "x-y", "xy"),
        (ImportKind.NAMESPACE, "../ns", "*", "ns"),
        (ImportKind.SIDE_EFFECT, "./side-effect", None, None),
        (ImportKind.DEFAULT, "lodash", "default", "lib"),
        (ImportKind.NAMESPACE, "./req", "*", "req"),
        (ImportKind.NAMED, "./pq", "p", "p"),
        (ImportKind.NAMED, "./pq", "q", "r"),
    ]
    assert [i.is_relative for i in result.imports].count(False) == 1  # lodash
    assert not any(c.callee == "require" for c in result.calls)


def test_exports_and_exported_flags() -> None:
    result = extract(
        "src/exports.js",
        """export function direct() {}
export default function main() {}
export const arrow = () => 1, value = 2;
function viaClause() {}
function aliased() {}
function internal() {}
export { viaClause, aliased as renamed };
export { remote } from "./remote";
export * from "./all";
export * as everything from "./ns";
export class Klass {}
""",
    )
    exported = {r.node.qualified_name: r.node.is_exported for r in result.functions}
    exports = sorted((e.exported_name, e.local_name or "", e.source or "") for e in result.exports)

    assert exported == {
        "direct": True,
        "main": True,
        "arrow": True,
        "viaClause": True,
        "aliased": True,
        "internal": False,
    }
    assert exports == sorted(
        [
            ("direct", "direct", ""),
            ("default", "main", ""),
            ("arrow", "arrow", ""),
            ("value", "value", ""),
            ("viaClause", "viaClause", ""),
            ("renamed", "aliased", ""),
            ("remote", "remote", "./remote"),
            ("*", "", "./all"),
            ("everything", "*", "./ns"),
            ("Klass", "Klass", ""),
        ]
    )


def test_default_export_of_anonymous_function() -> None:
    result = extract("src/default.js", "export default () => {};\n")

    node = result.functions[0].node
    assert node.is_anonymous and node.is_exported
    assert [(e.exported_name, e.function_id) for e in result.exports] == [("default", node.id)]


def test_commonjs_exports() -> None:
    result = extract(
        "src/cjs.js",
        """function helper() {}
function other() {}
module.exports.go = function () {};
exports.h = helper;
module.exports = { other, alias: helper };
""",
    )
    exported = {r.node.qualified_name: r.node.is_exported for r in result.functions}

    assert exported == {"helper": True, "other": True, "module.exports.go": True}
    assert [(e.exported_name, e.local_name) for e in result.exports] == [
        ("go", None),
        ("h", "helper"),
        ("other", "other"),
        ("alias", "helper"),
    ]


# -- malformed and edge-case input ---------------------------------------------------------


def test_syntax_errors_are_diagnosed_and_partial_results_kept() -> None:
    result = extract("src/broken.js", "function ok() { a(); }\nfunction broken( {\n  b();\n}\n")

    assert result.has_syntax_errors
    assert result.parse_errors
    assert all(e.path == "src/broken.js" and e.line is not None for e in result.parse_errors)
    assert result.functions[0].node.qualified_name == "ok"
    assert result.calls[0].callee == "a"


def test_parse_error_count_is_capped() -> None:
    broken = "".join(f"function f{i}( {{\n" for i in range(50))
    result = extract("src/many.js", broken, max_parse_errors_per_file=3)

    assert len(result.parse_errors) <= 3


def test_empty_and_comment_only_files() -> None:
    empty = extract("src/empty.ts", "")
    comments = extract("src/comments.ts", "// nothing\n/* here */\n")

    for result in (empty, comments):
        assert result.functions == [] and result.calls == [] and not result.has_syntax_errors
    assert (empty.line_count, comments.line_count) == (0, 2)


def test_deeply_nested_input_is_handled_iteratively() -> None:
    chain = "const x = " + " + ".join(["a()"] * 20_000) + ";\n"
    nested = "f(" * 2_000 + ")" * 2_000 + ";\n"

    assert len(extract("src/chain.js", chain).calls) == 20_000
    assert len(extract("src/nested.js", nested).calls) == 2_000


# -- contract consistency ----------------------------------------------------------------


def test_fixture_repository_matches_documented_graph_nodes() -> None:
    from app.ingestion.scanner import scan_repository

    settings = make_settings()
    files, _ = scan_repository(FIXTURE_REPOS / "shop_api", settings)
    parsed = parse_repository(files, settings)
    actual = sorted(
        (r.node.model_dump(mode="json") for f in parsed.files for r in f.functions),
        key=lambda n: n["id"],
    )
    documented = json.loads(Path(DOCS_FIXTURES / "graph.json").read_text())["nodes"]

    assert actual == sorted(documented, key=lambda n: n["id"])
