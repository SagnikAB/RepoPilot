"""Per-file extraction results. Internal to the analyzer; not API contracts.

The parser records *facts* about each file. It never decides which function a
call targets — call resolution belongs to the graph layer, which uses
``binding_name``, ``parent_id``, ``scope_locals``, imports and exports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.models.analysis import LimitReached, ParseDiagnostic, SkippedFile
from app.models.common import Language
from app.models.findings import Finding
from app.models.graph import CallSite, FunctionNode, UnresolvedReason
from app.parsers.languages import Grammar


class CalleeKind(StrEnum):
    IDENTIFIER = "identifier"  # foo()
    THIS_MEMBER = "this_member"  # this.foo()
    MEMBER = "member"  # ns.foo() where ns is a plain identifier
    NEW = "new"  # new Foo()
    OTHER = "other"  # anything else; always carries an unresolved_reason


class ImportKind(StrEnum):
    DEFAULT = "default"  # import x from "m"
    NAMED = "named"  # import { a as b } from "m"; const { a } = require("m")
    NAMESPACE = "namespace"  # import * as ns from "m"; const ns = require("m")
    SIDE_EFFECT = "side_effect"  # import "m"


@dataclass(frozen=True, slots=True)
class FunctionRecord:
    node: FunctionNode
    parent_id: str  # enclosing function id, or the file's module id
    binding_name: str | None  # name callable from the parent scope, if statically known
    this_class: str | None  # class that `this` refers to inside the body, if known
    # Class whose body directly declares this method/field function, if any.
    # The class itself is declared in ``parent_id``'s scope.
    owner_class: str | None = None
    is_static: bool = False


@dataclass(frozen=True, slots=True)
class ClassRecord:
    name: str
    scope_id: str
    line: int
    superclass: str | None = None  # `extends` expression text, e.g. "Base" or "ns.Base"


@dataclass(frozen=True, slots=True)
class InstanceRecord:
    """``const <local_name> = new <class_name>(...)``: the binding's class is fixed."""

    scope_id: str
    local_name: str
    class_name: str
    line: int


@dataclass(frozen=True, slots=True)
class CallRecord:
    caller_id: str
    callee: str  # whitespace-collapsed callee text, at most 200 characters
    kind: CalleeKind
    name: str | None  # called identifier, property or constructor name
    receiver: str | None  # object identifier for MEMBER calls
    site: CallSite
    unresolved_reason: UnresolvedReason | None  # set when resolution is impossible


@dataclass(frozen=True, slots=True)
class ImportRecord:
    kind: ImportKind
    source: str  # module specifier as written
    imported_name: str | None  # "default", "*", an export name, or None (side effect)
    local_name: str | None
    line: int
    is_require: bool = False

    @property
    def is_relative(self) -> bool:
        return self.source.startswith(("./", "../")) or self.source in {".", ".."}


@dataclass(frozen=True, slots=True)
class ExportRecord:
    exported_name: str  # "default", "*", or the public name
    local_name: str | None  # local binding being exported, if any
    function_id: str | None  # set when a function literal is exported directly
    source: str | None  # set for re-exports: export { a } from "./m"
    line: int


@dataclass(slots=True)
class FileExtraction:
    path: str
    language: Language
    grammar: Grammar
    line_count: int
    module_id: str
    functions: list[FunctionRecord] = field(default_factory=list)
    classes: list[ClassRecord] = field(default_factory=list)
    calls: list[CallRecord] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    exports: list[ExportRecord] = field(default_factory=list)
    instances: list[InstanceRecord] = field(default_factory=list)
    # Non-function names declared in each scope (parameters, variables, catch
    # bindings). Block scoping is approximated by function scoping.
    scope_locals: dict[str, frozenset[str]] = field(default_factory=dict)
    parse_errors: list[ParseDiagnostic] = field(default_factory=list)
    has_syntax_errors: bool = False
    # Rule engine output, produced in the same (isolated) parse step.
    findings: list[Finding] = field(default_factory=list)
    findings_truncated: bool = False  # more than max_findings_per_file matched
    # Code-point spans of credential-like values to redact wherever text is served.
    redactions: list[tuple[int, int]] = field(default_factory=list)
    rule_errors: list[str] = field(default_factory=list)  # "<rule_id>: <reason>"


@dataclass(slots=True)
class ParsedRepository:
    files: list[FileExtraction] = field(default_factory=list)
    parse_errors: list[ParseDiagnostic] = field(default_factory=list)
    parse_errors_truncated: bool = False
    failed_files: list[str] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)
    limits_reached: list[LimitReached] = field(default_factory=list)
