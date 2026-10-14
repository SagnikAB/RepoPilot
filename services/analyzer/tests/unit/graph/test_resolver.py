"""Call resolution, one behavior per test. Edges are described by file:qualified name."""

from __future__ import annotations

from tests.helpers import build_graph, describe_edges, describe_unresolved

# -- 1. same-file calls ---------------------------------------------------------------


def test_direct_same_file_calls_and_hoisting() -> None:
    graph = build_graph(
        {
            "src/a.js": """caller();
function caller() { helper(); later(); }
function helper() { helper(); }
const later = () => 1;
"""
        }
    )

    assert describe_edges(graph) == {
        ("src/a.js:<module>", "src/a.js:caller", "same_file"),
        ("src/a.js:caller", "src/a.js:helper", "same_file"),
        ("src/a.js:caller", "src/a.js:later", "same_file"),
        ("src/a.js:helper", "src/a.js:helper", "same_file"),  # recursion: self edge
    }


def test_parameters_and_variables_shadow_functions() -> None:
    graph = build_graph(
        {
            "src/a.js": """function helper() {}
function viaParam(helper) { helper(); }
function viaLocal() { const run = pick(); run(); }
"""
        }
    )

    assert describe_edges(graph) == set()
    assert describe_unresolved(graph) == {
        "helper": "dynamic_call",
        "pick": "unknown_symbol",
        "run": "dynamic_call",
    }


# -- 2. identical names -------------------------------------------------------------------


def test_identical_names_resolve_by_scope_and_file() -> None:
    graph = build_graph(
        {
            "src/a.js": """function helper() {}
function outer() { function helper() {} helper(); }
function top() { helper(); }
""",
            "src/b.js": "function helper() {}\nfunction useB() { helper(); }\n",
            "src/c.js": "function useC() { helper(); }\n",  # no helper here: must not borrow one
        }
    )

    assert describe_edges(graph) == {
        ("src/a.js:outer", "src/a.js:outer.helper", "same_file"),
        ("src/a.js:top", "src/a.js:helper", "same_file"),
        ("src/b.js:useB", "src/b.js:helper", "same_file"),
    }
    [unresolved] = graph.unresolved
    assert (unresolved.path, unresolved.reason.value) == ("src/c.js", "unknown_symbol")


def test_duplicate_declarations_in_one_scope_are_ambiguous() -> None:
    graph = build_graph({"src/a.js": "function f() {}\nfunction f() {}\nfunction g() { f(); }\n"})

    assert describe_edges(graph) == set()
    assert describe_unresolved(graph) == {"f": "ambiguous_symbol"}


# -- 3. named imports and exports -----------------------------------------------------------


def test_named_imports_aliases_and_namespaces() -> None:
    graph = build_graph(
        {
            "src/lib.ts": "export function a() {}\nexport const b = () => 1;\n"
            "function c() {}\nexport { c as renamed };\n",
            "src/app.ts": """import { a, b as bee, renamed } from "./lib";
import * as lib from "./lib";
export function main() { a(); bee(); renamed(); lib.a(); lib.missing(); }
""",
        }
    )

    assert describe_edges(graph) == {
        ("src/app.ts:main", "src/lib.ts:a", "import"),
        ("src/app.ts:main", "src/lib.ts:b", "import"),
        ("src/app.ts:main", "src/lib.ts:c", "import"),
    }
    [edge_to_a] = [e for e in graph.edges if graph.nodes[e.target].name == "a"]
    assert len(edge_to_a.call_sites) == 2  # a() and lib.a(): one edge, two call sites
    assert describe_unresolved(graph) == {"lib.missing": "unresolved_import"}


def test_reexport_chains() -> None:
    graph = build_graph(
        {
            "src/impl.ts": "export function deep() {}\nexport function other() {}\n",
            "src/mid.ts": 'export { deep as surface } from "./impl";\nexport * from "./impl";\n',
            "src/ns.ts": 'export * as tools from "./impl";\n',
            "src/app.ts": 'import { surface, other } from "./mid";\nimport { tools } from "./ns";\n'
            "export function run() { surface(); other(); tools.deep(); }\n",
        }
    )

    assert describe_edges(graph) == {
        ("src/app.ts:run", "src/impl.ts:deep", "import"),
        ("src/app.ts:run", "src/impl.ts:other", "import"),
    }


def test_star_exports_with_the_same_name_are_ambiguous() -> None:
    graph = build_graph(
        {
            "src/x.ts": "export function dup() {}\n",
            "src/y.ts": "export function dup() {}\n",
            "src/all.ts": 'export * from "./x";\nexport * from "./y";\n',
            "src/app.ts": 'import { dup } from "./all";\nexport function run() { dup(); }\n',
        }
    )

    assert describe_edges(graph) == set()
    assert describe_unresolved(graph) == {"dup": "ambiguous_symbol"}


def test_reexport_cycle_terminates() -> None:
    graph = build_graph(
        {
            "src/a.ts": 'export * from "./b";\n',
            "src/b.ts": 'export * from "./a";\n',
            "src/app.ts": 'import { nothing } from "./a";\nexport function run() { nothing(); }\n',
        }
    )

    assert describe_unresolved(graph) == {"nothing": "unresolved_import"}


# -- 4. default imports and exports -----------------------------------------------------------


def test_default_imports_and_exports() -> None:
    graph = build_graph(
        {
            "src/decl.js": "export default function main() {}\n",
            "src/named.js": "function helper() {}\nexport default helper;\n",
            "src/anon.js": "export default () => {};\n",
            "src/value.js": "export default makeHandler();\n",
            "src/app.js": """import main from "./decl";
import helper from "./named";
import anon from "./anon";
import value from "./value";
function run() { main(); helper(); anon(); value(); }
""",
        }
    )

    assert describe_edges(graph) == {
        ("src/app.js:run", "src/decl.js:main", "import"),
        ("src/app.js:run", "src/named.js:helper", "import"),
        ("src/app.js:run", "src/anon.js:<anonymous>", "import"),
    }
    assert describe_unresolved(graph)["value"] == "dynamic_call"


# -- 5. CommonJS -----------------------------------------------------------------------------


def test_commonjs_require_and_exports() -> None:
    graph = build_graph(
        {
            "lib/fn.js": "module.exports = function () {};\n",
            "lib/named.js": "function helper() {}\nexports.helper = helper;\n"
            "exports.direct = function () {};\n",
            "lib/obj.js": "function a() {}\nfunction b() {}\nmodule.exports = { a, bee: b };\n",
            "app.js": """const fn = require("./lib/fn");
const { helper } = require("./lib/named");
const named = require("./lib/named");
const obj = require("./lib/obj");
function run() { fn(); helper(); named.direct(); obj.a(); obj.bee(); obj.nope(); }
""",
        }
    )

    assert describe_edges(graph) == {
        ("app.js:run", "lib/fn.js:module.exports", "import"),
        ("app.js:run", "lib/named.js:helper", "import"),
        ("app.js:run", "lib/named.js:exports.direct", "import"),
        ("app.js:run", "lib/obj.js:a", "import"),
        ("app.js:run", "lib/obj.js:b", "import"),
    }
    assert describe_unresolved(graph) == {"obj.nope": "unresolved_import"}


# -- 6. this.method() --------------------------------------------------------------------------


def test_this_method_calls() -> None:
    graph = build_graph(
        {
            "src/svc.ts": """export class Svc {
  run() { this.step(); const cb = () => this.step(); function inner() { this.step(); } }
  step() {}
  handler = () => this.step();
  static make() { this.step(); }
  missing() { this.inherited(); }
}
"""
        }
    )

    assert describe_edges(graph) == {
        ("src/svc.ts:Svc.run", "src/svc.ts:Svc.step", "this_method"),
        ("src/svc.ts:Svc.run.cb", "src/svc.ts:Svc.step", "this_method"),
        ("src/svc.ts:Svc.handler", "src/svc.ts:Svc.step", "this_method"),
    }
    reasons = sorted((u.callee, u.reason.value) for u in graph.unresolved)
    assert reasons == [
        ("this.inherited", "unknown_symbol"),  # possibly inherited: not guessed
        ("this.step", "member_call"),  # function expression rebinds `this`
        ("this.step", "member_call"),  # static method: `this` is the class
    ]


def test_this_method_overridden_by_subclass_is_ambiguous() -> None:
    graph = build_graph(
        {
            "src/base.ts": "export class Base { run() { this.hook(); this.fixed(); }\n"
            "  hook() {}\n  fixed() {} }\n",
            "src/child.ts": 'import { Base } from "./base";\n'
            "export class Child extends Base { hook() {} }\n",
        }
    )

    assert describe_edges(graph) == {
        ("src/base.ts:Base.run", "src/base.ts:Base.fixed", "this_method"),
    }
    assert describe_unresolved(graph) == {"this.hook": "ambiguous_symbol"}


def test_object_literal_methods_do_not_resolve_this() -> None:
    graph = build_graph({"src/o.js": "const o = { a() { this.b(); }, b() {} };\n"})

    assert describe_unresolved(graph) == {"this.b": "member_call"}


# -- 7. instances, static methods and constructors ----------------------------------------------


def test_instance_static_and_constructor_calls() -> None:
    graph = build_graph(
        {
            "src/repo.ts": """export class Repo {
  constructor() {}
  find() {}
  static create() {}
}
export class Plain { go() {} }
export const shared = new Repo();
""",
            "src/app.ts": """import { Repo, Plain, shared } from "./repo";
function Legacy() {}
export function run() {
  const repo = new Repo();
  repo.find();
  shared.find();
  Repo.create();
  const p = new Plain();
  p.go();
  new Legacy();
  let mutable = new Repo();
  mutable.find();
  repo.absent();
  Repo.find();
}
""",
        }
    )

    assert describe_edges(graph) == {
        ("src/app.ts:run", "src/repo.ts:Repo.constructor", "constructor"),
        ("src/app.ts:run", "src/repo.ts:Repo.find", "instance_method"),
        ("src/app.ts:run", "src/repo.ts:Repo.create", "import"),
        ("src/app.ts:run", "src/repo.ts:Plain.go", "instance_method"),
        ("src/app.ts:run", "src/app.ts:Legacy", "constructor"),
        ("src/repo.ts:<module>", "src/repo.ts:Repo.constructor", "constructor"),
    }
    [find_edge] = [e for e in graph.edges if graph.nodes[e.target].name == "find"]
    assert len(find_edge.call_sites) == 2  # repo.find() and shared.find()
    assert graph.stats.implicit_constructor_calls == 1  # new Plain(): no explicit constructor
    assert describe_unresolved(graph) == {
        "mutable.find": "member_call",  # `let` may be reassigned
        "repo.absent": "unknown_symbol",
        "Repo.find": "unknown_symbol",  # instance method called as static
    }


def test_getter_and_setter_pair_is_ambiguous() -> None:
    graph = build_graph(
        {"src/a.ts": "class A { get v() { return 1; } set v(x) {} run() { this.v(); } }\n"}
    )

    assert describe_unresolved(graph) == {"this.v": "ambiguous_symbol"}


# -- 8. unresolved, external and dynamic calls ---------------------------------------------------


def test_unresolved_and_dynamic_calls_keep_reasons() -> None:
    graph = build_graph(
        {
            "src/a.ts": """import express from "express";
import { gone } from "./missing";
import { absent } from "./b";
import { outside } from "../../etc/x";
export function run(cb: () => void, obj: { m(): void }) {
  express(); gone(); absent(); outside(); cb(); obj.m(); console.log("x");
  handlers[name](); setTimeout(run, 1); (() => 1)(); run.call(null);
}
""",
            "src/b.ts": "export function present() {}\n",
        }
    )

    assert describe_edges(graph) == set()
    assert describe_unresolved(graph) == {
        "express": "external_module",
        "gone": "unresolved_import",
        "absent": "unresolved_import",
        "outside": "unresolved_import",
        "cb": "dynamic_call",
        "obj.m": "member_call",
        "console.log": "unknown_symbol",
        "handlers[name]": "dynamic_call",
        "setTimeout": "unknown_symbol",
        "(() => 1)": "unsupported_syntax",
        "run.call": "member_call",
    }


# -- 9. relative imports and index files ----------------------------------------------------------


def test_relative_paths_index_files_and_ts_esm_extensions() -> None:
    graph = build_graph(
        {
            "src/utils/index.ts": "export function fromIndex() {}\n",
            "src/lib/esm.ts": "export function fromEsm() {}\n",
            "src/deep/nested/caller.ts": """import { fromIndex } from "../../utils";
import { fromEsm } from "../../lib/esm.js";
import { root } from "../../..";
export function run() { fromIndex(); fromEsm(); root(); }
""",
            "index.ts": "export function root() {}\n",
        }
    )

    assert describe_edges(graph) == {
        ("src/deep/nested/caller.ts:run", "src/utils/index.ts:fromIndex", "import"),
        ("src/deep/nested/caller.ts:run", "src/lib/esm.ts:fromEsm", "import"),
        ("src/deep/nested/caller.ts:run", "index.ts:root", "import"),
    }


def test_ambiguous_module_files_are_not_guessed() -> None:
    graph = build_graph(
        {
            "src/dual.ts": "export function f() {}\n",
            "src/dual.js": "export function f() {}\n",
            "src/dir.ts": "export function g() {}\n",
            "src/dir/index.ts": "export function g() {}\n",
            "src/app.ts": 'import { f } from "./dual";\nimport { g } from "./dir";\n'
            "export function run() { f(); g(); }\n",
        }
    )

    assert describe_edges(graph) == set()
    assert describe_unresolved(graph) == {"f": "ambiguous_symbol", "g": "ambiguous_symbol"}
