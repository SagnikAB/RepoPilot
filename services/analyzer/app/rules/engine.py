"""A small, deterministic, syntax-aware rule engine.

Rules inspect the Tree-sitter syntax tree of one file; nothing is executed.
The engine runs inside the parser step (and therefore inside the isolated
parser worker, under its timeout), right after extraction, because syntax
trees cannot be shipped across processes.

* One iterative traversal per file; each node is offered to the rules that
  registered for its type, together with its parent. ``Node.parent`` must not
  be used in rules: Tree-sitter computes it by descending from the root, which
  makes it O(depth) and deeply nested files quadratic.
* A rule that raises is recorded in ``rule_errors`` and skipped for that file;
  extraction and other rules are unaffected.
* Every finding gets a stable ID, a valid location in the analyzed file, its
  enclosing function (if it is a graph node), and evidence with credential-like
  values redacted. Findings are leads for review, never confirmed issues.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from tree_sitter import Node

from app.models.common import SourceReference
from app.models.findings import MAX_EVIDENCE_LENGTH, Confidence, Finding, Severity
from app.models.graph import FunctionKind
from app.models.ids import finding_id
from app.parsers.extractor import FUNCTION_NODE_TYPES
from app.parsers.positions import LineIndex, apply_redactions, split_lines
from app.parsers.types import FileExtraction, ImportRecord

logger = logging.getLogger(__name__)

MAX_EVIDENCE_LINES = 3


@dataclass(frozen=True, slots=True)
class RuleMeta:
    rule_id: str
    title: str
    description: str
    severity: Severity
    confidence: Confidence
    next_step: str
    limitations: tuple[str, ...]
    cwe_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """One match. Optional fields override the rule's defaults."""

    node: Node
    severity: Severity | None = None
    confidence: Confidence | None = None
    description: str | None = None
    secret_nodes: tuple[Node, ...] = ()  # literal-content nodes whose text must be redacted
    secret_spans: tuple[tuple[int, int], ...] = ()  # or explicit (start_byte, end_byte) spans


@dataclass(slots=True)
class RuleContext:
    path: str
    source: bytes
    imports: Sequence[ImportRecord]

    def text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


class Rule(Protocol):
    meta: RuleMeta
    node_types: frozenset[str]

    def check(self, node: Node, parent: Node | None, ctx: RuleContext) -> Iterable[RuleMatch]: ...


@dataclass(slots=True)
class _Collected:
    rule: Rule
    match: RuleMatch
    function: Node | None  # innermost enclosing function-like node with a body


@dataclass(slots=True)
class RuleRun:
    findings: list[Finding] = field(default_factory=list)
    redactions: list[tuple[int, int]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    truncated: bool = False


def run_rules(
    rules: Sequence[Rule],
    extraction: FileExtraction,
    text: str,
    root: Node,
    *,
    max_findings: int,
) -> RuleRun:
    source = text.encode("utf-8")
    ctx = RuleContext(path=extraction.path, source=source, imports=extraction.imports)
    by_type: dict[str, list[Rule]] = {}
    for rule in rules:
        for node_type in rule.node_types:
            by_type.setdefault(node_type, []).append(rule)

    collected: list[_Collected] = []
    failed: set[str] = set()
    # (node, parent, innermost enclosing function): tracked here so no rule
    # ever needs Node.parent.
    stack: list[tuple[Node, Node | None, Node | None]] = [(root, None, None)]
    while stack:
        node, parent, function = stack.pop()
        for rule in by_type.get(node.type, ()):
            rule_id = rule.meta.rule_id
            if rule_id in failed:
                continue
            try:
                matches = list(rule.check(node, parent, ctx))
            except Exception:
                # Path and rule id only; never the source text.
                logger.exception("Rule %s failed on %s", rule_id, extraction.path)
                failed.add(rule_id)
                continue
            collected.extend(_Collected(rule, m, function) for m in matches)
        if node.type in FUNCTION_NODE_TYPES and node.child_by_field_name("body") is not None:
            function = node
        stack.extend((child, node, function) for child in reversed(node.named_children))

    run = RuleRun(errors=[f"{rule_id}: internal error; rule skipped" for rule_id in sorted(failed)])
    lines = LineIndex(source)
    for item in collected:
        for secret in item.match.secret_nodes:
            run.redactions.append(
                (lines.char_offset(secret.start_byte), lines.char_offset(secret.end_byte))
            )
        for start, end in item.match.secret_spans:
            run.redactions.append((lines.char_offset(start), lines.char_offset(end)))

    redacted_lines = split_lines(apply_redactions(text, run.redactions)[0])
    functions = _function_starts(extraction)
    findings: dict[str, Finding] = {}
    for item in collected:
        finding = _to_finding(item, extraction, lines, redacted_lines, functions)
        if finding.id not in findings:
            findings[finding.id] = finding
    ordered = sorted(
        findings.values(),
        key=lambda f: (f.location.start_line, f.location.end_line, f.rule_id, f.id),
    )
    run.truncated = len(ordered) > max_findings
    run.findings = ordered[:max_findings]
    return run


def _to_finding(
    item: _Collected,
    extraction: FileExtraction,
    lines: LineIndex,
    redacted_lines: list[str],
    functions: dict[tuple[int, int], str],
) -> Finding:
    meta, match = item.rule.meta, item.match
    start_line, end_line = lines.span(match.node)
    start_column = lines.column(match.node.start_byte)
    return Finding(
        id=finding_id(meta.rule_id, extraction.path, start_line, start_column),
        rule_id=meta.rule_id,
        title=meta.title,
        description=match.description or meta.description,
        severity=match.severity or meta.severity,
        confidence=match.confidence or meta.confidence,
        location=SourceReference(path=extraction.path, start_line=start_line, end_line=end_line),
        function_id=_enclosing_function(item.function, lines, functions, extraction),
        evidence=_evidence(redacted_lines, start_line, end_line),
        next_step=meta.next_step,
        limitations=list(meta.limitations),
        cwe_id=meta.cwe_id,
    )


def _evidence(redacted_lines: list[str], start_line: int, end_line: int) -> str:
    last = min(end_line, start_line + MAX_EVIDENCE_LINES - 1)
    snippet = "\n".join(line.strip() for line in redacted_lines[start_line - 1 : last])
    if last < end_line:
        snippet += "\n..."
    if len(snippet) > MAX_EVIDENCE_LENGTH:
        snippet = snippet[: MAX_EVIDENCE_LENGTH - 3] + "..."
    return snippet


def _function_starts(extraction: FileExtraction) -> dict[tuple[int, int], str]:
    return {
        (r.node.start_line, r.node.start_column): r.node.id
        for r in extraction.functions
        if r.node.kind is not FunctionKind.MODULE
    }


def _enclosing_function(
    function: Node | None,
    lines: LineIndex,
    functions: dict[tuple[int, int], str],
    extraction: FileExtraction,
) -> str | None:
    if function is not None:
        position = (lines.line(function.start_byte), lines.column(function.start_byte))
        found = functions.get(position)
        if found is not None:
            return found
    has_module_node = any(r.node.id == extraction.module_id for r in extraction.functions)
    return extraction.module_id if has_module_node else None
