"""Supported source languages and Tree-sitter grammar loading.

Verified against tree-sitter 0.26.0, tree-sitter-javascript 0.25.0 (ABI 15)
and tree-sitter-typescript 0.23.2 (ABI 14); the core library accepts ABI 13-15.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cache

import tree_sitter
import tree_sitter_javascript
import tree_sitter_typescript

from app.models.common import Language


class Grammar(StrEnum):
    JAVASCRIPT = "javascript"  # also parses JSX
    TYPESCRIPT = "typescript"
    TSX = "tsx"


GRAMMAR_LANGUAGE: dict[Grammar, Language] = {
    Grammar.JAVASCRIPT: Language.JAVASCRIPT,
    Grammar.TYPESCRIPT: Language.TYPESCRIPT,
    Grammar.TSX: Language.TYPESCRIPT,
}

EXTENSION_GRAMMAR: dict[str, Grammar] = {
    ".js": Grammar.JAVASCRIPT,
    ".jsx": Grammar.JAVASCRIPT,
    ".mjs": Grammar.JAVASCRIPT,
    ".cjs": Grammar.JAVASCRIPT,
    ".ts": Grammar.TYPESCRIPT,
    ".mts": Grammar.TYPESCRIPT,
    ".cts": Grammar.TYPESCRIPT,
    ".tsx": Grammar.TSX,
}


def grammar_for_path(path: str) -> Grammar | None:
    dot = path.rfind(".")
    if dot <= path.rfind("/"):
        return None
    return EXTENSION_GRAMMAR.get(path[dot:].lower())


@cache
def _language(grammar: Grammar) -> tree_sitter.Language:
    if grammar is Grammar.JAVASCRIPT:
        capsule = tree_sitter_javascript.language()
    elif grammar is Grammar.TYPESCRIPT:
        capsule = tree_sitter_typescript.language_typescript()
    else:
        capsule = tree_sitter_typescript.language_tsx()
    return tree_sitter.Language(capsule)


def new_parser(grammar: Grammar) -> tree_sitter.Parser:
    """Return a fresh parser. Parsers are not thread-safe; do not share them."""
    return tree_sitter.Parser(_language(grammar))
