"""Resolve extracted calls to function IDs, conservatively.

Principles:

* A name is looked up through the caller's lexical scopes (innermost first),
  then through that file's imports. A name is never matched against other
  files by spelling alone, and globals are never assumed to be repository code.
* Exactly one declaration resolves; several are ``ambiguous_symbol``; none is
  ``unknown_symbol``. A variable or parameter whose value is not statically
  known never resolves.
* Relative imports follow export/re-export chains with a depth limit and cycle
  detection. Bare package imports are ``external_module``.
* ``this.m()`` resolves only inside class members whose ``this`` is known, and
  only when no subclass (matched by name) redeclares ``m``.
* ``x.m()`` resolves when ``x`` is a ``const`` bound to ``new X(...)``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.graph.modules import ModuleStatus, resolve_module
from app.models.graph import FunctionKind, ResolutionMethod, UnresolvedReason
from app.parsers.types import (
    CalleeKind,
    CallRecord,
    ClassRecord,
    ExportRecord,
    FileExtraction,
    FunctionRecord,
    ImportKind,
    ImportRecord,
)

MAX_IMPORT_DEPTH = 16

R = UnresolvedReason
M = ResolutionMethod


# -- symbols -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassRef:
    path: str
    scope_id: str
    name: str


@dataclass(frozen=True, slots=True)
class FunctionSymbol:
    function_id: str
    via: ResolutionMethod  # SAME_FILE or IMPORT


@dataclass(frozen=True, slots=True)
class ClassSymbol:
    ref: ClassRef
    via: ResolutionMethod


@dataclass(frozen=True, slots=True)
class InstanceSymbol:
    ref: ClassRef


@dataclass(frozen=True, slots=True)
class NamespaceSymbol:
    path: str  # module whose exports this binding exposes
    is_require: bool  # a CommonJS module object is itself callable via its default


@dataclass(frozen=True, slots=True)
class ValueSymbol:
    """A parameter or variable whose value is not statically known."""


@dataclass(frozen=True, slots=True)
class ExternalSymbol:
    module: str


@dataclass(frozen=True, slots=True)
class NotExported:
    """A resolved module that does not export the requested name."""


@dataclass(frozen=True, slots=True)
class Unresolved:
    reason: UnresolvedReason


Symbol = (
    FunctionSymbol
    | ClassSymbol
    | InstanceSymbol
    | NamespaceSymbol
    | ValueSymbol
    | ExternalSymbol
    | NotExported
    | Unresolved
)


@dataclass(frozen=True, slots=True)
class CallResolution:
    """Exactly one of: ``target_id`` (+ ``method``), ``reason``, or ``implicit``."""

    target_id: str | None = None
    method: ResolutionMethod | None = None
    reason: UnresolvedReason | None = None
    implicit: bool = False  # `new X()` where X has no explicit constructor: nothing to link


# -- per-file index ------------------------------------------------------------------


class _FileIndex:
    def __init__(self, extraction: FileExtraction) -> None:
        self.path = extraction.path
        self.module_id = extraction.module_id
        self.records: dict[str, FunctionRecord] = {}
        self.functions: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
        self.classes: defaultdict[tuple[str, str], list[ClassRecord]] = defaultdict(list)
        self.instances: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
        self.locals = extraction.scope_locals
        self.imports: defaultdict[str, list[ImportRecord]] = defaultdict(list)
        self.exports: defaultdict[str, list[ExportRecord]] = defaultdict(list)
        self.reexports: list[ExportRecord] = []
        self.members: defaultdict[ClassRef, list[FunctionRecord]] = defaultdict(list)

        for record in extraction.functions:
            fid = record.node.id
            self.records.setdefault(fid, record)
            if record.binding_name is not None:
                self.functions[(record.parent_id, record.binding_name)].append(fid)
            if record.owner_class is not None:
                ref = ClassRef(self.path, record.parent_id, record.owner_class)
                self.members[ref].append(record)
        for cls in extraction.classes:
            self.classes[(cls.scope_id, cls.name)].append(cls)
        for instance in extraction.instances:
            key = (instance.scope_id, instance.local_name)
            self.instances[key].append(instance.class_name)
        for imp in extraction.imports:
            if imp.local_name is not None:
                self.imports[imp.local_name].append(imp)
        for export in extraction.exports:
            if export.source is None:
                self.exports[export.exported_name].append(export)
            else:
                self.reexports.append(export)

    def parent_scope(self, scope_id: str) -> str | None:
        if scope_id == self.module_id:
            return None
        record = self.records.get(scope_id)
        return record.parent_id if record is not None else self.module_id


# -- resolver --------------------------------------------------------------------------


class Resolver:
    def __init__(self, files: Sequence[FileExtraction]) -> None:
        self._files: dict[str, _FileIndex] = {}
        for extraction in files:
            self._files.setdefault(extraction.path, _FileIndex(extraction))
        self._subclasses: defaultdict[str, list[ClassRef]] = defaultdict(list)
        for index in self._files.values():
            for (scope_id, name), records in index.classes.items():
                for cls in records:
                    if cls.superclass is not None:
                        base = cls.superclass.rsplit(".", 1)[-1]
                        self._subclasses[base].append(ClassRef(index.path, scope_id, name))

    def resolve(self, path: str, call: CallRecord) -> CallResolution:
        index = self._files.get(path)
        if index is None or call.caller_id not in index.records:
            return CallResolution(reason=R.UNKNOWN_SYMBOL)
        if call.unresolved_reason is not None:
            return CallResolution(reason=call.unresolved_reason)
        if call.kind is CalleeKind.IDENTIFIER and call.name is not None:
            return self._call_identifier(index, call.caller_id, call.name)
        if call.kind is CalleeKind.THIS_MEMBER and call.name is not None:
            return self._call_this(index, index.records[call.caller_id], call.name)
        if call.kind is CalleeKind.MEMBER and call.name and call.receiver:
            return self._call_member(index, call.caller_id, call.receiver, call.name)
        if call.kind is CalleeKind.NEW and call.name is not None:
            return self._call_new(index, call.caller_id, call.name)
        return CallResolution(reason=R.UNSUPPORTED_SYNTAX)

    # -- call shapes -----------------------------------------------------------------

    def _call_identifier(self, index: _FileIndex, scope: str, name: str) -> CallResolution:
        symbol = self._lookup(index, scope, name, 0)
        if isinstance(symbol, NamespaceSymbol) and symbol.is_require:
            # const f = require("./m"); f() calls module.exports.
            symbol = self._as_import(self._export(symbol.path, "default", 0, frozenset()))
        if isinstance(symbol, FunctionSymbol):
            return CallResolution(symbol.function_id, symbol.via)
        if isinstance(symbol, ClassSymbol):
            return CallResolution(reason=R.UNSUPPORTED_SYNTAX)  # class called without `new`
        return CallResolution(reason=_reason(symbol, R.DYNAMIC_CALL))

    def _call_this(self, index: _FileIndex, caller: FunctionRecord, name: str) -> CallResolution:
        ref = self._this_class(index, caller)
        if ref is None:
            return CallResolution(reason=R.MEMBER_CALL)  # `this` is not a known class instance
        target = self._member(ref, name, static=False)
        if isinstance(target, Unresolved):
            return CallResolution(reason=target.reason)
        if self._overridden(ref, name):
            return CallResolution(reason=R.AMBIGUOUS_SYMBOL)  # a subclass may override it
        return CallResolution(target, M.THIS_METHOD)

    def _call_member(
        self, index: _FileIndex, scope: str, receiver: str, name: str
    ) -> CallResolution:
        symbol = self._lookup(index, scope, receiver, 0)
        if isinstance(symbol, NamespaceSymbol):
            exported = self._as_import(self._export(symbol.path, name, 0, frozenset()))
            if isinstance(exported, FunctionSymbol):
                return CallResolution(exported.function_id, M.IMPORT)
            if isinstance(exported, ClassSymbol):
                return CallResolution(reason=R.UNSUPPORTED_SYNTAX)
            return CallResolution(reason=_reason(exported, R.MEMBER_CALL))
        if isinstance(symbol, InstanceSymbol):
            target = self._member(symbol.ref, name, static=False)
            if isinstance(target, Unresolved):
                return CallResolution(reason=target.reason)
            return CallResolution(target, M.INSTANCE_METHOD)
        if isinstance(symbol, ClassSymbol):
            target = self._member(symbol.ref, name, static=True)
            if isinstance(target, Unresolved):
                return CallResolution(reason=target.reason)
            return CallResolution(target, symbol.via)
        if isinstance(symbol, (FunctionSymbol, ValueSymbol)):
            return CallResolution(reason=R.MEMBER_CALL)  # e.g. fn.call(), obj.method()
        return CallResolution(reason=_reason(symbol, R.MEMBER_CALL))

    def _call_new(self, index: _FileIndex, scope: str, name: str) -> CallResolution:
        symbol = self._lookup(index, scope, name, 0)
        if isinstance(symbol, ClassSymbol):
            constructors = [
                r for r in self._members(symbol.ref) if r.node.kind is FunctionKind.CONSTRUCTOR
            ]
            if not constructors:
                return CallResolution(implicit=True)
            if len(constructors) > 1:
                return CallResolution(reason=R.AMBIGUOUS_SYMBOL)
            return CallResolution(constructors[0].node.id, M.CONSTRUCTOR)
        if isinstance(symbol, FunctionSymbol):
            return CallResolution(symbol.function_id, M.CONSTRUCTOR)  # ES5 constructor function
        return CallResolution(reason=_reason(symbol, R.DYNAMIC_CALL))

    # -- classes ------------------------------------------------------------------------

    def _this_class(self, index: _FileIndex, caller: FunctionRecord) -> ClassRef | None:
        """The class whose instance `this` is, found via the defining member."""
        if caller.this_class is None:
            return None
        record: FunctionRecord | None = caller
        while record is not None:
            if record.owner_class is not None:
                if record.owner_class != caller.this_class or record.is_static:
                    return None
                ref = ClassRef(index.path, record.parent_id, record.owner_class)
                return ref if len(index.classes[(ref.scope_id, ref.name)]) == 1 else None
            if record.node.kind is not FunctionKind.ARROW_FUNCTION:
                return None  # only arrows inherit `this`
            record = index.records.get(record.parent_id)
        return None

    def _members(self, ref: ClassRef) -> list[FunctionRecord]:
        index = self._files.get(ref.path)
        return index.members.get(ref, []) if index is not None else []

    def _member(self, ref: ClassRef, name: str, *, static: bool) -> str | Unresolved:
        matches = [
            r
            for r in self._members(ref)
            if r.node.name == name
            and r.is_static == static
            and r.node.kind is not FunctionKind.CONSTRUCTOR
        ]
        if not matches:
            return Unresolved(R.UNKNOWN_SYMBOL)  # e.g. inherited or assigned at runtime
        if len(matches) > 1:
            return Unresolved(R.AMBIGUOUS_SYMBOL)  # e.g. getter and setter
        return matches[0].node.id

    def _overridden(self, ref: ClassRef, name: str) -> bool:
        """Does any (transitive, name-matched) subclass declare an instance member `name`?"""
        seen: set[ClassRef] = set()
        pending = list(self._subclasses.get(ref.name, []))
        while pending:
            sub = pending.pop()
            if sub in seen:
                continue
            seen.add(sub)
            if any(r.node.name == name and not r.is_static for r in self._members(sub)):
                return True
            pending.extend(self._subclasses.get(sub.name, []))
        return False

    # -- names, imports and exports -------------------------------------------------------

    def _lookup(self, index: _FileIndex, scope: str, name: str, depth: int) -> Symbol:
        if depth > MAX_IMPORT_DEPTH:
            return Unresolved(R.UNRESOLVED_IMPORT)  # e.g. const A = new A()
        current: str | None = scope
        while current is not None:
            candidates = self._declared(index, current, name, depth)
            if candidates:
                unique = list(dict.fromkeys(candidates))
                return unique[0] if len(unique) == 1 else Unresolved(R.AMBIGUOUS_SYMBOL)
            current = index.parent_scope(current)
        return Unresolved(R.UNKNOWN_SYMBOL)

    def _declared(self, index: _FileIndex, scope: str, name: str, depth: int) -> list[Symbol]:
        found: list[Symbol] = [
            FunctionSymbol(fid, M.SAME_FILE) for fid in index.functions.get((scope, name), [])
        ]
        found += [
            ClassSymbol(ClassRef(index.path, scope, name), M.SAME_FILE)
            for _ in index.classes.get((scope, name), [])
        ]
        instance_classes = index.instances.get((scope, name), [])
        for class_name in instance_classes:
            cls = self._lookup(index, scope, class_name, depth + 1)
            found.append(InstanceSymbol(cls.ref) if isinstance(cls, ClassSymbol) else ValueSymbol())
        if name in index.locals.get(scope, frozenset()) and not instance_classes:
            found.append(ValueSymbol())
        if scope == index.module_id:
            found += [self._import(index, imp, depth) for imp in index.imports.get(name, [])]
        return found

    def _import(self, index: _FileIndex, imp: ImportRecord, depth: int) -> Symbol:
        module = resolve_module(index.path, imp.source, self._files.keys())
        if module.status is ModuleStatus.EXTERNAL:
            return ExternalSymbol(imp.source)
        if module.status is ModuleStatus.AMBIGUOUS:
            return Unresolved(R.AMBIGUOUS_SYMBOL)
        if module.status is not ModuleStatus.FOUND or module.path is None:
            return Unresolved(R.UNRESOLVED_IMPORT)
        if imp.kind is ImportKind.NAMESPACE:
            return NamespaceSymbol(module.path, imp.is_require)
        name = "default" if imp.kind is ImportKind.DEFAULT else imp.imported_name
        if name is None:
            return Unresolved(R.UNRESOLVED_IMPORT)
        return self._as_import(self._export(module.path, name, depth + 1, frozenset()))

    def _export(self, path: str, name: str, depth: int, visiting: frozenset[str]) -> Symbol:
        key = f"{path}\x00{name}"
        if depth > MAX_IMPORT_DEPTH or key in visiting:
            return Unresolved(R.UNRESOLVED_IMPORT)  # re-export cycle or chain too deep
        visiting = visiting | {key}
        index = self._files[path]

        found: list[Symbol] = []
        for export in index.exports.get(name, []):
            if export.function_id is not None:
                found.append(
                    FunctionSymbol(export.function_id, M.SAME_FILE)
                    if export.function_id in index.records
                    else Unresolved(R.UNRESOLVED_IMPORT)  # inconsistent parser output
                )
            elif export.local_name is not None:
                found.append(self._lookup(index, index.module_id, export.local_name, depth + 1))
            else:
                found.append(Unresolved(R.DYNAMIC_CALL))  # export default <expression>
        for export in index.reexports:
            if export.exported_name == name:
                found.append(self._reexport(index, export, name, depth, visiting))
        if not found and name != "default":  # `export *` never re-exports default
            star = [
                self._reexport(index, e, name, depth, visiting)
                for e in index.reexports
                if e.exported_name == "*"
            ]
            found = [s for s in star if not isinstance(s, NotExported)]

        unique = list(dict.fromkeys(found))
        if not unique:
            return NotExported()
        return unique[0] if len(unique) == 1 else Unresolved(R.AMBIGUOUS_SYMBOL)

    def _reexport(
        self,
        index: _FileIndex,
        export: ExportRecord,
        name: str,
        depth: int,
        visiting: frozenset[str],
    ) -> Symbol:
        """Follow ``export ... from "<source>"`` for the requested ``name``."""
        if export.source is None:
            return NotExported()
        module = resolve_module(index.path, export.source, self._files.keys())
        if module.status is ModuleStatus.EXTERNAL:
            return ExternalSymbol(export.source)
        if module.status is ModuleStatus.AMBIGUOUS:
            return Unresolved(R.AMBIGUOUS_SYMBOL)
        if module.status is not ModuleStatus.FOUND or module.path is None:
            return Unresolved(R.UNRESOLVED_IMPORT)
        if export.exported_name == "*":  # export * from "m": same name in m
            lookup = name
        elif export.local_name == "*":  # export * as ns from "m"
            return NamespaceSymbol(module.path, is_require=False)
        else:  # export { a as b } from "m"
            lookup = export.local_name or export.exported_name
        return self._as_import(self._export(module.path, lookup, depth + 1, visiting))

    @staticmethod
    def _as_import(symbol: Symbol) -> Symbol:
        if isinstance(symbol, FunctionSymbol):
            return FunctionSymbol(symbol.function_id, M.IMPORT)
        if isinstance(symbol, ClassSymbol):
            return ClassSymbol(symbol.ref, M.IMPORT)
        return symbol


def _reason(symbol: Symbol, value_reason: UnresolvedReason) -> UnresolvedReason:
    if isinstance(symbol, Unresolved):
        return symbol.reason
    if isinstance(symbol, ExternalSymbol):
        return R.EXTERNAL_MODULE
    if isinstance(symbol, NotExported):
        return R.UNRESOLVED_IMPORT
    return value_reason


def resolve_all(
    files: Sequence[FileExtraction],
) -> Iterable[tuple[FileExtraction, CallRecord, CallResolution]]:
    resolver = Resolver(files)
    for extraction in files:
        for call in extraction.calls:
            yield extraction, call, resolver.resolve(extraction.path, call)
