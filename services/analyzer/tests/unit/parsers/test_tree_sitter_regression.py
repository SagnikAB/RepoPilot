"""Regression tests for the tree-sitter 0.26.0 ``Point`` memory-safety bug.

Root cause: reading ``Point.row`` / ``Point.column`` by attribute drops one
reference to the returned int on every access. Once a non-cached int is freed
the heap is corrupted and the process later crashes (SIGSEGV, exit code 139),
often far from the faulty access (it first surfaced inside ``Node.text``).
Index access (``point[1]``) is correct.

Upstream fixed the getters after 0.26.0 (py-tree-sitter commit afb3836b,
"fix(point): fix reference counting issues"); 0.25.2 (namedtuple ``Point``) is
also unaffected.

The analyzer never touches ``Point``; it derives positions from byte offsets.

Default runs keep only safe checks: application code never reads ``Point``
positions, the accessors it does use are refcount-safe, and the inputs that
crashed the first extractor now complete. The two tests that deliberately
trigger the upstream bug are opt-in (``native_crash``; see
``tests/helpers/native.py``). Everything still runs in subprocesses so pytest
itself survives.
"""

from __future__ import annotations

import ast
import json
import signal
import subprocess
import sys
import textwrap

from tests.helpers import TESTS_DIR
from tests.helpers.native import native_crash_canary

SCANNED_DIRS = (TESTS_DIR.parent / "app", TESTS_DIR.parent / "scripts")

POINT_REPRO = textwrap.dedent(
    """
    import sys
    import tree_sitter as ts
    import tree_sitter_javascript as js

    access = sys.argv[1]
    source = b" " * 1000 + b"a();\\n"  # column 1000: not a cached small int
    root = ts.Parser(ts.Language(js.language())).parse(source).root_node
    point = root.named_children[0].named_children[0].start_point
    for _ in range(3):
        value = point.column if access == "attr" else point[1]
        del value
    junk = [str(i) * 3 for i in range(200_000)]
    print("survived", point[1], flush=True)
    """
)


def _run(code: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code, *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=TESTS_DIR.parent,
    )


@native_crash_canary
def test_minimal_reproducer_crashes_with_attribute_access() -> None:
    """Canary for the upstream bug. If this starts passing cleanly, tree-sitter
    has fixed ``Point``; the byte-offset workaround can then be revisited."""
    crashed = _run(POINT_REPRO, "attr")
    safe = _run(POINT_REPRO, "index")

    assert safe.returncode == 0, safe.stderr
    assert safe.stdout.strip() == "survived 1000"
    assert crashed.returncode != 0, (
        "tree-sitter Point attribute access no longer crashes; upstream may have fixed it"
    )
    assert crashed.returncode == -signal.SIGSEGV or "Fatal Python error" in crashed.stderr


@native_crash_canary
def test_point_attribute_access_leaks_a_reference() -> None:
    """Measures the defect without crashing, but still corrupts a refcount: opt-in."""
    code = textwrap.dedent(
        """
        import os, sys
        import tree_sitter as ts
        import tree_sitter_javascript as js
        root = ts.Parser(ts.Language(js.language())).parse(b" " * 1000 + b"a();").root_node
        point = root.named_children[0].named_children[0].start_point
        value = point[1]
        before = sys.getrefcount(value)
        point.column
        print(sys.getrefcount(value) - before, flush=True)
        os._exit(0)  # skip teardown, which would free the over-released int
        """
    )
    completed = _run(code)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "-1"


def test_node_accessors_used_by_the_extractor_are_refcount_safe() -> None:
    code = textwrap.dedent(
        """
        import json, sys
        import tree_sitter as ts
        import tree_sitter_javascript as js
        root = ts.Parser(ts.Language(js.language())).parse(
            b" " * 1000 + b"const value = foo(1);\\n").root_node
        call = root.named_children[0].named_children[0].child_by_field_name("value")
        getters = {
            "type": lambda: call.type, "start_byte": lambda: call.start_byte,
            "end_byte": lambda: call.end_byte, "id": lambda: call.id,
            "text": lambda: call.text, "named_child_count": lambda: call.named_child_count,
            "descendant_count": lambda: root.descendant_count,
            "has_error": lambda: call.has_error, "is_missing": lambda: call.is_missing,
            "is_error": lambda: call.is_error, "children": lambda: call.children,
            "named_children": lambda: call.named_children,
            "child_by_field_name": lambda: call.child_by_field_name("function"),
            "parent": lambda: call.parent,
        }
        def delta(get, calls):
            first = get(); before = sys.getrefcount(first)
            for _ in range(calls):
                get()
            return sys.getrefcount(first) - before
        # A getter that over-releases loses one reference per call, so its delta
        # scales with the call count. Shared small ints show constant +/-1 noise.
        growth = {name: delta(get, 200) - delta(get, 10) for name, get in getters.items()}
        print(json.dumps(growth))
        """
    )
    completed = _run(code)

    assert completed.returncode == 0, completed.stderr
    growth = json.loads(completed.stdout)
    assert len(growth) == 14
    assert growth == dict.fromkeys(growth, 0)


def test_extractor_survives_the_original_crash_inputs() -> None:
    """The inputs that crashed the first extractor now complete, in a subprocess."""
    code = textwrap.dedent(
        """
        from app.parsers.languages import Grammar
        from app.ingestion.types import SourceFile
        from app.parsers.service import parse_source_file
        from tests.helpers import make_settings
        settings = make_settings()
        inputs = {
            "terms_50.js": "const x = " + " + ".join(["a()"] * 50) + ";\\n",
            "terms_20000.js": "const x = " + " + ".join(["a()"] * 20000) + ";\\n",
            "wide.js": (" " * 1000 + "a(); b(); c();\\n") * 200,
        }
        for name, text in inputs.items():
            source = SourceFile(name, Grammar.JAVASCRIPT, text, len(text))
            for _ in range(5):
                result = parse_source_file(source, settings)
            print(name, len(result.calls), flush=True)
        """
    )
    completed = _run(code)

    assert completed.returncode == 0, f"exit {completed.returncode}: {completed.stderr[-2000:]}"
    assert completed.stdout.split("\n")[:3] == [
        "terms_50.js 50",
        "terms_20000.js 20000",
        "wide.js 600",
    ]


def test_app_code_never_reads_point_positions() -> None:
    forbidden = {"start_point", "end_point", "range", "byte_range"}
    offenders = []
    scanned = [path for directory in SCANNED_DIRS for path in directory.rglob("*.py")]
    assert len(scanned) > 30  # guard against silently scanning nothing
    for path in scanned:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [
            f"{path.relative_to(TESTS_DIR.parent)}:{node.lineno} .{node.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in forbidden
        ]

    assert offenders == []
