"""JavaScript/TypeScript rules. Every match is a potential issue for review.

Detection is syntax-aware: rules inspect syntax-tree nodes (calls, string
literals, object pairs, assignments) and imports, never raw text lines. Regexes
are applied only to string-literal content (SQL shape, known token formats).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from tree_sitter import Node

from app.models.findings import Confidence, Severity
from app.parsers.types import ImportKind
from app.rules.engine import RuleContext, RuleMatch, RuleMeta

# -- shared helpers ------------------------------------------------------------------


def _arguments(call: Node) -> list[Node]:
    args = call.child_by_field_name("arguments")
    if args is None or args.type != "arguments":
        return []
    return [a for a in args.named_children if a.type != "comment"]


def _unwrap(node: Node | None) -> Node | None:
    while node is not None and node.type == "parenthesized_expression":
        children = [c for c in node.named_children if c.type != "comment"]
        node = children[0] if children else None
    return node


def _is_static_string(node: Node | None) -> bool:
    node = _unwrap(node)
    if node is None:
        return False
    if node.type == "string":
        return True
    return node.type == "template_string" and not any(
        c.type == "template_substitution" for c in node.named_children
    )


def _string_content(node: Node, ctx: RuleContext) -> tuple[str, int, int] | None:
    """Content and byte span (quotes excluded) of a static string literal."""
    if not _is_static_string(node) or node.end_byte - node.start_byte < 2:
        return None
    start, end = node.start_byte + 1, node.end_byte - 1
    return ctx.source[start:end].decode("utf-8", errors="replace"), start, end


def _property_key(node: Node | None, ctx: RuleContext) -> str:
    if node is None:
        return ""
    text = ctx.text(node)
    return text[1:-1] if node.type == "string" and len(text) >= 2 else text


def _collapse(text: str) -> str:
    return re.sub(r"\s+", "", text)


# -- 1. dynamic code execution ----------------------------------------------------------

_GLOBAL_OBJECTS = frozenset({"window", "globalThis", "global", "self"})
_EVAL_FUNCTIONS = frozenset({"eval", "Function"})
_STRING_TIMERS = frozenset({"setTimeout", "setInterval"})


class DynamicCodeExecutionRule:
    meta = RuleMeta(
        rule_id="js.dynamic-code-execution",
        title="Dynamic code execution",
        description=(
            "Code is evaluated from a string at runtime (eval, Function, or a string passed "
            "to setTimeout/setInterval). If any part of the string can be influenced by a user, "
            "this may allow code injection."
        ),
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        next_step=(
            "Identify where the evaluated string comes from; check whether request data or "
            "other external input can reach it, and whether the evaluation can be removed."
        ),
        limitations=(
            "The rule does not track where the evaluated string originates.",
            "A local function that shadows eval or Function would also match.",
        ),
        cwe_id="CWE-95",
    )
    node_types = frozenset({"call_expression", "new_expression"})

    def check(self, node: Node, parent: Node | None, ctx: RuleContext) -> Iterator[RuleMatch]:
        target = node.child_by_field_name(
            "function" if node.type == "call_expression" else "constructor"
        )
        name = _global_name(target, ctx)
        args = _arguments(node)
        if node.type == "new_expression":
            if name == "Function":
                yield self._match(node, constant=all(_is_static_string(a) for a in args))
            return
        if name in _EVAL_FUNCTIONS:
            yield self._match(node, constant=bool(args) and all(_is_static_string(a) for a in args))
        elif name in _STRING_TIMERS and args:
            first = _unwrap(args[0])
            if first is not None and first.type in {
                "string",
                "template_string",
                "binary_expression",
            }:
                if first.type == "binary_expression" and not _is_plus(first, ctx):
                    return  # e.g. `a || b`: not string building
                yield self._match(node, constant=_is_static_string(first))

    def _match(self, node: Node, *, constant: bool) -> RuleMatch:
        if not constant:
            return RuleMatch(node)
        return RuleMatch(
            node,
            severity=Severity.LOW,
            description=(
                "Code is evaluated from a constant string at runtime. This is lower risk "
                "than evaluating dynamic input, but the evaluation is still worth reviewing."
            ),
        )


def _global_name(target: Node | None, ctx: RuleContext) -> str | None:
    target = _unwrap(target)
    if target is None:
        return None
    if target.type == "identifier":
        return ctx.text(target)
    if target.type == "member_expression":
        obj = target.child_by_field_name("object")
        prop = target.child_by_field_name("property")
        if obj is not None and obj.type == "identifier" and ctx.text(obj) in _GLOBAL_OBJECTS:
            return ctx.text(prop)
    return None


# -- 2. shell command execution ---------------------------------------------------------

_CHILD_PROCESS = frozenset({"child_process", "node:child_process"})
_ALWAYS_SHELL = frozenset({"exec", "execSync"})
_OPTIONAL_SHELL = frozenset({"spawn", "spawnSync", "execFile", "execFileSync"})


class ShellCommandRule:
    meta = RuleMeta(
        rule_id="js.shell-command-construction",
        title="Shell command built from dynamic input",
        description=(
            "A child_process command that runs through a shell is built from non-constant "
            "input. If any part is user-controlled, this may allow command injection."
        ),
        severity=Severity.HIGH,
        confidence=Confidence.MEDIUM,
        next_step=(
            "Trace the dynamic parts of the command to their sources; prefer execFile/spawn "
            "with an argument array and no shell, and validate any external input."
        ),
        limitations=(
            "Only calls whose child_process import is visible in the same file are checked.",
            "The rule does not track whether the dynamic parts are validated or user-controlled.",
        ),
        cwe_id="CWE-78",
    )
    node_types = frozenset({"call_expression"})

    def check(self, node: Node, parent: Node | None, ctx: RuleContext) -> Iterator[RuleMatch]:
        method = _child_process_method(node.child_by_field_name("function"), ctx)
        if method is None:
            return
        args = _arguments(node)
        if not args:
            return
        if method in _ALWAYS_SHELL:
            if not _is_static_string(args[0]):
                yield RuleMatch(node)
        elif method in _OPTIONAL_SHELL and any(_has_shell_true(a, ctx) for a in args[1:]):
            argv = _unwrap(args[1]) if len(args) > 1 else None
            dynamic_argv = (
                argv is not None
                and argv.type == "array"
                and any(
                    not _is_static_string(e) for e in argv.named_children if e.type != "comment"
                )
            )
            if not _is_static_string(args[0]) or dynamic_argv:
                yield RuleMatch(
                    node,
                    description=(
                        "A child_process call with `shell: true` receives non-constant input. "
                        "If any part is user-controlled, this may allow command injection."
                    ),
                )


def _child_process_method(callee: Node | None, ctx: RuleContext) -> str | None:
    callee = _unwrap(callee)
    if callee is None:
        return None
    if callee.type == "identifier":
        local = ctx.text(callee)
        for imp in ctx.imports:
            if (
                imp.local_name == local
                and imp.source in _CHILD_PROCESS
                and imp.kind is ImportKind.NAMED
            ):
                return imp.imported_name
        return None
    if callee.type != "member_expression":
        return None
    receiver = _unwrap(callee.child_by_field_name("object"))
    method = ctx.text(callee.child_by_field_name("property"))
    if receiver is None:
        return None
    if receiver.type == "identifier":
        local = ctx.text(receiver)
        if any(
            imp.local_name == local
            and imp.source in _CHILD_PROCESS
            and imp.kind in {ImportKind.NAMESPACE, ImportKind.DEFAULT}
            for imp in ctx.imports
        ):
            return method
    if receiver.type == "call_expression":  # require("child_process").exec(...)
        fn = receiver.child_by_field_name("function")
        args = _arguments(receiver)
        if fn is not None and ctx.text(fn) == "require" and len(args) == 1:
            content = _string_content(args[0], ctx)
            if content is not None and content[0] in _CHILD_PROCESS:
                return method
    return None


def _has_shell_true(node: Node, ctx: RuleContext) -> bool:
    node = _unwrap(node) or node
    if node.type != "object":
        return False
    return any(
        pair.type == "pair"
        and _property_key(pair.child_by_field_name("key"), ctx) == "shell"
        and (value := pair.child_by_field_name("value")) is not None
        and value.type == "true"
        for pair in node.named_children
    )


# -- 3. SQL string construction -----------------------------------------------------------

_SQL = re.compile(
    r"^\s*(?:select\s.+?\sfrom\s|insert\s+into\s|update\s+\S+\s+set\s|delete\s+from\s"
    r"|(?:create|drop|alter|truncate)\s+table\s|merge\s+into\s)",
    re.IGNORECASE | re.DOTALL,
)
_PLACEHOLDER = " __expr__ "


class SqlConstructionRule:
    meta = RuleMeta(
        rule_id="js.sql-string-construction",
        title="SQL query built with string interpolation",
        description=(
            "A string that looks like a SQL statement is built from a template literal or "
            "concatenation with non-constant values. If any interpolated value is "
            "user-controlled, this may allow SQL injection."
        ),
        severity=Severity.HIGH,
        confidence=Confidence.MEDIUM,
        next_step=(
            "Check whether the interpolated values can come from request input (trace the "
            "enclosing function's callers) and whether the query is executed with parameter "
            "binding instead."
        ),
        limitations=(
            "The rule does not track where interpolated values originate.",
            "Sanitization performed before this line is not detected.",
        ),
        cwe_id="CWE-89",
    )
    node_types = frozenset({"template_string", "binary_expression"})

    def check(self, node: Node, parent: Node | None, ctx: RuleContext) -> Iterator[RuleMatch]:
        if node.type == "template_string":
            if _is_static_string(node) or _is_tagged(node, parent):
                return  # constant, or a tagged template (often a parameterizing sql`...`)
            if _SQL.match(_template_text(node, ctx)):
                yield RuleMatch(node)
            return
        if not _is_plus(node, ctx) or _is_plus(parent, ctx):
            return  # only the outermost `+` of a concatenation chain
        pieces = _concat_pieces(node, ctx)
        if any(p is None for p in pieces) and _SQL.match(
            "".join(_PLACEHOLDER if p is None else p for p in pieces)
        ):
            yield RuleMatch(node)


def _is_tagged(template: Node, parent: Node | None) -> bool:
    if parent is None or parent.type != "call_expression":
        return False
    args = parent.child_by_field_name("arguments")
    return args is not None and args.id == template.id


def _template_text(template: Node, ctx: RuleContext) -> str:
    parts = []
    for child in template.named_children:
        if child.type == "template_substitution":
            parts.append(_PLACEHOLDER)
        elif child.type in {"string_fragment", "escape_sequence"}:
            parts.append(ctx.text(child))
    return "".join(parts)


def _is_plus(node: Node | None, ctx: RuleContext) -> bool:
    if node is None or node.type != "binary_expression":
        return False
    operator = node.child_by_field_name("operator")
    return operator is not None and ctx.text(operator) == "+"


def _concat_pieces(node: Node, ctx: RuleContext) -> list[str | None]:
    """Left-to-right operands of a `+` chain: literal text, or None if dynamic."""
    pieces: list[str | None] = []
    stack: list[Node] = [node]
    while stack:
        current = _unwrap(stack.pop())
        if current is None:
            pieces.append(None)
        elif _is_plus(current, ctx):
            right, left = current.child_by_field_name("right"), current.child_by_field_name("left")
            stack.extend(n for n in (right, left) if n is not None)
        else:
            content = _string_content(current, ctx)
            pieces.append(content[0] if content is not None else None)
    return pieces


# -- 4. TLS verification disabled -----------------------------------------------------------

_TLS_KEYS = frozenset({"rejectUnauthorized", "strictSSL"})
_TLS_ENV_TARGETS = frozenset(
    {
        "process.env.NODE_TLS_REJECT_UNAUTHORIZED",
        'process.env["NODE_TLS_REJECT_UNAUTHORIZED"]',
        "process.env['NODE_TLS_REJECT_UNAUTHORIZED']",
    }
)


class TlsVerificationDisabledRule:
    meta = RuleMeta(
        rule_id="js.tls-verification-disabled",
        title="TLS certificate verification disabled",
        description=(
            "TLS certificate verification is turned off, so connections accept any "
            "certificate. This may allow man-in-the-middle interception."
        ),
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        next_step=(
            "Check whether this code path runs outside local development or tests; if so, "
            "trust the required CA explicitly instead of disabling verification."
        ),
        limitations=(
            "The rule cannot tell whether this code only runs in development or tests.",
            'Only literal `false` (or "0" for NODE_TLS_REJECT_UNAUTHORIZED) is detected.',
        ),
        cwe_id="CWE-295",
    )
    node_types = frozenset({"pair", "assignment_expression"})

    def check(self, node: Node, parent: Node | None, ctx: RuleContext) -> Iterator[RuleMatch]:
        if node.type == "pair":
            key = _property_key(node.child_by_field_name("key"), ctx)
            value = _unwrap(node.child_by_field_name("value"))
            if key in _TLS_KEYS and value is not None and value.type == "false":
                yield RuleMatch(node)
            return
        left = _collapse(ctx.text(node.child_by_field_name("left")))
        right = _unwrap(node.child_by_field_name("right"))
        if right is None:
            return
        if left in _TLS_ENV_TARGETS:
            content = _string_content(right, ctx)
            if (content is not None and content[0] == "0") or (
                right.type == "number" and ctx.text(right) == "0"
            ):
                yield RuleMatch(node)
        elif left.endswith(".rejectUnauthorized") and right.type == "false":
            yield RuleMatch(node)


# -- 5. hardcoded credentials -----------------------------------------------------------------

_SECRET_LAST_WORDS = frozenset(
    {"password", "passwd", "pwd", "passphrase", "secret", "token", "credential", "credentials"}
)
_SECRET_LAST_PAIRS = frozenset(
    {
        "apikey",
        "privatekey",
        "accesskey",
        "secretkey",
        "signingkey",
        "encryptionkey",
        "clientsecret",
    }
)
_NAME_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_PLACEHOLDER_VALUE = re.compile(
    r"^(?:<.*>|\$\{.*\}|\{\{.*\}\}|changeme|change[-_]me|password|secret|example|placeholder"
    r"|x{3,}|\*{3,}|todo|tbd|null|undefined|none|redacted)$",
    re.IGNORECASE,
)
MIN_SECRET_LENGTH = 8
TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "GitHub token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    ),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Stripe live key", re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
)


class HardcodedCredentialRule:
    meta = RuleMeta(
        rule_id="js.hardcoded-credential",
        title="Hardcoded credential-like value",
        description=(
            "A variable or property whose name suggests a secret is assigned a string "
            "literal. Secrets in source code can leak through version control."
        ),
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        next_step=(
            "Confirm whether this is a real secret or a placeholder; if real, rotate it and "
            "load it from configuration or a secret store instead."
        ),
        limitations=(
            "The matched value is redacted; the rule cannot tell real secrets from test "
            "placeholders.",
            "Secrets assembled at runtime or stored in non-source files are not detected.",
        ),
        cwe_id="CWE-798",
    )
    node_types = frozenset(
        {
            "string",
            "template_string",
            "variable_declarator",
            "pair",
            "assignment_expression",
            "public_field_definition",
            "field_definition",
        }
    )

    def check(self, node: Node, parent: Node | None, ctx: RuleContext) -> Iterator[RuleMatch]:
        if node.type in {"string", "template_string"}:
            content = _string_content(node, ctx)
            kind = _token_kind(content[0]) if content is not None else None
            if content is not None and kind is not None:
                yield RuleMatch(
                    node,
                    severity=Severity.HIGH,
                    confidence=Confidence.HIGH,
                    description=f"A string literal matches the format of a {kind}. Secrets in "
                    "source code can leak through version control.",
                    secret_spans=((content[1], content[2]),),
                )
            return
        name_node, value_node = _named_value(node)
        value = _unwrap(value_node)
        if name_node is None or value is None or not _is_secret_name(ctx.text(name_node)):
            return
        content = _string_content(value, ctx)
        if content is None or _token_kind(content[0]) is not None:
            return  # not a literal, or already reported as a known token format
        if _looks_like_secret_value(content[0]):
            yield RuleMatch(value, secret_spans=((content[1], content[2]),))


def _named_value(node: Node) -> tuple[Node | None, Node | None]:
    if node.type == "variable_declarator":
        name = node.child_by_field_name("name")
        return (name if name is not None and name.type == "identifier" else None), (
            node.child_by_field_name("value")
        )
    if node.type == "pair":
        return node.child_by_field_name("key"), node.child_by_field_name("value")
    if node.type == "assignment_expression":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "member_expression":
            left = left.child_by_field_name("property")
        return left, node.child_by_field_name("right")
    name = node.child_by_field_name("property") or node.child_by_field_name("name")
    return name, node.child_by_field_name("value")


def _is_secret_name(name: str) -> bool:
    words = [w.lower() for w in _NAME_WORDS.findall(name.strip("\"'`"))]
    if not words:
        return False
    return words[-1] in _SECRET_LAST_WORDS or "".join(words[-2:]) in _SECRET_LAST_PAIRS


def _looks_like_secret_value(value: str) -> bool:
    return (
        len(value) >= MIN_SECRET_LENGTH
        and not any(c.isspace() for c in value)
        and len(set(value)) > 1
        and not _PLACEHOLDER_VALUE.match(value)
        and not value.startswith(("http://", "https://", "/", "./", "process.env"))
    )


def _token_kind(value: str) -> str | None:
    return next((kind for kind, pattern in TOKEN_PATTERNS if pattern.search(value)), None)


JAVASCRIPT_RULES = (
    DynamicCodeExecutionRule(),
    ShellCommandRule(),
    SqlConstructionRule(),
    TlsVerificationDisabledRule(),
    HardcodedCredentialRule(),
)
