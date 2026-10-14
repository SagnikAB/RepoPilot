"""Deterministic identifiers for graph nodes, edges and findings.

IDs are short, URL-safe and stable across re-analysis of identical source, so
the frontend and AI layer can reference them. Clients must treat them as opaque.
"""

from __future__ import annotations

import hashlib
import re
import uuid

_DIGEST_LENGTH = 16
_SEPARATOR = "\x1f"

ANALYSIS_ID_PATTERN = r"^[0-9a-f]{32}$"
_ANALYSIS_ID_RE = re.compile(ANALYSIS_ID_PATTERN)


def _digest(*parts: str) -> str:
    joined = _SEPARATOR.join(parts).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()[:_DIGEST_LENGTH]


def new_analysis_id() -> str:
    return uuid.uuid4().hex


def is_valid_analysis_id(value: str) -> bool:
    return bool(_ANALYSIS_ID_RE.fullmatch(value))


def function_id(path: str, qualified_name: str, start_line: int, start_column: int) -> str:
    return "fn_" + _digest("fn", path, qualified_name, str(start_line), str(start_column))


def edge_id(source_id: str, target_id: str) -> str:
    return "ce_" + _digest("ce", source_id, target_id)


def finding_id(rule_id: str, path: str, start_line: int, start_column: int) -> str:
    return "fd_" + _digest("fd", rule_id, path, str(start_line), str(start_column))
