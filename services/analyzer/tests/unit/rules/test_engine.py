"""Rule engine mechanics: isolation of failing rules, limits, ordering, performance."""

from __future__ import annotations

import ast
import time
from collections.abc import Iterator

from tree_sitter import Node

from app.models.findings import Confidence, Severity
from app.parsers.languages import Grammar, new_parser
from app.rules.engine import RuleContext, RuleMatch, RuleMeta, run_rules
from app.rules.javascript import JAVASCRIPT_RULES, DynamicCodeExecutionRule
from tests.helpers import TESTS_DIR, extract

RULES_DIR = TESTS_DIR.parent / "app" / "rules"


class ExplodingRule:
    meta = RuleMeta(
        rule_id="test.exploding",
        title="t",
        description="d",
        severity=Severity.LOW,
        confidence=Confidence.LOW,
        next_step="n",
        limitations=(),
    )
    node_types = frozenset({"call_expression"})

    def check(self, node: Node, parent: Node | None, ctx: RuleContext) -> Iterator[RuleMatch]:
        raise RuntimeError("rule bug")


def _run(code: str, rules: tuple[object, ...], max_findings: int = 100):  # type: ignore[no-untyped-def]
    extraction = extract("src/a.js", code)
    tree = new_parser(Grammar.JAVASCRIPT).parse(code.encode())
    assert tree is not None
    return run_rules(rules, extraction, code, tree.root_node, max_findings=max_findings)  # type: ignore[arg-type]


def test_failing_rule_is_isolated_and_reported() -> None:
    run = _run("eval(x);\n", (ExplodingRule(), DynamicCodeExecutionRule()))

    assert [f.rule_id for f in run.findings] == ["js.dynamic-code-execution"]
    assert run.errors == ["test.exploding: internal error; rule skipped"]


def test_findings_are_capped_per_file() -> None:
    run = _run("".join(f"eval(x{i});\n" for i in range(10)), JAVASCRIPT_RULES, max_findings=3)

    assert len(run.findings) == 3 and run.truncated
    assert [f.location.start_line for f in run.findings] == [1, 2, 3]


def test_findings_are_deterministic_and_unique() -> None:
    code = (
        'const token = "abcdefgh-1234";\n'
        "eval(a); eval(b);\n"
        "const q = `SELECT a FROM t WHERE x=${y}`;\n"
    )

    first = [f.model_dump() for f in extract("src/a.js", code).findings]
    second = [f.model_dump() for f in extract("src/a.js", code).findings]

    assert first == second
    assert len({f["id"] for f in first}) == len(first) == 4
    assert [(f["location"]["start_line"], f["rule_id"]) for f in first] == sorted(
        (f["location"]["start_line"], f["rule_id"]) for f in first
    )


def test_redaction_spans_cover_exactly_the_secret_value() -> None:
    code = 'const é = 1; const password = "pässwörd-1234";\n'

    result = extract("src/a.js", code)

    [(start, end)] = result.redactions
    assert code[start:end] == "pässwörd-1234"  # code-point offsets, not bytes


def test_deeply_nested_input_stays_linear() -> None:
    chain = "const x = " + " + ".join(["a()"] * 20_000) + ";\n"
    started = time.monotonic()

    result = extract("src/chain.js", chain)

    assert time.monotonic() - started < 3
    assert result.findings == []


def test_rules_never_use_node_parent() -> None:
    """Node.parent is O(depth) in Tree-sitter; rules get the parent from the engine."""
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in RULES_DIR.glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr == "parent"
    ]

    assert offenders == []
