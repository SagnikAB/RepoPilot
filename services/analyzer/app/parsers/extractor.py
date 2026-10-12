"""Extract functions, classes, imports, exports and calls from one JS/TS file.

Design rules:

* Iterative traversal (explicit stack): deeply nested expressions cannot hit
  Python's recursion limit.
* Facts only. A call is classified by the *shape* of its callee; whether it
  can be resolved, and to what, is decided later by the graph layer. Shapes
  that can never be resolved statically are marked unresolved here.
* Positions: lines are 1-based; columns are 1-based Unicode code points.
  They are computed from byte offsets (``start_byte``/``end_byte``) only.
  ``Node.start_point``/``end_point`` must not be used: in tree-sitter 0.26.0
  reading ``Point.row``/``Point.column`` drops a reference to the returned int
  on every access, which corrupts the interpreter heap and crashes the process.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from tree_sitter import Node

from app.models.analysis import ParseDiagnostic
from app.models.common import Language
from app.models.graph import CallSite, FunctionKind, FunctionNode, UnresolvedReason
from app.models.ids import function_id
from app.parsers.languages import GRAMMAR_LANGUAGE, Grammar
from app.parsers.positions import LineIndex, count_lines
from app.parsers.types import (
    CalleeKind,
    CallRecord,
    ClassRecord,
    ExportRecord,
    FileExtraction,
    FunctionRecord,
    ImportKind,
    ImportRecord,
    InstanceRecord,
)

MODULE_NAME = "<module>"
ANONYMOUS = "<anonymous>"
ANONYMOUS_CLASS = "<class>"

MAX_CALLEE_LENGTH = 200
MAX_NAME_LENGTH = 256
MAX_QUALIFIED_NAME_LENGTH = 1024

_FUNCTION_DECLARATIONS = frozenset({"function_declaration", "generator_function_declaration"})
_FUNCTION_EXPRESSIONS = frozenset({"function_expression", "function", "generator_function"})
_ARROW = "arrow_function"
_METHOD = "method_definition"
_FUNCTION_LIKE = _FUNCTION_DECLARATIONS | _FUNCTION_EXPRESSIONS | {_ARROW, _METHOD}
# Public: the rule engine maps matches to their enclosing function with these.
FUNCTION_NODE_TYPES = _FUNCTION_LIKE
_FUNCTION_VALUES = _FUNCTION_EXPRESSIONS | {_ARROW}
_CLASS_TYPES = frozenset({"class_declaration", "class", "abstract_class_declaration"})
_FIELD_TYPES = frozenset({"field_definition", "public_field_definition"})
_DECLARATION_LISTS = frozenset({"lexical_declaration", "variable_declaration"})

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class _Context:
    scope_id: str  # innermost enclosing function (or the module)
    prefix: str  # qualified-name prefix for declarations at this point
    this_class: str | None  # class bound to `this`, if statically known
    class_body: str | None = None  # set only directly inside a named class body


@dataclass(slots=True)
class _PendingFunction:
    id: str
    name: str
    qualified_name: str
    kind: FunctionKind
    start_line: int
    end_line: int
    start_column: int
    is_anonymous: bool
    is_exported: bool
    parent_id: str
    binding_name: str | None
    this_class: str | None
    owner_class: str | None
    is_static: bool


def extract_file(
    path: str, grammar: Grammar, text: str, root: Node, *, max_parse_errors: int
) -> FileExtraction:
    return _Extractor(path, grammar, text, max_parse_errors).run(root)


class _Extractor:
    def __init__(self, path: str, grammar: Grammar, text: str, max_parse_errors: int) -> None:
        self._path = path
        self._language: Language = GRAMMAR_LANGUAGE[grammar]
        self._lines = LineIndex(text.encode("utf-8"))
        self._max_parse_errors = max_parse_errors
        self._module_id = function_id(path, MODULE_NAME, 1, 1)
        self._functions: list[_PendingFunction] = []
        self._function_ids: set[str] = set()
        self._locals: defaultdict[str, set[str]] = defaultdict(set)
        self._exported_locals: set[str] = set()
        self._result = FileExtraction(
            path=path,
            language=self._language,
            grammar=grammar,
            line_count=count_lines(text),
            module_id=self._module_id,
        )

    # -- driver -------------------------------------------------------------

    def run(self, root: Node) -> FileExtraction:
        self._result.has_syntax_errors = root.has_error
        self._result.parse_errors = self._syntax_errors(root)

        stack: list[tuple[Node, _Context]] = [(root, _Context(self._module_id, "", None))]
        while stack:
            node, ctx = stack.pop()
            child_ctx = self._visit(node, ctx)
            if child_ctx is not None:
                stack.extend((child, child_ctx) for child in reversed(node.named_children))

        self._finalize()
        return self._result

    def _visit(self, node: Node, ctx: _Context) -> _Context | None:
        """Record facts for ``node``; return the context for its children, or None to prune."""
        kind = node.type
        if kind in _FUNCTION_LIKE:
            if node.child_by_field_name("body") is None:
                return ctx  # overload signature / declaration without a body
            pending = self._add_function(node, ctx)
            if pending is None:
                return ctx
            return _Context(pending.id, pending.qualified_name, pending.this_class)
        if kind in _CLASS_TYPES:
            name = self._class_name(node)
            if name is not None:
                self._result.classes.append(
                    ClassRecord(name, ctx.scope_id, self._line(node), _superclass(node))
                )
            prefix = _join(ctx.prefix, name or ANONYMOUS_CLASS)
            return _Context(ctx.scope_id, prefix, name, class_body=name)
        if kind == "object":
            owner = self._owner_name(node)
            return ctx if owner is None else _Context(ctx.scope_id, _join(ctx.prefix, owner), None)
        if kind == "call_expression":
            self._add_call(node, ctx)
        elif kind == "new_expression":
            self._add_new(node, ctx)
        elif kind == "import_statement":
            self._add_import(node)
            return None
        elif kind == "export_statement":
            self._add_export(node)
        elif kind == "variable_declarator":
            self._add_declarator(node, ctx)
        elif kind == "catch_clause":
            self._declare(ctx.scope_id, node.child_by_field_name("parameter"))
        elif kind == "for_in_statement":
            self._declare(ctx.scope_id, node.child_by_field_name("left"))
        elif kind == "assignment_expression" and ctx.scope_id == self._module_id:
            self._add_commonjs_export(node)
        return ctx

    # -- functions ----------------------------------------------------------

    def _add_function(self, node: Node, ctx: _Context) -> _PendingFunction | None:
        name: str | None
        binding: str | None = None
        exported = False
        this_class: str | None = None
        owner_class: str | None = None
        is_static = False
        qualified_override: str | None = None
        kind_name = node.type
        parent = node.parent

        if kind_name in _FUNCTION_DECLARATIONS:
            kind = FunctionKind.FUNCTION_DECLARATION
            name = _text(node.child_by_field_name("name")) or None
            binding = name
            exported = parent is not None and parent.type == "export_statement"
        elif kind_name == _METHOD:
            name = _property_name(node.child_by_field_name("name"))
            in_class = parent is not None and parent.type == "class_body"
            is_constructor = in_class and name == "constructor"
            kind = FunctionKind.CONSTRUCTOR if is_constructor else FunctionKind.METHOD
            # In a static method `this` is the constructor, not an instance.
            is_static = _has_child_type(node, "static")
            this_class = ctx.this_class if in_class and not is_static else None
            owner_class = ctx.class_body if in_class else None
        else:
            kind = (
                FunctionKind.ARROW_FUNCTION
                if kind_name == _ARROW
                else FunctionKind.FUNCTION_EXPRESSION
            )
            name, binding, exported, qualified_override = self._expression_name(node, ctx)
            if kind_name == _ARROW:
                this_class = ctx.this_class  # arrows inherit `this`
            field = _unwrap_parent(node)[1]
            if field is not None and field.type in _FIELD_TYPES:
                owner_class = ctx.class_body  # class field holding a function
                is_static = _has_child_type(field, "static")
                if is_static:
                    this_class = None

        is_anonymous = name is None
        display_name = _clip(name or ANONYMOUS, MAX_NAME_LENGTH)
        qualified = _clip(
            qualified_override or _join(ctx.prefix, display_name), MAX_QUALIFIED_NAME_LENGTH
        )
        start_line, end_line = self._lines.span(node)
        start_column = self._lines.column(node.start_byte)
        fid = function_id(self._path, qualified, start_line, start_column)
        if fid in self._function_ids:
            self._diagnose(start_line, "Duplicate function identifier; definition ignored")
            return None
        self._function_ids.add(fid)

        pending = _PendingFunction(
            id=fid,
            name=display_name,
            qualified_name=qualified,
            kind=kind,
            start_line=start_line,
            end_line=end_line,
            start_column=start_column,
            is_anonymous=is_anonymous,
            is_exported=exported,
            parent_id=ctx.scope_id,
            binding_name=binding,
            this_class=this_class,
            owner_class=owner_class,
            is_static=is_static,
        )
        self._functions.append(pending)
        self._record_direct_export(node, pending)
        self._declare(fid, node.child_by_field_name("parameters"))
        self._declare(fid, node.child_by_field_name("parameter"))
        return pending

    def _expression_name(
        self, node: Node, ctx: _Context
    ) -> tuple[str | None, str | None, bool, str | None]:
        """Name a function/arrow expression from where it is bound.

        Returns ``(name, binding_name, is_exported, qualified_override)``.
        """
        child, parent = _unwrap_parent(node)
        if parent is not None:
            parent_type = parent.type
            if parent_type == "variable_declarator" and _is_field(parent, "value", child):
                target = parent.child_by_field_name("name")
                if target is not None and target.type == "identifier":
                    name = _text(target)
                    return name, name, _is_exported_declarator(parent), None
            elif parent_type == "assignment_expression" and _is_field(parent, "right", child):
                left = parent.child_by_field_name("left")
                if left is not None and left.type == "identifier":
                    return _text(left), None, False, None
                if left is not None and left.type == "member_expression":
                    left_text = _collapse(_text(left))
                    commonjs = (
                        ctx.scope_id == self._module_id
                        and _commonjs_export_name(left_text) is not None
                    )
                    prop = _property_name(left.child_by_field_name("property"))
                    return prop, None, commonjs, _join(ctx.prefix, left_text)
            elif parent_type == "pair" and _is_field(parent, "value", child):
                return _property_name(parent.child_by_field_name("key")), None, False, None
            elif parent_type in _FIELD_TYPES and _is_field(parent, "value", child):
                field = parent.child_by_field_name("property") or parent.child_by_field_name("name")
                return _property_name(field), None, False, None
            elif parent_type == "export_statement":
                return None, None, True, None  # export default <expression>

        own_name = node.child_by_field_name("name")
        if own_name is not None:
            return _text(own_name), None, False, None
        return None, None, False, None

    def _record_direct_export(self, node: Node, fn: _PendingFunction) -> None:
        if not fn.is_exported:
            return
        line = self._line(node)
        parent = node.parent
        if node.type in _FUNCTION_DECLARATIONS and parent is not None:
            public = "default" if _has_default(parent) else fn.name
            self._result.exports.append(ExportRecord(public, fn.binding_name, fn.id, None, line))
            return
        _, owner = _unwrap_parent(node)
        if owner is not None and owner.type == "export_statement":
            self._result.exports.append(ExportRecord("default", None, fn.id, None, line))
        elif owner is not None and owner.type == "assignment_expression":
            left = owner.child_by_field_name("left")
            public = _commonjs_export_name(_collapse(_text(left))) or fn.name
            self._result.exports.append(ExportRecord(public, None, fn.id, None, line))
        elif fn.binding_name is not None:
            self._result.exports.append(
                ExportRecord(fn.binding_name, fn.binding_name, fn.id, None, line)
            )

    def _class_name(self, node: Node) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return _text(name_node)
        _, parent = _unwrap_parent(node)
        if parent is not None and parent.type == "variable_declarator":
            target = parent.child_by_field_name("name")
            if target is not None and target.type == "identifier":
                return _text(target)
        return None

    def _owner_name(self, node: Node) -> str | None:
        """Name of the binding an object literal is assigned to, for qualified names."""
        child, parent = _unwrap_parent(node)
        if parent is None:
            return None
        if parent.type == "variable_declarator" and _is_field(parent, "value", child):
            target = parent.child_by_field_name("name")
            return _text(target) if target is not None and target.type == "identifier" else None
        if parent.type == "assignment_expression" and _is_field(parent, "right", child):
            return _collapse(_text(parent.child_by_field_name("left"))) or None
        if parent.type == "pair" and _is_field(parent, "value", child):
            return _property_name(parent.child_by_field_name("key"))
        return None

    # -- calls --------------------------------------------------------------

    def _add_call(self, node: Node, ctx: _Context) -> None:
        callee = node.child_by_field_name("function")
        if callee is None or callee.type == "import":
            return  # dynamic import() is module loading, not a function call
        kind = CalleeKind.OTHER
        name: str | None = None
        receiver: str | None = None
        reason: UnresolvedReason | None = None

        callee_type = callee.type
        if callee_type == "identifier":
            name = _text(callee)
            if name == "require":
                return  # recorded as an import by the variable declarator
            kind = CalleeKind.IDENTIFIER
        elif callee_type == "member_expression":
            target = callee.child_by_field_name("object")
            name = _property_name(callee.child_by_field_name("property"))
            if target is not None and target.type == "this":
                kind = CalleeKind.THIS_MEMBER
            elif target is not None and target.type == "identifier":
                kind = CalleeKind.MEMBER
                receiver = _text(target)
            else:
                reason = UnresolvedReason.MEMBER_CALL
        elif callee_type == "super" or _is_iife(callee):
            reason = UnresolvedReason.UNSUPPORTED_SYNTAX
        else:
            reason = UnresolvedReason.DYNAMIC_CALL
        self._record_call(node, callee, ctx, kind, name, receiver, reason)

    def _add_new(self, node: Node, ctx: _Context) -> None:
        constructor = node.child_by_field_name("constructor")
        if constructor is None:
            return
        if constructor.type == "identifier":
            self._record_call(
                node, constructor, ctx, CalleeKind.NEW, _text(constructor), None, None
            )
        else:
            reason = (
                UnresolvedReason.MEMBER_CALL
                if constructor.type == "member_expression"
                else UnresolvedReason.DYNAMIC_CALL
            )
            self._record_call(node, constructor, ctx, CalleeKind.OTHER, None, None, reason)

    def _record_call(
        self,
        node: Node,
        callee: Node,
        ctx: _Context,
        kind: CalleeKind,
        name: str | None,
        receiver: str | None,
        reason: UnresolvedReason | None,
    ) -> None:
        line, column = self._lines.start(node)
        site = CallSite(line=line, column=column)
        callee_text = _clip(_collapse(_text(callee)), MAX_CALLEE_LENGTH) or "<unknown>"
        self._result.calls.append(
            CallRecord(ctx.scope_id, callee_text, kind, name, receiver, site, reason)
        )

    # -- imports / exports / declarations -----------------------------------

    def _add_import(self, node: Node) -> None:
        if _has_child_type(node, "type"):
            return  # `import type` brings in no callable values
        source = _string_value(node.child_by_field_name("source"))
        if source is None:
            return
        line = self._line(node)
        clause = next((c for c in node.named_children if c.type == "import_clause"), None)
        if clause is None:
            self._result.imports.append(
                ImportRecord(ImportKind.SIDE_EFFECT, source, None, None, line)
            )
            return
        for part in clause.named_children:
            if part.type == "identifier":
                self._result.imports.append(
                    ImportRecord(ImportKind.DEFAULT, source, "default", _text(part), line)
                )
            elif part.type == "namespace_import":
                alias_node = next((c for c in part.named_children if c.type == "identifier"), None)
                if alias_node is not None:
                    self._result.imports.append(
                        ImportRecord(ImportKind.NAMESPACE, source, "*", _text(alias_node), line)
                    )
            elif part.type == "named_imports":
                for spec in part.named_children:
                    if spec.type != "import_specifier" or _has_child_type(spec, "type"):
                        continue
                    imported = _module_export_name(spec.child_by_field_name("name"))
                    alias = spec.child_by_field_name("alias")
                    local = _text(alias) if alias is not None else imported
                    self._result.imports.append(
                        ImportRecord(ImportKind.NAMED, source, imported, local, line)
                    )

    def _add_export(self, node: Node) -> None:
        line = self._line(node)
        source = _string_value(node.child_by_field_name("source"))
        declaration = node.child_by_field_name("declaration")
        value = node.child_by_field_name("value")
        exports = self._result.exports

        if declaration is not None:
            if declaration.type in _CLASS_TYPES:
                name = self._class_name(declaration)
                public = "default" if _has_default(node) else (name or "default")
                exports.append(ExportRecord(public, name, None, None, line))
            elif declaration.type in _DECLARATION_LISTS:
                for declarator in declaration.named_children:
                    if declarator.type != "variable_declarator":
                        continue
                    initial = _unwrap(declarator.child_by_field_name("value"))
                    if initial is not None and initial.type in _FUNCTION_VALUES:
                        continue  # recorded with its function id
                    target = declarator.child_by_field_name("name")
                    for bound in sorted(_binding_names(target)) if target is not None else []:
                        exports.append(ExportRecord(bound, bound, None, None, line))
            # Function declarations are recorded when the function is visited.
            return
        if value is not None:
            unwrapped = _unwrap(value)
            if unwrapped is not None and unwrapped.type in _FUNCTION_VALUES:
                return
            default_local = (
                _text(unwrapped)
                if unwrapped is not None and unwrapped.type == "identifier"
                else None
            )
            if default_local is not None:
                self._exported_locals.add(default_local)
            exports.append(ExportRecord("default", default_local, None, None, line))
            return
        for child in node.named_children:
            if child.type == "export_clause":
                for spec in child.named_children:
                    if spec.type != "export_specifier":
                        continue
                    local = _module_export_name(spec.child_by_field_name("name"))
                    alias = spec.child_by_field_name("alias")
                    public = _module_export_name(alias) if alias is not None else local
                    if source is None:
                        self._exported_locals.add(local)
                    exports.append(ExportRecord(public, local, None, source, line))
                return
            if child.type == "namespace_export":
                alias = next((c for c in child.named_children if c.type == "identifier"), None)
                public = _text(alias) if alias is not None else "*"
                exports.append(ExportRecord(public, "*", None, source, line))
                return
        if source is not None:
            exports.append(ExportRecord("*", None, None, source, line))  # export * from "m"

    def _add_commonjs_export(self, node: Node) -> None:
        left = node.child_by_field_name("left")
        right = _unwrap(node.child_by_field_name("right"))
        if left is None or right is None or right.type in _FUNCTION_VALUES:
            return  # function values are recorded when the function is visited
        public = _commonjs_export_name(_collapse(_text(left)))
        if public is None:
            return
        line = self._line(node)
        if right.type == "identifier":
            local = _text(right)
            self._exported_locals.add(local)
            self._result.exports.append(ExportRecord(public, local, None, None, line))
        elif right.type == "object" and public == "default":
            for prop in right.named_children:
                if prop.type == "shorthand_property_identifier":
                    local = _text(prop)
                    self._exported_locals.add(local)
                    self._result.exports.append(ExportRecord(local, local, None, None, line))
                elif prop.type == "pair":
                    value = _unwrap(prop.child_by_field_name("value"))
                    if value is not None and value.type == "identifier":
                        key = _property_name(prop.child_by_field_name("key"))
                        local = _text(value)
                        self._exported_locals.add(local)
                        self._result.exports.append(
                            ExportRecord(key or local, local, None, None, line)
                        )

    def _add_declarator(self, node: Node, ctx: _Context) -> None:
        target = node.child_by_field_name("name")
        value = _unwrap(node.child_by_field_name("value"))
        if target is None:
            return
        source = _require_source(value)
        if source is not None:
            self._add_require(target, source, self._line(node))
            return
        if value is not None and value.type in _CLASS_TYPES:
            return  # recorded as a class
        if value is not None and value.type in _FUNCTION_VALUES and target.type == "identifier":
            return  # recorded as a function binding
        self._declare(ctx.scope_id, target)
        instance_class = _new_class_name(value)
        if instance_class is not None and target.type == "identifier" and _is_const(node):
            self._result.instances.append(
                InstanceRecord(ctx.scope_id, _text(target), instance_class, self._line(node))
            )

    def _add_require(self, target: Node, source: str, line: int) -> None:
        imports = self._result.imports
        if target.type == "identifier":
            imports.append(
                ImportRecord(ImportKind.NAMESPACE, source, "*", _text(target), line, True)
            )
            return
        if target.type != "object_pattern":
            return
        for prop in target.named_children:
            if prop.type == "shorthand_property_identifier_pattern":
                name = _text(prop)
                imports.append(ImportRecord(ImportKind.NAMED, source, name, name, line, True))
            elif prop.type == "pair_pattern":
                key = _property_name(prop.child_by_field_name("key"))
                value = prop.child_by_field_name("value")
                if value is not None and value.type == "identifier":
                    imports.append(
                        ImportRecord(ImportKind.NAMED, source, key, _text(value), line, True)
                    )

    def _declare(self, scope_id: str, pattern: Node | None) -> None:
        if pattern is not None:
            self._locals[scope_id].update(_binding_names(pattern))

    # -- diagnostics / finalization -------------------------------------------

    def _line(self, node: Node) -> int:
        return self._lines.line(node.start_byte)

    def _syntax_errors(self, root: Node) -> list[ParseDiagnostic]:
        if not root.has_error:
            return []
        found: list[tuple[int, str]] = []
        stack = [root]
        while stack and len(found) < self._max_parse_errors:
            node = stack.pop()
            if node.is_missing:
                found.append((self._line(node), f"Missing '{node.type}'"))
            elif node.is_error:
                found.append((self._line(node), "Syntax error"))
            else:
                stack.extend(c for c in reversed(node.children) if c.has_error or c.is_missing)
        return [
            ParseDiagnostic(path=self._path, line=line, message=message)
            for line, message in sorted(found)
        ]

    def _diagnose(self, line: int, message: str) -> None:
        if len(self._result.parse_errors) < self._max_parse_errors:
            self._result.parse_errors.append(
                ParseDiagnostic(path=self._path, line=line, message=message)
            )

    def _finalize(self) -> None:
        result = self._result
        if any(call.caller_id == self._module_id for call in result.calls):
            module_node = FunctionNode(
                id=self._module_id,
                name=MODULE_NAME,
                qualified_name=MODULE_NAME,
                kind=FunctionKind.MODULE,
                language=self._language,
                path=self._path,
                start_line=1,
                end_line=max(1, result.line_count),
                start_column=1,
            )
            result.functions.append(FunctionRecord(module_node, self._module_id, None, None))

        for fn in self._functions:
            exported = fn.is_exported or (
                fn.parent_id == self._module_id
                and fn.binding_name is not None
                and fn.binding_name in self._exported_locals
            )
            node = FunctionNode(
                id=fn.id,
                name=fn.name,
                qualified_name=fn.qualified_name,
                kind=fn.kind,
                language=self._language,
                path=self._path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                start_column=fn.start_column,
                is_anonymous=fn.is_anonymous,
                is_exported=exported,
            )
            result.functions.append(
                FunctionRecord(
                    node,
                    fn.parent_id,
                    fn.binding_name,
                    fn.this_class,
                    owner_class=fn.owner_class,
                    is_static=fn.is_static,
                )
            )
        result.scope_locals = {
            scope: frozenset(names) for scope, names in self._locals.items() if names
        }


# -- helpers -----------------------------------------------------------------


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def _collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _join(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name


def _unwrap(node: Node | None) -> Node | None:
    while node is not None and node.type == "parenthesized_expression":
        node = node.named_children[0] if node.named_children else None
    return node


def _unwrap_parent(node: Node) -> tuple[Node, Node | None]:
    child, parent = node, node.parent
    while parent is not None and parent.type == "parenthesized_expression":
        child, parent = parent, parent.parent
    return child, parent


def _is_field(parent: Node, field: str, child: Node) -> bool:
    value = parent.child_by_field_name(field)
    return value is not None and value.id == child.id


def _has_child_type(node: Node, child_type: str) -> bool:
    return any(child.type == child_type for child in node.children)


def _has_default(export_statement: Node) -> bool:
    return export_statement.type == "export_statement" and _has_child_type(
        export_statement, "default"
    )


def _is_exported_declarator(declarator: Node) -> bool:
    declaration = declarator.parent
    return (
        declaration is not None
        and declaration.type in _DECLARATION_LISTS
        and declaration.parent is not None
        and declaration.parent.type == "export_statement"
    )


def _superclass(class_node: Node) -> str | None:
    heritage = next((c for c in class_node.named_children if c.type == "class_heritage"), None)
    if heritage is None:
        return None
    clause = next((c for c in heritage.named_children if c.type == "extends_clause"), None)
    target = (
        clause.child_by_field_name("value")
        if clause is not None
        else next(iter(heritage.named_children), None)
    )
    return _collapse(_text(target)) or None


def _new_class_name(value: Node | None) -> str | None:
    if value is None or value.type != "new_expression":
        return None
    constructor = value.child_by_field_name("constructor")
    if constructor is None or constructor.type != "identifier":
        return None
    return _text(constructor)


def _is_const(declarator: Node) -> bool:
    declaration = declarator.parent
    if declaration is None or declaration.type != "lexical_declaration":
        return False
    kind = declaration.child_by_field_name("kind")
    return kind is not None and kind.type == "const"


def _is_iife(callee: Node) -> bool:
    unwrapped = _unwrap(callee)
    return unwrapped is not None and unwrapped.type in _FUNCTION_VALUES


def _property_name(node: Node | None) -> str | None:
    if node is None:
        return None
    if node.type == "string":
        return _string_value(node)
    return _collapse(_text(node)) or None


def _module_export_name(node: Node | None) -> str:
    return (_string_value(node) if node is not None and node.type == "string" else None) or _text(
        node
    )


def _string_value(node: Node | None) -> str | None:
    if node is None or node.type != "string":
        return None
    raw = _text(node)
    return raw[1:-1] if len(raw) >= 2 else None


def _require_source(value: Node | None) -> str | None:
    """Return the module for ``require("<literal>")``, else None."""
    if value is None or value.type != "call_expression":
        return None
    callee = value.child_by_field_name("function")
    arguments = value.child_by_field_name("arguments")
    if callee is None or callee.type != "identifier" or _text(callee) != "require":
        return None
    if arguments is None or arguments.named_child_count != 1:
        return None
    return _string_value(arguments.named_children[0])


def _commonjs_export_name(left_text: str) -> str | None:
    if left_text == "module.exports":
        return "default"
    for prefix in ("module.exports.", "exports."):
        if left_text.startswith(prefix):
            rest = left_text[len(prefix) :]
            if rest and "." not in rest and "[" not in rest:
                return rest
    return None


def _binding_names(pattern: Node) -> set[str]:
    """Identifiers bound by a parameter list, parameter, or destructuring pattern."""
    names: set[str] = set()
    stack = [pattern]
    while stack:
        node = stack.pop()
        kind = node.type
        if kind in {"identifier", "shorthand_property_identifier_pattern"}:
            names.add(_text(node))
        elif kind in {"formal_parameters", "object_pattern", "array_pattern", "rest_pattern"}:
            stack.extend(node.named_children)
        elif kind == "pair_pattern":
            stack.extend(_fields(node, "value"))
        elif kind in {"assignment_pattern", "object_assignment_pattern"}:
            stack.extend(_fields(node, "left"))
        elif kind in {"required_parameter", "optional_parameter"}:
            stack.extend(_fields(node, "pattern"))
    return names


def _fields(node: Node, name: str) -> list[Node]:
    child = node.child_by_field_name(name)
    return [child] if child is not None else []
