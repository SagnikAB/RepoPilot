"""Resolve relative module specifiers to analyzed repository files.

Only relative specifiers (``./x``, ``../x``) are resolved. Bare specifiers
(``react``, ``@scope/pkg``) are external packages, and ``tsconfig`` path
aliases are not supported. A specifier that matches more than one analyzed
file is reported as ambiguous rather than guessed.
"""

from __future__ import annotations

import posixpath
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

# Probe order mirrors common bundler/TypeScript resolution; with more than one
# match the result is ambiguous, so the order never decides the target.
SOURCE_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
# TypeScript ESM code imports "./x.js" while the file on disk is "./x.ts".
_TS_FOR_JS = {".js": (".ts", ".tsx"), ".mjs": (".mts",), ".cjs": (".cts",), ".jsx": (".tsx",)}


class ModuleStatus(StrEnum):
    FOUND = "found"
    EXTERNAL = "external"  # bare package specifier
    NOT_FOUND = "not_found"  # relative, but no analyzed file matches
    AMBIGUOUS = "ambiguous"  # several analyzed files match
    OUTSIDE_REPOSITORY = "outside_repository"  # escapes the repository root


@dataclass(frozen=True, slots=True)
class ModuleResolution:
    status: ModuleStatus
    path: str | None = None
    candidates: tuple[str, ...] = ()


def is_relative_specifier(specifier: str) -> bool:
    return specifier in {".", ".."} or specifier.startswith(("./", "../"))


def resolve_module(
    importer_path: str, specifier: str, analyzed_paths: Collection[str]
) -> ModuleResolution:
    if not is_relative_specifier(specifier):
        return ModuleResolution(ModuleStatus.EXTERNAL)
    if "\\" in specifier or "\x00" in specifier:
        return ModuleResolution(ModuleStatus.NOT_FOUND)

    base = posixpath.normpath(posixpath.join(posixpath.dirname(importer_path), specifier))
    if base == ".." or base.startswith("../") or base.startswith("/"):
        return ModuleResolution(ModuleStatus.OUTSIDE_REPOSITORY)

    candidates = _candidates(base, specifier)
    matches = tuple(dict.fromkeys(c for c in candidates if c in analyzed_paths))
    if not matches:
        return ModuleResolution(ModuleStatus.NOT_FOUND)
    # Node and TypeScript disagree on precedence (e.g. "./x.js" with both x.js
    # and x.ts present), so any multi-file match is ambiguous.
    if len(matches) > 1:
        return ModuleResolution(ModuleStatus.AMBIGUOUS, candidates=matches)
    return ModuleResolution(ModuleStatus.FOUND, matches[0])


def _candidates(base: str, specifier: str) -> list[str]:
    candidates = [base]
    stem, extension = posixpath.splitext(base)
    for replacement in _TS_FOR_JS.get(extension, ()):
        candidates.append(stem + replacement)
    if not specifier.endswith("/"):
        candidates += [base + ext for ext in SOURCE_EXTENSIONS]
    index_base = "index" if base == "." else posixpath.join(base, "index")
    candidates += [index_base + ext for ext in SOURCE_EXTENSIONS]
    return candidates
